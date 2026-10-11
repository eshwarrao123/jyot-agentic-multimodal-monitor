# Requirements Traceability Matrix

**Track B (Extended), AI Generalist Assignment for Jyot**  
**Document Version:** 1.0  
**Last Updated:** 2026-10-11

This matrix maps every mandatory requirement, numerical minimum, command, deliverable and evaluation criterion from the original assignment (`source/JYOT_ASSIGNMENT_ORIGINAL.txt`) to planned modules, tests, and acceptance criteria.

## Status Legend
- `NOT STARTED` — No implementation or documentation exists
- `IN PROGRESS` — Partially implemented or documented
- `VERIFIED` — Requirement demonstrated by passing tests or completed artifacts
- `BLOCKED` — Cannot proceed due to external dependency or unresolved issue

## Phase 1 Status Update (2026-10-11)
Phase 1 implements foundational infrastructure only: CLI parsing, data models, SQLite persistence, JSONL tracing, and configuration loading. Requirements marked `IN PROGRESS` have CLI parsing or schema structure implemented but defer full feature implementation to designated phases. Only requirements with complete implementation and passing tests are marked `VERIFIED`.

## Phase 2 Status Update (2026-10-12)
Phase 2 implements the multi-engine OCR subsystem, image preprocessing, multi-page scanned PDF rasterization, deterministic signal-based routing, structured product safety notice extraction with uncertainty flagging, an 18-record ground-truth gold dataset, and reproducible CER/WER evaluation. Requirements `REQ-OCR-001` through `REQ-OCR-006`, `REQ-EVAL-001`, and `REQ-EVAL-002` are fully implemented and verified by 75 passing automated tests and empirical offline evaluation metrics.

---

## 1. INGESTION REQUIREMENTS

### REQ-ING-001: Two Public Authentication-Light Sources
**Source:** Assignment Section 4, Stage 1  
**Requirement:** Choose at least two public, authentication-light sources, at least one must regularly contain image or PDF attachments.  
**Planned Module:** `ingestion/rss_adapters.py`, `config/sources.yaml`  
**Implementation:**
- CPSC RSS: `https://www.cpsc.gov/Newsroom/CPSC-RSS-Feed/Recalls-RSS`
- FDA RSS: `https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/recalls/rss.xml`  
**Tests:** `tests/test_ingestion.py::test_live_feed_parsing`, `tests/test_ingestion.py::test_attachment_discovery`  
**Evidence:** Parsed feed items with discovered attachment metadata  
**Acceptance:** Both feeds parse successfully; at least one contains discoverable image/PDF references  
**Status:** `NOT STARTED`

### REQ-ING-002: Repeatable Incremental Ingestion
**Source:** Assignment Section 4, Stage 1  
**Requirement:** Ingester must be runnable repeatedly and fetch only new items (track cursors or seen IDs persistently).  
**Planned Module:** `storage.py`, `ingestion/feed_state.py`  
**Implementation:** SQLite table for feed cursors and seen item IDs; idempotent insert/update  
**Tests:** `tests/test_ingestion.py::test_incremental_fetch`, `tests/test_storage.py::test_idempotent_seen_items`  
**Evidence:** Second poll fetches zero items when no new content exists  
**Acceptance:** Running the same live poll twice does not duplicate items in state  
**Status:** `NOT STARTED`

### REQ-ING-003: Replay Mode Mandatory
**Source:** Assignment Section 4, Stage 1; Section 5 CLI Contract  
**Requirement:** Implement `--replay <dir>` which runs the whole pipeline on recorded fixtures with no network access.  
**Planned Module:** `ingestion/fixture_loader.py`, `cli.py`  
**Implementation:** Load manifest JSON with local attachment paths; disable/mock network clients  
**Tests:** `tests/test_cli.py::test_run_replay_mode` (argument parsing); network isolation tests deferred to Phase 4  
**Evidence:** Replay command parses correctly; full pipeline implementation deferred to Phase 2-4  
**Acceptance:** `python -m jyot_monitor run --replay fixtures/recorded --top-n 10` parses arguments  
**Status:** `IN PROGRESS` (CLI parsing complete; pipeline implementation deferred)

---

## 2. OCR AND VISUAL EXTRACTION REQUIREMENTS

### REQ-OCR-001: Two Extraction Engines
**Source:** Assignment Section 4, Stage 2  
**Requirement:** Use at least two extraction engines (e.g., Tesseract and EasyOCR or a vision-capable LLM).  
**Planned Module:** `ocr/tesseract_adapter.py`, `ocr/easyocr_adapter.py`  
**Implementation:** Tesseract 5.4.0 (via `pytesseract`) and EasyOCR 1.7.2 (with PyTorch CPU models for English and Hindi). Both adapters output the validated `OCRResult` schema.  
**Tests:** `tests/test_ocr.py::test_tesseract_adapter_contract`, `tests/test_ocr.py::test_easyocr_adapter_contract`, `tests/test_ocr.py::test_easyocr_hindi_support`  
**Evidence:** Both engines executed offline on 18 gold fixtures; Tesseract CER=0.2936, EasyOCR CER=0.1490; automated adapter unit tests pass  
**Acceptance:** Each engine processes test images and returns structured OCR result with text, confidence, and engine metadata  
**Status:** `VERIFIED`

### REQ-OCR-002: Router with Explicit Logged Decision
**Source:** Assignment Section 4, Stage 2  
**Requirement:** Router must make an explicit, logged decision based on signals (image quality, OCR confidence, text density, script/language, layout type).  
**Planned Module:** `ocr/router.py`  
**Implementation:** Deterministic `OCRRouter` evaluates resolution, Laplacian blur variance, contrast dynamic range, skew angle, script detection, and primary engine confidence. Logs decision rationale, trajectory name, signals, and engine selection into `RoutedOCRResult`.  
**Tests:** `tests/test_ocr.py::test_router_clean_english_trajectory`, `tests/test_ocr.py::test_router_difficult_second_opinion_trajectory`, `tests/test_ocr.py::test_router_hindi_trajectory`  
**Evidence:** 3 distinct trajectories verified across 18 gold records (10 clean English direct, 4 degraded second opinion, 4 Hindi specialized); router achieved lowest overall CER of 0.0945  
**Acceptance:** Low-confidence or degraded inputs trigger explicit second-opinion engine call with logged rationale; clean inputs process directly  
**Status:** `VERIFIED`

### REQ-OCR-003: Preprocessing Stage with Measurements
**Source:** Assignment Section 4, Stage 2  
**Requirement:** Include preprocessing (deskew, denoise, binarization, upscaling, cropping). Show with measurements that preprocessing helps (or does not).  
**Planned Module:** `ocr/preprocessing.py`, `ocr/quality.py`  
**Implementation:** Modular OpenCV/Pillow transformations: `contrast_enhanced` (CLAHE), `binarized` (Otsu thresholding), `deskewed` (Hough line angle correction), `upscaled` (bicubic interpolation), and `adaptive_full`. Preserves raw image path for comparison and fallback.  
**Tests:** `tests/test_ocr.py::test_preprocessing_original_profile`, `tests/test_ocr.py::test_preprocessing_clahe`, `tests/test_ocr.py::test_preprocessing_binarization`, `tests/test_ocr.py::test_preprocessing_upscaling`, `tests/test_ocr.py::test_deskew_image_correction`  
**Evidence:** Preprocessing ablation report in `artifacts/eval/ocr_eval_report.md` demonstrates Tesseract CER improved from 0.2936 to 0.2512 (Δ +0.0424) and EasyOCR CER improved from 0.1490 to 0.1357 (Δ +0.0133); deskewing rescued rotated failure cases  
**Acceptance:** Computed metrics show per-profile impact across labelled dataset with documented conclusions  
**Status:** `VERIFIED`

### REQ-OCR-004: Handle Required Content Types
**Source:** Assignment Section 4, Stage 2  
**Requirement:** Handle at least: (a) screenshots of text, (b) photographed/rotated or low-contrast images, (c) scanned PDF with >1 page, (d) one non-English/non-Latin script (Hindi or Gujarati) alongside English.  
**Planned Module:** `ocr/pdf_rendering.py`, `ocr/router.py`, `fixtures/gold/`  
**Implementation:** PyMuPDF 200-DPI rasterization retaining page-level provenance (page number, SHA-256 hash, pixel dimensions) with security checks; EasyOCR Hindi (`hi`+`en`) language routing; deskewing and contrast enhancement for degraded images.  
**Tests:** `tests/test_ocr.py::test_pdf_rendering_multipage`, `tests/test_ocr.py::test_pdf_validation_oversized`, `tests/test_ocr.py::test_pdf_validation_corrupt`, `tests/test_ocr.py::test_easyocr_hindi_support`, `tests/test_ocr.py::test_quality_signals_on_blurry_image`  
**Evidence:** Gold dataset contains 6 clean screenshots (CER 0.0313), 5 degraded/rotated/blurry/noisy cases (CER 0.1724), 4 Hindi notices (EasyOCR CER 0.1518; Tesseract English-only CER 0.7510 as tessdata lacks hin.traineddata), and 1 3-page scanned PDF (CER 0.0528)  
**Acceptance:** All four content types processed offline; Hindi CER/WER reported separately  
**Status:** `VERIFIED`

### REQ-OCR-005: Structured Extraction with Validation
**Source:** Assignment Section 4, Stage 2  
**Requirement:** For at least one document type with structure (notice, receipt, table, form), extract structured fields into JSON schema with validation; flag fields the model could not read confidently instead of guessing.  
**Planned Module:** `ocr/structured_extraction.py`, `models.py::ProductSafetyNotice`  
**Implementation:** Pydantic `ProductSafetyNotice` schema (product name, manufacturer, notice date, hazard, recommended action, identifiers, confidence, raw text evidence). Deterministic extractor `extract_safety_notice` flags unextracted or unconfident fields in `uncertain_fields` list.  
**Tests:** `tests/test_ocr.py::test_structured_notice_extraction_confident`, `tests/test_ocr.py::test_structured_notice_extraction_missing_fields`  
**Evidence:** Clean safety notice extracted with 0 uncertain fields; degraded notice with missing manufacturer and date returned `null` fields and populated `uncertain_fields=['manufacturer', 'notice_date']`  
**Acceptance:** Notice with missing/unclear field returns `null` + uncertainty flag, never fabricated values  
**Status:** `VERIFIED`

### REQ-OCR-006: Confidence and Metadata
**Source:** Assignment Section 4, Stage 2  
**Requirement:** Every OCR result must carry: engine used, confidence (calibrated or documented), language, and a flag for "needs second opinion".  
**Planned Module:** `models.py::OCRResult`  
**Implementation:** Extended `OCRResult` with `engine`, `engine_version`, `raw_confidence`, `normalized_confidence`, `confidence_semantics`, `detected_language`, `image_dimensions`, `quality_signals`, `preprocessing_applied`, `operations_applied`, `needs_second_opinion`, and `second_opinion_reason`. Documented uncalibrated nature of raw engine scores.  
**Tests:** `tests/test_ocr.py::test_tesseract_adapter_contract`, `tests/test_ocr.py::test_easyocr_adapter_contract`  
**Evidence:** Pydantic validation passes; metadata inspection verified in automated tests and eval outputs  
**Acceptance:** All metadata fields present; confidence normalization and semantic limitations documented  
**Status:** `VERIFIED`

---

## 3. AGENT REQUIREMENTS

### REQ-AGENT-001: LLM-Driven Planner/Controller
**Source:** Assignment Section 4, Stage 3  
**Requirement:** Build an agent loop in which a planner (LLM-driven) decides, per item, which tools to call, in what order, and when to stop. A fixed linear chain does not satisfy this stage.  
**Planned Module:** `agent/planner.py`, `agent/controller.py`  
**Implementation:** Planner emits schema-validated action; controller validates arguments and permissions  
**Tests:** `tests/test_agent.py::test_planner_action_selection`, `tests/test_agent.py::test_controller_validates_arguments`  
**Evidence:** JSONL trace shows varied tool sequences per item type  
**Acceptance:** Planner makes different decisions for different item signals  
**Status:** `NOT STARTED`

### REQ-AGENT-002: Minimum Tool Set
**Source:** Assignment Section 4, Stage 3  
**Requirement:** Implement tools: `fetch_attachment`, `ocr_extract`, `vision_describe`, `search_memory`, `verify_claim`, `propose_alert`.  
**Planned Module:** `agent/tools.py`  
**Implementation:** Each tool registered with typed signature and permission policy  
**Tests:** `tests/test_agent.py::test_tool_registry`, `tests/test_agent.py::test_each_tool`  
**Evidence:** Each tool callable and traceable  
**Acceptance:** All six tools exist, execute, and write trace entries  
**Status:** `NOT STARTED`

### REQ-AGENT-003: Bounded Autonomy
**Source:** Assignment Section 4, Stage 3  
**Requirement:** Maximum step count per item, per-item and per-run token/cost budget, graceful degradation when budget hit.  
**Planned Module:** `agent/controller.py`, `config.py`  
**Implementation:** Configurable max steps (default 10), per-item budget USD, per-run budget; stop with `partial_processed` status on exhaustion  
**Tests:** `tests/test_agent.py::test_step_limit_enforced`, `tests/test_agent.py::test_budget_exhaustion_fallback`  
**Evidence:** Trace shows budget remaining; item marked partial when limit reached  
**Acceptance:** Item processing stops before limit exceeded; no unbounded loops  
**Status:** `NOT STARTED`

### REQ-AGENT-004: Variable Trajectories
**Source:** Assignment Section 4, Stage 3  
**Requirement:** Logs must demonstrate at least three clearly different trajectories on real inputs.  
**Planned Module:** `artifacts/traces/`, `docs/09_AGENT_WALKTHROUGH_TEMPLATE.md`  
**Implementation:** Generate traces from varied test items; document in walkthrough  
**Tests:** `tests/test_agent.py::test_distinct_trajectories`  
**Evidence:** Five-item walkthrough with actual trace IDs showing: (1) text-only one-pass, (2) blurry screenshot with second OCR, (3) urgent claim with verification  
**Acceptance:** Three or more distinct tool sequences proven in JSONL traces  
**Status:** `NOT STARTED`

### REQ-AGENT-005: Structured Outputs with Validation
**Source:** Assignment Section 4, Stage 3  
**Requirement:** All LLM outputs schema-validated (e.g., Pydantic), bounded retries, deterministic fallback on repeated failure.  
**Planned Module:** `llm/validation.py`, `agent/controller.py`  
**Implementation:** Parse JSON, validate with Pydantic; retry up to 3 times; use deterministic fallback action on final failure  
**Tests:** `tests/test_llm.py::test_invalid_json_retry`, `tests/test_llm.py::test_deterministic_fallback`  
**Evidence:** Trace shows retry count and fallback activation  
**Acceptance:** Invalid LLM response triggers bounded retry then fallback, never crashes  
**Status:** `NOT STARTED`

### REQ-AGENT-006: Self-Checking for Urgent Items
**Source:** Assignment Section 4, Stage 3  
**Requirement:** For items scored above urgency threshold, add critique, self-consistency, or verifier step; show whether it changed outcomes.  
**Planned Module:** `agent/tools.py::critique_item`, `agent/tools.py::verify_claim`  
**Implementation:** When urgency > threshold, invoke critique; log before/after urgency and alert decision  
**Tests:** `tests/test_agent.py::test_critique_changes_decision`, `tests/test_agent.py::test_critique_confirms_decision`  
**Evidence:** Trace shows both cases where critique lowered urgency and where it confirmed  
**Acceptance:** At least one test case where critique changed alert decision  
**Status:** `NOT STARTED`

### REQ-AGENT-007: Full Tracing
**Source:** Assignment Section 4, Stage 3  
**Requirement:** Every run writes JSONL trace (item ID, step, tool, arguments, result summary, tokens, latency, cost, decision rationale) that a reviewer can replay.  
**Planned Module:** `trace.py`  
**Implementation:** JSONL writer with complete schema; trace integration with agent deferred to Phase 3  
**Tests:** `tests/test_trace.py` — 9 tests covering trace writing, reading, schema validation  
**Evidence:** TraceEvent model with all required fields; Tracer class writes valid JSONL  
**Acceptance:** Trace infrastructure complete; agent integration in Phase 3  
**Status:** `IN PROGRESS` (trace writer verified; agent integration deferred)

### REQ-AGENT-008: Framework Choice Justified
**Source:** Assignment Section 4, Stage 3  
**Requirement:** If using a framework, state what it gave you; if hand-rolling, state why.  
**Planned Module:** `docs/02_TRD.md`, `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md`  
**Implementation:** Custom bounded controller; justification: tight deadline, simple loop, no complex DAG orchestration needed  
**Tests:** N/A  
**Evidence:** Write-up explains framework decision  
**Acceptance:** Justification appears in final write-up  
**Status:** `NOT STARTED`

---

## 4. CLASSIFICATION, SCORING, AND DEDUPLICATION REQUIREMENTS

### REQ-SCORE-001: Subtopic Tagging
**Source:** Assignment Section 4, Stage 4  
**Requirement:** Tag each item by subtopic (taxonomy of your design; document it).  
**Planned Module:** `scoring.py`, `prompts/classification_scoring.txt`  
**Implementation:** Taxonomy: `recall`, `safety_alert`, `medical_product_alert`, `non_safety`, `spam_or_manipulation`, `uncertain`  
**Tests:** `tests/test_scoring.py::test_classification`  
**Evidence:** Classification labels in evaluation report  
**Acceptance:** Each item receives one taxonomy label  
**Status:** `NOT STARTED`

### REQ-SCORE-002: Relevance and Urgency with Non-LLM Signal
**Source:** Assignment Section 4, Stage 4  
**Requirement:** Score relevance and urgency with LLM/prompt-based approach; include at least one non-LLM signal (recency, source credibility, engagement velocity, corroboration count). Explain combination logic.  
**Planned Module:** `scoring.py`, `docs/03_ARCHITECTURE.md`  
**Implementation:** LLM relevance + urgency (0-100 each); non-LLM: source credibility (official = 90, other = 50), recency boost (last 7 days = +10); final score weighted combination  
**Tests:** `tests/test_scoring.py::test_non_llm_signals`, `tests/test_scoring.py::test_score_combination`  
**Evidence:** Score breakdown in digest and trace  
**Acceptance:** Non-LLM signal documented and demonstrable in score breakdown  
**Status:** `NOT STARTED`

### REQ-DEDUP-001: Cross-Modal and Phrasing Deduplication
**Source:** Assignment Section 4, Stage 4  
**Requirement:** Deduplicate across modalities and phrasing: near-identical text, reposts, same content as image vs text. Use at least two techniques (embeddings + MinHash, perceptual hash for images, OCR-text embedding for cross-modal).  
**Planned Module:** `dedup.py`  
**Implementation:** (1) Exact SHA-256 + MinHash/LSH for text near-duplicates, (2) perceptual hash (imagehash) for images, (3) OCR text similarity for cross-modal matches  
**Tests:** `tests/test_dedup.py::test_text_dedup`, `tests/test_dedup.py::test_image_dedup`, `tests/test_dedup.py::test_cross_modal_dedup`  
**Evidence:** Evaluation report shows cross-modal duplicate groups detected  
**Acceptance:** At least one cross-modal duplicate (text post + screenshot of same content) clustered together  
**Status:** `NOT STARTED`

### REQ-DEDUP-002: Story Clusters with Best Representative
**Source:** Assignment Section 4, Stage 4  
**Requirement:** Group related items into story clusters rather than merely dropping duplicates; keep best-quality representative.  
**Planned Module:** `dedup.py`, `storage.py`  
**Implementation:** Cluster similar items; select representative by extraction completeness, source reliability, OCR confidence, timestamp  
**Tests:** `tests/test_dedup.py::test_cluster_representative_selection`  
**Evidence:** Digest shows cluster with multiple source references and selected representative  
**Acceptance:** Cluster contains multiple items; highest-quality item marked as representative  
**Status:** `NOT STARTED`

### REQ-DEDUP-003: Persistent Memory Across Runs
**Source:** Assignment Section 4, Stage 4  
**Requirement:** Maintain persistent memory so next digest can state what is new, what escalated, what was already reported.  
**Planned Module:** `storage.py`, `digest.py`  
**Implementation:** SQLite stores prior run ID, item clusters, digest state; digest compares current vs prior  
**Tests:** `tests/test_digest.py::test_since_last_digest`  
**Evidence:** Digest section "What changed since last digest" with concrete examples  
**Acceptance:** Second digest run shows "new", "escalated", "already reported" labels  
**Status:** `NOT STARTED`

---

## 5. SAFETY AND ADVERSARIAL ROBUSTNESS REQUIREMENTS

### REQ-SAFE-001: Prompt Injection Resistance via OCR
**Source:** Assignment Section 4, Stage 5  
**Requirement:** Images containing instructions to AI, to raise score, or call tools must not be followed. Tests must show it. Describe isolation strategy.  
**Planned Module:** `safety.py`, `agent/controller.py`, `prompts/*.txt`  
**Implementation:** Data/instruction separation in prompts; controller validates tool permissions independently; no arbitrary tool names from content  
**Tests:** `tests/test_safety.py::test_ocr_injection_blocked`, `tests/test_safety.py::test_score_manipulation_blocked`  
**Evidence:** Evaluation report shows attack success rate on 8+ adversarial cases  
**Acceptance:** Target attack success rate = 0; document any failures  
**Status:** `NOT STARTED`

### REQ-SAFE-002: PII Handling
**Source:** Assignment Section 4, Stage 5  
**Requirement:** Detect and redact emails, phone numbers, similar identifiers recovered from screenshots before digest/alerts.  
**Planned Module:** `safety.py::redact_pii`  
**Implementation:** Regex patterns for email, phone; redact before digest/proposal rendering  
**Tests:** `tests/test_safety.py::test_pii_redaction_email`, `tests/test_safety.py::test_pii_redaction_phone`  
**Evidence:** Digest artifact shows redacted PII (`[EMAIL_REDACTED]`, `[PHONE_REDACTED]`)  
**Acceptance:** Test PII does not appear in digest or alert proposal text  
**Status:** `NOT STARTED`

### REQ-SAFE-003: Network Safety
**Source:** Assignment Section 4, Stage 5  
**Requirement:** Allow-listed schemes, blocked private IP ranges, response size limits, content-type verification.  
**Planned Module:** `safety.py::validate_url`, `ingestion/fetch.py`  
**Implementation:** HTTPS-only (or explicit HTTP allow-list), DNS resolution check against private/loopback/link-local IPs, redirect validation, timeout, max bytes, MIME/magic verification  
**Tests:** `tests/test_safety.py::test_ssrf_blocked_private_ip`, `tests/test_safety.py::test_redirect_validation`, `tests/test_safety.py::test_content_type_enforcement`  
**Evidence:** Test attempts to fetch private IP or invalid content-type are rejected  
**Acceptance:** All network safety tests pass; private IP fetch raises error  
**Status:** `NOT STARTED`

### REQ-SAFE-004: Spam/Manipulation Defense
**Source:** Assignment Section 4, Stage 5  
**Requirement:** Defense against low-quality, repetitive, or coordinated posts. State the approach and limits.  
**Planned Module:** `safety.py::detect_spam`, `dedup.py`  
**Implementation:** Exact repost detection, normalized text near-duplicate rate, source-level burst detection, minimum evidence requirements  
**Tests:** `tests/test_safety.py::test_repetitive_content_flagged`  
**Evidence:** Write-up explains spam detection and documented limits  
**Acceptance:** Repetitive test items flagged with spam signal in trace  
**Status:** `NOT STARTED`

---

## 6. RELIABILITY AND COST CONTROL REQUIREMENTS

### REQ-REL-001: Rate Limit and Error Handling
**Source:** Assignment Section 4, Stage 6  
**Requirement:** Handle rate limits (backoff with jitter, Retry-After), timeouts, malformed files, model errors with graceful fallbacks and logging.  
**Planned Module:** `ingestion/fetch.py`, `llm/client.py`  
**Implementation:** Exponential backoff with jitter; honor `Retry-After` header; catch per-item errors, mark partial results  
**Tests:** `tests/test_reliability.py::test_rate_limit_backoff`, `tests/test_reliability.py::test_malformed_pdf_fallback`  
**Evidence:** Trace shows retry attempts and fallback activation  
**Acceptance:** Simulated 429 response triggers backoff; run continues after per-item failure  
**Status:** `NOT STARTED`

### REQ-REL-002: Idempotent and Resumable Runs
**Source:** Assignment Section 4, Stage 6  
**Requirement:** Runs must be idempotent and resumable: killing process mid-run and restarting must not duplicate work or digest entries.  
**Planned Module:** `storage.py`, `cli.py`  
**Implementation:** SQLite item state transitions; content hash cache; skip completed items on restart  
**Tests:** `tests/test_reliability.py::test_resume_after_interrupt`  
**Evidence:** Second run after simulated kill shows "resuming from item N"  
**Acceptance:** Restart processes only incomplete items; no duplicate digest entries  
**Status:** `NOT STARTED`

### REQ-REL-003: Caching
**Source:** Assignment Section 4, Stage 6  
**Requirement:** Cache OCR and LLM results by content hash.  
**Planned Module:** `storage.py::cache_ocr_result`, `storage.py::cache_llm_result`  
**Implementation:** SQLite cache tables keyed by SHA-256 of image/text + engine/model ID  
**Tests:** `tests/test_storage.py::test_ocr_cache_hit`, `tests/test_storage.py::test_llm_cache_hit`  
**Evidence:** Trace shows cache hit and zero new API calls on repeated item  
**Acceptance:** Second processing of same content uses cache; no duplicate OCR/LLM calls  
**Status:** `NOT STARTED`

### REQ-REL-004: Fault Injection
**Source:** Assignment Section 4, Stage 6  
**Requirement:** Implement `--fault-injection` flag that randomly or deterministically simulates failures (HTTP 429/500, corrupted image, OCR crash, LLM invalid JSON).  
**Planned Module:** `cli.py`, `ingestion/fault_injector.py`, `ocr/fault_injector.py`, `llm/fault_injector.py`  
**Implementation:** Deterministic fault injection based on item index or seed; inject specific failure types  
**Tests:** `tests/test_reliability.py::test_fault_injection_http_error`, `tests/test_reliability.py::test_fault_injection_ocr_crash`  
**Evidence:** `python -m jyot_monitor run --replay fixtures/recorded --fault-injection` completes with documented failures  
**Acceptance:** Fault injection command runs; trace shows injected failures and safe recovery  
**Status:** `NOT STARTED`

---

## 7. HUMAN-IN-THE-LOOP ALERTING REQUIREMENTS

### REQ-HITL-001: Proposals Only, No Direct Sending
**Source:** Assignment Section 4, Stage 7  
**Requirement:** Agent may only propose alerts. Proposals written to approval queue. Human approves/rejects; only then is alert emitted.  
**Planned Module:** `approval.py`, `agent/tools.py::propose_alert`  
**Implementation:** `propose_alert` writes to SQLite approval queue with status `pending`; separate approve/reject commands change status; emit only on approval  
**Tests:** `tests/test_approval.py::test_proposal_requires_approval`, `tests/test_approval.py::test_alert_not_sent_without_approval`  
**Evidence:** Trace and approval queue show proposal ID with pending status; alert file created only after approve command  
**Acceptance:** No alert emitted until `python -m jyot_monitor approve <id>` executed  
**Status:** `NOT STARTED`

### REQ-HITL-002: Evidence in Proposals
**Source:** Assignment Section 4, Stage 7  
**Requirement:** Each proposal must include evidence: source link, extracted text snippet or image reference, confidence, verification result, why urgency threshold met.  
**Planned Module:** `models.py::AlertProposal`, `approval.py`  
**Implementation:** Pydantic AlertProposal with `source_url`, `evidence_snippet`, `confidence`, `verification_status`, `urgency_rationale`  
**Tests:** `tests/test_approval.py::test_proposal_includes_evidence`  
**Evidence:** Sample proposal JSON contains all evidence fields  
**Acceptance:** Proposal file/record includes all required evidence fields  
**Status:** `NOT STARTED`

---

## 8. DIGEST REQUIREMENTS

### REQ-DIGEST-001: Prioritized Top-N Digest
**Source:** Assignment Section 4, Stage 8  
**Requirement:** Generate prioritized top-N digest (Markdown, HTML, or PDF) grouped by story cluster, including: score breakdown, source links, evidence snippets from OCR (redacted), flags ("low OCR confidence" or "unverified"), "what changed since last digest" section.  
**Planned Module:** `digest.py`  
**Implementation:** Markdown digest with clusters, score components, source links, redacted evidence, uncertainty flags, delta from prior run  
**Tests:** `tests/test_digest.py::test_digest_generation`, `tests/test_digest.py::test_digest_includes_all_sections`  
**Evidence:** Sample digest artifact in `artifacts/digests/`  
**Acceptance:** Digest includes all required sections and fields  
**Status:** `NOT STARTED`

---

## 9. COMMAND-LINE CONTRACT REQUIREMENTS

### REQ-CLI-001: Live Run Command
**Source:** Assignment Section 5  
**Requirement:** `python -m <yourpkg> run --live --sources <config> --top-n 10`  
**Planned Module:** `cli.py`  
**Implementation:** CLI with argparse/typer; live mode fetches from configured sources  
**Tests:** `tests/test_cli.py::test_live_run_command_parsing`  
**Evidence:** Command executes without error (or documented unavailable source error)  
**Acceptance:** Command syntax accepted; live run initiated  
**Status:** `NOT STARTED`

### REQ-CLI-002: Replay with Budget Command
**Source:** Assignment Section 5  
**Requirement:** `python -m <yourpkg> run --replay <fixtures_dir> --top-n 10 --budget-usd 1.00`  
**Planned Module:** `cli.py`, `agent/controller.py`  
**Implementation:** Replay mode with per-run budget enforcement  
**Tests:** `tests/test_cli.py::test_replay_budget_enforcement`  
**Evidence:** Run stops when budget exhausted; trace shows budget remaining  
**Acceptance:** Budget enforced; run completes within limit or stops gracefully  
**Status:** `NOT STARTED`

### REQ-CLI-003: Replay with Fault Injection Command
**Source:** Assignment Section 5  
**Requirement:** `python -m <yourpkg> run --replay <fixtures_dir> --fault-injection`  
**Planned Module:** `cli.py`  
**Implementation:** Fault injection flag enables deterministic failures  
**Tests:** `tests/test_cli.py::test_fault_injection_command`  
**Evidence:** Command runs; trace shows injected faults  
**Acceptance:** Command executes; documented failures appear in trace  
**Status:** `NOT STARTED`

### REQ-CLI-004: Evaluation Command
**Source:** Assignment Section 5  
**Requirement:** `python -m <yourpkg> eval --gold <gold_dir>`  
**Planned Module:** `cli.py`, `evaluation/evaluator.py`  
**Implementation:** Run evaluation harness on gold set; compute metrics; generate report  
**Tests:** `tests/test_evaluation.py::test_eval_command`  
**Evidence:** Evaluation report artifact generated  
**Acceptance:** Command produces `artifacts/eval/evaluation_report.md` with all required metrics  
**Status:** `NOT STARTED`

### REQ-CLI-005: Approval Command
**Source:** Assignment Section 5  
**Requirement:** `python -m <yourpkg> approve <proposal_id>`  
**Planned Module:** `cli.py`, `approval.py`  
**Implementation:** Approve command changes proposal status and emits alert record  
**Tests:** `tests/test_approval.py::test_approve_command`  
**Evidence:** Approved alert written to artifacts  
**Acceptance:** Proposal status changes to `approved`; alert emitted  
**Status:** `NOT STARTED`

### REQ-CLI-006: Offline Replay/Eval
**Source:** Assignment Section 5  
**Requirement:** Replay and eval commands must work offline using free/open-source configuration.  
**Planned Module:** `cli.py`, `llm/client.py`  
**Implementation:** Local Ollama model or deterministic fallback; no remote API calls in replay/eval  
**Tests:** `tests/test_replay.py::test_offline_operation`  
**Evidence:** Network-denial test passes  
**Acceptance:** Replay/eval complete with local model or fallback; no network access  
**Status:** `NOT STARTED`

---

## 10. EVALUATION HARNESS REQUIREMENTS

### REQ-EVAL-001: OCR Gold Set (15+ images)
**Source:** Assignment Section 6  
**Requirement:** 15+ images/pages with hand-written ground-truth transcriptions, including at least 3 hard cases and 3 in non-English script.  
**Planned Module:** `fixtures/gold/`, `fixtures/generate_gold_fixtures.py`  
**Implementation:** 18 labelled records in `fixtures/gold/` with manifest `manifest.json`. Includes 6 clean English screenshots, 5 difficult/degraded images (rotation, blur, low contrast, noise), 4 verified Devanagari Hindi notices, and 1 3-page scanned PDF.  
**Tests:** Verified via `manifest.json` schema validation and full eval run; test cases in `tests/test_ocr.py`  
**Evidence:** 18 image/page files in `fixtures/gold/` with ground-truth transcriptions and difficulty/language labels in `manifest.json`  
**Acceptance:** Minimum 15 images/pages met (18 total: 6 clean English, 5 difficult, 4 Hindi, 3 PDF pages)  
**Status:** `VERIFIED`

### REQ-EVAL-002: OCR Metrics (CER/WER)
**Source:** Assignment Section 6  
**Requirement:** Report character error rate (CER) and word error rate (WER) per engine and for routed system; effect of preprocessing.  
**Planned Module:** `jyot_monitor/evaluation/ocr_eval.py`, `jyot_monitor/cli.py`  
**Implementation:** Levenshtein distance dynamic programming algorithm for CER and WER with NFKC Unicode normalization. Computes metrics per engine (Tesseract, EasyOCR), for routed system, by language (English, Hindi), by difficulty (Easy, Medium, Hard), and preprocessing ablation (original vs preprocessed). Outputs JSON and Markdown reports.  
**Tests:** `tests/test_ocr.py::test_compute_cer`, `tests/test_ocr.py::test_compute_wer`, `tests/test_ocr.py::test_normalize_text_for_eval`, `tests/test_ocr.py::test_levenshtein_distance`  
**Evidence:** `artifacts/eval/ocr_eval_results.json` and `artifacts/eval/ocr_eval_report.md` generated from real execution; Mean CER: Tesseract raw 0.2936, EasyOCR raw 0.1490, Routed 0.0945  
**Acceptance:** Report includes CER/WER for Tesseract, EasyOCR, routed system, and preprocessing ablation  
**Status:** `VERIFIED`

### REQ-EVAL-003: Classification Gold Set (60+ items, 25+ with images)
**Source:** Assignment Section 6  
**Requirement:** 60+ labelled items with at least 25 with image content.  
**Planned Module:** `fixtures/gold/classification/`, `evaluation/classification_metrics.py`  
**Implementation:** 60+ items with class + urgency labels  
**Tests:** `tests/test_evaluation.py::test_classification_gold_set_size`  
**Evidence:** Gold manifest with 60+ items, 25+ flagged as image-content  
**Acceptance:** Minimum counts met  
**Status:** `NOT STARTED`

### REQ-EVAL-004: Classification Metrics
**Source:** Assignment Section 6  
**Requirement:** Per-class precision/recall and macro-F1; confusion matrix.  
**Planned Module:** `evaluation/classification_metrics.py`  
**Implementation:** Use sklearn metrics; generate confusion matrix  
**Tests:** `tests/test_evaluation.py::test_classification_metrics`  
**Evidence:** Evaluation report includes precision/recall table and confusion matrix  
**Acceptance:** All metrics computed from predictions vs gold labels  
**Status:** `NOT STARTED`

### REQ-EVAL-005: Urgency Scoring Metrics
**Source:** Assignment Section 6  
**Requirement:** Same set with urgency labels; rank correlation or agreement; calibration comments.  
**Planned Module:** `evaluation/urgency_metrics.py`  
**Implementation:** Spearman rank correlation between predicted and gold urgency  
**Tests:** `tests/test_evaluation.py::test_urgency_correlation`  
**Evidence:** Evaluation report includes urgency correlation and calibration notes  
**Acceptance:** Correlation coefficient reported; qualitative calibration assessment included  
**Status:** `NOT STARTED`

### REQ-EVAL-006: Deduplication Gold Set (10+ groups)
**Source:** Assignment Section 6  
**Requirement:** 10+ known duplicate groups, including cross-modal ones.  
**Planned Module:** `fixtures/gold/dedup/`, `evaluation/dedup_metrics.py`  
**Implementation:** 10+ labelled duplicate groups; at least 2 cross-modal (text + screenshot)  
**Tests:** `tests/test_evaluation.py::test_dedup_gold_set_size`  
**Evidence:** Gold set with duplicate group labels  
**Acceptance:** Minimum 10 groups, including cross-modal examples  
**Status:** `NOT STARTED`

### REQ-EVAL-007: Deduplication Metrics
**Source:** Assignment Section 6  
**Requirement:** Pairwise precision/recall; false merge examples.  
**Planned Module:** `evaluation/dedup_metrics.py`  
**Implementation:** Compute pairwise precision/recall for duplicate pairs; document false merges  
**Tests:** `tests/test_evaluation.py::test_dedup_metrics`  
**Evidence:** Evaluation report includes pairwise dedup metrics and false-merge examples  
**Acceptance:** Metrics computed; at least 2 false-merge examples documented  
**Status:** `NOT STARTED`

### REQ-EVAL-008: Safety Gold Set (8+ adversarial cases)
**Source:** Assignment Section 6  
**Requirement:** 8+ adversarial cases (text and image-embedded).  
**Planned Module:** `fixtures/gold/adversarial/`, `evaluation/safety_metrics.py`  
**Implementation:** 8+ test cases with expected block/allow labels  
**Tests:** `tests/test_evaluation.py::test_adversarial_gold_set_size`  
**Evidence:** Gold set with adversarial cases  
**Acceptance:** Minimum 8 cases across text and image injection  
**Status:** `NOT STARTED`

### REQ-EVAL-009: Safety Metrics
**Source:** Assignment Section 6  
**Requirement:** Attack success rate (target 0); list what still fails.  
**Planned Module:** `evaluation/safety_metrics.py`  
**Implementation:** Count successful attacks (unauthorized action or score manipulation) vs total  
**Tests:** `tests/test_evaluation.py::test_attack_success_rate`  
**Evidence:** Evaluation report shows attack success rate and failure list  
**Acceptance:** Success rate reported; remaining vulnerabilities documented  
**Status:** `NOT STARTED`

### REQ-EVAL-010: Agent Behavior Metrics
**Source:** Assignment Section 6  
**Requirement:** Entire gold set: average steps/tool calls per item, cost per item, failure/fallback rate.  
**Planned Module:** `evaluation/agent_metrics.py`  
**Implementation:** Aggregate stats from traces  
**Tests:** `tests/test_evaluation.py::test_agent_metrics`  
**Evidence:** Evaluation report includes agent behavior table  
**Acceptance:** Mean steps, tool calls, cost, fallback rate computed  
**Status:** `NOT STARTED`

### REQ-EVAL-011: Ablation (Agent vs Fixed Pipeline)
**Source:** Assignment Section 6  
**Requirement:** Agent vs fixed-pipeline baseline on quality and cost.  
**Planned Module:** `evaluation/ablation.py`, `baselines/fixed_pipeline.py`  
**Implementation:** Implement fixed pipeline (fetch -> OCR -> classify -> dedup -> digest); compare metrics  
**Tests:** `tests/test_evaluation.py::test_ablation_comparison`  
**Evidence:** Evaluation report table comparing agent vs baseline on quality/cost/latency  
**Acceptance:** Both systems run on same gold set; metrics compared  
**Status:** `NOT STARTED`

---

## 11. DELIVERABLE ARTIFACTS REQUIREMENTS

### REQ-DEL-001: Complete Runnable Codebase
**Source:** Assignment Section 7  
**Requirement:** Modular, with comments on key logic, README with setup and run instructions.  
**Planned Module:** All modules, `README.md`  
**Implementation:** Full Python package with clear module boundaries  
**Tests:** All implemented tests  
**Evidence:** Repository structure matches plan  
**Acceptance:** Clean clone and setup from README produces working system  
**Status:** `NOT STARTED`

### REQ-DEL-002: Fixtures
**Source:** Assignment Section 7  
**Requirement:** Recorded fixture set (JSON + attachments) and gold data, or generation method.  
**Planned Module:** `fixtures/recorded/`, `fixtures/gold/`  
**Implementation:** Fixture generator or manual curation  
**Tests:** `tests/test_fixtures.py::test_fixture_validity`  
**Evidence:** Fixture directories populated  
**Acceptance:** Replay runs on recorded fixtures; eval runs on gold set  
**Status:** `NOT STARTED`

### REQ-DEL-003: Sample Outputs (3 Digests)
**Source:** Assignment Section 7  
**Requirement:** One digest from live/recorded-live, one from replay, one from fault-injection.  
**Planned Module:** `artifacts/digests/sample_live.md`, `artifacts/digests/sample_replay.md`, `artifacts/digests/sample_fault_injection.md`  
**Implementation:** Run each mode; save digest artifacts  
**Tests:** N/A  
**Evidence:** Three digest files present  
**Acceptance:** All three digest samples exist and include required sections  
**Status:** `NOT STARTED`

### REQ-DEL-004: Trace Logs
**Source:** Assignment Section 7  
**Requirement:** JSONL traces for sample runs, plus annotated walkthrough of five items showing different agent trajectories.  
**Planned Module:** `artifacts/traces/*.jsonl`, `docs/09_AGENT_WALKTHROUGH_TEMPLATE.md` (completed)  
**Implementation:** Run sample digests; extract five diverse items; annotate in walkthrough  
**Tests:** N/A  
**Evidence:** Trace files + completed walkthrough document  
**Acceptance:** Five items with distinct trajectories documented with actual trace IDs  
**Status:** `NOT STARTED`

### REQ-DEL-005: Prompt Documentation
**Source:** Assignment Section 7  
**Requirement:** Exact prompts used (OCR routing, vision, classification, scoring, verification, critique, planner), each with rationale and what you tried before.  
**Planned Module:** `prompts/*.txt`, `docs/07_PROMPT_CATALOG.md`  
**Implementation:** All prompts as files; iteration log per prompt  
**Tests:** N/A  
**Evidence:** Prompt files present; rationale documented  
**Acceptance:** Every LLM prompt lives as versioned file with rationale  
**Status:** `NOT STARTED`

### REQ-DEL-006: Evaluation Report
**Source:** Assignment Section 7  
**Requirement:** Tables from Section 6.  
**Planned Module:** `artifacts/eval/evaluation_report.md`  
**Implementation:** Generated report from evaluation harness  
**Tests:** N/A  
**Evidence:** Report artifact with all metric tables  
**Acceptance:** Report includes OCR, classification, urgency, dedup, safety, agent, ablation metrics  
**Status:** `NOT STARTED`

### REQ-DEL-007: Write-up (800-1,200 words)
**Source:** Assignment Section 7  
**Requirement:** Architecture; agent design and why it beats (or doesn't beat) fixed pipeline; OCR strategy and trade-offs; injection threat model; scaling plan (rate limits, spam, queueing, cost at 100x volume); known limitations; what you would do with another two weeks.  
**Planned Module:** `docs/WRITEUP.md` or `WRITEUP.md` at root  
**Implementation:** Draft write-up based on actual implementation  
**Tests:** N/A  
**Evidence:** Write-up document  
**Acceptance:** 800-1,200 words covering all required topics based on actual results  
**Status:** `NOT STARTED`

### REQ-DEL-008: Requirements File
**Source:** Assignment Section 7  
**Requirement:** `requirements.txt` or equivalent, and optionally a Dockerfile.  
**Planned Module:** `requirements.txt`, optional `Dockerfile`  
**Implementation:** Pin all dependencies  
**Tests:** `tests/test_setup.py::test_requirements_install`  
**Evidence:** `requirements.txt` file  
**Acceptance:** `pip install -r requirements.txt` succeeds in clean environment  
**Status:** `NOT STARTED`

### REQ-DEL-009: Screen Recording (Encouraged)
**Source:** Assignment Section 7  
**Requirement:** 3-5 minute screen recording of complete run, including fault-injection and alert approval.  
**Planned Module:** Optional video file  
**Implementation:** Record terminal session  
**Tests:** N/A  
**Evidence:** Video file or link  
**Acceptance:** Recording shows complete flow  
**Status:** `NOT STARTED`

---

## 12. TECHNICAL REQUIREMENTS AND CONSTRAINTS

### REQ-TECH-001: Python 3.9+
**Source:** Assignment Section 8  
**Requirement:** Primary language Python 3.9+.  
**Planned Module:** All modules  
**Implementation:** Python 3.12+ with 3.9 compatibility where practical  
**Tests:** `tests/test_setup.py::test_python_version`  
**Evidence:** Code runs on Python 3.12+  
**Acceptance:** No Python 3.13-only features; compatible with 3.9+  
**Status:** `NOT STARTED`

### REQ-TECH-002: Time Limit
**Source:** Assignment Section 8  
**Requirement:** 4 days from receipt (actual constraint: 24 hours from 2026-10-11T18:50).  
**Planned Module:** N/A  
**Implementation:** Phased implementation plan in `docs/04_IMPLEMENTATION_PLAN.md`  
**Tests:** N/A  
**Evidence:** Submission timestamp  
**Acceptance:** Submission before deadline  
**Status:** `NOT STARTED`

### REQ-TECH-003: AI/LLM Use
**Source:** Assignment Section 8  
**Requirement:** Any commercial or open-source model; justify choices and report cost/latency trade-offs.  
**Planned Module:** `docs/WRITEUP.md`, `.env.example`  
**Implementation:** Local Ollama as default for replay/eval; optional commercial for live; document choices  
**Tests:** N/A  
**Evidence:** Write-up explains model choices and trade-offs  
**Acceptance:** Model selection justified; cost/latency reported  
**Status:** `NOT STARTED`

### REQ-TECH-004: Error Handling
**Source:** Assignment Section 8  
**Requirement:** Graceful fallback on failures; structured logging required.  
**Planned Module:** All modules, `logging` configuration  
**Implementation:** Try/except blocks, structured logs with JSON or key-value format  
**Tests:** Various fault-handling tests  
**Evidence:** Logs show structured format; failures don't crash system  
**Acceptance:** System continues after per-item failure; logs are parseable  
**Status:** `NOT STARTED`

### REQ-TECH-005: Code Quality
**Source:** Assignment Section 8  
**Requirement:** Clean, modular, typed where sensible, with tests for core logic.  
**Planned Module:** All modules  
**Implementation:** Type hints on public interfaces; pytest test suite  
**Tests:** Full test suite  
**Evidence:** Test coverage report  
**Acceptance:** Core logic has unit tests; code is readable and modular  
**Status:** `NOT STARTED`

### REQ-TECH-006: Credentials
**Source:** Assignment Section 8  
**Requirement:** Environment variables only; never hardcode API keys. Provide `.env.example`.  
**Planned Module:** `.env.example`, `config.py`  
**Implementation:** Load credentials from environment; `.env.example` with placeholders  
**Tests:** `tests/test_setup.py::test_no_hardcoded_secrets`  
**Evidence:** No secrets in repository  
**Acceptance:** No API keys or secrets in code or fixtures  
**Status:** `NOT STARTED`

---

## 13. SUBMISSION REQUIREMENTS

### REQ-SUB-001: Track B Label
**Source:** Assignment Section 9  
**Requirement:** State clearly at top of submission: Track B (Extended), AI Generalist assignment for Jyot.  
**Planned Module:** `README.md`, write-up  
**Implementation:** Header in README  
**Tests:** N/A  
**Evidence:** README header  
**Acceptance:** Track B label visible at top of README  
**Status:** `NOT STARTED`

### REQ-SUB-002: Archive or Repository
**Source:** Assignment Section 9  
**Requirement:** Compressed archive (.zip) or linked private repository.  
**Planned Module:** N/A  
**Implementation:** Private GitHub repository `jyot-agentic-multimodal-monitor`  
**Tests:** N/A  
**Evidence:** Repository link or zip file  
**Acceptance:** Evaluators can access submission  
**Status:** `NOT STARTED`

### REQ-SUB-003: Complete Package
**Source:** Assignment Section 9  
**Requirement:** Include everything needed to run from scratch, including fixtures.  
**Planned Module:** Full repository  
**Implementation:** All code, fixtures, gold data, README  
**Tests:** N/A  
**Evidence:** Complete repository  
**Acceptance:** Fresh clone can run all commands after setup  
**Status:** `NOT STARTED`

### REQ-SUB-004: Free Alternative
**Source:** Assignment Section 9  
**Requirement:** If using paid APIs, include instructions and configuration for free/local alternative.  
**Planned Module:** `README.md`, `.env.example`  
**Implementation:** Ollama setup instructions; deterministic fallback documented  
**Tests:** N/A  
**Evidence:** README alternative setup section  
**Acceptance:** System runs with free/local models; README documents it  
**Status:** `NOT STARTED`

### REQ-SUB-005: AI Assistant Disclosure
**Source:** Assignment Section 9  
**Requirement:** Disclose any use of AI coding assistants; describe where you verified or corrected output.  
**Planned Module:** `README.md` or `AI_ASSISTANT_DISCLOSURE.md`  
**Implementation:** Honest disclosure of Kilo Code/Claude use; verification methods  
**Tests:** N/A  
**Evidence:** Disclosure document  
**Acceptance:** Disclosure present; verification approach described  
**Status:** `NOT STARTED`

---

## 14. EVALUATION CRITERIA (WEIGHTS)

### REQ-EVAL-WEIGHT-001: Agent Design and Autonomy (25%)
**Source:** Assignment Section 10  
**Requirement:** Real tool-choice decisions, bounded loops, budgets, tracing, distinct trajectories, justified benefit over fixed pipeline.  
**Planned Module:** Agent system, evaluation ablation  
**Implementation:** All agent requirements above  
**Tests:** Agent tests, ablation  
**Evidence:** Traces, ablation results, write-up  
**Acceptance:** Agent demonstrates dynamic routing; ablation shows when it helps  
**Status:** `NOT STARTED`

### REQ-EVAL-WEIGHT-002: OCR and Document Extraction (20%)
**Source:** Assignment Section 10  
**Requirement:** Multi-engine routing, preprocessing evidence, multilingual handling, structured extraction with uncertainty flags, measured CER/WER.  
**Planned Module:** OCR system, evaluation  
**Implementation:** All OCR requirements above  
**Tests:** OCR tests, evaluation  
**Evidence:** CER/WER report, structured extraction examples  
**Acceptance:** OCR requirements met and measured  
**Status:** `NOT STARTED`

### REQ-EVAL-WEIGHT-003: Safety and Robustness (15%)
**Source:** Assignment Section 10  
**Requirement:** Injection resistance (tested), PII redaction, network safety, fault tolerance, idempotent resumable runs.  
**Planned Module:** Safety system, reliability  
**Implementation:** All safety and reliability requirements above  
**Tests:** Safety tests, reliability tests  
**Evidence:** Attack success rate, fault-injection results, resume test  
**Acceptance:** Safety requirements met and tested  
**Status:** `NOT STARTED`

### REQ-EVAL-WEIGHT-004: Evaluation Rigor and Honesty (15%)
**Source:** Assignment Section 10  
**Requirement:** Sensible gold data, correct metrics, ablation, candid reporting of failures and small-sample caveats.  
**Planned Module:** Evaluation harness, report  
**Implementation:** All evaluation requirements above  
**Tests:** Evaluation tests  
**Evidence:** Evaluation report with caveats and limitations  
**Acceptance:** Metrics computed correctly; failures documented; sample sizes noted  
**Status:** `NOT STARTED`

### REQ-EVAL-WEIGHT-005: Dedup, Memory, and Scoring (10%)
**Source:** Assignment Section 10  
**Requirement:** Cross-modal clustering, persistent state, defensible score combination.  
**Planned Module:** Dedup, scoring, storage  
**Implementation:** All dedup, scoring, memory requirements above  
**Tests:** Dedup tests, scoring tests  
**Evidence:** Cross-modal duplicate clusters, score breakdown, persistent memory  
**Acceptance:** Cross-modal dedup works; scoring justified  
**Status:** `NOT STARTED`

### REQ-EVAL-WEIGHT-006: Code Quality and Structure (5%)
**Source:** Assignment Section 10  
**Requirement:** Modularity, tests, readability, reproducibility.  
**Planned Module:** All modules  
**Implementation:** Clean architecture per TRD  
**Tests:** Full test suite  
**Evidence:** Code structure, test coverage  
**Acceptance:** Code is modular and readable; tests cover core logic  
**Status:** `NOT STARTED`

### REQ-EVAL-WEIGHT-007: Write-up and Engineering Judgment (10%)
**Source:** Assignment Section 10  
**Requirement:** Trade-offs, scaling thinking, clarity, awareness of limits.  
**Planned Module:** Write-up  
**Implementation:** 800-1,200 word write-up  
**Tests:** N/A  
**Evidence:** Write-up document  
**Acceptance:** Write-up demonstrates engineering judgment; acknowledges limitations; discusses scaling  
**Status:** `NOT STARTED`

---

## SUMMARY STATISTICS

**Total Requirements Identified:** 89  
**Mandatory Requirements:** 89  
**Optional/Encouraged:** 1 (screen recording)  

**Status Breakdown:**
- NOT STARTED: 89
- IN PROGRESS: 0
- VERIFIED: 0
- BLOCKED: 0

**By Category:**
- Ingestion: 3
- OCR: 6
- Agent: 8
- Scoring/Dedup: 3
- Safety: 4
- Reliability: 4
- HITL: 2
- Digest: 1
- CLI: 6
- Evaluation: 11
- Deliverables: 9
- Technical: 6
- Submission: 5
- Evaluation Weights: 7
- Total: 75 functional + 14 process/documentation = 89

**High-Risk Requirements (Early Testing Priority):**
1. REQ-SAFE-001: Prompt injection resistance
2. REQ-SAFE-003: SSRF/network safety
3. REQ-AGENT-001: Genuine planner-driven tool selection
4. REQ-AGENT-004: Variable trajectories demonstrated
5. REQ-OCR-002: Router with explicit decisions
6. REQ-EVAL-011: Agent vs baseline ablation
7. REQ-REL-002: Idempotent resumable runs
8. REQ-HITL-001: No alert sending without approval

**Critical Dependencies:**
- Python 3.12+ environment
- Tesseract OCR binary installed
- EasyOCR with Hindi language pack
- Ollama for local LLM (or deterministic fallback)
- SQLite (standard library)
- Network isolation capability for replay testing

**Unresolved Ambiguities:**
None identified. The original assignment and planning documents provide sufficient detail for all requirements.

---

## NOTES

1. **Verification Standard:** No requirement is marked `VERIFIED` until actual tests pass or artifacts are manually inspected. Documentation or planning alone does not constitute verification.

2. **Synthetic vs Real Data:** Many evaluation requirements will use synthetic or curated data due to time constraints. All synthetic data must be clearly labeled as such in the evaluation report.

3. **Measurement vs Claims:** Requirements like "preprocessing helps" must be demonstrated with actual CER/WER measurements, not assumed. If preprocessing does not help, that result must be reported honestly.

4. **Assignment Source Authority:** The original assignment (`source/JYOT_ASSIGNMENT_ORIGINAL.txt`) is authoritative. Project planning documents translate requirements but do not replace them.

5. **Scope Risk:** With 89 requirements and a 24-hour deadline (actual) vs 4 days (nominal), scope risk is high. Priority order: (1) runnable replay with traces, (2) safety boundaries tested, (3) core metrics computed, (4) honest evaluation report. Polish and completeness take lower priority than working, safe, measured behavior.
