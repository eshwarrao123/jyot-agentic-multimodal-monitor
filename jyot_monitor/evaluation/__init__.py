"""
Evaluation subsystem for jyot_monitor.
"""

from jyot_monitor.evaluation.ocr_eval import (
    OCREvaluator,
    compute_cer,
    compute_wer,
    normalize_text_for_eval,
    run_ocr_eval_and_save,
)

__all__ = [
    "OCREvaluator",
    "compute_cer",
    "compute_wer",
    "normalize_text_for_eval",
    "run_ocr_eval_and_save",
]
