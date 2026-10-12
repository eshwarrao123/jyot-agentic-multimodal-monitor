"""
Tests for reliability, rate-limit backoff, caching, fault injection, and human approval boundary.
"""

import argparse
from pathlib import Path
import pytest
import respx
import httpx

from jyot_monitor.cli import cmd_approve, cmd_reject
from jyot_monitor.fault_injection import FaultInjector
from jyot_monitor.ingestion.network import SafeHttpClient
from jyot_monitor.models import (
    AlertProposal,
    Attachment,
    ItemStatus,
    ProposalStatus,
    RecallTaxonomy,
    SourceItem,
)
from jyot_monitor.agent.planner import DeterministicFallbackPlanner
from jyot_monitor.replay import run_replay
from jyot_monitor.storage import Storage


@respx.mock
def test_rate_limit_429_with_retry_after():
    """Verify SafeHttpClient backs off on 429 using Retry-After header."""
    url = "https://www.cpsc.gov/limited"
    # First response: 429 with Retry-After: 0.05
    # Second response: 200 OK
    respx.get(url).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0.05"}),
            httpx.Response(200, text="<xml>Success</xml>", headers={"Content-Type": "application/xml"}),
        ]
    )

    client = SafeHttpClient(max_retries=2)
    response = client.get(url, allowed_hosts=["www.cpsc.gov"])
    assert response.status_code == 200
    assert response.text == "<xml>Success</xml>"


@respx.mock
def test_server_error_500_retries_and_exhaustion():
    """Verify SafeHttpClient retries on 500 up to limit and returns final response."""
    url = "https://www.cpsc.gov/error"
    respx.get(url).respond(500, text="Internal Server Error")

    client = SafeHttpClient(max_retries=2, backoff_base_seconds=0.01)
    response = client.get(url, allowed_hosts=["www.cpsc.gov"])
    assert response.status_code == 500


def test_deterministic_fault_injection_replay(tmp_path: Path):
    """Verify offline replay executes through deterministic fault injection with isolation."""
    db_path = tmp_path / "fault_test.db"
    artifacts_dir = tmp_path / "artifacts"
    
    # Run replay with fault_injection=True on recorded fixtures using deterministic fallback
    summary = run_replay(
        fixtures_dir=Path("fixtures/recorded"),
        db_path=db_path,
        artifacts_dir=artifacts_dir,
        top_n=3,
        planner=DeterministicFallbackPlanner(),
        fault_injection=True,
    )

    assert summary.total_items == 3
    # Items should be handled and isolated without crashing the entire run
    assert summary.error_count == 0
    assert summary.completed_count + summary.partial_count == 3
    assert summary.trace_file.exists()

    # Verify trace file contains events
    trace_lines = summary.trace_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(trace_lines) > 0


def test_ocr_and_llm_caching(tmp_path: Path):
    """Verify Storage cache saves and retrieves OCR and LLM results by content hash."""
    db_path = tmp_path / "cache_test.db"
    storage = Storage(db_path)

    # 1. OCR Cache test
    content_hash = "abc_hash_123"
    storage.save_ocr_cache(
        content_hash=content_hash,
        engine="tesseract",
        preprocessing="none",
        text="BATCH 123 RECALLED",
        confidence=0.95,
    )

    cached_ocr = storage.get_ocr_cache(content_hash, "tesseract", "none")
    assert cached_ocr is not None
    assert cached_ocr["text"] == "BATCH 123 RECALLED"

    # Mismatched engine returns None
    assert storage.get_ocr_cache(content_hash, "easyocr", "none") is None

    # 2. LLM Cache test
    prompt_hash = "prompt_hash_456"
    storage.save_llm_cache(prompt_hash, "qwen2.5:3b", '{"action": "finish"}', tokens_in=50, tokens_out=10)

    cached_llm = storage.get_llm_cache(prompt_hash, "qwen2.5:3b")
    assert cached_llm is not None
    assert cached_llm["response_json"] == '{"action": "finish"}'
    assert storage.get_llm_cache(prompt_hash, "different_model") is None


def test_human_approved_alert_emission_boundary(tmp_path: Path):
    """Verify approval gate: proposals require human approval, emit redacted records, and are idempotent."""
    db_path = tmp_path / "monitor_approve.db"
    storage = Storage(db_path)

    item = SourceItem(
        item_id="item_hitl_01",
        source="CPSC",
        url="https://cpsc.gov/test",
        title="High Voltage Choking Hazard",
        content_hash="hash_hitl_01",
    )
    storage.save_item(item)

    proposal = AlertProposal(
        proposal_id="prop_hitl_01",
        item_id="item_hitl_01",
        urgency=90.0,
        evidence_json={
            "source_url": "https://cpsc.gov/test",
            "title": "High Voltage Choking Hazard",
            "evidence_snippet": "Urgent notice. Contact support@company.com or 1-800-555-0199 for refund.",
        },
        status=ProposalStatus.PENDING,
    )
    storage.save_alert_proposal(proposal)

    # 1. Proposal is initially pending, not emitted
    assert not storage.is_alert_emitted("prop_hitl_01")

    # 2. Approve via CLI cmd_approve
    args_approve = argparse.Namespace(proposal_id="prop_hitl_01", db_path=db_path)
    ret_code = cmd_approve(args_approve)
    assert ret_code == 0
    assert storage.is_alert_emitted("prop_hitl_01")

    # Verify emitted alert is stored and PII redacted
    emitted = storage.get_emitted_alert("prop_hitl_01")
    assert emitted is not None
    payload_str = str(emitted.get("alert_payload", {}))
    assert "support@company.com" not in payload_str
    assert "1-800-555-0199" not in payload_str
    assert "[EMAIL_REDACTED]" in payload_str
    assert "[PHONE_REDACTED]" in payload_str

    # 3. Repeated approval is idempotent and does not crash or double-emit
    ret_code_2 = cmd_approve(args_approve)
    assert ret_code_2 == 0

    # 4. Cannot reject already emitted proposal
    args_reject = argparse.Namespace(proposal_id="prop_hitl_01", db_path=db_path)
    ret_reject = cmd_reject(args_reject)
    assert ret_reject == 1


def test_proposal_rejection_never_emits_alert(tmp_path: Path):
    """Verify rejecting a proposal updates status to REJECTED and emits NO alert."""
    db_path = tmp_path / "monitor_reject.db"
    storage = Storage(db_path)

    proposal = AlertProposal(
        proposal_id="prop_reject_01",
        item_id="item_hitl_01",
        urgency=80.0,
        evidence_json={
            "source_url": "https://cpsc.gov/test",
            "title": "Low quality notice.",
        },
        status=ProposalStatus.PENDING,
    )
    storage.save_alert_proposal(proposal)

    args_reject = argparse.Namespace(proposal_id="prop_reject_01", db_path=db_path)
    ret_code = cmd_reject(args_reject)
    assert ret_code == 0

    updated = storage.get_alert_proposal("prop_reject_01")
    assert updated.status == ProposalStatus.REJECTED
    assert not storage.is_alert_emitted("prop_reject_01")
