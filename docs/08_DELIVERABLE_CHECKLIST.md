# Deliverables and Final Submission Checklist

**Project:** `jyot-agentic-multimodal-monitor`  
**Track:** Track B (Extended), AI Generalist Technical Assignment for Jyot  
**Phase:** Phase 5 — Final Submission Package  

This checklist records every deliverable, its verified disk location, and the exact CLI command used to validate it.

---

## 1. Codebase & Environment Foundation

- [x] **Track B (Extended) Header in README:**  
  *Path:* `README.md` (Top header clearly states: `Track B (Extended), AI Generalist assignment for Jyot`).
- [x] **Clean Setup & Dependencies:**  
  *Path:* `pyproject.toml`, `requirements.txt`. Tested on Windows Python 3.10–3.12 (and Python 3.14 via `-E` flag).  
  *Verification:* `.\.venv\Scripts\python.exe -E -m pip install -e .`
- [x] **Zero Hardcoded Secrets / Template Env:**  
  *Path:* `.env.example` (Only placeholders, no credentials or confidential assignments).
- [x] **Full Automated Regression Suite:**  
  *Path:* `tests/` (127 unit, integration, safety, network, and OCR tests).  
  *Verification:* `.\.venv\Scripts\python.exe -E -m pytest tests/ -q` &rarr; **127 passed in 34.25s**.

---

## 2. Required CLI Commands & Verification Paths

- [x] **Offline Replay Ingestion:**  
  *Command:* `python -m jyot_monitor run --replay fixtures/recorded --top-n 3`  
  *Evidence:* Tested offline; produces structured SQLite records, clustering, and Markdown digest.
- [x] **Deterministic Fault Injection Run:**  
  *Command:* `python -m jyot_monitor run --replay fixtures/recorded --top-n 3 --fault-injection`  
  *Evidence:* Injects HTTP 429, 500, corrupted file signatures, and OCR crashes; runs to completion with 0 unhandled errors.
- [x] **Comprehensive Offline Gold Evaluation:**  
  *Command:* `python -m jyot_monitor eval --gold fixtures/classification_gold`  
  *Evidence:* Runs in ~3 seconds offline; generates `artifacts/eval/eval_results.json` and `artifacts/eval/evaluation_report.md`.
- [x] **Human-in-the-Loop Alert Approval Workflow:**  
  *Commands:*  
  `python -m jyot_monitor approve <proposal_id>`  
  `python -m jyot_monitor reject <proposal_id>`  
  *Evidence:* Validated in `tests/test_reliability.py`; ensures unapproved proposals are never dispatched.
- [x] **Live Public Ingestion (with Internet):**  
  *Command:* `python -m jyot_monitor run --live --sources config/sources.yaml --top-n 3`  
  *Evidence:* Successfully ingests live CPSC Recalls items; isolates FDA RSS 404 via `SourceUnavailableError` without crashing.

---

## 3. Evaluation Datasets & Ground Truth Fixtures

- [x] **Original OCR Ground Truth Gold Set (18 units):**  
  *Path:* `fixtures/gold/manifest.json`, `fixtures/gold/images/`, `fixtures/gold/pdfs/`  
  *Composition:* 18 units (10 English clean/rotated/blur/contrast, 4 Hindi clean/skew/blur, 4 multi-page PDF pages). Preserved and verified.
- [x] **Classification & Urgency Gold Dataset (65 items, 28 images):**  
  *Path:* `fixtures/classification_gold/manifest.json`, `fixtures/classification_gold/images/`  
  *Composition:* 65 items (12 product_recall, 10 health_hazard, 8 contamination, 8 unsafe_equipment, 7 consumer_warning, 7 non_safety, 5 uncertain, 8 spam_manipulation), 28 with image attachments, 10 duplicate groups, 8 adversarial attacks. Documented in `fixtures/classification_gold/README.md`.

---

## 4. Submission Evidence & Sample Artifacts

- [x] **Sample Top-N Executive Digests (3 required):**
  1. *Live Digest:* `artifacts/digests/live_digest.md` (generated from actual live CPSC items)
  2. *Replay Digest:* `artifacts/digests/replay_digest.md` (generated from recorded fixtures)
  3. *Fault-Injection Digest:* `artifacts/digests/fault_injection_digest.md` (generated from fault-injected run)
- [x] **Curated Sample Execution JSONL Traces (3 required):**
  1. *Live Sample:* `submission_evidence/traces/live_sample.jsonl`
  2. *Replay Sample:* `submission_evidence/traces/replay_sample.jsonl`
  3. *Fault Injection Sample:* `submission_evidence/traces/fault_injection_sample.jsonl`
- [x] **Five-Item Annotated Walkthrough:**  
  *Path:* `submission_evidence/WALKTHROUGH.md`  
  *Content:* Detailed breakdown of 5 distinct trajectories (text-only, multimodal direct, degraded visual second opinion & critique downgrade, story deduplication, and fault injection recovery) referencing exact trace line numbers and LLM rationales.
- [x] **Documented Prompt Catalog:**  
  *Path:* `docs/07_PROMPT_CATALOG.md` (and exact prompt files in `prompts/`).  
  *Content:* Exact templates, delimiters, JSON schemas, versions, observed weaknesses, and test references.
- [x] **Full Evaluation Report:**  
  *Path:* `artifacts/eval/evaluation_report.md` (and machine-readable `eval_results.json`).  
  *Content:* Classification macro-F1 (0.4172) and confusion matrix, urgency Spearman rank correlation ($\rho=0.6464$, MAE=16.52), deduplication pairwise F1 (0.6667, 85.7% recall, 54.5% precision across 7 genuine duplicate groups), adversarial attack success rate (25.0% heuristic bypass, 0.0% runtime exploit), and agent vs baseline ablation (19.8% tool savings, 3.55 vs 4.43 steps).
- [x] **Technical Submission Report (800–1,200 words):**  
  *Path:* `SUBMISSION_WRITEUP.md`  
  *Word Count:* **1,185 words** (strictly within 800–1,200 words). Covers all 10 required architectural, security, OCR, deduplication, and scaling topics.

---

## 5. Honest Status of Unresolved Items & Scope Boundaries

1. **FDA Live RSS Endpoint:**
   - Both `https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/recalls/rss.xml` and the food safety feed return HTTP 404 due to upstream portal deprecation by the FDA.
   - Handled cleanly via `SourceUnavailableError` in `jyot_monitor/ingestion/fetcher.py`.
   - CPSC live feed operates with HTTP 200, successfully ingesting live public notices.
2. **Offline Replay Invariant:**
   - Replay and evaluation runs enforce `offline_mode=True` on `SafeHttpClient`. Any network attempt immediately raises `SecurityError`.
3. **Approval Boundary:**
   - Alerts are staged as `pending` proposals in SQLite. Zero external messages are emitted without explicit human CLI invocation.
