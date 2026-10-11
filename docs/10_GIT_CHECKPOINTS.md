# Git Checkpoints

The assignment is confidential. Use the private repository `jyot-agentic-multimodal-monitor`.

## Checkpoint 1 — Planning pack copied
After the starter pack is in the project root and files are verified:
```bash
git status --short
git add .gitignore AGENT_RULES.md README_START_HERE.md docs prompts
git commit -m "docs: add Jyot assignment plan and agent rules"
```

## Checkpoint 2 — Phase 1 foundation verified
Only after required CLI shapes parse, state/tracing tests pass, and replay is network-free:
```bash
git status --short
git diff --check
git add .
git commit -m "feat: add CLI, schemas, SQLite state, and tracing"
```

## Later checkpoints
Make one commit after each of these gates—not after every prompt or minor patch:
- OCR router + measured labelled fixtures: `feat: add routed OCR and labelled fixtures`
- Agent + three distinct trace trajectories + scoring/dedup/memory: `feat: add bounded agent, scoring, memory, and dedup`
- Guarded sources + SSRF/network/PII/fault tests: `feat: add guarded sources and fault-safe network handling`
- Computed evaluation metrics + actual digests/traces: `test: add evaluation suite and submission artifacts`
- Clean final audit and submission packaging: `chore: finalize Jyot assignment submission`

Before each commit, inspect `git diff --check`, `git diff --stat`, staged files, and actual test output. Make sure `.env`, API keys, PII, model weights, caches, virtual environments and temporary artefacts are ignored. Do not commit failed or fabricated test results.

## Checkpoint timing guidance
- **Checkpoint 1:** Within first hour (planning copied)
- **Checkpoint 2:** After Phase 1 (~3 hours from start)
- **Checkpoint 3:** After Phase 2 (~5.5 hours)
- **Checkpoint 4:** After Phase 3 (~9.5 hours)
- **Checkpoint 5:** After Phase 4 (~11.5 hours)
- **Checkpoint 6:** After Phase 5 (~15.5 hours)
- **Checkpoint 7:** After Phase 6 final audit (~17-18 hours)

These are target times assuming smooth progress. Actual timing may vary based on blockers and debugging needs.

## Commit message format
Follow conventional commits style:
- `feat:` for new features/capabilities
- `test:` for evaluation/testing additions
- `fix:` for bug fixes
- `docs:` for documentation-only changes
- `chore:` for maintenance/packaging

Keep messages concise but descriptive:
✅ Good: `feat: add bounded agent with step limits and cost tracking`
✅ Good: `test: add OCR evaluation with CER/WER metrics`
❌ Too vague: `feat: add agent`
❌ Too verbose: `feat: implement the complete bounded agent loop with planner that decides which tools to call and a controller that validates actions and enforces budget limits and schema validation`

## What not to commit
Never commit:
- `.env` files with real secrets
- API keys or tokens in any file
- Virtual environment directories (`venv/`, `test_env/`, `.venv/`)
- Python cache (`__pycache__/`, `*.pyc`, `*.pyo`)
- IDE settings (`.vscode/`, `.idea/`, except shared workspace settings if desired)
- OS files (`.DS_Store`, `Thumbs.db`)
- Large model weights (EasyOCR models, Ollama models)
- Generated caches (`data/cache/`, `*.sqlite3-journal`)
- Personal data or PII recovered from test runs
- Test fixtures containing real user data (use synthetic/public domain only)

## .gitignore template
The project should include:
```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
test_env/
.venv/
env/
ENV/

# Secrets
.env
*.key
*.pem

# IDEs
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Project-specific
data/state.sqlite3
data/state.sqlite3-journal
data/cache/
artifacts/traces/*.jsonl
artifacts/digests/*.md
artifacts/eval/*.md
artifacts/approvals/*.json

# Keep example/fixture files
!fixtures/**
!data/.gitkeep
!artifacts/.gitkeep
```

## Repository structure after all checkpoints
```
jyot-agentic-multimodal-monitor/
├── .gitignore
├── README.md
├── requirements.txt
├── .env.example
├── pyproject.toml (optional)
├── Dockerfile (optional)
├── AGENT_RULES.md
├── README_START_HERE.md
├── docs/
│   ├── 00_ASSIGNMENT_BRIEF.md
│   ├── 01_PRD.md
│   ├── 02_TRD.md
│   ├── 03_ARCHITECTURE.md
│   ├── 04_IMPLEMENTATION_PLAN.md
│   ├── 05_EVALUATION_PLAN.md
│   ├── 06_SAFETY_THREAT_MODEL.md
│   ├── 07_PROMPT_CATALOG.md
│   ├── 08_DELIVERABLE_CHECKLIST.md
│   ├── 09_AGENT_WALKTHROUGH_TEMPLATE.md (completed with actual data)
│   ├── 10_GIT_CHECKPOINTS.md
│   ├── REQUIREMENTS_TRACEABILITY_MATRIX.md
│   └── WRITEUP.md (800-1,200 words)
├── prompts/
│   ├── planner_system.txt
│   ├── planner_user_template.txt
│   ├── ocr_routing.txt
│   ├── vision_describe.txt
│   ├── classification_scoring.txt
│   ├── verification.txt
│   ├── critique.txt
│   ├── structured_notice_extraction.txt
│   ├── digest_generation.txt
│   ├── ITERATION_LOG.md
│   ├── PHASE_1_REPO_BOOTSTRAP.md
│   └── PHASE_2_TO_6_PROMPTS.md
├── source/
│   └── JYOT_ASSIGNMENT_ORIGINAL.txt
├── config/
│   └── sources.yaml
├── jyot_monitor/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── trace.py
│   ├── storage.py
│   ├── ingestion/
│   ├── ocr/
│   ├── agent/
│   ├── llm/
│   ├── scoring.py
│   ├── dedup.py
│   ├── safety.py
│   ├── digest.py
│   ├── approval.py
│   └── evaluation/
├── tests/
│   ├── __init__.py
│   ├── test_cli.py
│   ├── test_storage.py
│   ├── test_ocr.py
│   ├── test_agent.py
│   ├── test_safety.py
│   ├── test_reliability.py
│   ├── test_evaluation.py
│   └── fixtures/
├── fixtures/
│   ├── recorded/
│   │   ├── manifest.json
│   │   └── attachments/
│   └── gold/
│       ├── ocr/
│       ├── classification/
│       ├── dedup/
│       └── adversarial/
├── artifacts/
│   ├── traces/ (contains .jsonl files, not committed)
│   ├── digests/ (contains sample .md files, committed)
│   ├── eval/ (contains evaluation_report.md, committed)
│   └── approvals/ (contains sample proposals, committed)
└── data/
    └── .gitkeep (state.sqlite3 not committed)
```

## Pre-commit checklist
Before each checkpoint commit:
1. Run tests: `python -m pytest -v`
2. Check diffs: `git diff --check` (detects whitespace errors)
3. Review changes: `git diff --stat` and `git diff` for key files
4. Verify no secrets: `git diff | grep -i "api_key\|password\|secret\|token"`
5. Stage intentionally: `git add <specific files>` rather than `git add .`
6. Verify staged: `git status` and review file list
7. Write commit: `git commit -m "type: description"`
8. Test after commit: Verify tests still pass

## Recovery from accidental commit
If secrets accidentally committed:
```bash
# For most recent commit not yet pushed
git reset --soft HEAD~1
# Remove secret from file, add to .gitignore
git add .gitignore <fixed_file>
git commit -m "fix: remove secrets and update gitignore"

# If already pushed (requires force push - use carefully)
# Contact Git admin or consider repository as compromised
# Rotate all exposed credentials immediately
```

## Requirements traceability
See `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md`:
- REQ-TECH-006: Credentials in environment only, never hardcoded
- REQ-SUB-002: Repository or archive format
- REQ-SUB-003: Complete package for running from scratch
- All checkpoint-related commits map to phase exit criteria
