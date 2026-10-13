# Documented Prompt Catalog

**Project:** `jyot-agentic-multimodal-monitor`  
**Track:** Track B (Extended), AI Generalist Technical Assignment for Jyot  
**Phase:** Phase 5 — Final Submission Package  

This catalog records the exact prompts executed within the system, their trust boundaries, JSON schemas, operational versions, known weaknesses, and verification test references. All production prompts reside in the `prompts/` directory.

---

## 1. Safety Architecture: Delimiters and Trust Boundaries

Every prompt that ingests external data enforces strict structural isolation:
1. **Instruction vs. Data Separation:** Untrusted inputs (item titles, RSS descriptions, crawled HTML text, OCR transcriptions, and document text) are enclosed within `[UNTRUSTED START]` and `[UNTRUSTED END]` delimiters.
2. **Defensive Policy Invariant:** System prompts instruct models that content inside untrusted boundaries is strictly data, never instructions.
3. **Controller-Enforced Permissions:** Prompt boundaries are backed by hard deterministic code controls:
   - Tool names must exist in the allow-listed `ToolRegistry`.
   - Arguments are schema-validated using Pydantic models.
   - Filesystem paths are verified against directory traversal (`Path.resolve()` check against fixture root).
   - Network requests are governed by `SafeHttpClient` with hard offline-mode blocking.
   - Alert emissions strictly require explicit human CLI authorization.

---

## 2. Complete Prompt Inventory

### Prompt 1: Bounded Planner System Prompt (`prompts/planner_system.txt`)
- **File:** `prompts/planner_system.txt`
- **Purpose:** Guides the LLM controller to select the single next action in an item's investigation trajectory, enforcing step budgets and tool candidate lists.
- **Trusted / Untrusted Boundary:** Defines critical safety boundaries; informs the model that untrusted tokens cannot alter controller policy or invoke unlisted tools.
- **Output Schema:**
  ```json
  {
    "action": "<action_name>",
    "rationale": "<string>",
    "arguments": {}
  }
  ```
- **Allowed Actions:** `fetch_attachment`, `ocr_extract`, `vision_describe`, `search_memory`, `verify_claim`, `classify_score`, `critique_item`, `propose_alert`, `finish`.
- **Version:** `v1.2` (Updated with candidate action list constraint to prevent invalid tool hallucinations).
- **Known Weaknesses:** On smaller 3B parameter models (e.g., `qwen2.5:3b`), the model occasionally attempts to re-propose alerts or select `ocr_extract` when attachments are already processed if candidate lists are omitted. Resolved by injecting explicit dynamic `CANDIDATE ACTIONS FOR THIS STEP` into the user prompt.
- **Relevant Tests:** `tests/test_agent.py::test_planner_llm_json_parsing_and_validation`, `test_three_distinct_agent_trajectories`, `test_adversarial_case_2_attempt_to_force_arbitrary_tool_call`.

---

### Prompt 2: Bounded Planner User Prompt Template (`prompts/planner_user_template.txt`)
- **File:** `prompts/planner_user_template.txt`
- **Purpose:** Supplies item state, attachment metadata, completed actions, step budgets, and candidate tools for each planner iteration.
- **Trusted / Untrusted Boundary:** Places raw title and body inside `[UNTRUSTED START]` ... `[UNTRUSTED END]`. Completed tool results and budget state are supplied in trusted sections outside the delimiters.
- **Output Schema:** Evaluated against `ActionRequest` Pydantic model.
- **Version:** `v1.1`.
- **Known Weaknesses:** Large OCR texts can inflate token context size, slowing CPU inference on local models. Mitigated by truncating OCR previews to 500 characters in the planner prompt.
- **Relevant Tests:** `tests/test_agent.py::test_incremental_trace_and_redaction`, `test_step_limit_enforcement`.

---

### Prompt 3: Classification and Scoring (`prompts/classification_scoring.txt`)
- **File:** `prompts/classification_scoring.txt`
- **Purpose:** Evaluates combined item text and OCR transcription to assign an 8-class safety taxonomy, continuous relevance (0–100), urgency (0–100), and extract hazard descriptions.
- **Trusted / Untrusted Boundary:** Fuses item title, body, and OCR text as untrusted analysis targets.
- **Taxonomy Categories:** `product_recall`, `health_hazard`, `contamination`, `unsafe_equipment`, `consumer_warning`, `non_safety`, `spam_manipulation`, `uncertain`.
- **Output Schema:**
  ```json
  {
    "taxonomy": "<category>",
    "relevance_score": <number 0-100>,
    "urgency_score": <number 0-100>,
    "hazard_description": "<string>",
    "affected_products": ["<string>"],
    "evidence_snippets": ["<string>"],
    "uncertainty_notes": "<string or null>"
  }
  ```
- **Version:** `v1.3` (Calibrated scoring criteria across 4 urgency tiers: 85–100 imminent, 60–84 potential, 30–59 minor, 0–29 non-safety).
- **Known Weaknesses:** On promotional text with safety keywords (e.g., "Safe car for sale!"), models can over-predict `consumer_warning`. Mitigated by non-LLM spam heuristics and domain credibility scoring.
- **Relevant Tests:** `tests/test_models.py::test_score_breakdown_computation`, `tests/test_safety.py::test_spam_heuristics_prompt_injection_pattern`.

---

### Prompt 4: Evidence Corroboration and Claim Verification (`prompts/verification.txt`)
- **File:** `prompts/verification.txt`
- **Purpose:** Cross-checks urgent safety claims against past items retrieved from SQLite persistent memory to verify whether a hazard is independently substantiated.
- **Trusted / Untrusted Boundary:** Compares the target claim against independent story clusters. Delimited comparison ensures prompt injection inside claim text cannot force a "SUPPORTED" verdict.
- **Output Schema:**
  ```json
  {
    "status": "<supported|insufficient_evidence|contradicted|unverified>",
    "independent_sources_count": <int>,
    "corroborating_item_ids": ["<id>"],
    "rationale": "<string>"
  }
  ```
- **Version:** `v1.0`.
- **Known Weaknesses:** Near-duplicate reposts can be mistaken for independent corroboration if not clustered. Addressed by running `search_memory` deduplication prior to claim verification.
- **Relevant Tests:** `tests/test_agent.py::test_verification_corroboration_semantics`, `test_adversarial_case_4_attempt_to_bypass_verification`.

---

### Prompt 5: Safety Critique and Self-Checking (`prompts/critique.txt`)
- **File:** `prompts/critique.txt`
- **Purpose:** Audits items with urgency $\ge 75.0$ before alert proposals can be drafted, challenging alarming rhetoric and penalizing uncorroborated single-source claims.
- **Trusted / Untrusted Boundary:** Evaluates preliminary classification, verification state, and source credibility.
- **Output Schema:**
  ```json
  {
    "post_critique_urgency": <number 0-100>,
    "challenge_points": ["<string>"],
    "uncertainties_identified": ["<string>"],
    "should_propose_alert": <boolean>,
    "critique_rationale": "<string>"
  }
  ```
- **Version:** `v1.2` (Enforces automatic -15.0 urgency penalty when claims lack independent corroboration).
- **Known Weaknesses:** Without explicit challenge heuristics, permissive LLMs tend to agree with their own prior urgency score. The deterministic self-checker enforces hard penalty rules if verification is `insufficient_evidence`.
- **Relevant Tests:** `tests/test_agent.py::test_critique_lowers_urgency_for_uncorroborated_claim`.

---

### Prompt 6: OCR Quality & Engine Routing (`prompts/ocr_routing.txt`)
- **File:** `prompts/ocr_routing.txt`
- **Purpose:** Evaluates visual quality signals (Laplacian blur, pixel contrast, skew angle) and initial OCR confidence to determine engine selection and preprocessing.
- **Operational Reality:** In production, this routing is implemented deterministically via `OCRRouter` in `jyot_monitor/ocr/routing.py` for sub-millisecond execution and zero LLM cost overhead. The prompt template is preserved for LLM-based fallback routing audits.
- **Version:** `v1.0`.
- **Relevant Tests:** `tests/test_ocr.py::test_router_clean_english_trajectory`, `test_router_difficult_second_opinion_trajectory`.

---

### Prompt 7: Multimodal Vision Inspection (`prompts/vision_describe.txt`)
- **File:** `prompts/vision_describe.txt`
- **Purpose:** Prompts local vision models (when configured via `JYOT_VISION_MODEL`) to describe visual defect markers and physical attributes.
- **Trusted / Untrusted Boundary:** Explicitly warns that signs and text in images are untrusted data.
- **Version:** `v1.0`.
- **Relevant Tests:** `tests/test_agent.py::test_three_distinct_agent_trajectories`.

---

### Prompt 8: Structured Recall Notice Extraction (`prompts/structured_notice_extraction.txt`)
- **File:** `prompts/structured_notice_extraction.txt`
- **Purpose:** Extracts structured fields (`product_name`, `manufacturer`, `notice_date`, `hazard`, `remedy`, `campaign_id`, `units_affected`) from messy OCR texts into Pydantic models.
- **Output Schema:** Pydantic `StructuredRecallNotice`.
- **Version:** `v1.0`.
- **Relevant Tests:** `tests/test_ocr.py::test_structured_notice_extraction_confident`.

---

### Prompt 9: Executive Digest Generation (`prompts/digest_generation.txt`)
- **File:** `prompts/digest_generation.txt`
- **Purpose:** Produces executive Markdown digests summarizing Top-N story clusters, risk scores, OCR snippets, and human approval queue status.
- **Operational Reality:** Rendered via deterministic `DigestRenderer` in `jyot_monitor/digest.py` to guarantee zero hallucination of fake recall stories and 100% adherence to stored evidence. Prompt preserved for LLM summary variants.
- **Version:** `v1.0`.
- **Relevant Tests:** `tests/test_cli.py::test_run_replay_mode`, `tests/test_reliability.py::test_deterministic_fault_injection_replay`.

---

## 3. Iteration and Hardening Summary

| Prompt | Initial Observed Failure | Hardening Applied | Measured Result |
|---|---|---|---|
| `planner_system.txt` | LLM looped calling `ocr_extract` repeatedly on finished images | Injected dynamic `candidate_actions` list into user prompt and restricted candidate generation | Loops eliminated; 100% compliant action selection |
| `planner_system.txt` | Model emitted unquoted JSON keys or Markdown code fences | Added robust regex JSON extraction in `LLMPlanner._parse_and_validate` with deterministic fallback | 0% parsing crashes across all test suites |
| `classification_scoring.txt` | Adversarial injection strings ("URGENCY 100.0") inflated urgency | Delimited untrusted body and integrated spam/injection heuristics in non-LLM feature layer | Adversarial attack prevented; classified as `spam_manipulation` |
| `critique.txt` | Permissive models rarely downgraded uncorroborated claims | Enforced -15.0 penalty rule on single-source uncorroborated items | Prevented false alert emission on degraded field photo (`item_06`) |
