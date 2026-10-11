"""
Pydantic data models for the Jyot monitor.

All models represent the foundational data contracts for:
- Source items and attachments
- OCR results
- Agent actions and tool calls
- Trace events
- Alert proposals
- Budget tracking

Security boundary: All content from sources is untrusted data.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
import hashlib


class ItemStatus(str, Enum):
    """Processing status for an item."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"  # Budget exhausted or safe degradation
    ERROR = "error"
    SKIPPED = "skipped"


class PlannerMode(str, Enum):
    """How the planner decision was made."""
    LLM = "llm"  # LLM-driven decision
    FALLBACK = "fallback"  # Deterministic rule-based fallback


class ToolName(str, Enum):
    """Allowed tool names (security boundary)."""
    FETCH_ATTACHMENT = "fetch_attachment"
    OCR_EXTRACT = "ocr_extract"
    VISION_DESCRIBE = "vision_describe"
    SEARCH_MEMORY = "search_memory"
    VERIFY_CLAIM = "verify_claim"
    CLASSIFY_SCORE = "classify_score"
    CRITIQUE_ITEM = "critique_item"
    PROPOSE_ALERT = "propose_alert"
    FINISH = "finish"


class ProposalStatus(str, Enum):
    """Alert proposal approval state."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# --- Source Item Models ---

class SourceItem(BaseModel):
    """
    A single item from a source feed.
    
    Security: title, body, and metadata are UNTRUSTED DATA.
    Never use them to construct file paths, URLs, or commands.
    """
    item_id: str = Field(..., description="Unique item identifier")
    source: str = Field(..., description="Source name (e.g., CPSC, FDA)")
    url: str = Field(..., description="Source URL for evidence")
    title: str = Field(..., description="Item title (untrusted)")
    body: Optional[str] = Field(None, description="Item body text (untrusted)")
    content_hash: str = Field(..., description="SHA-256 of normalized content")
    fetch_time: datetime = Field(default_factory=datetime.utcnow)
    status: ItemStatus = Field(default=ItemStatus.PENDING)
    error_code: Optional[str] = None

    @staticmethod
    def compute_content_hash(title: str, body: Optional[str]) -> str:
        """Compute SHA-256 hash of normalized content for deduplication."""
        # Normalize: lowercase, collapse whitespace
        normalized = f"{title.lower()} {(body or '').lower()}"
        normalized = " ".join(normalized.split())
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


class Attachment(BaseModel):
    """An image or PDF attachment associated with a source item."""
    attachment_id: str
    item_id: str
    url: str = Field(..., description="Original URL (metadata only in replay)")
    local_path: Optional[str] = Field(None, description="Path in fixture or cache")
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    content_hash: Optional[str] = Field(None, description="SHA-256 of file bytes")


# --- OCR Models ---

class OCRResult(BaseModel):
    """
    Result from OCR extraction.
    
    Confidence values are engine-specific and should be documented.
    """
    engine: str = Field(..., description="tesseract, easyocr, etc.")
    text: str = Field(..., description="Extracted text (untrusted data)")
    raw_confidence: Optional[float] = Field(None, description="Engine-specific confidence")
    normalized_confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Normalized 0.0-1.0 confidence scale"
    )
    language: Optional[str] = Field(None, description="Detected language code")
    needs_second_opinion: bool = Field(
        default=False,
        description="Flag indicating low confidence or quality"
    )
    preprocessing: Optional[str] = Field(None, description="Preprocessing profile used")
    metadata: Dict[str, Any] = Field(default_factory=dict)


# --- Agent Models ---

class ActionRequest(BaseModel):
    """
    Planner's requested next action.
    
    Security: arguments are validated by controller before execution.
    """
    action: ToolName = Field(..., description="Tool to invoke")
    rationale: str = Field(..., description="Why this action was selected")
    arguments: Dict[str, Any] = Field(default_factory=dict)


class BudgetState(BaseModel):
    """Current budget remaining for item and run."""
    item_usd: float = Field(..., ge=0.0)
    run_usd: float = Field(..., ge=0.0)
    steps: int = Field(..., ge=0)


class TraceEvent(BaseModel):
    """
    A single step in the agent's execution trace.
    
    Written as JSONL for append efficiency and readability.
    """
    run_id: str
    item_id: str
    step_index: int = Field(..., ge=0)
    timestamp_utc: datetime = Field(default_factory=datetime.utcnow)
    planner_mode: PlannerMode
    tool: ToolName
    arguments_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Safe summary; do not include raw PII or secrets"
    )
    result_summary: Dict[str, Any] = Field(default_factory=dict)
    decision_rationale: str = ""
    input_hashes: List[str] = Field(default_factory=list, description="Content hashes processed")
    tokens_in: Optional[int] = Field(None, description="Null if unavailable")
    tokens_out: Optional[int] = Field(None, description="Null if unavailable")
    cost_usd: Optional[float] = Field(None, description="Null if unavailable or free")
    latency_ms: Optional[float] = Field(None, ge=0.0)
    status: ItemStatus
    fallback_used: bool = False
    error_code: Optional[str] = None
    budget_remaining: Optional[BudgetState] = None
    cache_hit: bool = False
    prompt_version: Optional[str] = Field(None, description="SHA-256 of prompt")
    model: Optional[str] = Field(None, description="Model name or 'fallback'")

    def to_jsonl_line(self) -> str:
        """Serialize to compact JSONL line."""
        return self.model_dump_json(exclude_none=False) + "\n"


# --- Scoring and Classification Models ---

class ScoreBreakdown(BaseModel):
    """Component scores for transparency."""
    relevance: float = Field(..., ge=0.0, le=100.0)
    urgency: float = Field(..., ge=0.0, le=100.0)
    credibility: float = Field(..., ge=0.0, le=100.0, description="Source credibility")
    recency_boost: float = Field(..., ge=0.0, le=100.0)
    final_score: float = Field(..., ge=0.0, le=100.0)
    
    @classmethod
    def compute_final(
        cls,
        relevance: float,
        urgency: float,
        credibility: float,
        recency_boost: float
    ) -> float:
        """Compute weighted final score using documented formula."""
        return (
            0.45 * relevance +
            0.40 * urgency +
            0.10 * credibility +
            0.05 * recency_boost
        )


class AlertProposal(BaseModel):
    """
    A proposed alert that requires human approval.
    
    Never sent automatically; requires explicit approve command.
    """
    proposal_id: str
    item_id: str
    urgency: float = Field(..., ge=0.0, le=100.0)
    evidence_json: Dict[str, Any] = Field(
        ...,
        description="Source URL, redacted snippets, confidence, verification"
    )
    status: ProposalStatus = Field(default=ProposalStatus.PENDING)
    created_time: datetime = Field(default_factory=datetime.utcnow)
    approved_time: Optional[datetime] = None
    
    @field_validator('evidence_json')
    @classmethod
    def validate_evidence_has_source(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure evidence includes source URL."""
        if 'source_url' not in v:
            raise ValueError("evidence_json must include source_url")
        return v


# --- Run Metadata ---

class RunMetadata(BaseModel):
    """Metadata for a single run of the monitor."""
    run_id: str
    run_time: datetime = Field(default_factory=datetime.utcnow)
    mode: str = Field(..., description="live or replay")
    item_count: int = Field(default=0, ge=0)
    budget_used_usd: float = Field(default=0.0, ge=0.0)
    digest_path: Optional[str] = None


# --- Configuration Models ---

class SourceConfig(BaseModel):
    """Configuration for a single source."""
    name: str
    type: str = Field(..., description="rss, etc.")
    url: str
    allowed_hosts: List[str] = Field(..., min_length=1)
    poll_interval_seconds: int = Field(default=3600, gt=0)


class LimitsConfig(BaseModel):
    """Runtime limits."""
    max_items_per_run: int = Field(default=100, gt=0)
    max_steps_per_item: int = Field(default=10, gt=0)
    http_timeout_seconds: int = Field(default=30, gt=0)
    max_download_bytes: int = Field(default=10485760, gt=0)  # 10 MB
    max_retries: int = Field(default=3, ge=0)


class BudgetsConfig(BaseModel):
    """Cost budgets."""
    per_item_usd: float = Field(default=0.10, gt=0.0)
    per_run_usd: float = Field(default=5.00, gt=0.0)


class ThresholdsConfig(BaseModel):
    """Decision thresholds."""
    ocr_confidence_second_opinion: float = Field(default=0.7, ge=0.0, le=1.0)
    urgency_critique_threshold: float = Field(default=75.0, ge=0.0, le=100.0)
    urgency_alert_threshold: float = Field(default=85.0, ge=0.0, le=100.0)


class MonitorConfig(BaseModel):
    """Complete monitor configuration."""
    sources: List[SourceConfig] = Field(default_factory=list)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    budgets: BudgetsConfig = Field(default_factory=BudgetsConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
