# Antigravity Prompt — Phase 1: Repository Bootstrap and Contracts

**Recommended model:** Claude Sonnet 4.5 via OmniRoute in the Kilo Code extension inside Antigravity  
**Thinking level:** High, if configurable for this provider/model; otherwise leave the supported default  
**Why:** this is a careful multi-file foundation task with shared contracts. Sonnet 4.5 is the preferred implementation route because it has more available credits than the Claude models directly available in Antigravity.

Copy the whole starter pack into the project root, then paste this prompt into Kilo Code in Antigravity with the model above selected.

---

You are implementing the **Track B (Extended), AI Generalist assignment for Jyot**. Read these files first and treat the original assignment requirements they summarize as the source of truth:
- `AGENT_RULES.md`
- `docs/00_ASSIGNMENT_BRIEF.md`
- `docs/01_PRD.md`
- `docs/02_TRD.md`
- `docs/03_ARCHITECTURE.md`
- `docs/04_IMPLEMENTATION_PLAN.md`
- `docs/05_EVALUATION_PLAN.md`
- `docs/06_SAFETY_THREAT_MODEL.md`
- `docs/07_PROMPT_CATALOG.md`
- `docs/08_DELIVERABLE_CHECKLIST.md`

## Current task: build the foundation only
Do not try to implement every feature in one pass. First inspect the current repository and environment. Preserve user files and report Python version, Git status, Tesseract availability, Ollama availability, and any obvious RAM/disk or dependency blockers. Do not print secrets.

Then create a clean, modular Python package named `jyot_monitor` with:
1. `python -m jyot_monitor` entry point and argparse/typer CLI supporting the exact required command shapes (commands may initially produce clearly labelled TODO errors for not-yet-implemented phases, but `--help` and argument parsing must work).
2. Shared Pydantic models for source item, attachment, OCR result, tool action, planner result, score breakdown, alert proposal and trace event.
3. A SQLite state layer for seen IDs, item state, content-hash cache, clusters, digest/run state and alert proposals. Create schema/migrations in a safe, repeatable way.
4. A JSONL trace writer with the schema in `docs/03_ARCHITECTURE.md`; avoid raw PII/secrets. Missing token/cost measurements must be nullable rather than fabricated.
5. A fixture-manifest loader whose paths are constrained to the fixture root. The `--replay` code path must not import/use live network clients or resolve DNS.
6. Config loading and `.env.example` with placeholders only. Add starter `config/sources.yaml` with the CPSC and FDA RSS URLs from `docs/01_PRD.md`, and host allow-listing.
7. Unit tests for models, SQLite idempotency, trace shape, CLI parsing and replay's network-denial behavior.
8. README setup placeholders and a project tree that follows `docs/02_TRD.md` without unnecessary extra architecture.

## Constraints
- Python 3.12+; also check compatibility with the installed Python version.
- Comments only for serious/non-obvious logic.
- Do not make a UI.
- Do not claim functionality exists until its test passes.
- Do not install every skill. This is a CLI project, so skip Impeccable/Taste/animation/web-design/Playwright. If useful and time permits, install Ponytail with `npx skills add DietrichGebert/ponytail --skill ponytail`; use it for YAGNI/reuse-first judgment, but do not block on it.
- Use `pytest`. Do not add an entire agent framework unless a concrete benefit is justified; the plan uses a small custom bounded controller.
- Do not make a Git commit automatically. First report changes and test results so the human can inspect them. The human will commit this milestone only after the phase exit gate passes.

## Finish this phase by
- Running the phase tests and showing actual pass/fail output.
- Listing exact files created/changed.
- Listing any dependency/environment blocker and the exact command needed to resolve it.
- Updating `docs/08_DELIVERABLE_CHECKLIST.md` only for items genuinely completed.
- Stopping before feature implementation; then wait for the next phase prompt.
