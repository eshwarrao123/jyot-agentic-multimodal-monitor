# Antigravity Follow-up Prompts — Phases 2–6

Use one phase at a time. Inspect output and run tests after every phase. Do not paste the next phase until the current gate passes or known failures are explicitly recorded.

## Phase 2 — OCR, preprocessing, PDFs, fixtures and structured extraction
**Recommended model:** Claude Sonnet 4.5 via OmniRoute in Kilo Code; **High** thinking if configurable (otherwise use the supported default). For a difficult OCR/PDF/language-pack blocker, use Gemini 3.1 Pro; **High**.

Implement `ocr/` per `docs/02_TRD.md`: Tesseract engine, EasyOCR engine, PDF page rendering, image preprocessing profiles (original, grayscale/contrast, threshold and deskew/upscale where appropriate), explicit route policy based on quality and OCR confidence, language, text density, and `needs_second_opinion`. Add per-engine raw confidence plus a documented normalized confidence scale; don't pretend raw confidences from different engines are directly calibrated. Implement notice field extraction with schema validation and `null`/uncertain flags instead of guessing. Create a reproducible fixture/gold generator using a fixed seed with at least 15 transcription-labelled image/pages, at least 3 difficult cases and 3 Hindi cases, plus a multi-page scanned PDF. Add tests and an initial computed CER/WER/preprocessing report. If an engine/language pack is unavailable, produce a clear setup instruction and visible unavailable status, not silent fallback or fake metrics.

Run tests, list exact commands and results, update checklist, then stop.

## Phase 3 — Bounded agent, scoring, memory, dedup and alert proposal
**Recommended model:** Claude Sonnet 4.5 via OmniRoute in Kilo Code; **High** thinking if configurable. Use Gemini 3.1 Pro; **High** only for a critical controller/architecture bug.

Implement the custom planner/controller in `agent/`. Planner responses must be JSON-schema/Pydantic validated and select only from allow-listed actions. Use local Ollama only when explicitly configured/available; otherwise use a deterministic planner fallback that is clearly labelled in traces. Never make claims that fallback mode is LLM-driven. Strict replay/eval must not use remote APIs. Implement step/item/run cost/token budgets, max tool-call count, bounded invalid-JSON retries, deterministic recovery, high-urgency critique/verifier, score components plus at least one non-LLM signal, SQLite memory search, exact hashes + near-text/MinHash + perceptual image hash + OCR-text cross-modal candidate matching, story clusters and a safe proposal queue. `propose_alert` must only enqueue a pending proposal. Add tests for at least three different trajectories and controller rejection of unapproved/invalid tool calls. Create prompt files for all LLM operations and ensure code loads those exact files.

Run tests and show actual JSONL excerpts (redacted); stop after phase gate.

## Phase 4 — Live sources, guarded fetch, PII, network and reliability safety
**Recommended model:** Gemini 3.1 Pro; **High** thinking. This phase handles SSRF/network boundaries and must be tested carefully; avoid using Opus unless a critical flaw remains unresolved.

Implement CPSC and FDA RSS adapters and incremental persistence. For live attachment retrieval, enforce URL scheme/hostname allow-list, DNS resolution and public-IP checks, redirect-by-redirect validation, timeouts, max bytes, MIME/signature verification and per-host/request limits. Never fetch a URL merely because it appeared in OCR text. Discover attached images/PDFs only from trusted official source records and guarded official page parsing. Implement exponential backoff with jitter and `Retry-After`, and per-item partial failure. Implement PII detection/redaction before digest/proposal/log surfaces. `--replay`/`eval` must be provably network-free: inject a network-denial fake or make the network client unavailable in those modes, and include a test that fails on any request. Add deterministic `--fault-injection` cases for HTTP 429/500, corrupt image/PDF, OCR crash, malformed model JSON and timeout/budget exhaustion. Verify restarting a partial run does not duplicate state, clusters, digests or proposals.

Run targeted safety tests and report any residual issues. Stop after phase gate.

## Phase 5 — Digest, evaluation harness, baseline and artifacts
**Recommended model:** Claude Sonnet 4.5 via OmniRoute in Kilo Code; **High** thinking if configurable. Routine test repairs may use Gemini 3.6 Flash; **Medium/Low**.

Complete at least 60 labelled items with 25+ image-content items, 10 duplicate groups including cross-modal pairs, and 8+ adversarial cases. Keep labels separate from predictions. Implement computed OCR CER/WER per engine/router and preprocessing ablation; per-class classification precision/recall, macro-F1 and confusion matrix; urgency rank correlation/agreement; pairwise dedup precision/recall with false-merge examples; injection attack success rate and failure list; and agent-vs-fixed-pipeline ablation with mean steps/tool calls, per-item cost/latency and fallback rate. Make the report state sample sizes and synthetic-vs-real data limits. Generate three actual digests (live or recorded-live, replay, fault-injection), traces for those runs and a five-item annotated walkthrough based on trace IDs. Implement approval and rejection commands; test that alert emission cannot occur before approval. Draft the 800–1,200-word write-up based on actual implementation/results; explain what the agent improves and where it does not beat the baseline.

Run the full suite and update checklist only for verified items. Stop before final review.

## Phase 6 — Final audit and packaging
**Recommended model:** Claude Sonnet 4.6 in Antigravity; **High** for one careful cross-file review. Cost-aware alternative: Claude Sonnet 4.5 via OmniRoute/Kilo Code; **Medium/High** if configurable. Claude Opus 4.6 is last-resort only for a critical defect that cheaper models cannot resolve.

Audit against every checkbox in `docs/08_DELIVERABLE_CHECKLIST.md` and every required item in `docs/00_ASSIGNMENT_BRIEF.md`. Inspect actual output, do not trust self-reported completion. From a clean shell, run each required command. Check the exact archive/repository includes fixtures, gold labels, prompt files, sample digests, traces, eval report, write-up, `requirements.txt`, `.env.example` and README. Search for secrets/PII. Verify replay has no external HTTP/DNS/model calls. Verify zip opens and the CLI command works. Add an accurate AI coding assistant disclosure and known limitations. Mark incomplete items honestly and prioritise fixing mandatory gaps over style cleanup. Provide a concise final report with evidence (commands and test counts) and remaining limitations.
