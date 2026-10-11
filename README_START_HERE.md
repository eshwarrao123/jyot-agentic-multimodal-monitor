# Jyot AI Generalist Assignment — Starter Pack

**Track B (Extended), AI Generalist assignment for Jyot.**

This folder is the planning and agent-instruction pack for the **Agentic Multimodal Monitor with OCR: Live Discussion Monitor & Digest**. Copy these files into a new Antigravity project folder before implementation.

## Read in this order

1. `docs/00_ASSIGNMENT_BRIEF.md` — plain-English explanation of the brief and pass-critical requirements.
2. `docs/01_PRD.md` — product scope, topic, user journey and acceptance criteria.
3. `docs/02_TRD.md` — stack, modules, CLI contract and operating constraints.
4. `docs/03_ARCHITECTURE.md` — data flow, planner/tool contracts, state and trace shape.
5. `docs/04_IMPLEMENTATION_PLAN.md` — deadline-aware phases and model choices.
6. `docs/05_EVALUATION_PLAN.md` — honest gold-set strategy and metrics.
7. `docs/06_SAFETY_THREAT_MODEL.md` — injection, PII, SSRF and fault handling.
8. `docs/07_PROMPT_CATALOG.md` — prompts that must be versioned in the repo.
9. `docs/08_DELIVERABLE_CHECKLIST.md` — final submission gate.
10. `docs/09_AGENT_WALKTHROUGH_TEMPLATE.md` — five-item trace walkthrough template.
11. `docs/10_GIT_CHECKPOINTS.md` — meaningful commit gates.
12. `AGENT_RULES.md` — code-generation rules for Antigravity.
13. `prompts/PHASE_1_REPO_BOOTSTRAP.md` — first prompt to run in Antigravity.
14. `prompts/PHASE_2_TO_6_PROMPTS.md` — follow-up phase prompts.

## Workspace and Git setup

- Project folder: `jyot-agentic-multimodal-monitor`
- GitHub repository: `jyot-agentic-multimodal-monitor` (**Private**, because the source assignment is marked confidential)
- Copy the contents of this folder into the project root; do not keep an accidental nested `jyot_assignment_starter_pack/jyot_assignment_starter_pack/` directory.
- Create the GitHub repository empty (do not add a second README or license at GitHub creation time). A local `.gitignore` is included in this pack.
- Commit only at meaningful milestone gates listed in `AGENT_RULES.md`; inspect diffs and test results before each commit.

## Important working rules

- The source assignment is authoritative. These plans translate it into a feasible implementation; they do not replace any requirement.
- Do not fabricate evaluation scores, test results, source citations, trace contents, or successful run claims.
- Build and test incrementally. Preserve a working commit/state before large changes.
- Prefer a reliable, headless Python CLI over an unnecessary dashboard: the required interface is CLI-based.
- Record actual decisions and limitations in the final evaluation report.
