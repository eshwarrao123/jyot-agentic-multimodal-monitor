# Deliverables and Final Submission Gate

Update every checkbox only after inspecting the actual file or running the command.

## Codebase
- [ ] `TRACK B (EXTENDED), AI GENERALIST ASSIGNMENT FOR JYOT` is clearly stated at the top of README/submission.
- [ ] Runnable modular Python codebase and `requirements.txt` or equivalent.
- [ ] `.env.example`; no hardcoded credentials or secrets.
- [ ] Setup and run instructions verified from a clean environment.
- [ ] Core logic has meaningful tests; comments only on serious/non-obvious logic.

## Required commands
- [ ] `python -m jyot_monitor run --live --sources config/sources.yaml --top-n 10`
- [ ] `python -m jyot_monitor run --replay fixtures/recorded --top-n 10 --budget-usd 1.00`
- [ ] `python -m jyot_monitor run --replay fixtures/recorded --fault-injection`
- [ ] `python -m jyot_monitor eval --gold fixtures/gold`
- [ ] `python -m jyot_monitor approve <proposal_id>` and a rejection path.

## Evidence and artifacts
- [ ] Two public auth-light sources configured; at least one source/page has attachments discovered or fixture attachment behavior demonstrated.
- [ ] Replay works without network; explicit test or trace proves it.
- [ ] OCR engine 1 and 2, routing signals, preprocessing-on/off comparison, English + Hindi, rotated/low-contrast image and multi-page scanned PDF.
- [ ] Structured notice JSON schema with validation and uncertain fields flagged.
- [ ] At least three different actual agent trajectories in JSONL traces.
- [ ] Persistent state, content-hash cache, dedup clustering, cross-modal duplicate case.
- [ ] High urgency runs critique/verification and logs if it changed the decision.
- [ ] Step and token/cost budgets; invalid LLM JSON/fallback behavior.
- [ ] PII redaction; injection, SSRF/private-IP, content-type, rate-limit and fault tests.
- [ ] Human approval queue has no direct agent-sending path.
- [ ] Digest includes evidence, score breakdown, flags, links and what changed since last run.

## Evaluation
- [ ] 15+ ground-truth OCR images/pages including 3 difficult and 3 Hindi cases.
- [ ] 60+ labelled classification/urgency items, at least 25 with images.
- [ ] 10+ duplicate groups including cross-modal duplicates.
- [ ] 8+ text/image adversarial cases.
- [ ] Computed OCR CER/WER per engine/router and preprocessing ablation.
- [ ] Computed per-class precision/recall, macro-F1 and confusion matrix.
- [ ] Computed urgency rank agreement/correlation.
- [ ] Computed pairwise dedup precision/recall and false-merge examples.
- [ ] Computed attack success rate and listed remaining failures.
- [ ] Agent vs fixed-pipeline quality/cost ablation; average steps/tool calls, cost and fallback rate.
- [ ] Small sample sizes and synthetic data are clearly disclosed.

## Required submission artifacts
- [ ] Sample digest from live or recorded-live run.
- [ ] Sample digest from replay run.
- [ ] Sample digest from fault-injection run.
- [ ] JSONL traces for these sample runs.
- [ ] Annotated walkthrough of five items with distinct trajectories/outcomes.
- [ ] Exact prompt catalogue, rationale and honest iteration history.
- [ ] Evaluation report with required metric tables.
- [ ] 800–1,200-word write-up (architecture, agent vs baseline, OCR trade-offs, injection threat model, scaling to 100x, limits and next two weeks).
- [ ] AI coding assistant use disclosed, including how output was verified/corrected.
- [ ] Zip or private repository access checked by opening/downloading it once.

## Final verification
- [ ] Start from a clean shell or new virtual environment.
- [ ] Run the complete test suite and save actual output.
- [ ] Run each required CLI command.
- [ ] Run replay with network disabled/mocked and verify no network access occurs.
- [ ] Confirm no API keys, PII or private local paths appear in the archive.
- [ ] Re-run digest/eval generation and inspect the artifacts manually.
- [ ] Update this checklist honestly; do not check a box because the agent says it is done.

## Pre-submission validation commands
Run these in sequence from project root:

```bash
# 1. Clean environment test
python -m venv test_env
test_env\Scripts\activate  # Windows
# source test_env/bin/activate  # Unix
pip install -r requirements.txt
python -m pytest -v

# 2. CLI contract verification
python -m jyot_monitor run --live --sources config/sources.yaml --top-n 10 --dry-run
python -m jyot_monitor run --replay fixtures/recorded --top-n 10 --budget-usd 1.00
python -m jyot_monitor run --replay fixtures/recorded --fault-injection
python -m jyot_monitor eval --gold fixtures/gold
python -m jyot_monitor approve <proposal_id_from_previous_run>

# 3. Network isolation test
python -m pytest tests/test_replay.py::test_network_denial_raises -v

# 4. Secret scan
grep -r "sk-" . --exclude-dir=test_env --exclude-dir=.git
grep -r "API_KEY" . --exclude-dir=test_env --exclude-dir=.git --include="*.py" --include="*.json"

# 5. Archive creation and test
cd ..
tar -czf jyot-agentic-multimodal-monitor.tar.gz jyot-agentic-multimodal-monitor/ --exclude=test_env --exclude=.git --exclude=__pycache__ --exclude=*.pyc
# Or: Compress-Archive -Path jyot-agentic-multimodal-monitor -DestinationPath jyot-agentic-multimodal-monitor.zip
mkdir test_extract
cd test_extract
tar -xzf ../jyot-agentic-multimodal-monitor.tar.gz
# Verify extracted archive works from scratch
```

## Checklist progression tracking
This checklist maps to requirements in `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md`.

**Phase 1 completions (Foundation):**
- REQ-CLI-001 through REQ-CLI-005 (command parsing)
- REQ-ING-003 (replay mode exists)
- REQ-AGENT-007 (trace schema defined)

**Phase 2 completions (OCR):**
- REQ-OCR-001 through REQ-OCR-006 (all OCR requirements)
- REQ-EVAL-001, REQ-EVAL-002 (OCR gold set and metrics)

**Phase 3 completions (Agent):**
- REQ-AGENT-001 through REQ-AGENT-008 (all agent requirements)
- REQ-SCORE-001, REQ-SCORE-002 (classification and scoring)
- REQ-DEDUP-001 through REQ-DEDUP-003 (deduplication)
- REQ-EVAL-010, REQ-EVAL-011 (agent metrics and ablation)

**Phase 4 completions (Safety):**
- REQ-SAFE-001 through REQ-SAFE-004 (all safety requirements)
- REQ-REL-001 through REQ-REL-004 (reliability)
- REQ-ING-001, REQ-ING-002 (live sources working)
- REQ-EVAL-008, REQ-EVAL-009 (adversarial testing)

**Phase 5 completions (Evaluation):**
- REQ-EVAL-003 through REQ-EVAL-007 (classification, urgency, dedup metrics)
- REQ-DEL-001 through REQ-DEL-009 (all deliverables)
- REQ-HITL-001, REQ-HITL-002 (approval queue)
- REQ-DIGEST-001 (digest generation)

**Phase 6 completions (Audit):**
- REQ-SUB-001 through REQ-SUB-005 (submission requirements)
- REQ-EVAL-WEIGHT-001 through REQ-EVAL-WEIGHT-007 (evaluation criteria coverage)
- REQ-TECH-001 through REQ-TECH-006 (technical requirements)

## Known scope risks
If time is insufficient to complete all 89 requirements:
1. **Must keep:** Network safety (REQ-SAFE-003), prompt injection tests (REQ-SAFE-001), agent trajectories (REQ-AGENT-004), evaluation report (REQ-DEL-006), honest limitations (REQ-EVAL-004)
2. **Can reduce:** Gold set sizes to absolute minimums (15→12 OCR, 60→40 classification), preprocessing ablation to 1-2 comparisons, vision_describe tool can be stubbed as unavailable
3. **Cannot drop:** Replay mode, approval gate, safety tests, measured metrics, write-up, Track B label

## Final submission format
**Option 1 (Recommended):** Private GitHub repository
- Repository name: `jyot-agentic-multimodal-monitor`
- Privacy: Private
- Access: Grant read access to ai@jyot.in or provided evaluator accounts
- Include: All code, fixtures, docs, prompts, .env.example, requirements.txt
- Exclude: .env (actual secrets), __pycache__, *.pyc, test_env/, .git/ (will be present naturally)

**Option 2:** Compressed archive
- Format: .zip or .tar.gz
- Name: `jyot-agentic-multimodal-monitor-<your_name>.zip`
- Test: Extract to new location and verify setup from README works
- Upload: To provided submission link or email (check assignment for instructions)

## Requirements coverage summary
**Total requirements:** 89  
**Mandatory:** 89  
**Optional:** 1 (screen recording)

See complete traceability matrix: `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md`

**Evaluation weight alignment:**
- Agent design (25%): REQ-AGENT-* requirements
- OCR extraction (20%): REQ-OCR-* requirements
- Safety (15%): REQ-SAFE-* and REQ-REL-* requirements
- Evaluation rigor (15%): REQ-EVAL-* requirements
- Dedup/scoring (10%): REQ-DEDUP-* and REQ-SCORE-* requirements
- Code quality (5%): REQ-TECH-005, REQ-DEL-001
- Write-up (10%): REQ-DEL-007, REQ-SUB-005
