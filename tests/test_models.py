"""Tests for Pydantic models."""

import pytest
from datetime import datetime

from jyot_monitor.models import (
    SourceItem,
    ItemStatus,
    Attachment,
    OCRResult,
    ActionRequest,
    ToolName,
    BudgetState,
    TraceEvent,
    PlannerMode,
    ScoreBreakdown,
    AlertProposal,
    ProposalStatus,
)


def test_source_item_creation():
    """Test creating a source item with required fields."""
    item = SourceItem(
        item_id="test_001",
        source="CPSC",
        url="https://example.com/item/1",
        title="Test Recall",
        body="Test body content",
        content_hash="abc123"
    )
    
    assert item.item_id == "test_001"
    assert item.status == ItemStatus.PENDING
    assert item.error_code is None
    assert isinstance(item.fetch_time, datetime)


def test_content_hash_computation():
    """Test content hash is computed consistently."""
    hash1 = SourceItem.compute_content_hash("Hello World", "Body text")
    hash2 = SourceItem.compute_content_hash("hello world", "body text")
    hash3 = SourceItem.compute_content_hash("Hello  World", "Body  text")
    
    # Should be equal after normalization
    assert hash1 == hash2
    assert hash1 == hash3
    assert len(hash1) == 64  # SHA-256


def test_attachment_model():
    """Test attachment model."""
    attachment = Attachment(
        attachment_id="att_001",
        item_id="test_001",
        url="https://example.com/image.jpg"
    )
    
    assert attachment.attachment_id == "att_001"
    assert attachment.local_path is None


def test_ocr_result_confidence_validation():
    """Test OCR result confidence is validated."""
    # Valid confidence
    ocr = OCRResult(
        engine="tesseract",
        text="Sample text",
        normalized_confidence=0.85
    )
    assert ocr.normalized_confidence == 0.85
    
    # Invalid confidence (out of range)
    with pytest.raises(ValueError):
        OCRResult(
            engine="tesseract",
            text="Sample text",
            normalized_confidence=1.5
        )


def test_action_request_with_tool_enum():
    """Test action request uses ToolName enum."""
    action = ActionRequest(
        action=ToolName.OCR_EXTRACT,
        rationale="Low quality image needs OCR",
        arguments={"engine": "tesseract"}
    )
    
    assert action.action == ToolName.OCR_EXTRACT
    assert action.rationale != ""
    
    # Invalid tool name should fail
    with pytest.raises(ValueError):
        ActionRequest(
            action="invalid_tool",
            rationale="Test"
        )


def test_budget_state_validation():
    """Test budget state requires non-negative values."""
    budget = BudgetState(item_usd=0.05, run_usd=2.5, steps=8)
    assert budget.item_usd == 0.05
    
    # Negative values should fail
    with pytest.raises(ValueError):
        BudgetState(item_usd=-0.1, run_usd=2.5, steps=8)


def test_trace_event_serialization():
    """Test trace event serializes to JSONL format."""
    event = TraceEvent(
        run_id="run_001",
        item_id="item_001",
        step_index=0,
        planner_mode=PlannerMode.LLM,
        tool=ToolName.OCR_EXTRACT,
        status=ItemStatus.COMPLETED,
        decision_rationale="Processing image attachment"
    )
    
    jsonl_line = event.to_jsonl_line()
    
    assert jsonl_line.endswith("\n")
    assert "run_001" in jsonl_line
    assert "ocr_extract" in jsonl_line
    
    # Should be valid JSON
    import json
    parsed = json.loads(jsonl_line.strip())
    assert parsed["run_id"] == "run_001"


def test_score_breakdown_computation():
    """Test score breakdown computes final score correctly."""
    final = ScoreBreakdown.compute_final(
        relevance=80.0,
        urgency=90.0,
        credibility=85.0,
        recency_boost=10.0
    )
    
    # Formula: 0.45*80 + 0.40*90 + 0.10*85 + 0.05*10 = 36+36+8.5+0.5 = 81
    assert abs(final - 81.0) < 0.01


def test_alert_proposal_requires_source_url():
    """Test alert proposal validates evidence includes source URL."""
    # Valid proposal
    proposal = AlertProposal(
        proposal_id="prop_001",
        item_id="item_001",
        urgency=90.0,
        evidence_json={
            "source_url": "https://example.com",
            "snippet": "Urgent recall notice"
        }
    )
    assert proposal.status == ProposalStatus.PENDING
    
    # Missing source_url should fail
    with pytest.raises(ValueError, match="source_url"):
        AlertProposal(
            proposal_id="prop_002",
            item_id="item_002",
            urgency=90.0,
            evidence_json={"snippet": "No URL"}
        )


def test_item_status_enum():
    """Test ItemStatus enum values."""
    assert ItemStatus.PENDING.value == "pending"
    assert ItemStatus.COMPLETED.value == "completed"
    assert ItemStatus.PARTIAL.value == "partial"


def test_planner_mode_enum():
    """Test PlannerMode distinguishes LLM from fallback."""
    assert PlannerMode.LLM.value == "llm"
    assert PlannerMode.FALLBACK.value == "fallback"
