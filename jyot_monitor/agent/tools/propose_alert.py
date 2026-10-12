"""
propose_alert tool implementation.

Creates a persisted alert proposal in SQLite approval queue.
Never sends an alert automatically; requires human approval command.
"""

from typing import Any, Dict
import uuid

from jyot_monitor.models import (
    AlertProposal,
    ProposalStatus,
    SourceItem,
    ToolName,
    ToolResult,
    utc_now,
)


def execute_propose_alert(arguments: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
    """Create a pending alert proposal with structured evidence."""
    storage = context.get("storage")
    item: SourceItem = context.get("item")
    if not storage or not item:
        return ToolResult(
            tool_name=ToolName.PROPOSE_ALERT,
            status="error",
            error_message="ContextError: Storage or item instance missing from context.",
            is_evidence=False,
        )

    completed_data = context.get("completed_tool_data", {})
    classify_data = completed_data.get("classify_score", {})
    critique_data = completed_data.get("critique_item", {})
    verify_data = completed_data.get("verify_claim", {})
    ocr_data = completed_data.get("ocr_extract", {})

    urgency = float(critique_data.get("post_critique_urgency") or classify_data.get("urgency_score") or 0.0)

    # Threshold check
    urgency_threshold = context.get("urgency_alert_threshold", 85.0)
    if urgency < urgency_threshold:
        return ToolResult(
            tool_name=ToolName.PROPOSE_ALERT,
            status="error",
            error_message=f"ThresholdNotMetError: Urgency {urgency} does not meet alert threshold {urgency_threshold}.",
            is_evidence=False,
        )

    # Evidence construction
    evidence_snippet = (
        classify_data.get("evidence_snippets", [item.title])[0]
        if classify_data.get("evidence_snippets")
        else item.title
    )
    confidence = float(ocr_data.get("normalized_confidence") or 0.9)
    run_id = context.get("run_id", "run_standalone")

    evidence_json = {
        "source_url": item.url,
        "source_name": item.source,
        "title": item.title,
        "evidence_snippet": evidence_snippet,
        "confidence": confidence,
        "verification_status": verify_data.get("status", "unverified"),
        "verification_rationale": verify_data.get("rationale", ""),
        "critique_summary": critique_data.get("critique_rationale", ""),
        "urgency_rationale": f"Urgency score {urgency} exceeded alert threshold {urgency_threshold}.",
        "run_id": run_id,
    }

    proposal_id = f"prop_{uuid.uuid4().hex[:12]}"
    proposal = AlertProposal(
        proposal_id=proposal_id,
        item_id=item.item_id,
        urgency=urgency,
        evidence_json=evidence_json,
        status=ProposalStatus.PENDING,
        created_time=utc_now(),
    )

    storage.save_alert_proposal(proposal)

    return ToolResult(
        tool_name=ToolName.PROPOSE_ALERT,
        status="success",
        data={
            "proposal_id": proposal_id,
            "item_id": item.item_id,
            "status": "pending",
            "urgency": urgency,
            "evidence_json": evidence_json,
            "message": "Alert proposal successfully created in pending approval queue. Requires human approval.",
        },
        is_evidence=True,
    )
