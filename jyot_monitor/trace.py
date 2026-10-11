"""
JSONL trace writer for structured event logging.

All agent steps are logged to JSONL files for:
- Evidence and auditability
- Debugging and walkthrough
- Evaluation and analysis
"""

from pathlib import Path
from typing import Optional
import json
from datetime import datetime

from jyot_monitor.models import TraceEvent


class TracerError(Exception):
    """Tracing errors."""
    pass


class Tracer:
    """
    JSONL trace writer.
    
    Writes one JSON object per line for efficient append and streaming.
    """
    
    def __init__(self, trace_dir: Path, run_id: str):
        """
        Initialize tracer for a specific run.
        
        Args:
            trace_dir: Directory for trace files
            run_id: Unique run identifier
        """
        self.trace_dir = trace_dir
        self.run_id = run_id
        self.trace_file = trace_dir / f"{run_id}.jsonl"
        
        # Ensure directory exists
        trace_dir.mkdir(parents=True, exist_ok=True)
        
        # Create or append to trace file
        self._handle = None
    
    def __enter__(self):
        """Context manager entry."""
        self._handle = open(self.trace_file, 'a', encoding='utf-8')
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self._handle:
            self._handle.close()
            self._handle = None
    
    def write_event(self, event: TraceEvent) -> None:
        """
        Write a trace event as a single JSONL line.
        
        Args:
            event: TraceEvent to write
            
        Raises:
            TracerError: If tracer is not opened or write fails
        """
        if not self._handle:
            raise TracerError("Tracer must be used as context manager")
        
        try:
            # Serialize to JSON line
            json_line = event.to_jsonl_line()
            self._handle.write(json_line)
            self._handle.flush()  # Ensure immediate write
        except Exception as e:
            raise TracerError(f"Failed to write trace event: {e}")
    
    @staticmethod
    def read_trace(trace_file: Path) -> list[TraceEvent]:
        """
        Read and parse a trace file.
        
        Args:
            trace_file: Path to JSONL trace file
            
        Returns:
            List of TraceEvent objects
        """
        events = []
        
        if not trace_file.exists():
            return events
        
        with open(trace_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                    event = TraceEvent(**data)
                    events.append(event)
                except Exception as e:
                    # Log parse error but continue
                    print(f"Warning: Failed to parse line {line_num} in {trace_file}: {e}")
        
        return events


def create_tracer(run_id: str, artifacts_dir: Optional[Path] = None) -> Tracer:
    """
    Factory function to create a tracer.
    
    Args:
        run_id: Unique run identifier
        artifacts_dir: Optional artifacts directory (defaults to ./artifacts)
        
    Returns:
        Configured Tracer instance
    """
    if artifacts_dir is None:
        artifacts_dir = Path("artifacts")
    
    trace_dir = artifacts_dir / "traces"
    return Tracer(trace_dir, run_id)
