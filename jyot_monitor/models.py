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

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator
import hashlib


def utc_now() -> datetime:
    """Return timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


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
    fetch_time: datetime = Field(default_factory=utc_now)
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
    
    Confidence values are engine-specific and documented.
    """
    item_id: Optional[str] = Field(None, description="Source item identifier if available")
    attachment_id: Optional[str] = Field(None, description="Attachment identifier if available")
    engine: str = Field(..., description="tesseract, easyocr, etc.")
    engine_version: Optional[str] = Field(None, description="Obtained engine version")
    text: str = Field(..., description="Extracted text (untrusted data)")
    raw_confidence: Optional[float] = Field(None, description="Engine-specific confidence")
    normalized_confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Normalized 0.0-1.0 confidence scale"
    )
    confidence_semantics: Optional[str] = Field(
        None,
        description="Explanation of engine-specific confidence metric and limitations"
    )
    language: Optional[str] = Field(None, description="Detected or selected language code")
    image_dimensions: Optional[Tuple[int, int]] = Field(
        None,
        description="Image dimensions as (width, height)"
    )
    quality_signals: Dict[str, Any] = Field(
        default_factory=dict,
        description="Image quality signals: blur_score, contrast_score, mean_brightness, etc."
    )
    preprocessing_applied: bool = Field(
        default=False,
        description="Whether image preprocessing was applied before OCR"
    )
    preprocessing_operations: List[str] = Field(
        default_factory=list,
        description="List of applied operations (e.g. ['deskew', 'clahe', 'otsu'])"
    )
    preprocessing: Optional[str] = Field(None, description="Preprocessing profile used")
    needs_second_opinion: bool = Field(
        default=False,
        description="Flag indicating low confidence, poor quality, or ambiguous output"
    )
    second_opinion_reason: Optional[str] = Field(
        None,
        description="Documented rationale for triggering second opinion"
    )
    errors: List[str] = Field(default_factory=list, description="Non-fatal errors encountered")
    warnings: List[str] = Field(default_factory=list, description="Warnings during OCR execution")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RoutedOCRResult(BaseModel):
    """
    Result of the explicit multi-engine OCR router.
    
    Records engine choice, routing signals, rationale, second opinion, and final output.
    """
    selected_engine: str = Field(..., description="Initial engine chosen by router")
    initial_result: OCRResult = Field(..., description="Initial OCR attempt result")
    second_opinion_result: Optional[OCRResult] = Field(
        None,
        description="Second opinion result if triggered"
    )
    final_result: OCRResult = Field(..., description="Final selected/best OCR result")
    routing_signals: Dict[str, Any] = Field(
        default_factory=dict,
        description="Signals considered by router (quality, language, confidence)"
    )
    decision_rationale: str = Field(..., description="Deterministic decision explanation")
    trajectory_name: str = Field(..., description="Trajectory name (e.g. clean_english_direct)")


class ProductSafetyNotice(BaseModel):
    """
    Validated structured schema for product safety and recall notice extraction.
    
    Fields that cannot be read confidently are set to None and recorded in uncertain_fields.
    Evidence text is preserved for provenance.
    """
    product_name: Optional[str] = Field(None, description="Name of the recalled product")
    manufacturer: Optional[str] = Field(None, description="Manufacturer, distributor, or brand")
    notice_date: Optional[str] = Field(None, description="Date of recall or safety notice")
    hazard: Optional[str] = Field(None, description="Safety hazard or risk description")
    recommended_action: Optional[str] = Field(None, description="Remedy or action required for consumers")
    recall_identifier: Optional[str] = Field(None, description="Official recall number, campaign ID, or units")
    raw_ocr_text: str = Field(..., description="Underlying OCR text evidence")
    uncertain_fields: List[str] = Field(
        default_factory=list,
        description="Fields that could not be determined with high confidence"
    )
    confidence_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Estimated completeness and confidence of structured extraction"
    )


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
    timestamp_utc: datetime = Field(default_factory=utc_now)
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


class RecallTaxonomy(str, Enum):
    """Documented taxonomy for product-recall and safety notices."""
    PRODUCT_RECALL = "product_recall"
    HEALTH_HAZARD = "health_hazard"
    CONTAMINATION = "contamination"
    UNSAFE_EQUIPMENT = "unsafe_equipment"
    CONSUMER_WARNING = "consumer_warning"
    NON_SAFETY = "non_safety"
    SPAM_MANIPULATION = "spam_manipulation"
    UNCERTAIN = "uncertain"


class ToolResult(BaseModel):
    """
    Standard schema for tool execution results.
    
    Security: returned data is evidence, not executable code.
    """
    tool_name: ToolName
    status: str = Field(default="success", description="success, error, or unavailable")
    data: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    is_evidence: bool = True


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


class ClassificationResult(BaseModel):
    """Structured classification and scoring result."""
    taxonomy: RecallTaxonomy
    relevance_score: float = Field(..., ge=0.0, le=100.0)
    urgency_score: float = Field(..., ge=0.0, le=100.0)
    score_breakdown: Optional[ScoreBreakdown] = None
    hazard_description: Optional[str] = None
    affected_products: List[str] = Field(default_factory=list)
    evidence_snippets: List[str] = Field(default_factory=list)
    uncertainty_notes: Optional[str] = None
    is_unverified: bool = False


class VerificationStatus(str, Enum):
    """Outcome of claim verification."""
    SUPPORTED = "supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONTRADICTED = "contradicted"
    UNVERIFIED = "unverified"


class VerificationResult(BaseModel):
    """Result of claim verification against independent sources."""
    status: VerificationStatus
    independent_sources_count: int = 0
    corroborating_item_ids: List[str] = Field(default_factory=list)
    rationale: str


class CritiqueResult(BaseModel):
    """Result of self-checking critique for high-urgency items."""
    pre_critique_urgency: float = Field(..., ge=0.0, le=100.0)
    post_critique_urgency: float = Field(..., ge=0.0, le=100.0)
    urgency_changed: bool = False
    challenge_points: List[str] = Field(default_factory=list)
    uncertainties_identified: List[str] = Field(default_factory=list)
    should_propose_alert: bool = False
    critique_rationale: str = ""


class StoryCluster(BaseModel):
    """A persistent story cluster grouping related/duplicate items."""
    cluster_id: str
    representative_item_id: str
    member_item_ids: List[str] = Field(default_factory=list)
    similarity_evidence: Dict[str, Any] = Field(default_factory=dict)
    created_time: datetime = Field(default_factory=utc_now)
    last_updated: datetime = Field(default_factory=utc_now)


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
    created_time: datetime = Field(default_factory=utc_now)
    approved_time: Optional[datetime] = None
    
    @field_validator('evidence_json')
    @classmethod
    def validate_evidence_has_source(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure evidence includes source URL."""
        if 'source_url' not in v:
            raise ValueError("evidence_json must include source_url")
        return v


class ItemProcessingResult(BaseModel):
    """Execution summary for a processed item."""
    item_id: str
    status: ItemStatus
    steps_taken: int
    completed_tools: List[ToolName]
    final_scores: Optional['ClassificationResult'] = None
    verification: Optional['VerificationResult'] = None
    critique: Optional['CritiqueResult'] = None
    alert_proposal: Optional[AlertProposal] = None
    cluster_id: Optional[str] = None
    error_message: Optional[str] = None
    fallback_used: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    total_latency_ms: float = 0.0


# --- Run Metadata ---

class RunMetadata(BaseModel):
    """Metadata for a single run of the monitor."""
    run_id: str
    run_time: datetime = Field(default_factory=utc_now)
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
