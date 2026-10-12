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
from jyot_monitor.storage import Storage
from jyot_monitor.trace import Tracer


def sanitize_summary(data: Any, max_len: int = 250) -> Any:
    """Recursively redact secrets and truncate large string fields for safe tracing."""
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
        if len(data) > max_len:
            return data[:max_len] + "... [truncated]"
        return data
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

    def process_item(
        self,
        item: SourceItem,
        attachments: Optional[List[Any]] = None,
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
        item_cost_used = 0.0
        total_tokens_in = 0
        total_tokens_out = 0
        total_latency_ms = 0.0
        fallback_used_overall = False
        final_status = ItemStatus.IN_PROGRESS
        error_msg: Optional[str] = None

        context: Dict[str, Any] = {
            "run_id": self.run_id,
            "item_id": item.item_id,
            "item": item,
            "attachments": attachments,
            "fixture_root": self.fixture_root,
            "storage": self.storage,
            "ocr_router": self.ocr_router,
            "completed_tools": completed_tools,
            "completed_tool_data": completed_tool_data,
            "steps_remaining": self.max_steps_per_item,
            "item_budget_usd": self.per_item_usd,
            "run_budget_usd": self.per_run_usd_remaining,
            "urgency_critique_threshold": self.urgency_critique_threshold,
            "urgency_alert_threshold": self.urgency_alert_threshold,
        }

        # Step loop
        for step_index in range(self.max_steps_per_item):
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

            # Check if planner chose FINISH
            if action_req.action == ToolName.FINISH:
                step_latency_ms = (time.perf_counter() - step_start) * 1000.0
                total_latency_ms += step_latency_ms
                final_status = ItemStatus.COMPLETED

                self._emit_trace_event(
                    item=item,
                    step_index=step_index,
                    planner_mode=planner_mode,
                    tool=ToolName.FINISH,
                    arguments=action_req.arguments,
                    result={"finished": True},
                    rationale=rationale or action_req.rationale,
                    status=ItemStatus.COMPLETED,
                    fallback_used=fallback_used,
                    context=context,
                    latency_ms=step_latency_ms,
                    tokens_in=tok_in if tok_in > 0 else None,
                    tokens_out=tok_out if tok_out > 0 else None,
                    cost_usd=step_cost if step_cost > 0 else None,
                )
                break

            # Security check: Validate tool name against registered allow-list
            if not self.tool_registry.is_allowed(action_req.action.value):
                step_latency_ms = (time.perf_counter() - step_start) * 1000.0
                total_latency_ms += step_latency_ms
                final_status = ItemStatus.PARTIAL
                error_msg = f"DisallowedToolError: Attempted call to unregistered tool '{action_req.action}'"

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
                    error_code="DisallowedToolError",
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
            error_msg = f"Step limit ({self.max_steps_per_item}) exhausted before completion"

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

        return ItemProcessingResult(
            item_id=item.item_id,
            status=final_status,
            steps_taken=len(completed_tools),
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
            model=model_name,
        )

        try:
            self.tracer.write_event(event)
        except Exception as e:
            # Tracer writing failure should not crash controller execution
            pass
