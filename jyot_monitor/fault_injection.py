"""
Deterministic fault injection module for Jyot Multimodal Monitor.

Simulates real failure and recovery paths under --fault-injection:
1. HTTP 429 Rate Limit with Retry-After (recovers via backoff).
2. HTTP 500 Server Error (exhausts retries and logs failure).
3. Corrupted image bytes (triggers InvalidFileSignatureError).
4. OCR engine crash (triggers error isolation and second opinion).
5. Malformed planner JSON (triggers bounded retry and deterministic fallback).

Guarantees:
- Fully reproducible via deterministic item index matching.
- Flows through standard retry, error handling, and trace emission.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class InjectedFault:
    """Record of an active or triggered fault scenario."""
    fault_type: str
    target_item_index: int
    description: str
    recovered: bool = False
    attempts: int = 0
    outcome_message: str = ""


class FaultInjector:
    """
    Deterministic fault coordinator for replay and reliability testing.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.triggered_faults: List[InjectedFault] = []

    def should_inject(self, fault_type: str, item_index: int) -> bool:
        """Check if a specific fault should be triggered on this item index."""
        if not self.enabled:
            return False

        # Deterministic scenario assignments based on item index (modulo 5)
        # item 0: HTTP 429 rate limit
        # item 1: HTTP 500 server error
        # item 2: Corrupted image input
        # item 3: OCR engine crash
        # item 4: Malformed LLM planner JSON
        mapping = {
            "http_429": 0,
            "http_500": 1,
            "corrupted_image": 2,
            "ocr_crash": 3,
            "malformed_json": 4,
        }
        return mapping.get(fault_type) == (item_index % 5)

    def record_fault(
        self,
        fault_type: str,
        item_index: int,
        description: str,
        recovered: bool,
        attempts: int = 1,
        outcome_message: str = "",
    ) -> InjectedFault:
        """Record the execution and outcome of an injected fault."""
        fault = InjectedFault(
            fault_type=fault_type,
            target_item_index=item_index,
            description=description,
            recovered=recovered,
            attempts=attempts,
            outcome_message=outcome_message,
        )
        self.triggered_faults.append(fault)
        return fault
