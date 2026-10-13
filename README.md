# Track B (Extended), AI Generalist assignment for Jyot

**Project:** `jyot-agentic-multimodal-monitor`  
**Description:** Bounded, multimodal AI agent for real-time consumer product safety monitoring, recall classification, OCR routing, cross-modal deduplication, and verified executive digest generation.

---

## 1. Supported Environments & Prerequisites

- **Operating System:** Windows 10/11 (fully supported; also portable to Linux/macOS).
- **Python Version:** Python 3.10 to 3.12 (Supported and tested; also runs on Python 3.14 via `-E` flag).
- **External Dependencies:**
  1. **Tesseract OCR (5.x):** Must be installed on your system PATH or at standard Windows paths (`C:\Program Files\Tesseract-OCR\tesseract.exe`).
     - Required language packs: English (`eng`) and Hindi (`hin`).
     - Verify with: `tesseract --list-langs`
  2. **EasyOCR Offline Models:** Pre-cached in `~/.EasyOCR/model/` (or downloaded on first run):
     - Detection: `craft_mlt_25k.pth`
     - Recognition: `english_g2.pth` and `hindi_g2.pth`
  3. **Local LLM via Ollama (Optional for Strict LLM Mode):**
     - Version: `ollama` CLI installed.
     - Model: `qwen2.5:3b`
     - If Ollama is not running, the system automatically uses `DeterministicFallbackPlanner` so all offline replays and tests succeed without remote network calls.

---

## 2. Clean Environment Setup (Windows PowerShell)

```powershell
# 1. Clone or navigate to the repository root
cd C:\Users\<Username>\path\to\jyot-agentic-multimodal-monitor

# 2. Create a clean virtual environment
python -m venv .venv

# 3. Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# 4. Upgrade pip and install package in editable mode with all dependencies
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

### Critical Windows Python `-E` Flag Workaround
On Windows systems where global Python packages or user site-packages exist in `APPDATA`, ambient packages can cause schema collisions. Always prefix Python commands with the `-E` flag (ignore environment variables/user site) when invoking the virtual environment:
```powershell
.\.venv\Scripts\python.exe -E -m jyot_monitor <command>
```

---

## 3. Configuration & Environment Variables

Copy the template configuration file:
```powershell
cp .env.example .env
```

Key environment variables:
| Variable | Default | Purpose |
|---|---|---|
| `JYOT_PLANNER_MODEL` | `qwen2.5:3b` | Target local model for Ollama planner |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama daemon endpoint |
| `JYOT_STRICT_LLM` | `false` | When `true`, raises error if Ollama is unavailable instead of falling back |
| `JYOT_VISION_MODEL` | *(empty)* | Optional local vision model identifier |
| `JYOT_MAX_STEPS_PER_ITEM`| `10` | Hard bounded step ceiling per item |
| `JYOT_PER_ITEM_BUDGET_USD`| `0.10` | Runtime cost ceiling per item |
| `JYOT_PER_RUN_BUDGET_USD` | `5.00` | Runtime cost ceiling per execution run |

Public source endpoints are configured in `config/sources.yaml`, including host allowlists and security limits.

---

## 4. Online vs. Offline Operation Summary

| Command | Network Mode | External Calls? | Notes |
|---|---|---|---|
| `jyot_monitor run --replay <dir>` | **STRICT OFFLINE** | **NO** | Reads only local fixture files and attachments |
| `jyot_monitor run --replay <dir> --fault-injection` | **STRICT OFFLINE** | **NO** | Exercises deterministic error recovery locally |
| `jyot_monitor eval --gold <dir>` | **STRICT OFFLINE** | **NO** | Calculates metrics against gold labels offline |
| `jyot_monitor approve <id>` | **STRICT OFFLINE** | **NO** | Human-in-the-loop approval gate in local SQLite |
| `jyot_monitor reject <id>` | **STRICT OFFLINE** | **NO** | Human-in-the-loop rejection gate in local SQLite |
| `jyot_monitor run --live --sources <file>` | **LIVE NETWORK** | **YES** | Ingests from configured public HTTPS feeds (CPSC/FDA) |

---

## 5. Every CLI Command & Usage Examples

### 1. Offline Replay Run (Default Fixtures)
Replays recorded items through the multimodal agent, extracting OCR text, clustering stories, and rendering the executive digest:
```powershell
.\.venv\Scripts\python.exe -E -m jyot_monitor run --replay fixtures/recorded --top-n 3
```

### 2. Deterministic Fault Injection Run
Simulates network timeouts, corrupted image bytes, OCR engine errors, and malformed LLM JSON to verify fault containment:
```powershell
.\.venv\Scripts\python.exe -E -m jyot_monitor run --replay fixtures/recorded --top-n 3 --fault-injection
```

### 3. Comprehensive Offline Gold Evaluation
Runs the full evaluation harness measuring classification macro-F1, urgency rank correlation, deduplication precision/recall, OCR CER/WER benchmarks, adversarial robustness, and pipeline ablation:
```powershell
.\.venv\Scripts\python.exe -E -m jyot_monitor eval --gold fixtures/classification_gold
```

### 4. Human-in-the-Loop Alert Approval Workflow
List pending alert proposals and inspect their evidence:
```powershell
# Approve a pending alert proposal (stages alert as approved)
.\.venv\Scripts\python.exe -E -m jyot_monitor approve prop_db8ff55562b7

# Reject an alert proposal (marks proposal rejected, prevents emission)
.\.venv\Scripts\python.exe -E -m jyot_monitor reject prop_db8ff55562b7
```

### 5. Live Public Ingestion (Requires Internet)
Ingests public recall notices from allowed HTTPS sources (`config/sources.yaml`):
```powershell
.\.venv\Scripts\python.exe -E -m jyot_monitor run --live --sources config/sources.yaml --top-n 5
```

---

## 6. Output Artifacts & File Locations

All generated runtime artifacts reside in `artifacts/`:
- **Executive Digests:**
  - Live Digest: `artifacts/digests/live_digest.md`
  - Replay Digest: `artifacts/digests/replay_digest.md`
  - Fault-Injection Digest: `artifacts/digests/fault_injection_digest.md`
- **Evaluation Results:**
  - Machine-readable JSON: `artifacts/eval/eval_results.json`
  - Markdown Report: `artifacts/eval/evaluation_report.md`
  - OCR Benchmark Results: `artifacts/eval/ocr_eval_results.json`
- **Audit Traces:**
  - JSONL Execution Traces: `artifacts/traces/replay_<run_id>.jsonl`
- **Persistent Database:**
  - SQLite Store: `artifacts/monitor.db` (items, clusters, caches, proposals, alerts)

---

## 7. Running the Full Test Suite

The test suite contains 189 automated regression tests verifying network security, SSRF filtering, PII redaction, OCR routing, tool sandboxing, and adversarial defenses:
```powershell
.\.venv\Scripts\python.exe -E -m pytest tests/ -q
```
*Expected result:* `189 passed in ~30s`.

---

## 8. Troubleshooting

1. **Tesseract Not Found Error:**
   - Install Tesseract from UB-Mannheim (`https://github.com/UB-Mannheim/tesseract/wiki`).
   - Add `C:\Program Files\Tesseract-OCR` to system PATH or set `TESSDATA_PREFIX=C:\Program Files\Tesseract-OCR\tessdata`.
2. **EasyOCR Memory / Torch Warnings:**
   - On Windows CPU without CUDA accelerators, PyTorch displays pin-memory deprecation warnings. These are standard non-fatal warnings and do not affect extraction accuracy.
3. **FDA Feed HTTP 404:**
   - The FDA has deprecated its legacy RSS XML paths. The ingestion client safely isolates this as `SourceUnavailableError` while processing CPSC items normally.
4. **Ollama Connection Refused:**
   - If `ollama serve` is not running, the monitor automatically degrades to `DeterministicFallbackPlanner`, ensuring all offline replays complete without failure.
