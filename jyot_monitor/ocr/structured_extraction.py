"""
Deterministic structured extraction for product safety and recall notices.

Extracts validated fields:
- product_name
- manufacturer
- notice_date
- hazard
- recommended_action
- recall_identifier

Uncertain or missing fields are explicitly recorded in `uncertain_fields`
and set to None, preventing fabrication or hallucination.
"""

import re
from typing import List, Optional, Tuple

from jyot_monitor.models import ProductSafetyNotice


# Regex patterns for common notice fields
DATE_PATTERNS = [
    # YYYY-MM-DD
    r"\b(20\d{2}[-/](?:0[1-9]|1[0-2])[-/](?:0[1-9]|[12]\d|3[01]))\b",
    # Month DD, YYYY
    r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2})\b",
    # MM/DD/YYYY
    r"\b((?:0[1-9]|1[0-2])/(?:0[1-9]|[12]\d|3[01])/20\d{2})\b",
]

RECALL_ID_PATTERNS = [
    r"(?:Recall\s+(?:Number|No\.?|ID|Campaign)|Campaign\s+#?)\s*[:#]?\s*([A-Za-z0-9\-]+)",
    r"\b(\d{2}-[A-Za-z0-9\-]+)\b",
    r"(?:Units|Count)\s*[:#]?\s*([\d,]+\s*(?:units)?)",
]

KEYWORD_SECTIONS = {
    "product_name": [
        r"(?:Product\s+Name|Product|Name\s+of\s+Product)\s*[:\-]\s*([^\n\r]+)",
        r"(?:Recalled\s+Product)\s*[:\-]\s*([^\n\r]+)",
    ],
    "manufacturer": [
        r"(?:Manufacturer|Manufactured\s+by|Distributor|Distributed\s+by|Brand)\s*[:\-]\s*([^\n\r]+)",
    ],
    "hazard": [
        r"(?:Hazard|Risk|Danger)\s*[:\-]\s*([^\n\r]+)",
    ],
    "recommended_action": [
        r"(?:Remedy|Recommended\s+Action|Action|Consumer\s+Action|Remedy/Action)\s*[:\-]\s*([^\n\r]+)",
        r"(?:Consumers\s+should)\s*[:\-]?\s*([^\n\r]+)",
    ],
}


def _extract_by_patterns(text: str, patterns: List[str]) -> Optional[str]:
    """Search text sequentially with regex patterns and return the first matched group."""
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            extracted = match.group(1).strip()
            # Clean up trailing punctuation
            extracted = re.sub(r"[\s,:;\-]+$", "", extracted)
            if len(extracted) > 1:
                return extracted
    return None


def extract_safety_notice(ocr_text: str) -> ProductSafetyNotice:
    """
    Extract structured recall notice fields from raw OCR text using deterministic rules.
    
    If any field is missing or ambiguous, it is set to None and added to uncertain_fields.
    No field values are fabricated.
    """
    cleaned_text = ocr_text or ""
    uncertain_fields: List[str] = []

    # 1. Product Name
    product_name = _extract_by_patterns(cleaned_text, KEYWORD_SECTIONS["product_name"])
    if not product_name:
        uncertain_fields.append("product_name")

    # 2. Manufacturer
    manufacturer = _extract_by_patterns(cleaned_text, KEYWORD_SECTIONS["manufacturer"])
    if not manufacturer:
        uncertain_fields.append("manufacturer")

    # 3. Notice Date
    notice_date = _extract_by_patterns(cleaned_text, DATE_PATTERNS)
    if not notice_date:
        uncertain_fields.append("notice_date")

    # 4. Hazard
    hazard = _extract_by_patterns(cleaned_text, KEYWORD_SECTIONS["hazard"])
    if not hazard:
        uncertain_fields.append("hazard")

    # 5. Recommended Action
    recommended_action = _extract_by_patterns(cleaned_text, KEYWORD_SECTIONS["recommended_action"])
    if not recommended_action:
        uncertain_fields.append("recommended_action")

    # 6. Recall Identifier
    recall_id = _extract_by_patterns(cleaned_text, RECALL_ID_PATTERNS)
    if not recall_id:
        uncertain_fields.append("recall_identifier")

    total_fields = 6
    confident_count = total_fields - len(uncertain_fields)
    confidence_score = float(round(confident_count / total_fields, 2))

    return ProductSafetyNotice(
        product_name=product_name,
        manufacturer=manufacturer,
        notice_date=notice_date,
        hazard=hazard,
        recommended_action=recommended_action,
        recall_identifier=recall_id,
        raw_ocr_text=cleaned_text,
        uncertain_fields=uncertain_fields,
        confidence_score=confidence_score,
    )
