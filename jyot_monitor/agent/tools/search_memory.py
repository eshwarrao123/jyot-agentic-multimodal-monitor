"""
search_memory tool implementation.

Queries persistent SQLite state for:
1. Exact and near-duplicate items.
2. Perceptual image hash matches.
3. Story cluster membership.
4. Prior reporting state (new, escalated, previously_reported, duplicate).
"""

from typing import Any, Dict
from jyot_monitor.dedup import StoryClusterManager, compute_image_dhash
from jyot_monitor.models import SourceItem, ToolName, ToolResult


def execute_search_memory(arguments: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
    """Query persistent storage for related stories and prior reporting status."""
    storage = context.get("storage")
    item: SourceItem = context.get("item")
    if not storage or not item:
        return ToolResult(
            tool_name=ToolName.SEARCH_MEMORY,
            status="error",
            error_message="ContextError: Storage or item instance missing from execution context.",
            is_evidence=False,
        )

    # Get OCR text from previous steps if available
    ocr_res = context.get("completed_tool_data", {}).get("ocr_extract", {})
    ocr_text = ocr_res.get("text", "")
    ocr_conf = ocr_res.get("normalized_confidence")

    # Get local image path if available to compute phash
    fetch_res = context.get("completed_tool_data", {}).get("fetch_attachment", {})
    local_path = fetch_res.get("local_path")
    image_phash = None
    if local_path and not str(local_path).lower().endswith(".pdf"):
        try:
            image_phash = compute_image_dhash(local_path)
        except Exception:
            pass

    cluster_mgr = StoryClusterManager(storage)
    has_attachment = bool(local_path or context.get("attachments"))

    cluster, is_new, sim_score, match_type = cluster_mgr.match_or_create_cluster(
        item=item,
        image_phash=image_phash,
        ocr_text=ocr_text,
        ocr_confidence=ocr_conf,
        has_attachment=has_attachment,
    )

    # Determine reporting status
    if is_new:
        reporting_status = "new"
    elif match_type in ("exact_content_hash", "image_phash_hamming_0", "text_jaccard_near_duplicate") and sim_score >= 0.95:
        reporting_status = "duplicate"
    else:
        reporting_status = "escalated" if len(cluster.member_item_ids) > 2 else "previously_reported"

    # Persist features for future memory searches
    storage.save_item_features(
        item_id=item.item_id,
        image_phash=image_phash,
        ocr_text=ocr_text,
        reporting_status=reporting_status,
    )

    return ToolResult(
        tool_name=ToolName.SEARCH_MEMORY,
        status="success",
        data={
            "cluster_id": cluster.cluster_id,
            "is_new_cluster": is_new,
            "representative_item_id": cluster.representative_item_id,
            "member_count": len(cluster.member_item_ids),
            "member_item_ids": cluster.member_item_ids,
            "similarity_score": round(sim_score, 4),
            "match_type": match_type,
            "reporting_status": reporting_status,
            "image_phash": image_phash,
        },
        is_evidence=True,
    )
