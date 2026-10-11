# Technical Requirements Document

## Runtime and packaging
- Python 3.12+ (must also be tested against the developer's installed Python 3.13 if available).
- Installable package named `jyot_monitor`; required entry point is `python -m jyot_monitor`.
- `requirements.txt` (or equivalent), `.env.example`, README, and optional Dockerfile.
- `pytest` for automated tests; `ruff` optional if time allows.

## Suggested dependencies (verify compatibility before pinning)
- `pydantic` for validated LLM/tool/evidence schemas.
- `feedparser` for RSS parsing.
- `httpx` for bounded HTTP; redirects handled/validated explicitly.
- `beautifulsoup4` for official HTML page metadata/attachment discovery.
- `Pillow`, `opencv-python-headless`, `numpy` for image inspection/preprocessing.
- `pytesseract` as engine 1, with Tesseract OCR installed separately.
- `easyocr` as engine 2 with English and Hindi support; load lazily and report if its runtime/model weights are unavailable.
- `pymupdf` or `pdf2image` plus PDF image rendering for scanned PDF pages; prefer PyMuPDF to avoid requiring a separate Poppler setup if compatibility is confirmed.
- `imagehash` for perceptual image hashes.
- `datasketch` for MinHash/LSH text near-duplicate candidate generation.
- `scikit-learn` for evaluation metrics/confusion matrices; simple TF-IDF/cosine similarity for a local/no-API text similarity path.
- SQLite via Python standard library for persistent state.
- Optional `ollama` Python package or direct HTTP client for a local open-weight text/vision model. Replay/eval must also have deterministic fallback mode if the local model server is unavailable.
- `python-dotenv` optional to load `.env` for local use; secrets remain environment-backed.

Do not blindly install every optional dependency. Put heavy OCR/LLM dependencies in clearly documented optional groups if doing so will make a minimal install more reliable, but keep a supported full evaluation install path.

## Configuration
- `config/sources.yaml`: allowed feeds, permitted hostnames, item limits and polling interval.
- `.env.example`: LLM backend/model and optional API credentials, with placeholders only.
- Configurable limits for steps/item, items/run, max download bytes, HTTP timeout, retries, token/cost budget, OCR thresholds and urgency threshold.

## State and artifacts
- `data/state.sqlite3`: seen items/cursors, content hashes, OCR/LLM cache entries, clusters, prior digest state, alert proposals and approval status.
- `artifacts/traces/*.jsonl`: per-step trace lines.
- `artifacts/digests/`: Markdown digests.
- `artifacts/approvals/`: pending/approved/rejected proposals and emitted local alert records.
- `artifacts/eval/`: computed metrics, confusion matrix and report.
- `fixtures/recorded/`: fixture manifest JSON plus image/PDF attachments.
- `fixtures/gold/`: image/text samples, transcription ground truth, class/urgency labels, duplicate groups, adversarial cases.
- `prompts/`: exact versioned prompts used by the planner, classification, urgency/scoring, OCR routing, vision description, verification and critique.

## Module boundaries (keep these modest)
- `cli.py`: CLI commands/arguments and readable errors.
- `config.py`: typed configuration and limit validation.
- `models.py`: Pydantic item/tool/OCR/score/alert/trace schemas.
- `ingestion/`: RSS feed adapters, safe official-page/attachment fetching and fixture loader.
- `ocr/`: preprocessing, Tesseract adapter, EasyOCR adapter, route policy, PDF page rendering and structured notice extraction.
- `agent/`: bounded controller/planner, allow-listed tool registry and tool execution policy.
- `llm/`: provider interface, local Ollama adapter, optional commercial adapter only if explicitly configured, schema validation/fallback.
- `scoring.py`: taxonomy, relevance/urgency, non-LLM features and calibrated combination.
- `dedup.py`: exact hash, normalized text/MinHash, perceptual image hash, OCR text similarity and cluster management.
- `safety.py`: PII redaction, network URL/IP guards, untrusted-content boundaries, spam signals.
- `storage.py`: SQLite migrations/queries, idempotency and cache.
- `digest.py`: Markdown output and since-last-run changes.
- `approval.py`: proposal queue and explicit approval/rejection; no direct emit path from agent.
- `evaluation/`: fixture generation, metrics, baseline comparison and report generation.
- `tests/`: unit/integration tests, including network-denial for replay and fault injection.

## Required CLI contract
```bash
python -m jyot_monitor run --live --sources config/sources.yaml --top-n 10
python -m jyot_monitor run --replay fixtures/recorded --top-n 10 --budget-usd 1.00
python -m jyot_monitor run --replay fixtures/recorded --fault-injection
python -m jyot_monitor eval --gold fixtures/gold
python -m jyot_monitor approve <proposal_id>
```

Add `--reject <proposal_id>` or a separate `reject` command if useful, without changing required syntax.

## Replay/offline guarantees
- Replay inputs are local JSON and local attachment paths only; external attachment URLs in a fixture are evidence metadata, never download instructions.
- No source feed fetch, URL fetch, DNS lookup, telemetry or remote LLM call in strict offline replay/eval mode.
- Local OCR engines and a local Ollama model may run after their binaries/models are installed. If the local LLM is unavailable, the deterministic planner fallback must still complete the command and label the fallback in traces.
- The README must explain the distinction between strict no-network replay and optional local model-server use.

## Network isolation testing
Implement explicit network denial for replay/eval modes:
- Option 1: Mock `httpx.Client` to raise exception on any request
- Option 2: Inject a network-disabled client that validates no DNS/HTTP occurs
- Test: `tests/test_replay.py::test_network_denial_raises` must fail if any network access attempted

## Deterministic planner fallback specification
When LLM is unavailable (offline mode, API failure, or explicit fallback configuration):
- Use rule-based action selection: if has_attachment and not ocr_complete → `ocr_extract`; elif not classified → `classify_score`; elif urgent and not verified → `verify_claim`; else → `finish`
- Mark all traces with `planner_mode: "fallback"` and `fallback_used: true`
- Do not claim fallback mode uses LLM reasoning
- Document in README and write-up that fallback is a deterministic policy, not intelligent planning

## Dependency installation requirements
Create clear installation paths:
1. **Minimal (tests only):** `pip install -r requirements-minimal.txt` — no OCR engines, no local LLM
2. **Standard (replay/eval):** `pip install -r requirements.txt` + Tesseract binary + EasyOCR + Ollama setup
3. **Full (live + commercial LLM):** Standard + API credentials in `.env`

Document external binary requirements:
- **Tesseract:** Install via system package manager; verify with `tesseract --version`
- **Ollama:** Download from ollama.ai; pull model with `ollama pull llama3.2` or similar
- **Hindi support:** EasyOCR automatically downloads Hindi model on first use; verify with test

## Configuration schema and validation
`config/sources.yaml`:
```yaml
sources:
  - name: "CPSC Recalls"
    type: rss
    url: "https://www.cpsc.gov/Newsroom/CPSC-RSS-Feed/Recalls-RSS"
    allowed_hosts:
      - "www.cpsc.gov"
      - "cpsc.gov"
    poll_interval_seconds: 3600
  - name: "FDA Recalls"
    type: rss
    url: "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/recalls/rss.xml"
    allowed_hosts:
      - "www.fda.gov"
      - "fda.gov"
    poll_interval_seconds: 3600

limits:
  max_items_per_run: 100
  max_steps_per_item: 10
  http_timeout_seconds: 30
  max_download_bytes: 10485760  # 10 MB
  max_retries: 3
  
budgets:
  per_item_usd: 0.10
  per_run_usd: 5.00
  
thresholds:
  ocr_confidence_second_opinion: 0.7
  urgency_critique_threshold: 75
  urgency_alert_threshold: 85
```

Validate schema on load; fail fast with clear error messages.

## SQLite schema design
Tables:
- `feed_state`: (feed_name, last_cursor, last_poll_time, item_count)
- `items`: (item_id PK, source, url, title, content_hash, fetch_time, status, error_code)
- `attachments`: (attachment_id PK, item_id FK, url, local_path, mime_type, size_bytes, content_hash)
- `ocr_cache`: (content_hash PK, engine, preprocessing, text, confidence, language, metadata_json)
- `llm_cache`: (input_hash PK, model, prompt_version, response_json, tokens_in, tokens_out, cost_usd)
- `clusters`: (cluster_id PK, representative_item_id FK, created_time, last_updated)
- `cluster_members`: (cluster_id FK, item_id FK, similarity_score, join_time)
- `digest_runs`: (run_id PK, run_time, item_count, digest_path, budget_used_usd)
- `alert_proposals`: (proposal_id PK, item_id FK, urgency, evidence_json, status, created_time, approved_time)
- `traces`: Not stored in SQLite; written to JSONL files for size/append efficiency

Indexes:
- `items.content_hash`, `items.status`
- `attachments.content_hash`
- `ocr_cache.content_hash`
- `cluster_members.item_id`
- `alert_proposals.status`

## Trace JSONL schema (expanded)
```json
{
  "run_id": "uuid",
  "item_id": "string",
  "step_index": 0,
  "timestamp_utc": "ISO-8601",
  "planner_mode": "llm|fallback",
  "tool": "fetch_attachment|ocr_extract|vision_describe|search_memory|verify_claim|classify_score|critique_item|propose_alert|finish",
  "arguments_summary": {"key": "redacted_value"},
  "result_summary": {"status": "success|partial|error", "details": "..."},
  "decision_rationale": "Why this tool was selected",
  "input_hashes": ["sha256:..."],
  "tokens_in": null,
  "tokens_out": null,
  "cost_usd": null,
  "latency_ms": 123,
  "status": "success|partial|error|skipped",
  "fallback_used": false,
  "error_code": null,
  "budget_remaining": {"item_usd": 0.08, "run_usd": 4.50, "steps": 8},
  "cache_hit": false,
  "prompt_version": "sha256:...",
  "model": "gpt-4o-mini|llama3.2|fallback"
}
```

## Requirements traceability
89 requirements mapped in `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md`. Key TRD-related requirements:
- REQ-TECH-001: Python 3.9+ (implementing with 3.12+)
- REQ-CLI-001 through REQ-CLI-006: All CLI commands specified above
- REQ-ING-003: Replay mode with network isolation
- REQ-TECH-006: No hardcoded credentials
