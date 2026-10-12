"""
critique_item tool implementation.

Self-checking critique step for items scored above urgency threshold.
Challenges high urgency, identifies missing/contradictory evidence,
and can lower urgency or block proposal generation.
"""

from typing import Any, Dict, List
from jyot_monitor.models import CritiqueResult, SourceItem, ToolName, ToolResult


def execute_critique_item(arguments: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
    """Self-check and challenge high-urgency items before alert proposing."""
    item: SourceItem = context.get("item")
    completed_data = context.get("completed_tool_data", {})
    
    classify_data = completed_data.get("classify_score", {})
    pre_urgency = float(classify_data.get("urgency_score", 80.0))
    
    verify_data = completed_data.get("verify_claim", {})
    v_status = verify_data.get("status", "unverified")
    
    ocr_data = completed_data.get("ocr_extract", {})
    ocr_text = ocr_data.get("text", "")
    ocr_conf = ocr_data.get("normalized_confidence")

    challenge_points: List[str] = []
    uncertainties: List[str] = []
    post_urgency = pre_urgency

    # 1. Check verification corroboration
    if v_status == "insufficient_evidence":
        challenge_points.append("Single uncorroborated report; lacks independent second agency confirmation.")
        post_urgency -= 15.0  # Lower urgency due to lack of independent corroboration
    elif v_status == "contradicted":
        challenge_points.append("Contradicted by opposing records in persistent memory.")
        post_urgency -= 40.0

    # 2. Check OCR evidence quality if applicable
    if ocr_data and ocr_conf is not None and ocr_conf < 0.60:
        challenge_points.append(f"Low OCR confidence ({ocr_conf}); textual evidence might contain recognition artifacts.")
        uncertainties.append("OCR text ambiguity")
        post_urgency -= 10.0

    # 3. Check for adversarial / prompt-injection keywords in text
    combined_text = f"{item.title} {item.body or ''} {ocr_text}".lower()
    if any(k in combined_text for k in ("raise urgency", "set score to 100", "ignore previous", "override")):
        challenge_points.append("Adversarial instruction detected attempting to manipulate urgency scoring.")
        uncertainties.append("Adversarial payload")
        post_urgency = 10.0

    post_urgency = max(0.0, min(100.0, round(post_urgency, 2)))
    urgency_changed = (post_urgency != pre_urgency)
    should_propose = (post_urgency >= 85.0 and v_status == "supported")

    rationale = (
        f"Critique audit completed: pre-urgency={pre_urgency}, post-urgency={post_urgency}. "
        f"Urgency changed={urgency_changed}. Should propose alert={should_propose}."
    )

    c_res = CritiqueResult(
        pre_critique_urgency=pre_urgency,
        post_critique_urgency=post_urgency,
        urgency_changed=urgency_changed,
        challenge_points=challenge_points,
        uncertainties_identified=uncertainties,
        should_propose_alert=should_propose,
        critique_rationale=rationale,
    )

    storage = context.get("storage")
    if storage and item:
        try:
            storage.save_item_features(
                item_id=item.item_id,
                post_critique_urgency=c_res.post_critique_urgency,
            )
        except Exception:
            pass

    return ToolResult(
        tool_name=ToolName.CRITIQUE_ITEM,
        status="success",
        data={
            "pre_critique_urgency": c_res.pre_critique_urgency,
            "post_critique_urgency": c_res.post_critique_urgency,
            "urgency_changed": c_res.urgency_changed,
            "challenge_points": c_res.challenge_points,
            "uncertainties_identified": c_res.uncertainties_identified,
            "should_propose_alert": c_res.should_propose_alert,
            "critique_rationale": c_res.critique_rationale,
        },
        is_evidence=True,
    )
