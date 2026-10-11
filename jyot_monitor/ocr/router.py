"""
Explicit deterministic OCR router and trajectory manager.

Routes items based on measurable signals:
- Language hints (Devanagari / Hindi triggers EasyOCR with ['hi', 'en'])
- Image quality metrics (resolution, blur score, contrast score)
- Engine 1 confidence and emptiness checks
- Conservative second-opinion policy
"""

from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union
from PIL import Image

from jyot_monitor.models import OCRResult, RoutedOCRResult
from jyot_monitor.ocr.easyocr_adapter import run_easyocr_ocr
from jyot_monitor.ocr.preprocessing import to_pil_image
from jyot_monitor.ocr.quality import assess_image_quality
from jyot_monitor.ocr.tesseract_adapter import run_tesseract_ocr


# Devanagari Unicode range: \u0900-\u097F
DEVANAGARI_REGEX = re.compile(r"[\u0900-\u097F]")


def contains_devanagari(text: str) -> bool:
    """Check if string contains any Devanagari script characters."""
    return bool(DEVANAGARI_REGEX.search(text))


class OCRRouter:
    """
    Deterministic multi-engine OCR router.
    
    Signals evaluated:
    - language_hint: requested or prior language ('en', 'hi', etc.)
    - quality_signals: blur_score, contrast_score, min_dimension, skew_angle
    - initial_confidence: normalized confidence of first engine
    """

    def __init__(
        self,
        confidence_threshold: float = 0.70,
        blur_threshold: float = 100.0,
        contrast_threshold: float = 35.0,
    ):
        self.confidence_threshold = confidence_threshold
        self.blur_threshold = blur_threshold
        self.contrast_threshold = contrast_threshold

    def route_and_extract(
        self,
        image_input: Union[Image.Image, str, Path],
        language_hint: str = "en",
        item_id: Optional[str] = None,
        attachment_id: Optional[str] = None,
    ) -> RoutedOCRResult:
        """
        Execute deterministic routing pipeline and return a RoutedOCRResult.
        
        Demonstrates three distinct trajectories:
        1. 'clean_english_direct': High quality, clean English -> direct Tesseract.
        2. 'difficult_low_confidence_second_opinion': Visual degradation or low confidence ->
           preprocessing + EasyOCR second opinion.
        3. 'hindi_specialized_engine': Hindi text / language hint -> EasyOCR with ['hi', 'en'].
        """
        pil_img = to_pil_image(image_input)
        quality_signals = assess_image_quality(pil_img)
        
        # Signal 1: Hindi language hint
        is_hindi = language_hint in ("hi", "hindi") or language_hint.startswith("hi")
        
        routing_signals = {
            "language_hint": language_hint,
            "is_hindi_hint": is_hindi,
            "width": quality_signals["width"],
            "height": quality_signals["height"],
            "min_dimension": quality_signals["min_dimension"],
            "blur_score": quality_signals["blur_score"],
            "contrast_score": quality_signals["contrast_score"],
            "is_blurry": quality_signals.get("is_blurry", False),
            "is_low_contrast": quality_signals.get("is_low_contrast", False),
            "is_skewed": quality_signals.get("is_skewed", False),
            "is_low_resolution": quality_signals.get("is_low_resolution", False),
        }

        # Trajectory 3: Hindi specialized engine
        if is_hindi:
            rationale = "Hindi script/language detected; routing directly to EasyOCR with ['hi', 'en']."
            trajectory = "hindi_specialized_engine"
            
            # Apply adaptive preprocessing if degraded
            needs_prep = routing_signals["is_blurry"] or routing_signals["is_low_contrast"] or routing_signals["is_skewed"]
            result = run_easyocr_ocr(
                pil_img,
                languages=["hi", "en"],
                apply_preprocessing=needs_prep,
                preprocessing_profile="adaptive_full" if needs_prep else "original",
                confidence_threshold=self.confidence_threshold,
                item_id=item_id,
                attachment_id=attachment_id,
            )
            return RoutedOCRResult(
                selected_engine="easyocr",
                initial_result=result,
                second_opinion_result=None,
                final_result=result,
                routing_signals=routing_signals,
                decision_rationale=rationale,
                trajectory_name=trajectory,
            )

        # For English / general: Engine 1 is Tesseract
        # If visually degraded, apply preprocessing on initial pass
        has_degradation = (
            routing_signals["is_blurry"] or
            routing_signals["is_low_contrast"] or
            routing_signals["is_skewed"] or
            routing_signals["is_low_resolution"]
        )

        initial_result = run_tesseract_ocr(
            pil_img,
            lang="eng",
            apply_preprocessing=has_degradation,
            preprocessing_profile="adaptive_full" if has_degradation else "original",
            confidence_threshold=self.confidence_threshold,
            item_id=item_id,
            attachment_id=attachment_id,
        )

        # Check if initial result is clean and confident
        is_clean_english = (
            not has_degradation and
            initial_result.normalized_confidence >= self.confidence_threshold and
            bool(initial_result.text.strip()) and
            not initial_result.errors
        )

        # Trajectory 1: Clean English direct
        if is_clean_english:
            rationale = (
                f"Clean English input with high confidence ({initial_result.normalized_confidence:.2f} >= "
                f"{self.confidence_threshold:.2f}); accepted Tesseract result directly without second opinion."
            )
            trajectory = "clean_english_direct"
            return RoutedOCRResult(
                selected_engine="tesseract",
                initial_result=initial_result,
                second_opinion_result=None,
                final_result=initial_result,
                routing_signals=routing_signals,
                decision_rationale=rationale,
                trajectory_name=trajectory,
            )

        # Trajectory 2: Difficult / low-confidence second opinion
        second_opinion_reasons = []
        if has_degradation:
            second_opinion_reasons.append("visual degradation detected")
        if initial_result.normalized_confidence < self.confidence_threshold:
            second_opinion_reasons.append(
                f"low confidence ({initial_result.normalized_confidence:.2f} < {self.confidence_threshold:.2f})"
            )
        if not initial_result.text.strip():
            second_opinion_reasons.append("empty text output from Tesseract")
        if initial_result.errors:
            second_opinion_reasons.append(f"Tesseract errors: {'; '.join(initial_result.errors)}")

        reason_str = ", ".join(second_opinion_reasons) or "uncertainty check"
        rationale = f"Triggered EasyOCR second opinion due to: {reason_str}."
        trajectory = "difficult_low_confidence_second_opinion"

        second_result = run_easyocr_ocr(
            pil_img,
            languages=["en"],
            apply_preprocessing=True,
            preprocessing_profile="adaptive_full",
            confidence_threshold=self.confidence_threshold,
            item_id=item_id,
            attachment_id=attachment_id,
        )

        # Select best result conservatively
        # Prefer result with higher normalized confidence and non-empty text
        if not initial_result.text.strip() and second_result.text.strip():
            final_result = second_result
            rationale += " Selected EasyOCR because Tesseract yielded empty text."
        elif second_result.normalized_confidence > initial_result.normalized_confidence:
            final_result = second_result
            rationale += f" Selected EasyOCR due to higher confidence ({second_result.normalized_confidence:.2f} vs {initial_result.normalized_confidence:.2f})."
        else:
            final_result = initial_result
            rationale += f" Retained Tesseract result ({initial_result.normalized_confidence:.2f} >= {second_result.normalized_confidence:.2f})."

        return RoutedOCRResult(
            selected_engine="tesseract",
            initial_result=initial_result,
            second_opinion_result=second_result,
            final_result=final_result,
            routing_signals=routing_signals,
            decision_rationale=rationale,
            trajectory_name=trajectory,
        )
