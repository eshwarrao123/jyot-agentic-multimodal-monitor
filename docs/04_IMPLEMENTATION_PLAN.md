# Implementation Plan — 24-Hour Sprint

## Model routing principle
Use **Claude Sonnet 4.5 through OmniRoute in the Kilo Code extension inside Antigravity** as the default implementation model while its available credits remain healthy. Use High thinking for multi-file or critical implementation when the selector exposes that setting; if Kilo/OmniRoute does not expose a thinking control for this model, leave its supported default and do not waste time trying to force a setting. Use Gemini 3.1 Pro for hard technical/security issues, Gemini 3.6 Flash for routine fixes, Sonnet 4.6 for a focused final review, and Opus 4.6 only as a last resort.

## Phase 0 — Workspace and spec lock (20–30 min)
**Recommended model:** Claude Sonnet 4.5 via OmniRoute in Kilo Code; **Medium** thinking if configurable.  
**Why:** clarify scope and create the workspace without spending limited Antigravity Claude credits.

Create `jyot-agentic-multimodal-monitor`. Copy the starter pack contents into the project root. Create a **private** GitHub repository with the same name; do not initialize the remote with an extra README/license/gitignore because the local starter files already exist. Confirm Python and pip; check Git, Tesseract, Ollama, RAM and disk. Do not print secrets. The project is CLI-first; no UI. Ponytail can be installed only if time permits:
```bash
npx skills add DietrichGebert/ponytail --skill ponytail
```
Use it for reuse-first/YAGNI decisions; do not block implementation on it.

**Git checkpoint:** commit the planning pack as `docs: add Jyot assignment plan and agent rules` after checking the copied files. Do not commit every phase sub-step.

## Phase 1 — Skeleton, schemas, CLI, state and trace (1.5–2 h)
**Recommended model:** Claude Sonnet 4.5 via OmniRoute in Kilo Code; **High** thinking if configurable.  
**Why:** precise multi-file contracts and foundation coding; uses the more available Sonnet 4.5 route rather than limited Antigravity Claude credits.

Implement package entry point, typed config/models, SQLite state, JSONL tracer, deterministic fixture loader, CLI contract and basic tests. Stub tools behind a small registry, but ensure each stub fails clearly rather than pretending success.

**Exit gate:** all required commands parse; replay loads fixtures offline; state/tracing tests pass. Review the diff and test output, then make one milestone commit: `feat: add CLI, schemas, SQLite state, and tracing`. Do not create commits for minor edits within the phase.

## Phase 2 — OCR and fixtures (2–3 h)
**Recommended model:** Claude Sonnet 4.5 via OmniRoute in Kilo Code; **High** thinking if configurable.  
**Escalation for a difficult OCR/PDF/language-pack blocker:** Gemini 3.1 Pro; **High**.

Implement PDF page rasterization, Tesseract, EasyOCR, preprocessing variants, explicit router, confidence/second-opinion metadata, structured notice extraction, and deterministic fixture/gold generator. Generate at least 15 OCR pages/images with ground truth (including 3 difficult and 3 Hindi); verify Hindi fonts/model/language pack really work on this machine.

**Exit gate:** OCR tests run; per-engine results are measurable; missing engine errors are explicit. Commit once the OCR path and first measured report are usable: `feat: add routed OCR and labelled fixtures`.

## Phase 3 — Agent, scoring, verification and memory/dedup (3–4 h)
**Recommended model:** Claude Sonnet 4.5 via OmniRoute in Kilo Code; **High** thinking if configurable.  
**Escalation:** Gemini 3.1 Pro; **High**, only for a critical planner-contract, budget or data-flow bug.

Implement a bounded planner interface with schema-validated action choice; use an available local Ollama text model if installed/configured, otherwise a visibly labelled deterministic fallback. Optional commercial provider only if explicitly configured. Strict replay/eval must not use remote APIs. Implement action allow-list, step/cost budgets, retries, critique for high urgency, score breakdown, SQLite memory, text/image/cross-modal dedup, clusters and pending alert proposals. Keep tool permission checks in code outside the LLM.

**Exit gate:** three or more distinct trajectories are proven by actual traces; no direct alert-emission path exists from the agent. Commit: `feat: add bounded agent, scoring, memory, and dedup`.

## Phase 4 — Sources and security (1.5–2 h)
**Recommended model:** Gemini 3.1 Pro; **High** thinking.  
**Why:** SSRF, redirects, DNS/IP validation and untrusted OCR require careful edge-case reasoning. Sonnet 4.5 can implement targeted fixes; reserve Sonnet 4.6/Opus 4.6 for review/escalation only when needed.

Implement CPSC and FDA feed adapters; discover page attachments only on explicitly allowed official hosts. Add DNS/public-IP and redirect checks, response time/size limits, MIME/signature verification, PII redaction, replay's hard network ban, retry-after/exponential backoff with jitter and safe error handling.

**Exit gate:** tests prove blocked private-IP/redirect/content-type cases and prove replay does not touch the network. Commit: `feat: add guarded sources and fault-safe network handling`.

## Phase 5 — Evaluation, faults, digest, approval and documentation (3–4 h)
**Recommended model:** Claude Sonnet 4.5 via OmniRoute in Kilo Code; **High** thinking if configurable.  
**Routine test fixes:** Gemini 3.6 Flash; **Medium**.  
**Why:** implement actual metrics and required artifacts efficiently; use smaller prompts for individual failing tests.

Complete 60 labelled items (25 or more with image content), 10 duplicate groups, and 8 adversarial cases; compute metrics; compare against a fixed-pipeline baseline; run deterministic fault injection; generate all three required digests/traces and the five-item walkthrough; draft the 800–1,200-word write-up.

**Exit gate:** computed outputs exist, failures are reported, and no metric is hardcoded. Commit: `test: add evaluation suite and submission artifacts`.

## Phase 6 — Submission audit (1–1.5 h; reserve this time)
**Recommended model:** Claude Sonnet 4.6 in Antigravity; **High** if configurable, for one final cross-file review.  
**Lower-cost alternative:** Claude Sonnet 4.5 via OmniRoute/Kilo Code; **Medium/High**.  
**Last resort only:** Opus 4.6 if a critical defect remains unresolved after targeted attempts.

Run the complete command contract from a clean terminal, test offline behavior, verify the deliverables, make the zip or private repository ready, and disclose AI-assistant use honestly. Ensure Track B label appears at the top of README and report. Commit the release state only after the final audit passes: `chore: finalize Jyot assignment submission`.

## Suggested time budget
| Work | Target |
|---|---:|
| Workspace + schemas/CLI/state | 2.5 h |
| OCR and gold OCR cases | 2.5 h |
| Agent, scoring, dedup, memory | 4 h |
| Sources and safety | 2 h |
| Eval/faults/digests/docs | 4 h |
| Testing, debugging, packaging buffer | 5 h |
| **Total** | **20 h** |

**Current status (2026-10-11T18:56):** Documentation audit phase  
**Remaining time to deadline:** ~52 hours (until 2026-10-13T23:59)  
**Planned implementation start:** After documentation review approval

This is a risk-based target, not a claim that every requirement will fit. If behind schedule, preserve runnable replay, actual traces, safety checks, core metrics and honest evaluation first. Never fabricate metrics or pretend unimplemented work is complete.

## Phase dependencies and critical path
```
Phase 0 (workspace) → Phase 1 (foundation) → Phase 2 (OCR) → Phase 3 (agent)
                                                ↓
Phase 4 (sources/safety) can partially parallel Phase 3
                                                ↓
Phase 5 (evaluation) requires Phases 2, 3, 4 complete
                                                ↓
Phase 6 (audit) is final gate
```

**Critical path:** Phase 1 → Phase 2 → Phase 3 → Phase 5 → Phase 6 (16-17 hours minimum)  
**Parallel opportunity:** Phase 4 network safety implementation while Phase 3 agent is in testing

## Risk mitigation strategies
**Risk 1:** OCR engine installation failures (Hindi language pack, Tesseract binary)  
**Mitigation:** Document clear installation steps in Phase 0; test immediately; have fallback plan to synthetic fixtures if live OCR unavailable

**Risk 2:** Agent trajectories all look similar despite dynamic routing  
**Mitigation:** Create deliberately diverse test items in Phase 3: (1) plain text, (2) very blurry image, (3) multi-page PDF, (4) urgent claim requiring verification

**Risk 3:** Evaluation gold set creation takes too long  
**Mitigation:** Generate synthetic fixtures programmatically where possible; prioritize minimum counts (15 OCR, 60 classification, 10 dedup, 8 adversarial) over large comprehensive sets

**Risk 4:** Network isolation testing is brittle or incomplete  
**Mitigation:** Use explicit mock injection in Phase 4; test with actual network disabled if possible; prioritize clear error message over perfect isolation

**Risk 5:** Time runs out before submission artifacts complete  
**Mitigation:** Phase 5 checklist prioritizes: (1) computed metrics report, (2) three sample digests, (3) trace walkthrough, (4) write-up. Skip optional screen recording if time is critical.

## Scope reduction triggers
If by Phase 3 end (12h mark) progress is <60% complete:
1. **Reduce gold set sizes:** 12 OCR images (drop 3), 40 classification items (drop 20), keep minimum adversarial/dedup
2. **Simplify vision tool:** Stub `vision_describe` as "not available" rather than integrating vision LLM
3. **Reduce preprocessing profiles:** Test original vs one preprocessing variant, not four variants
4. **Simplify baseline:** Fixed pipeline runs classifier + dedup only, not full tool simulation

Do not reduce:
- Network safety testing (critical for 15% evaluation weight)
- Prompt injection testing (critical for 15% evaluation weight)
- Agent trajectory diversity (critical for 25% evaluation weight)
- Basic OCR routing (critical for 20% evaluation weight)

## Quality gates (must pass before proceeding)
**Phase 1 gate:**
- `pytest tests/test_cli.py tests/test_storage.py` passes
- All five CLI commands parse without error
- Replay fixture loader works with network mocking

**Phase 2 gate:**
- Both OCR engines process one test image successfully
- Router makes different engine selections on two different images
- At least 10 OCR ground-truth samples created

**Phase 3 gate:**
- Planner selects at least 3 different tools across 5 test items
- Controller rejects invalid tool argument at least once in tests
- Trace JSONL contains recognizable decision rationale

**Phase 4 gate:**
- Private IP fetch attempt raises security error
- Retry-After honored in rate limit test
- PII redaction replaces email address in test

**Phase 5 gate:**
- Evaluation command produces report with all 7 metric tables
- At least one metric shows honest "failure" or "low performance" result
- Three digest artifacts exist

**Phase 6 gate:**
- All five CLI commands execute without crash
- `test_network_denial` passes in replay mode
- Track B label appears at top of README
- Zip file or repository is accessible

## Implementation sequence optimizations
1. **Parallel fixture generation:** While implementing agent in Phase 3, generate classification gold set items
2. **Incremental testing:** Write test alongside each module, not deferred to end
3. **Trace-first development:** Emit trace on every major operation from Phase 1; enables debugging and walkthrough without refactoring later
4. **Cache early:** Implement content-hash cache in Phase 1 so OCR/LLM caching works naturally in Phase 2-3

## Requirements traceability
See `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md` for all 89 requirements with implementation and testing plans mapped to phases.
