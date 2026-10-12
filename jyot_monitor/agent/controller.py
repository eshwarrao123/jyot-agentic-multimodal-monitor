"""
Agent controller module.

Orchestrates:
1. Per-item bounded execution loop with configurable max steps.
2. Tool execution through validated ToolRegistry.
3. Pre-execution budget checks (item and run cost/step limits).
4. Graceful degradation to ItemStatus.PARTIAL on budget exhaustion or error.
5. JSONL trace event emission for every step.
6. Safe, untrusted-data boundary protection.
"""

import os
from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional
from pathlib import Path

from jyot_monitor.agent.planner import LLMPlanner, DeterministicFallbackPlanner
from jyot_monitor.agent.tools.registry import ToolRegistry, get_default_tool_registry
from jyot_monitor.models import (
    ActionRequest,
    AlertProposal,
    BudgetState,
    ClassificationResult,
    CritiqueResult,
    ItemProcessingResult,
    ItemStatus,
    PlannerMode,
    SourceItem,
    ToolName,
    ToolResult,
    TraceEvent,
    VerificationResult,
    utc_now,
)
from jyot_monitor.ocr.router import OCRRouter
from jyot_monitor.safety.redaction import redact_text
from jyot_monitor.storage import Storage
from jyot_monitor.trace import Tracer


# Build the set of path prefixes that should be stripped from traces at startup
# so the list does not change between calls.
_HOME_DIR = str(Path.home()).replace("\\", "/")
_CWD = str(Path(os.getcwd()).resolve()).replace("\\", "/")
_PATH_PREFIXES_TO_SCRUB = [p for p in [_HOME_DIR, _CWD] if p]


def _scrub_machine_paths(value: str) -> str:
    """Replace absolute machine-specific path prefixes with a portable token."""
    norm = value.replace("\\", "/")
    for prefix in _PATH_PREFIXES_TO_SCRUB:
        if norm.startswith(prefix):
            return "<project-path>/" + norm[len(prefix):].lstrip("/")
    return value


def sanitize_summary(data: Any, max_len: int = 250) -> Any:
    """Recursively redact secrets, contact PII, machine paths and truncate large string fields for safe tracing."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(secret_key in k_lower for secret_key in ("secret", "token", "password", "api_key", "credential")):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_summary(v, max_len)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_summary(x, max_len) for x in data[:10]]
    elif isinstance(data, str):
        redacted = redact_text(data)
        redacted = _scrub_machine_paths(redacted)
        if len(redacted) > max_len:
            return redacted[:max_len] + "... [truncated]"
        return redacted
    elif isinstance(data, (int, float, bool)) or data is None:
        return data
    return str(data)[:max_len]


class AgentController:
    """
    Bounded Agent Controller.
    
    Coordinates the iterative loop between the planner (LLM or fallback)
    and registered tools, enforcing hard step and budget constraints.
    """

    def __init__(
        self,
        planner: Optional[Any] = None,
        tool_registry: Optional[ToolRegistry] = None,
        storage: Optional[Storage] = None,
        ocr_router: Optional[OCRRouter] = None,
        tracer: Optional[Tracer] = None,
        run_id: str = "run_default",
        max_steps_per_item: int = 10,
        per_item_usd: float = 0.10,
        per_run_usd: float = 5.00,
        urgency_critique_threshold: float = 75.0,
        urgency_alert_threshold: float = 85.0,
        fixture_root: str = "fixtures",
        fault_injector: Optional[Any] = None,
    ):
        self.planner = planner or DeterministicFallbackPlanner()
        self.tool_registry = tool_registry or get_default_tool_registry()
        self.storage = storage
        self.ocr_router = ocr_router
        self.tracer = tracer
        self.run_id = tracer.run_id if (tracer and run_id == "run_default") else run_id
        self.max_steps_per_item = max_steps_per_item
        self.per_item_usd = per_item_usd
        self.per_run_usd_remaining = per_run_usd
        self.urgency_critique_threshold = urgency_critique_threshold
        self.urgency_alert_threshold = urgency_alert_threshold
        self.fixture_root = fixture_root
        self.fault_injector = fault_injector

    def process_item(
        self,
        item: SourceItem,
        attachments: Optional[List[Any]] = None,
        item_index: int = 0,
    ) -> ItemProcessingResult:
        """
        Process a single item through the bounded agent loop.
        
        Guarantees:
        - Bounded execution (stops at max_steps_per_item).
        - Hard cost budget limits (stops if item or run budget exhausted).
        - Safe tool execution (only registered tools).
        - Incremental tracing of every decision and action.
        - Isolation: one failing item will never crash the overall run.
        """
        attachments = attachments or []
        completed_tools: List[ToolName] = []
        completed_tool_data: Dict[str, Any] = {}
        failed_tools: List[ToolName] = []
        item_cost_used = 0.0
        total_tokens_in = 0
        total_tokens_out = 0
        total_latency_ms = 0.0
        fallback_used_overall = False
        final_status = ItemStatus.IN_PROGRESS
        error_msg: Optional[str] = None

        # Extract LLM client from planner if available for tool use
        llm_client = getattr(self.planner, "llm_client", None) if hasattr(self.planner, "llm_client") else None
        planner_mode_str = "llm" if llm_client and not isinstance(self.planner, DeterministicFallbackPlanner) else "fallback"
        
        context: Dict[str, Any] = {
            "run_id": self.run_id,
            "item_id": item.item_id,
            "item_index": item_index,
            "item": item,
            "attachments": attachments,
            "fixture_root": self.fixture_root,
            "storage": self.storage,
            "ocr_router": self.ocr_router,
            "llm_client": llm_client,
            "planner_mode": planner_mode_str,
            "fault_injector": self.fault_injector,
            "completed_tools": completed_tools,
            "completed_tool_data": completed_tool_data,
            "steps_remaining": self.max_steps_per_item,
            "item_budget_usd": self.per_item_usd,
            "run_budget_usd": self.per_run_usd_remaining,
            "urgency_critique_threshold": self.urgency_critique_threshold,
            "urgency_alert_threshold": self.urgency_alert_threshold,
        }

        steps_executed = 0

        # Step loop
        for step_index in range(self.max_steps_per_item):
            steps_executed += 1
            # Budget check before next step
            if context["item_budget_usd"] <= 0.0 or self.per_run_usd_remaining <= 0.0:
                final_status = ItemStatus.PARTIAL
                error_msg = "Cost budget exhausted before completion"
                self._emit_trace_event(
                    item=item,
                    step_index=step_index,
                    planner_mode=PlannerMode.FALLBACK,
                    tool=ToolName.FINISH,
                    arguments={},
                    result={"error": error_msg},
                    rationale="Budget limit reached; halting item processing safely.",
                    status=ItemStatus.PARTIAL,
                    fallback_used=True,
                    context=context,
                    latency_ms=0.0,
                    error_code="BudgetExhaustedError",
                )
                break

            # Planner selects action
            step_start = time.perf_counter()
            try:
                action_req, planner_mode, fallback_used, rationale = self.planner.select_action(
                    item, context
                )
            except Exception as e:
                # Catch unexpected planner failure and activate fallback
                fallback_used = True
                planner_mode = PlannerMode.FALLBACK
                action_req = ActionRequest(
                    action=ToolName.FINISH,
                    rationale=f"Planner threw unexpected exception: {e}",
                    arguments={},
                )
                rationale = f"Emergency fallback triggered: {e}"

            if fallback_used:
                fallback_used_overall = True

            # Collect token and latency measurements from planner if recorded
            tok_in = context.pop("last_tokens_in", 0) or 0
            tok_out = context.pop("last_tokens_out", 0) or 0
            planner_latency = context.pop("last_latency_ms", 0.0) or 0.0
            total_tokens_in += tok_in
            total_tokens_out += tok_out

            # Estimate cost (local inference is 0 USD, but cloud/mock cost tracked if > 0)
            step_cost = 0.0
            if tok_in > 0 or tok_out > 0:
                # $0.15 / 1M input tokens, $0.60 / 1M output tokens (standard small model benchmark)
                step_cost = (tok_in * 0.15 + tok_out * 0.60) / 1_000_000.0
                item_cost_used += step_cost
                self.per_run_usd_remaining = max(0.0, self.per_run_usd_remaining - step_cost)
                context["item_budget_usd"] = max(0.0, context["item_budget_usd"] - step_cost)
                context["run_budget_usd"] = self.per_run_usd_remaining

            # Candidate action validation: validate against permitted actions for current state
            is_valid, validation_err = self._validate_candidate_action(
                action_req=action_req,
                item=item,
                context=context,
            )
            if not is_valid:
                step_latency_ms = (time.perf_counter() - step_start) * 1000.0
                total_latency_ms += step_latency_ms
                final_status = ItemStatus.PARTIAL
                error_msg = validation_err
                err_code = validation_err.split(":")[0] if validation_err else "DisallowedCandidateAction"
                context["steps_remaining"] -= 1

                self._emit_trace_event(
                    item=item,
                    step_index=step_index,
                    planner_mode=planner_mode,
                    tool=action_req.action,
                    arguments=action_req.arguments,
                    result={"error": error_msg},
                    rationale=rationale or action_req.rationale,
                    status=ItemStatus.PARTIAL,
                    fallback_used=fallback_used,
                    context=context,
                    latency_ms=step_latency_ms,
                    error_code=err_code,
                )
                continue

            # Check if planner chose FINISH
            if action_req.action == ToolName.FINISH:
                step_latency_ms = (time.perf_counter() - step_start) * 1000.0
                total_latency_ms += step_latency_ms

                # Enforce requirement: A required tool failure must not be followed by a successful finish marking COMPLETED
                has_mandatory_failure = len(failed_tools) > 0
                missing_mandatory = []
                if ToolName.CLASSIFY_SCORE.value not in completed_tool_data:
                    missing_mandatory.append("classify_score")

                if has_mandatory_failure or missing_mandatory:
                    final_status = ItemStatus.PARTIAL
                    reasons = []
                    if failed_tools:
                        reasons.append(f"failed tools: {[t.value for t in failed_tools]}")
                    if missing_mandatory:
                        reasons.append(f"unresolved mandatory stages: {missing_mandatory}")
                    error_msg = f"IncompleteProcessingError: Finish attempted but {'; '.join(reasons)}"
                else:
                    final_status = ItemStatus.COMPLETED

                self._emit_trace_event(
                    item=item,
                    step_index=step_index,
                    planner_mode=planner_mode,
                    tool=ToolName.FINISH,
                    arguments=action_req.arguments,
                    result={"finished": True, "final_status": final_status.value},
                    rationale=rationale or action_req.rationale,
                    status=final_status,
                    fallback_used=fallback_used,
                    context=context,
                    latency_ms=step_latency_ms,
                    tokens_in=tok_in if tok_in > 0 else None,
                    tokens_out=tok_out if tok_out > 0 else None,
                    cost_usd=step_cost if step_cost > 0 else None,
                    error_code="IncompleteProcessingError" if final_status != ItemStatus.COMPLETED else None,
                )
                break

            # Execute tool through registered handler
            tool_start = time.perf_counter()
            tool_result: ToolResult = self.tool_registry.execute(
                tool_name=action_req.action,
                arguments=action_req.arguments,
                context=context,
            )
            tool_latency_ms = (time.perf_counter() - tool_start) * 1000.0
            step_latency_ms = ((time.perf_counter() - step_start) * 1000.0) + planner_latency
            total_latency_ms += step_latency_ms

            # Update context state
            context["steps_remaining"] -= 1
            completed_tools.append(action_req.action)
            completed_tool_data[action_req.action.value] = tool_result.data

            step_status = ItemStatus.IN_PROGRESS if tool_result.status == "success" else ItemStatus.PARTIAL
            if tool_result.status == "error":
                error_msg = tool_result.error_message
                failed_tools.append(action_req.action)

            self._emit_trace_event(
                item=item,
                step_index=step_index,
                planner_mode=planner_mode,
                tool=action_req.action,
                arguments=action_req.arguments,
                result=tool_result.data if tool_result.status == "success" else {"error": tool_result.error_message},
                rationale=rationale or action_req.rationale,
                status=step_status,
                fallback_used=fallback_used,
                context=context,
                latency_ms=step_latency_ms,
                tokens_in=tok_in if tok_in > 0 else None,
                tokens_out=tok_out if tok_out > 0 else None,
                cost_usd=step_cost if step_cost > 0 else None,
                error_code=tool_result.error_message if tool_result.status == "error" else None,
            )
        else:
            # Reached max_steps_per_item without FINISH
            final_status = ItemStatus.PARTIAL
            if not error_msg:
                error_msg = f"Step limit ({self.max_steps_per_item}) exhausted before completion"
            else:
                error_msg = f"{error_msg}; Step limit ({self.max_steps_per_item}) exhausted before completion"

        # Extract structured final artifacts from completed tool data
        classification_res: Optional[ClassificationResult] = None
        if "classify_score" in completed_tool_data:
            c_data = completed_tool_data["classify_score"]
            try:
                classification_res = ClassificationResult.model_validate(c_data)
            except Exception:
                pass

        verification_res: Optional[VerificationResult] = None
        if "verify_claim" in completed_tool_data:
            v_data = completed_tool_data["verify_claim"]
            try:
                verification_res = VerificationResult.model_validate(v_data)
            except Exception:
                pass

        critique_res: Optional[CritiqueResult] = None
        if "critique_item" in completed_tool_data:
            cr_data = completed_tool_data["critique_item"]
            try:
                critique_res = CritiqueResult.model_validate(cr_data)
            except Exception:
                pass

        alert_prop: Optional[AlertProposal] = None
        if "propose_alert" in completed_tool_data and self.storage:
            p_data = completed_tool_data["propose_alert"]
            prop_id = p_data.get("proposal_id")
            if prop_id:
                alert_prop = self.storage.get_alert_proposal(prop_id)

        cluster_id: Optional[str] = None
        if "search_memory" in completed_tool_data:
            cluster_id = completed_tool_data["search_memory"].get("cluster_id")

        # Persist post-critique urgency and verification status to storage
        if self.storage:
            try:
                post_urg = critique_res.post_critique_urgency if critique_res else None
                v_stat = verification_res.status.value if verification_res else None
                if post_urg is not None or v_stat is not None:
                    self.storage.save_item_features(
                        item_id=item.item_id,
                        post_critique_urgency=post_urg,
                        verification_status=v_stat,
                    )
            except Exception:
                pass

        return ItemProcessingResult(
            item_id=item.item_id,
            status=final_status,
            steps_taken=steps_executed,
            completed_tools=completed_tools,
            final_scores=classification_res,
            verification=verification_res,
            critique=critique_res,
            alert_proposal=alert_prop,
            cluster_id=cluster_id,
            error_message=error_msg,
            fallback_used=fallback_used_overall,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            cost_usd=round(item_cost_used, 6),
            total_latency_ms=round(total_latency_ms, 2),
        )

    def _validate_candidate_action(
        self,
        action_req: ActionRequest,
        item: SourceItem,
        context: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate planner action against candidate actions currently permitted for the item's state.

        Rejects:
        - Disallowed / unregistered tools
        - Disallowed or unexpected tool arguments
        - Actions unsupported by current state (e.g., ocr without attachment)
        - Premature alert proposals
        - Repeated completed actions without an explicitly supported reason
        """
        tool = action_req.action
        tool_name = tool.value if hasattr(tool, "value") else str(tool)

        # 1. Allow-listed tool check
        if not self.tool_registry.is_allowed(tool_name):
            return False, f"DisallowedToolError: Attempted call to unregistered tool '{tool_name}'"

        completed_tools: List[ToolName] = context.get("completed_tools", [])
        completed_tool_names = [t.value if hasattr(t, "value") else str(t) for t in completed_tools]
        completed_data: Dict[str, Any] = context.get("completed_tool_data", {})
        attachments = context.get("attachments", [])
        args = action_req.arguments or {}

        # 2. Argument schema validation
        allowed_args = {
            ToolName.FETCH_ATTACHMENT.value: {"attachment_id"},
            ToolName.OCR_EXTRACT.value: {"language_hint", "attachment_id", "retry_reason"},
            ToolName.VISION_DESCRIBE.value: set(),
            ToolName.CLASSIFY_SCORE.value: set(),
            ToolName.SEARCH_MEMORY.value: set(),
            ToolName.VERIFY_CLAIM.value: {"claim_text"},
            ToolName.CRITIQUE_ITEM.value: set(),
            ToolName.PROPOSE_ALERT.value: set(),
            ToolName.FINISH.value: set(),
        }

        permitted_arg_keys = allowed_args.get(tool_name, set())
        unauthorized_args = set(args.keys()) - permitted_arg_keys
        if unauthorized_args:
            return False, f"DisallowedArgumentsError: Tool '{tool_name}' received unauthorized arguments: {sorted(list(unauthorized_args))}"

        # 3. Repeated completed actions check
        if tool_name in completed_tool_names:
            can_repeat = False
            if tool == ToolName.OCR_EXTRACT and args.get("retry_reason"):
                can_repeat = True
            elif tool == ToolName.FETCH_ATTACHMENT and args.get("attachment_id"):
                fetched_att = completed_data.get("fetch_attachment", {}).get("attachment_id")
                if fetched_att != args.get("attachment_id"):
                    can_repeat = True

            if not can_repeat:
                return False, f"RepeatedActionError: Tool '{tool_name}' has already completed and cannot be repeated without a supported reason"

        # 4. State-dependent candidate action validation
        if tool == ToolName.FETCH_ATTACHMENT:
            if not attachments:
                return False, "UnsupportedActionError: fetch_attachment requested but item has no attachments"

        elif tool == ToolName.OCR_EXTRACT:
            has_attachment_path = bool(
                completed_data.get("fetch_attachment", {}).get("local_path") or
                (attachments and getattr(attachments[0], "local_path", None))
            )
            if not has_attachment_path:
                return False, "UnsupportedActionError: ocr_extract requested but no attachment local path is available"

        elif tool == ToolName.VISION_DESCRIBE:
            ocr_res = completed_data.get("ocr_extract", {})
            if not ocr_res.get("needs_second_opinion"):
                return False, "UnsupportedActionError: vision_describe requested without OCR second-opinion requirement"

        elif tool == ToolName.VERIFY_CLAIM:
            if ToolName.CLASSIFY_SCORE.value not in completed_tool_names:
                return False, "UnsupportedActionError: verify_claim requested before classify_score"
            urgency = float(completed_data.get("classify_score", {}).get("urgency_score", 0.0))
            if urgency <= 75.0:
                return False, f"UnsupportedActionError: verify_claim requested but urgency {urgency} is below threshold 75.0"

        elif tool == ToolName.CRITIQUE_ITEM:
            if ToolName.CLASSIFY_SCORE.value not in completed_tool_names:
                return False, "UnsupportedActionError: critique_item requested before classify_score"
            urgency = float(completed_data.get("classify_score", {}).get("urgency_score", 0.0))
            if urgency <= 75.0:
                return False, f"UnsupportedActionError: critique_item requested but urgency {urgency} is below threshold 75.0"

        elif tool == ToolName.PROPOSE_ALERT:
            if ToolName.CLASSIFY_SCORE.value not in completed_tool_names:
                return False, "PrematureAlertProposalError: propose_alert requested before classify_score"
            if ToolName.VERIFY_CLAIM.value not in completed_tool_names:
                return False, "PrematureAlertProposalError: propose_alert requested before verify_claim"
            if ToolName.CRITIQUE_ITEM.value not in completed_tool_names:
                return False, "PrematureAlertProposalError: propose_alert requested before critique_item"

            critique_data = completed_data.get("critique_item", {})
            post_urgency = float(critique_data.get("post_critique_urgency", 0.0))
            threshold = context.get("urgency_alert_threshold", self.urgency_alert_threshold)
            if post_urgency < threshold:
                return False, f"PrematureAlertProposalError: post-critique urgency {post_urgency} is below threshold {threshold}"

            verify_data = completed_data.get("verify_claim", {})
            if verify_data.get("status") != "supported":
                return False, f"PrematureAlertProposalError: claim verification status is '{verify_data.get('status')}', not 'supported'"

            if critique_data.get("should_propose_alert") is False:
                return False, "PrematureAlertProposalError: critique decided item does not warrant alert proposal"

        return True, None

    def _emit_trace_event(
        self,
        item: SourceItem,
        step_index: int,
        planner_mode: PlannerMode,
        tool: ToolName,
        arguments: Dict[str, Any],
        result: Dict[str, Any],
        rationale: str,
        status: ItemStatus,
        fallback_used: bool,
        context: Dict[str, Any],
        latency_ms: float,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        cost_usd: Optional[float] = None,
        error_code: Optional[str] = None,
    ) -> None:
        """Create and emit a structured TraceEvent to JSONL file."""
        if not self.tracer:
            return

        budget_rem = BudgetState(
            item_usd=max(0.0, round(float(context.get("item_budget_usd", 0.0)), 4)),
            run_usd=max(0.0, round(float(context.get("run_budget_usd", 0.0)), 4)),
            steps=max(0, int(context.get("steps_remaining", 0))),
        )

        model_name = "fallback" if fallback_used else getattr(getattr(self.planner, "llm_client", None), "model", "llm")

        fault_injected = None
        fault_recovery = None
        attempt_count = None
        fault_injector = context.get("fault_injector")
        item_index = context.get("item_index", 0)
        if fault_injector:
            matching = [f for f in getattr(fault_injector, "triggered_faults", []) if f.target_item_index == item_index]
            if matching:
                latest = matching[-1]
                fault_injected = latest.fault_type
                fault_recovery = latest.outcome_message
                attempt_count = latest.attempts

        event = TraceEvent(
            run_id=self.run_id,
            item_id=item.item_id,
            step_index=step_index,
            timestamp_utc=utc_now(),
            planner_mode=planner_mode,
            tool=tool,
            arguments_summary=sanitize_summary(arguments),
            result_summary=sanitize_summary(result),
            decision_rationale=rationale,
            input_hashes=[item.content_hash],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=round(latency_ms, 2),
            status=status,
            fallback_used=fallback_used,
            error_code=error_code,
            budget_remaining=budget_rem,
            cache_hit=context.pop("cache_hit", False),
            model=model_name,
            fault_injected=fault_injected,
            fault_recovery_outcome=fault_recovery,
            attempt_count=attempt_count,
        )

        try:
            self.tracer.write_event(event)
        except Exception as e:
            # Tracer writing failure should not crash controller execution
            pass
