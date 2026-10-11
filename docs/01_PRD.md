# Product Requirements Document

## Product name
**Jyot Agentic Multimodal Monitor**

**Submission label:** Track B (Extended), AI Generalist assignment for Jyot.

## Problem
A small team cannot manually inspect every public notice about product safety. Notices may be duplicated, reposted in screenshots, scanned, blurry, rotated, multilingual or maliciously crafted to manipulate an AI system. The team needs a short, prioritised digest plus evidence-linked alert proposals that a person must approve.

## Chosen scope
**Topic:** Public product-safety recalls and safety alerts.

**Initial live sources:**
- U.S. Consumer Product Safety Commission (CPSC) recall RSS: `https://www.cpsc.gov/Newsroom/CPSC-RSS-Feed/Recalls-RSS`
- U.S. Food and Drug Administration (FDA) recalls RSS: `https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/recalls/rss.xml`

These are official public feeds. For each feed item, the ingester may retrieve the linked official page and discover its referenced image/PDF attachments through the guarded fetch tool. Treat actual availability of images/PDFs as something to measure and report; synthetic/recorded fixtures must guarantee attachment coverage regardless of live-feed variation.

## Users and use cases
- **Analyst:** starts live/replay monitoring and reads the prioritised digest.
- **Reviewer:** inspects sources, OCR evidence, scores and traces.
- **Approver:** accepts or rejects an alert proposal by proposal ID.

## Core journeys
1. Run on public feeds or a local fixture directory.
2. Each item gets an agent plan that may select fetch, OCR, vision, memory search, verification, and alert proposal tools.
3. The agent stops when resolved, budget exhausted, maximum steps reached, or a safe fallback is required.
4. The pipeline clusters duplicate/related items and calculates a score breakdown.
5. A digest shows evidence, uncertainty and what changed since the prior digest.
6. An alert remains queued until a human calls the approval command.
7. `eval` runs offline metrics against hand-labelled gold data.

## Functional acceptance criteria
- Stable source IDs and a persistent seen/cursor store prevent repeat ingestion on identical polls.
- `--replay` never requests a URL or resolves DNS; test with a network-denial mock.
- OCR results record engine, raw confidence, documented normalized confidence, language and second-opinion flag.
- Route to engine 2 when engine 1 confidence is low, language/quality signals suggest failure, or an explicit fault is injected.
- Structured notice fields are Pydantic-validated; untrusted/low-confidence fields are `null` with uncertainty flags.
- A planner emits a schema-validated next action from an allow-listed tool enum. The controller independently validates action arguments and budgets.
- At least three distinct item trajectories are demonstrated by actual traces.
- Urgent scores trigger a critique/verifier; changed and unchanged outcomes are both recorded.
- Digests include source URLs, redacted evidence snippets, score breakdown, cluster representative, uncertainty flags and since-last-digest changes.
- `propose_alert` never sends. A separate approval command is required to emit a local record/webhook stub.
- Eval report is generated from computed predictions and gold labels, not hardcoded results.

## Non-goals under the sprint deadline
- A production hosted dashboard or user-auth system.
- Real SMS/WhatsApp delivery.
- Claims of comprehensive coverage of all public recalls.
- Training OCR/LLM models.
- Unbounded crawling or unrestricted browsing.

## User-visible quality principles
Trust and auditability matter more than flashy UI. Surface source provenance, uncertainty, failures and evidence near every score. Never turn low-confidence OCR into a confident claim.

## Design constraints and trade-offs
- **Official feeds only:** CPSC and FDA RSS feeds are stable, authenticated public sources. Attachment discovery is limited to official page parsing with strict hostname allow-listing.
- **Attachment availability:** Live feeds may not always include image/PDF attachments. Recorded fixtures must guarantee attachment coverage for evaluation purposes.
- **Hindi language support:** Requires EasyOCR with Hindi language pack. Installation and model availability must be verified during setup phase.
- **Cross-modal deduplication challenge:** Detecting that a text post and a screenshot contain the same recall requires OCR text extraction + similarity matching. False merge risk exists when unrelated recalls mention similar products.
- **Urgency calibration:** LLM-based urgency scoring is uncalibrated without extensive ground-truth labeling. Report agreement with human labels, not absolute accuracy.
- **Prompt injection surface:** Any content rendered from OCR (especially image-embedded text) represents untrusted data. Defense relies on data/instruction separation in prompts plus controller permission validation.

## Success metrics (from evaluation criteria)
1. **Agent autonomy (25% weight):** Three or more distinct trajectories proven in traces; ablation shows measurable benefit over fixed pipeline on quality or cost efficiency.
2. **OCR quality (20% weight):** CER/WER measured on 15+ ground-truth samples; router demonstrably selects appropriate engine; Hindi handled correctly.
3. **Safety (15% weight):** Attack success rate on 8+ adversarial cases approaches zero; failures documented; no alert emission without approval.
4. **Evaluation rigor (15% weight):** Metrics computed from predictions vs gold labels; small-sample caveats visible; failures reported honestly.
5. **Dedup/scoring (10% weight):** Cross-modal duplicate clustering works; score components defensible and documented.
6. **Code quality (5% weight):** Modular, tested, reproducible from README.
7. **Engineering judgment (10% weight):** Write-up shows trade-off awareness, scaling thinking, and limits acknowledgment.

## Requirements coverage
See `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md` for complete mapping of 89 requirements from the original assignment to planned implementation.
