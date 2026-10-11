# Five-Item Agent Walkthrough (Complete from Actual Traces)

For each item, reference the real `run_id` and trace line(s). Avoid invented examples; redact PII.

## Item 1 — Plain text, one-pass
- Item ID / run ID:
- Source and evidence link:
- Initial signals:
- Planner-selected trajectory (actions in order):
- Why the planner stopped:
- Final classification/relevance/urgency:
- Duplicate/cluster state:
- Cost/latency/steps (measured or marked unavailable):
- What the trace proves:

## Item 2 — Blurry/rotated screenshot, second OCR engine
- Item ID / run ID:
- Image quality signal:
- Engine 1 output/confidence:
- Explicit routing decision and rationale:
- Engine 2 output/confidence:
- Preprocessing comparison:
- Impact on structured fields/scoring:
- Cost/latency/steps:

## Item 3 — High urgency, verification and critique
- Item ID / run ID:
- Initial score breakdown:
- Why verification/critique was triggered:
- Independent source/item searched:
- Verification outcome:
- Did critique change score/alert decision? Evidence:
- Alert proposal status (must remain pending until approved):

## Item 4 — Prompt injection in image/text
- Item ID / run ID:
- Injection payload class (do not repeat PII):
- OCR/text detection:
- Tool/action attempted or suggested:
- Controller rejection/isolation evidence:
- Did it alter score or generate an unauthorized alert?
- Test result and limitations:

## Item 5 — Fault, fallback and resume
- Item ID / run ID:
- Injected failure:
- Expected safe behavior:
- Actual fallback/trace error:
- Restart/idempotency check:
- Was any digest/proposal duplicated?
- Remaining limitation:

---

## Instructions for completing this walkthrough

This template must be completed with **actual trace data** from real runs, not invented examples. The walkthrough is a required deliverable (Assignment Section 7, Deliverable 4).

### Data sources
1. Run sample digests: `python -m jyot_monitor run --replay fixtures/recorded --top-n 10`
2. Identify trace files in `artifacts/traces/<run_id>.jsonl`
3. Select five items demonstrating different outcomes:
   - At least one plain-text, one-pass item (minimal trajectory)
   - At least one image item triggering OCR routing or second opinion
   - At least one urgent item showing verification/critique
   - At least one adversarial case showing isolation/rejection
   - At least one fault-injection case showing graceful degradation

### Walkthrough format requirements
- Reference actual `run_id` and `item_id` from traces
- Quote actual planner `decision_rationale` from trace lines
- Show actual tool sequences: `["fetch_attachment", "ocr_extract", "classify_score", "finish"]`
- Include actual confidence values, step counts, cost measurements (or mark as `null`/unavailable)
- Redact PII if present in evidence; use `[REDACTED]` placeholder
- For adversarial cases, describe payload class without repeating full attack content

### Trace line reference example
```json
{
  "run_id": "run_20261012_143022",
  "item_id": "cpsc_item_xyz123",
  "step_index": 2,
  "tool": "ocr_extract",
  "arguments_summary": {"attachment_id": "att_456", "engine": "easyocr", "preprocessing": "deskew"},
  "result_summary": {"status": "success", "confidence": 0.82, "text_length": 450},
  "decision_rationale": "Engine 1 (Tesseract) confidence 0.65 below threshold 0.70; trying EasyOCR with deskew preprocessing",
  "latency_ms": 2340,
  "cost_usd": null,
  "status": "success"
}
```

Becomes walkthrough entry:
> **Engine 1 output/confidence:** Tesseract, 0.65  
> **Explicit routing decision and rationale:** "Engine 1 (Tesseract) confidence 0.65 below threshold 0.70; trying EasyOCR with deskew preprocessing"  
> **Engine 2 output/confidence:** EasyOCR with deskew, 0.82  
> **Cost/latency/steps:** 3 steps, 2.34s latency, cost unavailable (local model)

### Validation checklist before submission
- [ ] All five items have actual trace IDs
- [ ] Tool sequences match trace files (not guessed)
- [ ] Confidence values match OCR results (not fabricated)
- [ ] Routing/critique rationales are quoted from traces
- [ ] At least three different tool sequences demonstrated
- [ ] All PII redacted
- [ ] No "TODO" or placeholder values remain

### Cross-reference
This walkthrough satisfies:
- **REQ-DEL-004:** Trace logs deliverable with annotated walkthrough
- **REQ-AGENT-004:** Variable trajectories requirement (three clearly different paths)
- **Assignment Section 7, Deliverable 4:** "JSONL traces for sample runs, plus a short annotated walkthrough of five items showing different agent trajectories"

See also:
- `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md` for complete requirement mapping
- `artifacts/traces/*.jsonl` for raw trace data
- `docs/03_ARCHITECTURE.md` for expected trajectory patterns
