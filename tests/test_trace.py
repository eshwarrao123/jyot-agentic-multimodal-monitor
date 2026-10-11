"""Tests for trace writer."""

import pytest
from pathlib import Path
import tempfile
import shutil
import json

from jyot_monitor.trace import Tracer, TracerError, create_tracer
from jyot_monitor.models import TraceEvent, ToolName, PlannerMode, ItemStatus


@pytest.fixture
def temp_trace_dir():
    """Create a temporary directory for traces."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


def test_tracer_creates_directory(temp_trace_dir):
    """Test tracer creates trace directory if it doesn't exist."""
    trace_dir = temp_trace_dir / "traces"
    assert not trace_dir.exists()
    
    tracer = Tracer(trace_dir, "run_001")
    
    assert trace_dir.exists()


def test_tracer_context_manager(temp_trace_dir):
    """Test tracer works as context manager."""
    tracer = Tracer(temp_trace_dir, "run_001")
    
    with tracer as t:
        assert t._handle is not None
    
    assert tracer._handle is None


def test_write_trace_event(temp_trace_dir):
    """Test writing a trace event."""
    tracer = Tracer(temp_trace_dir, "run_001")
    
    event = TraceEvent(
        run_id="run_001",
        item_id="item_001",
        step_index=0,
        planner_mode=PlannerMode.LLM,
        tool=ToolName.OCR_EXTRACT,
        status=ItemStatus.COMPLETED,
        decision_rationale="Testing trace write"
    )
    
    with tracer:
        tracer.write_event(event)
    
    # Verify file was created
    trace_file = temp_trace_dir / "run_001.jsonl"
    assert trace_file.exists()
    
    # Verify content
    content = trace_file.read_text()
    assert "run_001" in content
    assert "ocr_extract" in content


def test_write_multiple_events(temp_trace_dir):
    """Test writing multiple events to same file."""
    tracer = Tracer(temp_trace_dir, "run_002")
    
    events = [
        TraceEvent(
            run_id="run_002",
            item_id="item_001",
            step_index=i,
            planner_mode=PlannerMode.LLM,
            tool=ToolName.CLASSIFY_SCORE,
            status=ItemStatus.IN_PROGRESS
        )
        for i in range(3)
    ]
    
    with tracer:
        for event in events:
            tracer.write_event(event)
    
    # Verify all events written
    trace_file = temp_trace_dir / "run_002.jsonl"
    lines = trace_file.read_text().strip().split("\n")
    assert len(lines) == 3


def test_write_without_context_manager_fails(temp_trace_dir):
    """Test writing without context manager raises error."""
    tracer = Tracer(temp_trace_dir, "run_003")
    
    event = TraceEvent(
        run_id="run_003",
        item_id="item_001",
        step_index=0,
        planner_mode=PlannerMode.FALLBACK,
        tool=ToolName.FINISH,
        status=ItemStatus.COMPLETED
    )
    
    with pytest.raises(TracerError, match="context manager"):
        tracer.write_event(event)


def test_read_trace_file(temp_trace_dir):
    """Test reading a trace file."""
    tracer = Tracer(temp_trace_dir, "run_004")
    
    original_events = [
        TraceEvent(
            run_id="run_004",
            item_id="item_001",
            step_index=i,
            planner_mode=PlannerMode.LLM,
            tool=ToolName.SEARCH_MEMORY,
            status=ItemStatus.COMPLETED,
            decision_rationale=f"Step {i}"
        )
        for i in range(2)
    ]
    
    with tracer:
        for event in original_events:
            tracer.write_event(event)
    
    # Read back
    trace_file = temp_trace_dir / "run_004.jsonl"
    read_events = Tracer.read_trace(trace_file)
    
    assert len(read_events) == 2
    assert read_events[0].run_id == "run_004"
    assert read_events[0].step_index == 0
    assert read_events[1].step_index == 1


def test_read_nonexistent_file(temp_trace_dir):
    """Test reading nonexistent file returns empty list."""
    nonexistent = temp_trace_dir / "nonexistent.jsonl"
    events = Tracer.read_trace(nonexistent)
    assert events == []


def test_trace_event_jsonl_format(temp_trace_dir):
    """Test trace events are valid JSONL."""
    tracer = Tracer(temp_trace_dir, "run_005")
    
    event = TraceEvent(
        run_id="run_005",
        item_id="item_001",
        step_index=0,
        planner_mode=PlannerMode.LLM,
        tool=ToolName.VERIFY_CLAIM,
        status=ItemStatus.COMPLETED,
        tokens_in=100,
        tokens_out=50,
        cost_usd=0.002,
        latency_ms=250.5
    )
    
    with tracer:
        tracer.write_event(event)
    
    # Read and parse as JSON
    trace_file = temp_trace_dir / "run_005.jsonl"
    line = trace_file.read_text().strip()
    
    parsed = json.loads(line)
    assert parsed["run_id"] == "run_005"
    assert parsed["tokens_in"] == 100
    assert parsed["cost_usd"] == 0.002
    assert parsed["tool"] == "verify_claim"


def test_create_tracer_factory(temp_trace_dir):
    """Test tracer factory function."""
    tracer = create_tracer("run_006", artifacts_dir=temp_trace_dir)
    
    assert tracer.run_id == "run_006"
    assert tracer.trace_dir == temp_trace_dir / "traces"


def test_trace_includes_optional_fields(temp_trace_dir):
    """Test trace correctly handles null/optional fields."""
    tracer = Tracer(temp_trace_dir, "run_007")
    
    event = TraceEvent(
        run_id="run_007",
        item_id="item_001",
        step_index=0,
        planner_mode=PlannerMode.FALLBACK,
        tool=ToolName.FINISH,
        status=ItemStatus.COMPLETED,
        tokens_in=None,  # Not available
        tokens_out=None,
        cost_usd=None,
        model="fallback"
    )
    
    with tracer:
        tracer.write_event(event)
    
    # Read back and verify nulls preserved
    trace_file = temp_trace_dir / "run_007.jsonl"
    line = trace_file.read_text().strip()
    parsed = json.loads(line)
    
    assert parsed["tokens_in"] is None
    assert parsed["cost_usd"] is None
    assert parsed["model"] == "fallback"
