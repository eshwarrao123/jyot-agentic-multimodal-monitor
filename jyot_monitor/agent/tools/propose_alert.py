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
    """Create a pending alert proposal with structured evidence (idempotent)."""
    storage = context.get("storage")
    item: SourceItem = context.get("item")
    if not storage or not item:
        return ToolResult(
            tool_name=ToolName.PROPOSE_ALERT,
            status="error",
            error_message="ContextError: Storage or item instance missing from context.",
            is_evidence=False,
        )

    # Disallowed arguments check
    if arguments:
        return ToolResult(
            tool_name=ToolName.PROPOSE_ALERT,
            status="error",
            error_message=f"DisallowedArgumentsError: propose_alert does not accept arguments: {arguments}",
            is_evidence=False,
        )

    completed_data = context.get("completed_tool_data", {})
    classify_data = completed_data.get("classify_score", {})
    critique_data = completed_data.get("critique_item")
    verify_data = completed_data.get("verify_claim")
    ocr_data = completed_data.get("ocr_extract", {})

    # 1. Prerequisite check: critique_item must have executed
    if not critique_data:
        return ToolResult(
            tool_name=ToolName.PROPOSE_ALERT,
            status="error",
            error_message="PrerequisiteNotMetError: critique_item must be executed before propose_alert.",
            is_evidence=False,
        )

    # 2. Prerequisite check: verify_claim must have executed
    if not verify_data:
        return ToolResult(
            tool_name=ToolName.PROPOSE_ALERT,
            status="error",
            error_message="PrerequisiteNotMetError: verify_claim must be executed before propose_alert.",
            is_evidence=False,
        )

    # 3. Sufficient post-critique urgency
    urgency = float(critique_data.get("post_critique_urgency") or 0.0)
    urgency_threshold = context.get("urgency_alert_threshold", 85.0)
    if urgency < urgency_threshold:
        return ToolResult(
            tool_name=ToolName.PROPOSE_ALERT,
            status="error",
            error_message=f"ThresholdNotMetError: Post-critique urgency {urgency} does not meet alert threshold {urgency_threshold}.",
            is_evidence=False,
        )

    # 4. Valid verification result from sufficiently independent evidence
    verify_status = verify_data.get("status")
    indep_count = int(verify_data.get("independent_sources_count", 2 if verify_status == "supported" else 1))
    if verify_status != "supported" or indep_count < 2:
        return ToolResult(
            tool_name=ToolName.PROPOSE_ALERT,
            status="error",
            error_message=f"VerificationIntegrityError: Claim verification not supported by independent evidence (status={verify_status}, independent_sources={indep_count}).",
            is_evidence=False,
        )

    # 5. Explicit decision that the item warrants a proposal
    if critique_data.get("should_propose_alert") is False:
        return ToolResult(
            tool_name=ToolName.PROPOSE_ALERT,
            status="error",
            error_message="DecisionError: Critique decided this item does not warrant an alert proposal.",
            is_evidence=False,
        )

    # Idempotent safeguard: check if proposal already exists for this item or story cluster
    existing_prop = storage.get_alert_proposal_for_item_or_cluster(item.item_id)
    if existing_prop:
        return ToolResult(
            tool_name=ToolName.PROPOSE_ALERT,
            status="success",
            data={
                "proposal_id": existing_prop.proposal_id,
                "item_id": existing_prop.item_id,
                "status": existing_prop.status.value,
                "urgency": existing_prop.urgency,
                "evidence_json": existing_prop.evidence_json,
                "message": "Existing alert proposal referenced (idempotent; no duplicate created).",
                "is_existing": True,
            },
            is_evidence=True,
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
            "is_existing": False,
        },
        is_evidence=True,
    )
