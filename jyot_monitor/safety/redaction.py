"""
PII Redaction module for Jyot Multimodal Monitor.

Detects and redacts personally identifiable contact information:
- Email addresses -> [EMAIL_REDACTED]
- Telephone / hotline numbers -> [PHONE_REDACTED]

Designed to preserve non-PII product identifiers, recall campaign numbers
(e.g., CPSC-26-090, NHTSA-24V-123), dates (e.g., 2026-06-18), and scores.

LIMITATIONS:
Rule-based regular expressions catch standard email and phone syntax. They do NOT
detect personal names, residential addresses, or non-standard obfuscated contact info.
Full redaction for unrestricted unstructured data requires dedicated NER or human review.
"""

import re
from typing import Any, Dict, List, Union


EMAIL_PATTERN = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
)

PHONE_PATTERNS = [
    # International with leading + (e.g. +1 ..., +91 ...)
    re.compile(r'(?<![A-Za-z0-9])\+(?:1|91)[-.\s]?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,5}[-.\s]?\d{4,5}\b'),
    # Toll-free 1-800, 800, 888, 877, 866, 855, 844, 833
    re.compile(r'(?<![A-Za-z0-9])(?:\b1[-.\s]?)?\(?8(?:00|88|77|66|55|44|33)\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'),
    # Standard US 10-digit: (555) 123-4567 or 555-123-4567 or 555.123.4567
    re.compile(r'(?<![A-Za-z0-9])\(?[2-9]\d{2}\)?[-.\s]\d{3}[-.\s]\d{4}\b'),
    # Indian Toll-free: 1800-xxx-xxxx or 1800 xxx xxxx
    re.compile(r'(?<![A-Za-z0-9])1800[-.\s]?\d{3}[-.\s]?\d{3,4}\b'),
    # Standard 10-digit mobile (Indian: 98765 43210 or 9876543210 with context or space)
    re.compile(r'(?<![A-Za-z0-9])(?:\b(?:Tel|Phone|Call|Contact|Mob|Mobile|Helpline)[:\s]+)?[6-9]\d{4}[-.\s]?\d{5}\b', re.IGNORECASE),
]


def redact_text(text: str) -> str:
    """
    Redact email addresses and telephone numbers from text.
    
    Args:
        text: Raw input text (e.g. from post body or OCR extraction)
        
    Returns:
        Text with sensitive identifiers replaced by [EMAIL_REDACTED] or [PHONE_REDACTED].
    """
    if not text or not isinstance(text, str):
        return text

    # Redact emails first
    redacted = EMAIL_PATTERN.sub("[EMAIL_REDACTED]", text)

    # Redact phone numbers using compiled patterns
    for pattern in PHONE_PATTERNS:
        redacted = pattern.sub(
            lambda m: "[PHONE_REDACTED]" if not m.group(0).startswith("20") or len(m.group(0).split("-")) != 3 or len(m.group(0).split("-")[0]) != 4 else m.group(0),
            redacted
        )

    return redacted


def contains_pii(text: str) -> bool:
    """Check if the text contains any detectable email or phone number."""
    if not text or not isinstance(text, str):
        return False
    if EMAIL_PATTERN.search(text):
        return True
    for pattern in PHONE_PATTERNS:
        if pattern.search(text):
            return True
    return False


def redact_data(data: Any, max_depth: int = 10) -> Any:
    """
    Recursively redact PII from nested structures (dicts, lists, strings).
    Useful for sanitizing alert proposal evidence, summaries, and traces.
    """
    if max_depth <= 0:
        return data

    if isinstance(data, str):
        return redact_text(data)
    elif isinstance(data, dict):
        return {k: redact_data(v, max_depth - 1) for k, v in data.items()}
    elif isinstance(data, list):
        return [redact_data(item, max_depth - 1) for item in data]
    elif isinstance(data, tuple):
        return tuple(redact_data(item, max_depth - 1) for item in data)
    return data
