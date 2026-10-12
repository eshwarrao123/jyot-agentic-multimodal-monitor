"""
Replay engine for offline fixture execution.

Loads recorded fixture items and executes them through the AgentController.
Enforces network denial (no external requests or DNS queries).
Logs step-by-step traces to JSONL and persists state to SQLite.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from jyot_monitor.agent.controller import AgentController
from jyot_monitor.agent.planner import LLMPlanner, DeterministicFallbackPlanner
from jyot_monitor.agent.tools.registry import get_default_tool_registry
from jyot_monitor.fault_injection import FaultInjector
from jyot_monitor.llm.client import OllamaClient
from jyot_monitor.models import (
    Attachment,
    ItemProcessingResult,
    ItemStatus,
    SourceItem,
    utc_now,
)
from jyot_monitor.ocr.router import OCRRouter
from jyot_monitor.storage import Storage
from jyot_monitor.trace import Tracer, create_tracer


class ReplayExecutionSummary:
    """Summary of a completed replay run."""

    def __init__(
        self,
        run_id: str,
        total_items: int,
        results: List[ItemProcessingResult],
        total_cost_usd: float,
        duration_seconds: float,
        trace_file: Optional[Path] = None,
    ):
        self.run_id = run_id
        self.total_items = total_items
        self.results = results
        self.total_cost_usd = total_cost_usd
        self.duration_seconds = duration_seconds
        self.trace_file = trace_file

    @property
    def completed_count(self) -> int:
        return sum(1 for r in self.results if r.status == ItemStatus.COMPLETED)

    @property
    def partial_count(self) -> int:
        return sum(1 for r in self.results if r.status == ItemStatus.PARTIAL)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if r.status == ItemStatus.ERROR)

    @property
    def proposals_count(self) -> int:
        return sum(1 for r in self.results if r.alert_proposal is not None)


def load_replay_fixtures(fixtures_dir: Path) -> List[Dict[str, Any]]:
    """
    Load items and attachments from recorded replay fixtures.
    Supports either manifest.json or individual .json files.
    """
    fixtures_dir = Path(fixtures_dir)
    manifest_file = fixtures_dir / "manifest.json"

    if manifest_file.is_file():
        with open(manifest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", [])

    # Otherwise collect all JSON files in the directory
    raw_items = []
    for p in sorted(fixtures_dir.glob("*.json")):
        if p.name == "manifest.json":
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, list):
                    raw_items.extend(content)
                elif isinstance(content, dict):
                    raw_items.append(content)
        except Exception:
            pass

    return raw_items


def run_replay(
    fixtures_dir: Path,
    db_path: Optional[Path] = None,
    artifacts_dir: Optional[Path] = None,
    run_id: Optional[str] = None,
    budget_usd: Optional[float] = None,
    top_n: int = 10,
    planner: Optional[Any] = None,
    llm_client: Optional[Any] = None,
    strict_llm: bool = False,
    target_item_id: Optional[str] = None,
    fault_injection: bool = False,
) -> ReplayExecutionSummary:
    """
    Execute offline replay through AgentController.

    Strict offline safety:
    - Never makes external HTTP requests or resolves DNS.
    - Resolves attachments only from within project fixture root.
    """
    start_time = datetime.now(timezone.utc)
    run_id = run_id or f"replay_{uuid.uuid4().hex[:8]}"
    artifacts_dir = artifacts_dir or Path("artifacts")
    traces_dir = artifacts_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_path or (artifacts_dir / "monitor.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    storage = Storage(db_path)
    tracer = Tracer(traces_dir, run_id)
    ocr_router = OCRRouter()
    fault_injector = FaultInjector(enabled=True) if fault_injection else None

    # Determine planner: use provided planner, configure Ollama, or use fallback
    if planner is None:
        if llm_client is not None:
            planner = LLMPlanner(llm_client=llm_client, allow_fallback=not strict_llm)
        else:
            # Check if local Ollama model is configured via environment
            ollama_model = os.getenv("JYOT_PLANNER_MODEL", "qwen2.5:3b")
            client = OllamaClient(model=ollama_model)
            if client.is_available():
                planner = LLMPlanner(llm_client=client, allow_fallback=not strict_llm)
            else:
                if strict_llm:
                    raise RuntimeError(f"Ollama model '{ollama_model}' unavailable in strict LLM mode.")
                planner = DeterministicFallbackPlanner()

    # Setup controller
    per_run_budget = budget_usd if budget_usd is not None else 5.00
    controller = AgentController(
        planner=planner,
        tool_registry=get_default_tool_registry(),
        storage=storage,
        ocr_router=ocr_router,
        tracer=tracer,
        run_id=run_id,
        max_steps_per_item=10,
        per_item_usd=0.10,
        per_run_usd=per_run_budget,
        fixture_root=str(fixtures_dir),
        fault_injector=fault_injector,
    )

    raw_items = load_replay_fixtures(fixtures_dir)
    if target_item_id:
        items_to_process = [r for r in raw_items if r.get("item_id") == target_item_id]
    else:
        items_to_process = raw_items[:top_n]
    results: List[ItemProcessingResult] = []
    total_cost = 0.0

    with tracer:
        for idx, raw in enumerate(items_to_process):
            item_id = raw.get("item_id", f"item_{uuid.uuid4().hex[:6]}")
            title = raw.get("title", "Untitled Notice")
            body = raw.get("body")
            source = raw.get("source", "UNKNOWN")
            url = raw.get("url", f"https://example.com/notices/{item_id}")

            content_hash = SourceItem.compute_content_hash(title, body)

            # Skip already completed items only when content hash is unchanged
            existing_item = storage.get_item(item_id)
            if existing_item and existing_item.status == ItemStatus.COMPLETED and existing_item.content_hash == content_hash:
                existing_proposal = storage.get_alert_proposal_for_item_or_cluster(item_id)
                cluster = storage.get_item_cluster(item_id)
                cluster_id = cluster.cluster_id if cluster else None

                cached_res = ItemProcessingResult(
                    item_id=item_id,
                    status=ItemStatus.COMPLETED,
                    steps_taken=0,
                    completed_tools=[],
                    alert_proposal=existing_proposal,
                    cluster_id=cluster_id,
                    fallback_used=False,
                    cost_usd=0.0,
                    total_latency_ms=0.0,
                )
                results.append(cached_res)
                continue

            item = SourceItem(
                item_id=item_id,
                source=source,
                url=url,
                title=title,
                body=body,
                content_hash=content_hash,
                status=ItemStatus.PENDING,
            )

            # Persist item initially
            storage.save_item(item)

            # Build Attachment models
            attachments = []
            for att_raw in raw.get("attachments", []):
                att_id = att_raw.get("attachment_id", f"att_{uuid.uuid4().hex[:4]}")
                att = Attachment(
                    attachment_id=att_id,
                    item_id=item_id,
                    url=att_raw.get("url", f"replay://{item_id}/{att_id}"),
                    local_path=att_raw.get("local_path"),
                    mime_type=att_raw.get("mime_type"),
                )
                attachments.append(att)
                storage.save_attachment(att)

            # Execute through AgentController
            res = controller.process_item(item, attachments=attachments, item_index=idx)
            results.append(res)
            total_cost += res.cost_usd

            # Update item status in storage
            item.status = res.status
            if res.error_message:
                item.error_code = res.error_message[:100]
            storage.save_item(item)

    end_time = datetime.now(timezone.utc)
    duration_sec = (end_time - start_time).total_seconds()

    return ReplayExecutionSummary(
        run_id=run_id,
        total_items=len(results),
        results=results,
        total_cost_usd=round(total_cost, 6),
        duration_seconds=round(duration_sec, 2),
        trace_file=tracer.trace_file,
    )
