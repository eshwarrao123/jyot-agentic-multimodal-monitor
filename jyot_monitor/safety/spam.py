"""
Spam and manipulation detection heuristics for Jyot Multimodal Monitor.

Provides explainable, lightweight checks for:
1. Duplicate floods: identical or near-identical notices submitted repeatedly.
2. Source bursts: sudden volume spikes from unverified sources.
3. Keyword manipulation / promotional keyword stuffing / injection markers.

Signals are reported separately from verified urgency so legitimate syndicated notices
are never discarded without provenance.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Set

from jyot_monitor.models import SourceItem

MANIPULATION_PATTERNS = [
    re.compile(r'\b(?:system\s+override|ignore\s+(?:previous|all)\s+instructions)\b', re.IGNORECASE),
    re.compile(r'\b(?:set\s+urgency\s+to\s+100|broadcast\s+emergency\s+alert)\b', re.IGNORECASE),
    re.compile(r'\b(?:free\s+crypto|giveaway|click\s+here\s+now|earn\s+money\s+fast)\b', re.IGNORECASE),
    re.compile(r'\b(?:buy\s+cheap|discount\s+code\s+promo|limited\s+time\s+offer)\b', re.IGNORECASE),
]


@dataclass
class SpamAssessment:
    """Result of spam and manipulation heuristic checks."""
    is_spam: bool = False
    reasons: List[str] = field(default_factory=list)
    repetition_count: int = 0
    manipulation_signals: List[str] = field(default_factory=list)
    confidence: float = 0.0


def assess_spam(
    item: SourceItem,
    recent_items: Optional[List[Dict[str, Any]]] = None,
    burst_threshold: int = 5,
) -> SpamAssessment:
    """
    Assess whether an item exhibits spam or manipulation characteristics.
    
    Args:
        item: SourceItem being evaluated
        recent_items: List of existing item features / records from storage
        burst_threshold: Number of identical/near-duplicate posts indicating a flood
        
    Returns:
        SpamAssessment with explainable flags.
    """
    reasons: List[str] = []
    signals: List[str] = []
    recent_items = recent_items or []
    
    # 1. Manipulation keyword detection
    full_text = f"{item.title} {item.body or ''}"
    for pat in MANIPULATION_PATTERNS:
        match = pat.search(full_text)
        if match:
            sig = match.group(0)
            signals.append(sig)
            reasons.append(f"Detected suspicious keyword / instruction pattern: '{sig}'")

    # 2. Duplicate flood detection
    same_hash_count = 0
    same_title_count = 0
    clean_title = re.sub(r'[^a-zA-Z0-9]', '', item.title.lower())

    for prev in recent_items:
        # Check content hash match
        if prev.get("content_hash") == item.content_hash:
            same_hash_count += 1
        # Check title similarity
        prev_title = prev.get("title", "")
        if prev_title:
            prev_clean = re.sub(r'[^a-zA-Z0-9]', '', prev_title.lower())
            if clean_title and prev_clean == clean_title:
                same_title_count += 1

    repetition_count = max(same_hash_count, same_title_count)
    if repetition_count >= burst_threshold:
        reasons.append(
            f"Duplicate flood detected: item content or title repeated {repetition_count} times (threshold: {burst_threshold})"
        )

    # 3. Source credibility context
    is_untrusted_source = item.source.upper() in ("UNVERIFIED_BLOG", "UNTRUSTED_IMAGE_DROP", "SOCIAL_FEED")
    if is_untrusted_source and repetition_count >= 3:
        reasons.append(f"Rapid repetition ({repetition_count} occurrences) from untrusted source '{item.source}'")

    is_spam = len(reasons) > 0 or len(signals) > 0
    confidence = min(1.0, (len(signals) * 0.4) + (0.3 if repetition_count >= burst_threshold else 0.0))

    return SpamAssessment(
        is_spam=is_spam,
        reasons=reasons,
        repetition_count=repetition_count,
        manipulation_signals=signals,
        confidence=confidence,
    )
