# Technical Write-Up — Jyot Agentic Multimodal Monitor

**Track B (Extended), AI Generalist Assignment for Jyot**  
**Author:** [Your Name]  
**Date:** [YYYY-MM-DD]  
**Word Count:** [800-1,200 words]

---

## Instructions for Completing This Write-Up

This template guides the required 800-1,200 word write-up (Assignment Section 7, Deliverable 7). Complete all sections based on actual implementation and evaluation results. Do not fabricate performance claims or architectural decisions that were not implemented.

**Required topics (from assignment):**
1. Architecture overview
2. Agent design and why it beats (or does not beat) a fixed pipeline
3. OCR strategy and trade-offs
4. Injection threat model
5. Scaling plan (rate limits, spam, queueing, cost at 100x volume)
6. Known limitations
7. What you would do with another two weeks

**Style guidance:**
- Write for a technical audience familiar with ML systems
- Support claims with measurements from your evaluation report
- Be honest about what didn't work or couldn't be completed
- Use specific numbers: "CER improved from 0.15 to 0.09" not "OCR improved significantly"
- Acknowledge trade-offs and constraints

---

## 1. Architecture Overview (100-150 words)

[Describe the system architecture at a high level. Include:]
- Pipeline stages: ingestion → OCR → agent → scoring/dedup → digest/approval
- Key components: bounded planner/controller, tool registry, SQLite persistence, JSONL tracing
- Technology choices: Python 3.12+, Tesseract + EasyOCR, local Ollama LLM (or deterministic fallback)
- Why these choices (tight deadline, free/open-source requirement, reproducibility)
- Data flow: RSS feeds → fixture/live mode → item processing → clustered digest

**Template:**
> The system implements a bounded agentic pipeline for product-safety recall monitoring. Items from CPSC and FDA RSS feeds enter either live or replay mode, where a planner-driven agent decides which tools to invoke per item: fetch_attachment, ocr_extract (Tesseract or EasyOCR), vision_describe, search_memory, verify_claim, classify_score, critique_item, or propose_alert. A separate controller validates all actions against permission policies and budget constraints. SQLite provides persistent state and caching; JSONL traces enable reproducible walkthrough. The architecture prioritizes offline reproducibility (--replay mode) and safety boundaries over performance optimization.

---

## 2. Agent Design vs Fixed Pipeline (200-250 words)

[Compare your agent to the baseline. Include:]
- What the agent does differently: dynamic tool selection, adaptive OCR routing, conditional verification
- Ablation results: quality metrics (classification F1, dedup F1, urgency correlation) and cost/latency for both
- When the agent helps: examples of items where dynamic routing provided value (blurry image → second OCR, urgent claim → verification)
- When the agent doesn't help: examples where fixed pipeline is equivalent or better (plain text items, low-stakes content)
- Overall assessment: Is the agent worth the complexity? Under what conditions?

**Measurement template:**
> Ablation results on N=60 gold items: Agent achieved classification macro-F1 of X.XX vs baseline X.XX (±X.XX), deduplication F1 of X.XX vs X.XX (±X.XX), mean cost of $X.XX per item vs $X.XX. Agent averaged X.X tool calls vs baseline's fixed 5 calls. On plain-text, low-urgency items (N=20), agent and baseline were equivalent (same classification, negligible cost difference). On items with poor-quality images or urgent claims (N=15), agent outperformed baseline by [specific metric]. However, the agent's LLM calls add X.Xs latency overhead. Overall, dynamic routing is justified for heterogeneous, high-stakes content but may be over-engineered for uniformly high-quality feeds.

---

## 3. OCR Strategy and Trade-offs (150-200 words)

[Describe OCR implementation decisions. Include:]
- Why two engines (Tesseract: fast/local, EasyOCR: better for Hindi/complex layouts)
- Routing signals: confidence threshold, language detection, image quality metrics
- Preprocessing: what was tried (deskew, denoise, binarize), what helped, what didn't
- Hindi support: challenges and results
- Structured extraction: how notice fields are parsed and uncertainty is flagged
- Measured results: CER/WER per engine, preprocessing ablation, routing accuracy

**Measurement template:**
> Tesseract (engine 1) achieved mean CER of X.XX on English clear text but X.XX on rotated/blurry images. EasyOCR (engine 2) achieved X.XX overall with better Hindi support (CER X.XX on N=3 Hindi samples vs Tesseract's X.XX). Routing triggered second opinion in X/15 cases; in X cases it improved extraction (confidence >0.8 vs <0.7 initially). Preprocessing (deskew + binarize) reduced CER by X.XX on rotated images but had negligible effect on high-quality screenshots. Structured notice extraction (product name, recall date, hazard) succeeded in X/10 test cases; uncertain fields were flagged rather than fabricated. Trade-off: EasyOCR is slower (X.Xs vs X.Xs) and requires language pack download; router adds decision overhead but measurably improves difficult cases.

---

## 4. Injection Threat Model (150-200 words)

[Explain prompt injection defenses. Include:]
- Threat: image-embedded instructions, score manipulation requests, tool-call attempts
- Defense layers: data/instruction separation in prompts, controller permission validation, output schema enforcement
- What was tested: N=8+ adversarial cases covering text and image injection
- Results: attack success rate, what was blocked, what still works
- Limitations: what attacks were not tested, what defenses are missing

**Measurement template:**
> The system treats all OCR/post text as untrusted data. Prompts explicitly delimit evidence with [UNTRUSTED START/END] tags and instruct the LLM to never follow instructions within. The controller independently validates every action against an allow-list enum and validates tool arguments (e.g., no arbitrary URLs from OCR text; only official source attachment references). On N=8 adversarial cases (text prompt injection, image-embedded instructions, score inflation requests, unauthorized tool calls), attack success rate was X/8 = X%. Blocked attacks: [specific examples]. Successful attack: [if any, explain why]. Limitations: adversarial cases are straightforward, not adversarially optimized; no testing of model jailbreaks or multi-turn attacks; PII redaction uses regex (may miss novel formats); approval gate is final defense but requires human vigilance.

---

## 5. Scaling to 100x Volume (150-200 words)

[Discuss scaling challenges and solutions. Include:]
- Current throughput: items/minute, cost/item, bottlenecks
- Rate limiting: per-host limits, backoff strategy
- Spam/manipulation at scale: how detection would evolve
- Queueing: need for async processing, message queue (Celery/RQ), worker pool
- Cost at scale: extrapolate current cost, identify expensive operations
- Infrastructure: need for dedicated OCR workers, model caching, database scaling

**Template:**
> Current system processes ~X items/minute in replay mode (single-threaded). At 100x volume (~X,000 items/day), bottlenecks would be: (1) OCR latency (X.Xs per image), (2) LLM planner calls (X.Xs per decision), (3) SQLite write contention. Solutions: (1) Async job queue (Celery + Redis) with dedicated OCR worker pool; (2) Batch classification where dynamic routing is unnecessary; (3) PostgreSQL with connection pooling. Rate limiting becomes critical: implement per-source quotas and distributed rate-limit tracking (Redis). Spam detection needs clustering across time windows and cross-source coordination analysis (current approach is per-run only). Cost scales linearly with LLM calls; at 100x with $X.XX/item, expect $X/day. Mitigation: cache aggressively (content hashes), use smaller models for low-stakes items, implement tiered routing (quick classifier → full agent only for ambiguous cases).

---

## 6. Known Limitations (100-150 words)

[Be honest about what doesn't work or wasn't completed. Include:]
- Evaluation: sample sizes, synthetic data, lack of inter-rater agreement
- Coverage: untested scenarios, missing edge cases
- Performance: latency, cost inefficiency
- Safety: residual vulnerabilities, unmitigated risks
- Scope: features dropped due to time constraints

**Template:**
> (1) Small gold sets (N=15 OCR, N=60 classification) limit statistical confidence; most fixtures are synthetic. (2) Urgency scoring is uncalibrated (Spearman ρ=X.XX on N=60 but no extensive human agreement study). (3) Cross-modal deduplication misses paraphrases (only detects exact/near-exact matches). (4) Adversarial testing covers basic cases, not sophisticated attacks. (5) Vision model (vision_describe tool) is [stubbed/minimally implemented] due to time. (6) Local LLM fallback is deterministic rule-based, not intelligent. (7) Hindi evaluation is limited (N=3 samples). (8) No multi-page complex table extraction. (9) Cost tracking for local models is unavailable (marked null). (10) Performance not optimized (single-threaded, no caching on repeated fixture runs).

---

## 7. Next Steps with Two More Weeks (100-150 words)

[Describe improvements you would prioritize. Be realistic. Include:]
- Gold set expansion and quality improvement
- Unimplemented features (vision model integration, advanced preprocessing)
- Performance optimization (batching, caching, parallelization)
- Safety hardening (adversarial training, better PII detection)
- User experience (better digest formatting, approval UI)
- Evaluation rigor (inter-rater agreement, production A/B test)

**Template:**
> Priority 1: Expand gold sets to N=50+ OCR (with inter-rater agreement measurement), N=200+ classification (stratified by source and difficulty), and N=20+ adversarial cases (including jailbreak attempts). Priority 2: Integrate a vision model (e.g., LLaVA or GPT-4V) for chart/diagram/handwriting handling; measure impact on structured extraction. Priority 3: Optimize performance with async workers and batch classification; target <30s end-to-end latency for 10-item digest. Priority 4: Harden PII redaction with NER model (spaCy/Hugging Face) instead of regex. Priority 5: Improve digest UX with HTML template, severity color-coding, and expandable evidence. Priority 6: Test on real held-out feeds (e.g., Health Canada recalls) to validate generalization.

---

## Conclusion (50-100 words)

[Summarize key achievements and honest assessment.]

**Template:**
> This system demonstrates a bounded agentic approach to multimodal recall monitoring with measured safety boundaries and reproducible evaluation. The agent provides measurable value on heterogeneous, difficult content (dynamic OCR routing improved X cases, verification prevented X false alerts) but adds complexity and cost. Core requirements are met: replay mode, OCR routing, cross-modal dedup, prompt injection resistance, and honest evaluation. Key limitations are small sample sizes, uncalibrated urgency, and single-threaded performance. The architecture is production-ready for low-volume official feeds but requires queueing and worker scaling for high-throughput deployment.

---

## Writing Checklist

Before finalizing:
- [ ] Word count is 800-1,200 (use `wc -w WRITEUP.md`)
- [ ] All seven required topics covered
- [ ] Specific measurements cited from evaluation report
- [ ] No fabricated performance claims
- [ ] Honest about limitations and failures
- [ ] Trade-offs acknowledged (not just benefits)
- [ ] No "TODO" or placeholder values
- [ ] Proofread for clarity and technical accuracy

## Cross-Reference

This write-up satisfies:
- **REQ-DEL-007:** 800-1,200 word write-up deliverable
- **REQ-EVAL-WEIGHT-007:** Write-up and engineering judgment (10% weight)
- **Assignment Section 7, Deliverable 7:** All required topics listed above

See also:
- `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md` for requirement mapping
- `artifacts/eval/evaluation_report.md` for measurements to cite
- `docs/09_AGENT_WALKTHROUGH_TEMPLATE.md` for trajectory examples to reference
