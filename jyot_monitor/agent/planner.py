"""
Planner module for LLM-driven action selection and deterministic fallback.

Implements:
1. LLMPlanner: Formats prompt with untrusted data delimiters, calls LLM, validates ActionRequest schema.
2. Bounded retries (up to 3) on invalid JSON/schema failure.
3. DeterministicFallbackPlanner: Explicit fallback when LLM is unavailable.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from jyot_monitor.llm.client import BaseLLMClient, LLMResponse
from jyot_monitor.models import (
    ActionRequest,
    PlannerMode,
    SourceItem,
    ToolName,
)


# Devanagari Unicode range: \u0900-\u097F
DEVANAGARI_REGEX = re.compile(r"[\u0900-\u097F]")


def contains_devanagari(text: str) -> bool:
    """Check if string contains any Devanagari script characters."""
    return bool(DEVANAGARI_REGEX.search(text))


def detect_language_hint(item: SourceItem, ocr_text: str = "") -> str:
    """
    Detect appropriate language hint from item content.
    
    Checks for Devanagari script in title, body, or OCR text.
    Returns 'hi' for Hindi/Devanagari content, 'en' otherwise.
    """
    full_text = f"{item.title}\n{item.body or ''}\n{ocr_text}"
    if contains_devanagari(full_text):
        return "hi"
    return "en"


def load_prompt_template(filename: str) -> str:
    """Load prompt template from prompts/ directory."""
    prompt_path = Path("prompts") / filename
    if prompt_path.is_file():
        return prompt_path.read_text(encoding="utf-8")
    return ""


class DeterministicFallbackPlanner:
    """
    Deterministic rule-based planner.
    
    Used when local LLM is unavailable or repeatedly produces invalid output.
    Must always be recorded as fallback mode.
    """

    def select_action(
        self,
        item: SourceItem,
        context: Dict[str, Any],
    ) -> Tuple[ActionRequest, PlannerMode, bool, Optional[str]]:
        """Determine next action using deterministic rules."""
        completed_tools: List[str] = [t.value for t in context.get("completed_tools", [])]
        completed_data: Dict[str, Any] = context.get("completed_tool_data", {})
        attachments = context.get("attachments", [])

        # Rule 1: Fetch attachment if present and not yet fetched
        if attachments and ToolName.FETCH_ATTACHMENT.value not in completed_tools:
            att = attachments[0]
            att_id = getattr(att, "attachment_id", "att_1")
            return (
                ActionRequest(
                    action=ToolName.FETCH_ATTACHMENT,
                    rationale="Attachment present; fetching attachment into local context.",
                    arguments={"attachment_id": att_id},
                ),
                PlannerMode.FALLBACK,
                True,
                "Deterministic rule: fetch attachment",
            )

        # Rule 2: OCR extract if attachment fetched and not yet OCR'd
        has_attachment_path = bool(
            completed_data.get("fetch_attachment", {}).get("local_path") or
            (attachments and getattr(attachments[0], "local_path", None))
        )
        if has_attachment_path and ToolName.OCR_EXTRACT.value not in completed_tools:
            # Detect language hint from item content
            lang_hint = detect_language_hint(item)
            return (
                ActionRequest(
                    action=ToolName.OCR_EXTRACT,
                    rationale="Visual/PDF attachment available; extracting text via multi-engine OCR router.",
                    arguments={"language_hint": lang_hint},
                ),
                PlannerMode.FALLBACK,
                True,
                "Deterministic rule: run OCR",
            )

        # Rule 3: Vision describe if OCR requested a second opinion
        ocr_res = completed_data.get("ocr_extract", {})
        if ocr_res.get("needs_second_opinion") and ToolName.VISION_DESCRIBE.value not in completed_tools:
            return (
                ActionRequest(
                    action=ToolName.VISION_DESCRIBE,
                    rationale="OCR confidence is low or second opinion requested; requesting vision description.",
                    arguments={},
                ),
                PlannerMode.FALLBACK,
                True,
                "Deterministic rule: vision describe",
            )

        # Rule 4: Classify and score if not yet done
        if ToolName.CLASSIFY_SCORE.value not in completed_tools:
            return (
                ActionRequest(
                    action=ToolName.CLASSIFY_SCORE,
                    rationale="Evaluating relevance and urgency using taxonomy and source signals.",
                    arguments={},
                ),
                PlannerMode.FALLBACK,
                True,
                "Deterministic rule: classify and score",
            )

        # Rule 5: Memory search if not yet done
        if ToolName.SEARCH_MEMORY.value not in completed_tools:
            return (
                ActionRequest(
                    action=ToolName.SEARCH_MEMORY,
                    rationale="Querying persistent memory for duplicate clusters and prior reporting state.",
                    arguments={},
                ),
                PlannerMode.FALLBACK,
                True,
                "Deterministic rule: search memory",
            )

        classify_res = completed_data.get("classify_score", {})
        urgency = float(classify_res.get("urgency_score", 0.0))

        # Rule 6: If urgency > 75, verify claim
        if urgency > 75.0 and ToolName.VERIFY_CLAIM.value not in completed_tools:
            return (
                ActionRequest(
                    action=ToolName.VERIFY_CLAIM,
                    rationale="High urgency detected; verifying claim against independent sources in memory.",
                    arguments={"claim_text": item.title},
                ),
                PlannerMode.FALLBACK,
                True,
                "Deterministic rule: verify claim",
            )

        # Rule 7: If urgency > 75, run critique self-check
        if urgency > 75.0 and ToolName.CRITIQUE_ITEM.value not in completed_tools:
            return (
                ActionRequest(
                    action=ToolName.CRITIQUE_ITEM,
                    rationale="Self-checking high urgency before potential alert proposal.",
                    arguments={},
                ),
                PlannerMode.FALLBACK,
                True,
                "Deterministic rule: critique item",
            )

        # Rule 8: If post-critique urgency >= 85 and verified, propose alert
        critique_res = completed_data.get("critique_item", {})
        post_urgency = float(critique_res.get("post_critique_urgency", urgency))
        verify_status = completed_data.get("verify_claim", {}).get("status", "unverified")

        if (
            post_urgency >= 85.0 and
            verify_status == "supported" and
            ToolName.PROPOSE_ALERT.value not in completed_tools
        ):
            return (
                ActionRequest(
                    action=ToolName.PROPOSE_ALERT,
                    rationale="Urgency remains high post-critique and claim is verified; generating alert proposal.",
                    arguments={},
                ),
                PlannerMode.FALLBACK,
                True,
                "Deterministic rule: propose alert",
            )

        # Finish
        return (
            ActionRequest(
                action=ToolName.FINISH,
                rationale="All necessary pipeline stages complete for this item.",
                arguments={},
            ),
            PlannerMode.FALLBACK,
            True,
            "Deterministic rule: finish processing",
        )


class LLMPlanner:
    """
    LLM-driven planner component.
    
    Asks the configured LLM to choose the next action from the bounded tool set.
    Validates output with ActionRequest schema and handles bounded retries.
    Falls back gracefully to DeterministicFallbackPlanner if LLM is unavailable.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        max_retries: int = 3,
        allow_fallback: bool = True,
    ):
        self.llm_client = llm_client
        self.max_retries = max_retries
        self.allow_fallback = allow_fallback
        self.fallback_planner = DeterministicFallbackPlanner()
        self.system_prompt = load_prompt_template("planner_system.txt")
        self.user_template = load_prompt_template("planner_user_template.txt")

    def select_action(
        self,
        item: SourceItem,
        context: Dict[str, Any],
    ) -> Tuple[ActionRequest, PlannerMode, bool, Optional[str]]:
        """
        Request next action from LLM with schema validation and bounded retries.
        """
        completed_tools = [t.value for t in context.get("completed_tools", [])]
        completed_data = context.get("completed_tool_data", {})
        attachments = context.get("attachments", [])

        completed_tools_set = set(completed_tools)
        candidates = []

        if attachments and "fetch_attachment" not in completed_tools_set:
            att_id = getattr(attachments[0], "attachment_id", "att_1")
            candidates.append(f'- fetch_attachment: Load attachment into local context (arguments: {{"attachment_id": "{att_id}"}})')

        has_attachment_path = bool(
            completed_data.get("fetch_attachment", {}).get("local_path")
        )
        if has_attachment_path and "ocr_extract" not in completed_tools_set:
            # Detect language hint from item content
            lang_hint = detect_language_hint(item)
            candidates.append(f'- ocr_extract: Extract text from visual attachment via OCR router (arguments: {{"language_hint": "{lang_hint}"}})')

        ocr_res = completed_data.get("ocr_extract", {})
        if ocr_res.get("needs_second_opinion") and "vision_describe" not in completed_tools_set:
            candidates.append('- vision_describe: Request vision description for complex/low-confidence image (arguments: {})')

        if "classify_score" not in completed_tools_set:
            candidates.append('- classify_score: Classify recall taxonomy and compute relevance/urgency scores (arguments: {})')

        if "search_memory" not in completed_tools_set:
            candidates.append('- search_memory: Query persistent memory for duplicate clusters and prior reports (arguments: {})')

        classify_res = completed_data.get("classify_score", {})
        urgency = float(classify_res.get("urgency_score", 0.0))

        if urgency > 75.0 and "verify_claim" not in completed_tools_set:
            clean_title = item.title.replace('"', '').replace('\n', ' ')[:80]
            candidates.append(f'- verify_claim: Cross-check urgent claim against independent records in memory (arguments: {{"claim_text": "{clean_title}"}})')

        if urgency > 75.0 and "critique_item" not in completed_tools_set:
            candidates.append('- critique_item: Challenge high urgency with self-checking critique (arguments: {})')

        critique_res = completed_data.get("critique_item", {})
        post_urgency = float(critique_res.get("post_critique_urgency", urgency))
        verify_status = completed_data.get("verify_claim", {}).get("status", "unverified")

        if post_urgency >= 85.0 and verify_status == "supported" and "propose_alert" not in completed_tools_set:
            candidates.append('- propose_alert: Draft pending alert proposal for human review (arguments: {})')

        candidates.append('- finish: Mark item processing complete (arguments: {})')
        candidate_actions_str = "\n".join(candidates)
        candidate_names = {c.split(":")[0].lstrip("- ").strip() for c in candidates}

        user_prompt = self.user_template.format(
            item_id=item.item_id,
            source=item.source,
            has_attachments=bool(attachments),
            completed_actions=", ".join(completed_tools) if completed_tools else "None",
            steps_remaining=context.get("steps_remaining", 10),
            item_budget_usd=context.get("item_budget_usd", 0.10),
            ocr_summary=completed_data.get("ocr_extract", {}).get("text", "None")[:200],
            classification_summary=completed_data.get("classify_score", {}).get("taxonomy", "None"),
            memory_summary=completed_data.get("search_memory", {}).get("reporting_status", "None"),
            verification_summary=completed_data.get("verify_claim", {}).get("status", "None"),
            critique_summary=completed_data.get("critique_item", {}).get("critique_rationale", "None"),
            candidate_actions=candidate_actions_str,
            title=item.title,
            body=(item.body or "No body text provided")[:500],
        )

        # Fault injection check for malformed JSON
        fault_injector = context.get("fault_injector")
        item_index = context.get("item_index", 0)
        inject_malformed = bool(fault_injector and fault_injector.should_inject("malformed_json", item_index))
        if inject_malformed:
            fault_injector.record_fault("malformed_json", item_index, "Simulated malformed LLM JSON output", recovered=True, outcome_message="Recovered via bounded retries and fallback")

        # Check LLM response cache
        storage = context.get("storage")
        model_name = getattr(self.llm_client, "model", "qwen2.5:3b")
        prompt_bytes = (self.system_prompt + "\n---\n" + user_prompt).encode("utf-8")
        input_hash = hashlib.sha256(prompt_bytes).hexdigest()

        if storage and not inject_malformed:
            cached = storage.get_llm_cache(input_hash, model_name)
            if cached and cached.get("response_json"):
                try:
                    parsed = json.loads(cached["response_json"])
                    action_req = ActionRequest.model_validate(parsed)
                    context["cache_hit"] = True
                    return (
                        action_req,
                        PlannerMode.LLM,
                        False,
                        f"LLM decision (cached {model_name}): {action_req.rationale}",
                    )
                except Exception:
                    pass

        last_error = None
        for attempt in range(self.max_retries):
            if inject_malformed:
                # Simulated unparseable JSON
                resp = LLMResponse(content='{"action": "malformed_json, invalid_syntax...', error=None)
            else:
                resp = self.llm_client.generate(
                    prompt=user_prompt,
                    system=self.system_prompt,
                    json_format=True,
                    temperature=0.0,
                )

            # Record token usage into context for budgeting
            if resp.tokens_in is not None:
                context["last_tokens_in"] = resp.tokens_in
            if resp.tokens_out is not None:
                context["last_tokens_out"] = resp.tokens_out
            if resp.latency_ms is not None:
                context["last_latency_ms"] = resp.latency_ms

            if resp.error:
                last_error = resp.error
                if not self.allow_fallback:
                    raise RuntimeError(f"Strict LLM execution failed: {resp.error}")
                break

            if resp.parsed_json:
                try:
                    action_req = ActionRequest.model_validate(resp.parsed_json)
                    # Cache successful LLM decision
                    if storage:
                        try:
                            storage.save_llm_cache(
                                input_hash=input_hash,
                                model=model_name,
                                response_json=json.dumps(resp.parsed_json),
                                prompt_version=input_hash[:16],
                                tokens_in=resp.tokens_in,
                                tokens_out=resp.tokens_out,
                            )
                        except Exception:
                            pass

                    return (
                        action_req,
                        PlannerMode.LLM,
                        False,
                        f"LLM decision ({resp.model}): {action_req.rationale}",
                    )
                except Exception as e:
                    last_error = f"Schema validation error: {e}"
                    continue

        if not self.allow_fallback:
            raise RuntimeError(f"Strict LLM execution failed after {self.max_retries} attempts: {last_error}")

        # If LLM failed or was unavailable, fall back deterministically
        action_req, mode, _, rule_rationale = self.fallback_planner.select_action(item, context)
        return (
            action_req,
            PlannerMode.FALLBACK,
            True,
            f"Fallback activated after LLM unavail/error: {rule_rationale}",
        )
