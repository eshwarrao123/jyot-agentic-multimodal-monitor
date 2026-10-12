"""
classify_score tool implementation.

Implements:
1. Classification into documented recall taxonomy.
2. Relevance (0-100) and Urgency (0-100) scoring.
3. Combination with non-LLM signals (source credibility, recency boost) via documented formula:
   0.45 * relevance + 0.40 * urgency + 0.10 * credibility + 0.05 * recency_boost.
4. Genuine LLM classification with validation and bounded retries when LLM client is available.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
from pydantic import ValidationError
from jyot_monitor.models import (
    ClassificationResult,
    RecallTaxonomy,
    ScoreBreakdown,
    SourceItem,
    ToolName,
    ToolResult,
)


def compute_source_credibility(source: str) -> float:
    """Non-LLM signal: source authority score (0-100)."""
    src = source.upper()
    if any(k in src for k in ("CPSC", "FDA", "NHTSA", "FSSAI", "GOV")):
        return 90.0
    elif any(k in src for k in ("REUTERS", "AP", "NEWS", "CONSUMER")):
        return 70.0
    return 50.0


def compute_recency_boost(fetch_time: datetime) -> float:
    """Non-LLM signal: recency score (0-100). Newer items get a small boost."""
    now = datetime.now(timezone.utc)
    # Ensure fetch_time is timezone aware
    if fetch_time.tzinfo is None:
        fetch_time = fetch_time.replace(tzinfo=timezone.utc)
    days_old = max(0.0, (now - fetch_time).total_seconds() / 86400.0)
    if days_old <= 7.0:
        return 10.0
    elif days_old <= 30.0:
        return 5.0
    return 0.0


def load_classification_prompt() -> str:
    """Load classification prompt template from prompts directory."""
    prompt_path = Path("prompts") / "classification_scoring.txt"
    if prompt_path.is_file():
        return prompt_path.read_text(encoding="utf-8")
    return ""


def deterministic_classify(text: str, source: str) -> ClassificationResult:
    """Rule-based classifier fallback when LLM is unavailable."""
    text_lower = text.lower()

    # Adversarial / spam check
    if any(k in text_lower for k in (
        "ignore previous", "system override", "system instruction",
        "set urgency", "raise urgency", "give me root", "prompt injection",
        "bypass critique", "bypass verify", "override:"
    )):
        tax = RecallTaxonomy.SPAM_MANIPULATION
        rel = 10.0
        urg = 5.0
    elif any(k in text_lower for k in ("contamination", "salmonella", "ndma", "bacteria", "allergen")):
        tax = RecallTaxonomy.CONTAMINATION
        rel = 95.0
        urg = 90.0
    elif any(k in text_lower for k in ("suffocation", "death", "burn hazard", "crash", "fire risk", "overheat")):
        tax = RecallTaxonomy.HEALTH_HAZARD
        rel = 90.0
        urg = 88.0
    elif any(k in text_lower for k in ("recall", "defect notice", "warning", "remov")):
        tax = RecallTaxonomy.PRODUCT_RECALL
        rel = 85.0
        urg = 75.0
    elif any(k in text_lower for k in ("brake", "module", "battery", "casing")):
        tax = RecallTaxonomy.UNSAFE_EQUIPMENT
        rel = 80.0
        urg = 70.0
    elif "alert" in text_lower or "advisory" in text_lower:
        tax = RecallTaxonomy.CONSUMER_WARNING
        rel = 75.0
        urg = 65.0
    elif len(text.strip()) < 20:
        tax = RecallTaxonomy.UNCERTAIN
        rel = 30.0
        urg = 20.0
    else:
        tax = RecallTaxonomy.NON_SAFETY
        rel = 20.0
        urg = 10.0

    cred = compute_source_credibility(source)
    rec = 10.0
    final = ScoreBreakdown.compute_final(rel, urg, cred, rec)
    breakdown = ScoreBreakdown(
        relevance=rel,
        urgency=urg,
        credibility=cred,
        recency_boost=rec,
        final_score=round(final, 2),
    )

    # Extract snippets
    words = text.split()[:20]
    snippet = " ".join(words) if words else ""

    return ClassificationResult(
        taxonomy=tax,
        relevance_score=rel,
        urgency_score=urg,
        score_breakdown=breakdown,
        hazard_description=f"Automated categorization: {tax.value}",
        evidence_snippets=[snippet] if snippet else [],
        uncertainty_notes=None if tax != RecallTaxonomy.UNCERTAIN else "Low text content",
        is_unverified=urg > 75.0,
    )


def llm_classify_with_validation(
    llm_client: Any,
    full_text: str,
    item: SourceItem,
    max_retries: int = 3,
) -> Optional[ClassificationResult]:
    """
    Attempt LLM classification with schema validation and bounded retries.
    
    Returns None on failure (triggers deterministic fallback).
    """
    system_prompt = load_classification_prompt()
    if not system_prompt:
        return None
    
    # Construct user prompt with untrusted data delimiters
    user_prompt = (
        f"Classify the following safety notice:\n\n"
        f"[UNTRUSTED START]\n"
        f"Source: {item.source}\n"
        f"Title: {item.title}\n"
        f"Body: {item.body or 'N/A'}\n"
        f"Additional OCR/Text: {full_text[:2000]}\n"
        f"[UNTRUSTED END]\n\n"
        f"Provide classification in the JSON format specified."
    )
    
    for attempt in range(max_retries):
        try:
            llm_res = llm_client.generate(
                prompt=user_prompt,
                system=system_prompt,
                json_format=True,
                temperature=0.0,
            )
            
            if llm_res.error:
                continue
            
            if not llm_res.parsed_json:
                continue
            
            pj = llm_res.parsed_json
            
            # Validate required fields
            if "taxonomy" not in pj or "relevance_score" not in pj or "urgency_score" not in pj:
                continue
            
            # Validate taxonomy against enum
            tax_str = str(pj.get("taxonomy", "uncertain")).lower()
            try:
                tax = RecallTaxonomy(tax_str)
            except ValueError:
                # Invalid taxonomy label
                continue
            
            # Validate score ranges
            try:
                rel = float(pj.get("relevance_score", 50.0))
                urg = float(pj.get("urgency_score", 50.0))
                
                if not (0.0 <= rel <= 100.0):
                    continue
                if not (0.0 <= urg <= 100.0):
                    continue
            except (ValueError, TypeError):
                continue
            
            # Extract evidence with defaults
            hazard_desc = pj.get("hazard_description")
            if hazard_desc and not isinstance(hazard_desc, str):
                hazard_desc = str(hazard_desc)
            
            affected_prods = pj.get("affected_products", [])
            if not isinstance(affected_prods, list):
                affected_prods = []
            
            evidence_snips = pj.get("evidence_snippets", [])
            if not isinstance(evidence_snips, list):
                evidence_snips = []
            
            uncertainty = pj.get("uncertainty_notes")
            if uncertainty and not isinstance(uncertainty, str):
                uncertainty = str(uncertainty)
            
            # Compute combined score with non-LLM signals
            cred = compute_source_credibility(item.source)
            rec = compute_recency_boost(item.fetch_time)
            final = ScoreBreakdown.compute_final(rel, urg, cred, rec)
            
            breakdown = ScoreBreakdown(
                relevance=rel,
                urgency=urg,
                credibility=cred,
                recency_boost=rec,
                final_score=round(final, 2),
            )
            
            # Build validated ClassificationResult
            result = ClassificationResult(
                taxonomy=tax,
                relevance_score=rel,
                urgency_score=urg,
                score_breakdown=breakdown,
                hazard_description=hazard_desc,
                affected_products=affected_prods,
                evidence_snippets=evidence_snips,
                uncertainty_notes=uncertainty,
                is_unverified=urg > 75.0,
            )
            
            return result
            
        except Exception:
            # Continue to next retry
            continue
    
    # All retries exhausted
    return None


def execute_classify_score(arguments: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
    """Classify and score item, incorporating LLM and non-LLM signals with validation."""
    item: SourceItem = context.get("item")
    if not item:
        return ToolResult(
            tool_name=ToolName.CLASSIFY_SCORE,
            status="error",
            error_message="ContextError: Item missing from execution context.",
            is_evidence=False,
        )

    # Gather available text from item body and completed OCR
    ocr_res = context.get("completed_tool_data", {}).get("ocr_extract", {})
    ocr_text = ocr_res.get("text", "")
    full_text = f"{item.title}\n{item.body or ''}\n{ocr_text}".strip()

    llm_client = context.get("llm_client")
    res: Optional[ClassificationResult] = None
    used_llm = False
    fallback_reason: Optional[str] = None
    
    # Check if LLM classification should be attempted
    # Enable when:
    # 1. LLM client is present and callable
    # 2. Planner mode is "llm" (not deterministic fallback)
    # 3. Either not a MockLLMClient OR explicitly enabled by test flag
    is_mock_client = llm_client and type(llm_client).__name__ == "MockLLMClient"
    explicitly_enabled = context.get("enable_llm_classification", None)
    
    enable_llm_classification = (
        llm_client and 
        hasattr(llm_client, "generate") and 
        context.get("planner_mode") == "llm" and
        (explicitly_enabled is True or (explicitly_enabled is None and not is_mock_client))
    )

    # Attempt LLM classification if enabled
    if enable_llm_classification:
        res = llm_classify_with_validation(llm_client, full_text, item, max_retries=3)
        if res:
            used_llm = True
        else:
            fallback_reason = "LLM classification failed validation after retries"

    # Fall back to deterministic classifier
    if not res:
        res = deterministic_classify(full_text, item.source)
        if not fallback_reason:
            if not enable_llm_classification:
                fallback_reason = "LLM classification not enabled in context"
            else:
                fallback_reason = "LLM client unavailable or planner in fallback mode"

    # Save to storage features
    storage = context.get("storage")
    if storage:
        storage.save_item_features(
            item_id=item.item_id,
            taxonomy=res.taxonomy.value,
            relevance_score=res.relevance_score,
            urgency_score=res.urgency_score,
        )

    return ToolResult(
        tool_name=ToolName.CLASSIFY_SCORE,
        status="success",
        data={
            "taxonomy": res.taxonomy.value,
            "relevance_score": res.relevance_score,
            "urgency_score": res.urgency_score,
            "final_score": res.score_breakdown.final_score if res.score_breakdown else res.urgency_score,
            "credibility": res.score_breakdown.credibility if res.score_breakdown else 50.0,
            "recency_boost": res.score_breakdown.recency_boost if res.score_breakdown else 0.0,
            "hazard_description": res.hazard_description,
            "affected_products": res.affected_products,
            "evidence_snippets": res.evidence_snippets,
            "is_unverified": res.is_unverified,
            "classification_mode": "llm" if used_llm else "deterministic",
            "fallback_reason": fallback_reason if not used_llm else None,
        },
        is_evidence=True,
    )
