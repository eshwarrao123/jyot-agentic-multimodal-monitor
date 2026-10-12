"""
verify_claim tool implementation.

Enforces:
1. Verification against independent evidence in memory/current run.
2. Exact reposts/duplicate copies do NOT count as independent corroboration.
3. If no independent evidence exists, returns typed insufficient_evidence result.
4. Never fabricates verification.
"""

import re
from typing import Any, Dict, List, Set
from urllib.parse import urlparse

from jyot_monitor.dedup import compute_text_containment, compute_text_jaccard
from jyot_monitor.models import (
    RecallTaxonomy,
    SourceItem,
    ToolName,
    ToolResult,
    VerificationResult,
    VerificationStatus,
)

GENERIC_RECALL_WORDS: Set[str] = {
    "recall", "recalls", "safety", "warning", "warnings", "alert", "alerts",
    "notice", "notices", "urgent", "consumer", "product", "products", "hazard",
    "hazards", "risk", "risks", "fda", "cpsc", "usda", "cdc", "nhtsa", "epa",
    "announces", "announced", "issued", "issues", "the", "a", "an", "of", "in",
    "on", "at", "to", "for", "with", "by", "from", "and", "or", "is", "are",
    "was", "were", "be", "this", "that", "it", "as", "new", "update", "press",
    "release", "statement", "public", "health", "department", "agency"
}


def extract_substantive_tokens(text: str) -> Set[str]:
    """Extract substantive tokens excluding boilerplate recall stop-words."""
    words = re.findall(r"\b[a-zA-Z0-9_-]+\b", text.lower())
    return {w for w in words if w not in GENERIC_RECALL_WORDS and len(w) > 2}


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

    # Retrieve existing cluster members for the item to prevent counting story duplicates
    cluster_member_ids: Set[str] = set()
    if hasattr(storage, "get_item_cluster"):
        cluster = storage.get_item_cluster(item.item_id)
        if cluster and cluster.member_item_ids:
            cluster_member_ids = set(cluster.member_item_ids)

    # Query all stored items in memory
    all_stored = storage.get_all_item_features()
    independent_matches: List[str] = []
    duplicate_copies: List[str] = []

    claim_substantive = extract_substantive_tokens(claim_text)
    item_source_norm = item.source.strip().lower()
    item_netloc = ""
    if item.url:
        try:
            item_netloc = urlparse(item.url).netloc.lower()
        except Exception:
            item_netloc = ""

    for other in all_stored:
        other_id = other["item_id"]
        if other_id == item.item_id:
            continue

        other_text = f"{other.get('title', '')} {other.get('body', '')} {other.get('ocr_text', '')}".strip()
        other_hash = other.get("content_hash")

        # 1. Exact repost or duplicate member of same story cluster
        if other_hash == item_hash or other_id in cluster_member_ids:
            duplicate_copies.append(other_id)
            continue

        # 2. Reject spam/manipulation items as corroboration
        other_tax = str(other.get("taxonomy") or "").lower()
        if other_tax == RecallTaxonomy.SPAM_MANIPULATION.value.lower() or "spam" in other_tax:
            continue

        # 3. Reject same underlying source or domain
        other_source_norm = (other.get("source") or "").strip().lower()
        if other_source_norm == item_source_norm:
            duplicate_copies.append(other_id)
            continue

        other_url = other.get("url") or ""
        if item_netloc and other_url:
            try:
                other_netloc = urlparse(other_url).netloc.lower()
                if other_netloc and other_netloc == item_netloc:
                    duplicate_copies.append(other_id)
                    continue
            except Exception:
                pass

        # 4. Check for substantive content similarity (reject generic word overlap)
        other_substantive = extract_substantive_tokens(other_text)
        if not claim_substantive or not other_substantive:
            continue

        overlap_tokens = claim_substantive.intersection(other_substantive)
        # Must share at least 2 substantive tokens, or all tokens if claim has only 1 substantive token
        min_required_overlap = min(2, len(claim_substantive))
        if len(overlap_tokens) < min_required_overlap:
            continue

        # Compute substantive Jaccard and containment
        sub_jaccard = len(overlap_tokens) / len(claim_substantive.union(other_substantive))
        sub_containment = len(overlap_tokens) / len(claim_substantive)
        sub_sim = max(sub_jaccard, sub_containment)

        # Also check general surface similarity
        raw_sim = max(
            compute_text_jaccard(claim_text, other_text),
            compute_text_containment(claim_text, other_text),
        )

        if sub_sim >= 0.30 and (raw_sim >= 0.15 or len(overlap_tokens) >= 2):
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
            rationale=f"Found {len(duplicate_copies)} duplicate repost(s) or same-source copy(s), but zero independent corroborating sources.",
        )
    else:
        v_res = VerificationResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            independent_sources_count=1,
            corroborating_item_ids=[],
            rationale="No independent corroborating sources found in persistent memory for this claim.",
        )

    # Persist verification status to storage
    if storage:
        try:
            storage.save_item_features(
                item_id=item.item_id,
                verification_status=v_res.status.value,
            )
        except Exception:
            pass

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
