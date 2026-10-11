# Evaluation Plan — Measure, Do Not Assert

## Evaluation principles
- Gold labels and transcription ground truth are created independently from the predicted outputs.
- Store the gold labels in files; do not generate predicted metrics from the same labels directly.
- Compute all report values from the actual run. Keep small-sample caveats visible.
- Use seeded synthetic fixtures where real public examples are difficult to curate in time; label them as synthetic and state that synthetic performance does not equal production performance.
- Never claim an attack is blocked merely because a prompt says it should be. Show the actual planner/tool decisions and test result.

## Gold set targets
### OCR set — minimum 15 pages/images
Include clear English, screenshot with UI chrome, low contrast, rotated/deskewable image, noisy/blurry image, a multi-page scanned PDF, and at least 3 Hindi samples. Each image/page needs exact ground-truth transcription authored and reviewed separately. Keep original and preprocessed paths/metadata so preprocessing can be ablated.

Metrics:
- Character error rate: `(substitutions + deletions + insertions) / number_of_ground_truth_characters`.
- Word error rate: `(word substitutions + deletions + insertions) / number_of_ground_truth_words`.
- Report per-engine and router results, plus preprocess-on vs preprocess-off. Report engine errors/timeouts separately rather than silently dropping hard cases.

### Classification and urgency — minimum 60 items, 25+ image cases
Use a documented taxonomy such as `recall`, `safety_alert`, `medical_product_alert`, `non_safety`, `spam_or_manipulation`, `uncertain`. Label relevance and ordinal urgency separately. Include hard negatives and adversarial items. Use fixed train/development versus test split where tuning occurs; with a small gold set, clearly note uncertainty.

Report per-class precision/recall/F1, macro-F1, confusion matrix, urgency Spearman rank correlation or weighted agreement, threshold precision/recall and qualitative calibration notes. An unscorable item remains a result; do not remove difficult cases without explanation.

### Deduplication
At least 10 known duplicate groups, including text/text reposts, image/image duplicates and text/screenshot cross-modal duplicates. Include difficult non-duplicates from the same product/topic. Report pairwise precision/recall/F1, cluster purity or an equivalent summary, and examples of false merges and missed duplicates.

### Safety
At least 8 labelled adversarial cases covering direct text prompt injection, OCR-visible instruction in an image, instructions to inflate urgency, tool-call attempts, PII in image/text, spam/repetition and hostile or unsafe URLs. Define success as the attempted instruction causing an unauthorized action or scoring/alert manipulation. Report attack success rate and blocked/partial/failed outcomes with trace IDs. Do not use the word “immune.”

### Agent and baseline ablation
Run the same gold set through:
1. Agent controller with its allowed dynamic next-tool choices.
2. Fixed baseline pipeline using a fixed sequence (e.g., fetch/parse, OCR attachments, classify/score, deduplicate, render digest).

Compare quality metrics (class/urgency/dedup/OCR as relevant), mean steps/tool calls, latency, failures/fallbacks and estimated cost per item/run. Do not claim the agent is superior if results do not support it. Explain what dynamic routing costs and when it helps.

## Fault-injection matrix
At minimum simulate deterministic cases for: HTTP 429 with Retry-After, HTTP 500, corrupted image, malformed/multi-page PDF error, OCR engine crash, invalid LLM JSON/schema, planner timeout, item budget exhaustion and process restart after partial completion. Verify the run continues where safe and persistent state avoids duplicate work.

## Report artifact
`artifacts/eval/evaluation_report.md` should have tables for OCR, classification, urgency, dedup, safety, agent-vs-baseline, costs/latency, plus failure examples and limitations. Include item counts and test-set construction method beside every metric.

## Report structure and required sections
```markdown
# Evaluation Report — Jyot Agentic Multimodal Monitor
**Track B (Extended), AI Generalist Assignment for Jyot**  
**Date:** YYYY-MM-DD  
**Gold Set Construction:** [Synthetic|Curated|Mixed]

## Executive Summary
- Total gold items evaluated: N
- Evaluation mode: [replay with local models|replay with fallback|mixed]
- Key findings: [2-3 bullet summary]
- Known limitations: [Sample size, synthetic data, etc.]

## 1. OCR Performance

### 1.1 Test Set Composition
- Total images/pages: N (minimum 15)
- Clear text: N
- Difficult cases: N (blurry, rotated, low-contrast)
- Hindi cases: N (minimum 3)
- Multi-page PDF: Y/N

### 1.2 Character Error Rate (CER)
| Engine/Config | CER (mean) | CER (median) | CER (95th %ile) | Failures |
|---|---:|---:|---:|---:|
| Tesseract (original) | X.XX | X.XX | X.XX | N |
| Tesseract (preprocessed) | X.XX | X.XX | X.XX | N |
| EasyOCR (original) | X.XX | X.XX | X.XX | N |
| Routed system | X.XX | X.XX | X.XX | N |

### 1.3 Word Error Rate (WER)
| Engine/Config | WER (mean) | WER (median) | WER (95th %ile) | Failures |
|---|---:|---:|---:|---:|
| [Same structure as CER] | ... | ... | ... | ... |

### 1.4 Preprocessing Ablation
**Finding:** [Preprocessing helped/did not help/mixed results]  
**Evidence:** [Comparison on N images]

### 1.5 Routing Decisions
- Engine 1 selected: N cases
- Engine 2 (second opinion) triggered: N cases
- Routing signals: [List actual signals that triggered routing]

### 1.6 Hindi Performance
- Hindi CER: X.XX (N samples)
- Observations: [Script recognition, mixed Hindi/English handling]

## 2. Classification Performance

### 2.1 Test Set Composition
- Total items: N (minimum 60)
- Items with image content: N (minimum 25)
- Class distribution: [Table of class counts]

### 2.2 Per-Class Metrics
| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| recall | X.XX | X.XX | X.XX | N |
| safety_alert | X.XX | X.XX | X.XX | N |
| medical_product_alert | X.XX | X.XX | X.XX | N |
| non_safety | X.XX | X.XX | X.XX | N |
| spam_or_manipulation | X.XX | X.XX | X.XX | N |
| uncertain | X.XX | X.XX | X.XX | N |
| **Macro-F1** | — | — | **X.XX** | **N** |

### 2.3 Confusion Matrix
[ASCII or Markdown table showing predicted vs actual]

### 2.4 Failure Analysis
- Most common misclassification: [class A → class B, N cases]
- Root cause hypothesis: [Explanation]

## 3. Urgency Scoring

### 3.1 Rank Correlation
- Spearman ρ: X.XX (p < 0.05 or n.s.)
- Interpretation: [Agreement level with human labels]

### 3.2 Threshold Analysis
| Threshold | Precision | Recall | F1 |
|---:|---:|---:|---:|
| 75 (critique trigger) | X.XX | X.XX | X.XX |
| 85 (alert trigger) | X.XX | X.XX | X.XX |

### 3.3 Calibration Assessment
**Finding:** [Uncalibrated/moderately calibrated/well-calibrated]  
**Evidence:** [Qualitative or quantitative assessment]  
**Caveat:** Small sample size (N=XX) limits calibration claims.

## 4. Deduplication Performance

### 4.1 Test Set Composition
- Known duplicate groups: N (minimum 10)
- Cross-modal groups (text + screenshot): N
- Hard negative pairs (similar but not duplicate): N

### 4.2 Pairwise Metrics
| Technique | Precision | Recall | F1 |
|---|---:|---:|---:|
| Exact hash | X.XX | X.XX | X.XX |
| MinHash + LSH | X.XX | X.XX | X.XX |
| Perceptual image hash | X.XX | X.XX | X.XX |
| Cross-modal (OCR text) | X.XX | X.XX | X.XX |
| **Combined system** | **X.XX** | **X.XX** | **X.XX** |

### 4.3 Clustering Quality
- Correctly merged groups: N / N
- False merges: N (examples below)
- Missed duplicates: N (examples below)

### 4.4 False Merge Examples
1. Item A (recall X) + Item B (recall Y) incorrectly clustered because [reason]
2. [Additional examples]

### 4.5 Missed Duplicate Examples
1. Item C and Item D are duplicates but not clustered because [reason]

## 5. Safety and Robustness

### 5.1 Adversarial Test Set
- Total adversarial cases: N (minimum 8)
- Text-based injection: N
- Image-embedded injection: N
- Score manipulation attempts: N
- Unauthorized tool call attempts: N

### 5.2 Attack Success Rate
**Success rate:** X / N = X.X% (target: 0%)

### 5.3 Attack Outcomes
| Attack Type | Blocked | Partial | Successful | Notes |
|---|---:|---:|---:|---|
| Text prompt injection | N | N | N | [Details] |
| Image-embedded instruction | N | N | N | [Details] |
| Score inflation request | N | N | N | [Details] |
| Unauthorized tool call | N | N | N | [Details] |

### 5.4 Successful Attacks (Failures)
1. **Attack ID XX:** [Description]  
   **Outcome:** [What unauthorized action occurred]  
   **Root cause:** [Analysis]  
   **Mitigation plan:** [If known]

### 5.5 PII Redaction
- Test cases: N
- Emails redacted: N / N
- Phone numbers redacted: N / N
- False positives: N
- False negatives: N

### 5.6 Network Safety
- Private IP blocks tested: N / N passed
- Invalid content-type rejections: N / N passed
- Redirect validation: N / N passed

## 6. Agent Behavior

### 6.1 Trajectory Statistics
| Metric | Mean | Median | 95th %ile | Max |
|---|---:|---:|---:|---:|
| Steps per item | X.XX | X | X | X |
| Tool calls per item | X.XX | X | X | X |
| Latency (seconds) | X.XX | X.XX | X.XX | X.XX |
| Cost (USD) per item | X.XX | X.XX | X.XX | X.XX |

### 6.2 Tool Usage Distribution
| Tool | Invocations | % of total |
|---|---:|---:|
| fetch_attachment | N | X% |
| ocr_extract | N | X% |
| vision_describe | N | X% |
| search_memory | N | X% |
| verify_claim | N | X% |
| classify_score | N | X% |
| critique_item | N | X% |
| propose_alert | N | X% |

### 6.3 Fallback and Failure Rate
- Items completed successfully: N / N (X%)
- Items with partial results: N / N (X%)
- Items with fallback planner: N / N (X%)
- Budget exhaustion: N / N (X%)
- Other failures: N / N (X%)

## 7. Ablation: Agent vs Fixed Pipeline

### 7.1 Configuration
**Agent:** Dynamic tool selection with bounded planner  
**Baseline:** Fixed sequence: fetch → OCR all attachments → classify → deduplicate → score → digest

### 7.2 Quality Comparison
| Metric | Agent | Baseline | Difference |
|---|---:|---:|---:|
| Classification Macro-F1 | X.XX | X.XX | ±X.XX |
| Dedup Pairwise F1 | X.XX | X.XX | ±X.XX |
| Urgency Spearman ρ | X.XX | X.XX | ±X.XX |

### 7.3 Efficiency Comparison
| Metric | Agent | Baseline | Difference |
|---|---:|---:|---:|
| Mean steps | X.XX | X.XX (fixed) | — |
| Mean tool calls | X.XX | X.XX | ±X.XX |
| Mean latency (s) | X.XX | X.XX | ±X.XX |
| Mean cost (USD) | X.XX | X.XX | ±X.XX |
| Total cost (USD) | X.XX | X.XX | ±X.XX |

### 7.4 Analysis
**When agent helps:** [Situations where dynamic routing provides benefit]  
**When agent doesn't help:** [Situations where fixed pipeline is equivalent or better]  
**Cost/benefit trade-off:** [Overall assessment]

## 8. Fault Injection Results

### 8.1 Injected Faults
- HTTP 429 (rate limit): [Outcome]
- HTTP 500 (server error): [Outcome]
- Corrupted image: [Outcome]
- Malformed PDF: [Outcome]
- OCR engine crash: [Outcome]
- Invalid LLM JSON: [Outcome]
- Timeout: [Outcome]
- Budget exhaustion: [Outcome]

### 8.2 Recovery Behavior
- Graceful degradation: [Y/N, details]
- Run continuation: [Y/N, details]
- Idempotent restart: [Y/N, details]

## 9. Known Limitations

1. **Sample size:** [Statement about gold set sizes and statistical power]
2. **Synthetic data:** [% synthetic, implications for generalization]
3. **Model choice:** [Local vs commercial, calibration limitations]
4. **Coverage gaps:** [Untested scenarios, edge cases]
5. **Evaluation methodology:** [Manual labeling, inter-rater agreement not measured]
6. **Attack sophistication:** [Adversarial cases are straightforward, not adversarially optimized]
7. **Cross-modal deduplication:** [Limited to exact+similar cases, may miss paraphrases]
8. **Urgency calibration:** [No extensive human agreement study]
9. **Source coverage:** [Limited to two official feeds, not representative of all recall sources]
10. **Time constraints:** [4-day deadline limited gold set quality and size]

## 10. Conclusion

[2-3 paragraph summary of evaluation results, honest assessment of strengths and weaknesses, and confidence in meeting assignment requirements]
```

## Metrics computation implementation notes
- **CER/WER:** Use python-Levenshtein or similar; normalize ground truth and predictions (lowercase, strip punctuation for WER)
- **Classification metrics:** Use `sklearn.metrics.classification_report`, `confusion_matrix`
- **Rank correlation:** Use `scipy.stats.spearmanr`
- **Pairwise dedup:** Generate all pairs from gold groups; compute TP, FP, FN
- **Attack success:** Binary per case (0 = blocked, 1 = successful manipulation)

## Honest reporting requirements
- Report actual computed values, not placeholders
- Include "N/A" or "not measured" when data unavailable
- Document when preprocessing did not help
- Show failure examples, not just successes
- State small-sample caveats prominently
- Do not claim robustness without testing

## Requirements traceability
See `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md`:
- REQ-EVAL-001 through REQ-EVAL-011: All evaluation requirements with minimum gold set sizes and required metrics
- REQ-DEL-006: Evaluation report deliverable with complete metric tables
