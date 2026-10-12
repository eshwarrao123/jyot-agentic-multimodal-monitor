"""
verify_claim tool implementation.

Enforces:
1. Verification against independent evidence in memory/current run.
2. Exact reposts/duplicate copies do NOT count as independent corroboration.
3. If no independent evidence exists, returns typed insufficient_evidence result.
4. Never fabricates verification.
"""

from typing import Any, Dict, List
from jyot_monitor.dedup import compute_text_jaccard, compute_text_containment
from jyot_monitor.models import (
    SourceItem,
    ToolName,
    ToolResult,
    VerificationResult,
    VerificationStatus,
)


def execute_verify_claim(arguments: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
    """Verify urgent claim against independent stored sources."""
    storage = context.get("storage")
    item: SourceItem = context.get("item")
    if not storage or not item:
        return ToolResult(
            tool_name=ToolName.VERIFY_CLAIM,
            status="error",
            error_message="ContextError: Storage or item missing from execution context.",
            is_evidence=False,
        )

    claim_text = arguments.get("claim_text") or item.title
    item_hash = item.content_hash

    # Query all stored items in memory
    all_stored = storage.get_all_item_features()
    independent_matches: List[str] = []
    duplicate_copies: List[str] = []

    for other in all_stored:
        other_id = other["item_id"]
        if other_id == item.item_id:
            continue

        other_text = f"{other.get('title', '')} {other.get('body', '')}".strip()
        other_hash = other.get("content_hash")

        # Check if it's an exact duplicate copy
        if other_hash == item_hash:
            duplicate_copies.append(other_id)
            continue

        # Check lexical similarity and claim containment
        sim = max(
            compute_text_jaccard(claim_text, other_text),
            compute_text_containment(claim_text, other_text),
        )
        if sim >= 0.35:
            # Check source independence: must be a different source or author
            other_src = other.get("source", "")
            if other_src.lower() != item.source.lower():
                independent_matches.append(other_id)
            elif sim >= 0.60:
                # Same source but distinct item hash and distinct ID
                independent_matches.append(other_id)

    if independent_matches:
        v_res = VerificationResult(
            status=VerificationStatus.SUPPORTED,
            independent_sources_count=len(independent_matches) + 1,
            corroborating_item_ids=independent_matches,
            rationale=f"Claim corroborated by {len(independent_matches)} independent record(s): {independent_matches}",
        )
    elif duplicate_copies:
        v_res = VerificationResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            independent_sources_count=1,
            corroborating_item_ids=[],
            rationale=f"Found {len(duplicate_copies)} duplicate repost(s), but zero independent corroborating sources.",
        )
    else:
        v_res = VerificationResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            independent_sources_count=1,
            corroborating_item_ids=[],
            rationale="No independent corroborating sources found in persistent memory for this claim.",
        )

    return ToolResult(
        tool_name=ToolName.VERIFY_CLAIM,
        status="success",
        data={
            "status": v_res.status.value,
            "independent_sources_count": v_res.independent_sources_count,
            "corroborating_item_ids": v_res.corroborating_item_ids,
            "rationale": v_res.rationale,
        },
        is_evidence=True,
    )
