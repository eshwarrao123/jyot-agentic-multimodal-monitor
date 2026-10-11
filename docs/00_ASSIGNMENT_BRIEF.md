# Assignment Brief — Plain-English Contract

**Track B (Extended), AI Generalist assignment for Jyot.**

## What Jyot is asking us to build
A repeatable monitor for a chosen public topic. It fetches new posts/notices, reads visible text and text embedded in images/scanned PDFs, groups duplicate or related stories, estimates relevance and urgency, checks urgent claims, writes a ranked evidence-linked digest, and places high-priority alert proposals in a human approval queue.

This is not just an LLM summarizer. The agent must decide what to do next for each item. A readable text item might need only classification; a blurry screenshot may need preprocessing and a second OCR engine; a high-urgency claim may need a corroboration check. These different paths must appear in the JSONL traces.

## Main assessment weights
- Agent design/autonomy: 25%
- OCR and document extraction: 20%
- Safety and robustness: 15%
- Evaluation rigor and honesty: 15%
- Deduplication, memory and scoring: 10%
- Write-up and engineering judgment: 10%
- Code quality and structure: 5%

## Required end-to-end capabilities
1. Two public, authentication-light sources and persistent incremental ingestion.
2. `--replay <dir>` using only recorded JSON and attachments, without network access.
3. Two OCR engines plus explicit, traceable routing; preprocessing measured rather than assumed beneficial.
4. English plus Hindi, including screenshots, rotated/low-contrast images, and a multi-page scanned PDF.
5. Validated structured fields for a notice-like document; uncertain values must be flagged, not guessed.
6. An actual bounded planner/controller that selects tool calls; schemas, retries, budgets, traces, and varied trajectories.
7. LLM relevance/urgency with at least one non-LLM score signal.
8. Text and image/cross-modal deduplication, story clustering and persistent memory.
9. Prompt-injection isolation, PII redaction, SSRF controls and spam/manipulation defense.
10. Rate-limit/error fallback, idempotence, resume, content-hash caching and fault injection.
11. Alert proposals that cannot be emitted until explicitly approved.
12. Measured evaluation, three sample digests, sample JSONL traces, a five-item trajectory walkthrough, exact prompts, and an 800–1,200-word design write-up.

## Commands the evaluator expects
```bash
python -m jyot_monitor run --live --sources config/sources.yaml --top-n 10
python -m jyot_monitor run --replay fixtures/recorded --top-n 10 --budget-usd 1.00
python -m jyot_monitor run --replay fixtures/recorded --fault-injection
python -m jyot_monitor eval --gold fixtures/gold
python -m jyot_monitor approve <proposal_id>
```

## Required minimum evaluation set
- OCR: 15+ images/pages with hand-authored ground-truth text; at least 3 hard cases and 3 Hindi cases. Report CER/WER for each OCR engine, routed OCR, and preprocessing comparison.
- Classification/urgency: 60+ labelled items, at least 25 with image content. Report per-class precision/recall, macro-F1, confusion matrix and urgency agreement/correlation.
- Deduplication: 10+ known duplicate groups including cross-modal groups; pairwise precision/recall and false-merge examples.
- Safety: 8+ adversarial inputs across text and image-embedded attacks; report attack success rate (target 0) and failures.
- Agent: mean steps/tool calls, cost and failure/fallback rates; compare agent with a fixed-pipeline baseline for quality and cost.

## Deadline note
The supplied assignment document says **Tuesday, 13 October 2026, 23:59 local time** (four days from issue date of Friday, 9 October 2026). This provides approximately 72 hours from the current time (2026-10-11T18:55). Execute as a focused sprint with milestone gates. Aim to finish and validate with buffer time before the deadline.

## Cross-Reference
See `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md` for complete requirement-to-implementation mapping with 89 tracked requirements.

## What counts as a good submission
A smaller system that runs from a clean setup, survives bad inputs, presents real traces and reports honest weaknesses is stronger than an expansive system with unsupported accuracy/safety claims. Do not fabricate metrics or imply that live sources were tested if they were not.
