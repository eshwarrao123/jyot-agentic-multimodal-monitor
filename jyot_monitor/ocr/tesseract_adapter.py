"""
Tesseract OCR engine adapter using pytesseract.

Provides validated OCR extraction, binary location discovery,
word-level confidence aggregation, and structured error handling.
"""

import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image

import pytesseract

from jyot_monitor.models import OCRResult
from jyot_monitor.ocr.preprocessing import preprocess_image, to_pil_image
from jyot_monitor.ocr.quality import assess_image_quality


class TesseractNotFoundError(FileNotFoundError):
    """Raised when tesseract binary cannot be located on the host."""
    pass


class TesseractExecutionError(RuntimeError):
    """Raised when tesseract fails during execution."""
    pass


def find_tesseract_cmd() -> Optional[str]:
    """
    Locate tesseract executable across common Windows paths and system PATH.
    """
    env_path = os.environ.get("TESSERACT_CMD")
    if env_path and os.path.isfile(env_path):
        return env_path
        
    which_cmd = shutil.which("tesseract")
    if which_cmd:
        return which_cmd

    candidate_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for p in candidate_paths:
        if os.path.isfile(p):
            return p
    return None


def get_tesseract_version(tesseract_cmd: Optional[str] = None) -> Optional[str]:
    """Retrieve Tesseract version string if binary is present."""
    cmd = tesseract_cmd or find_tesseract_cmd()
    if not cmd:
        return None
    try:
        pytesseract.pytesseract.tesseract_cmd = cmd
        v = pytesseract.get_tesseract_version()
        return str(v)
    except Exception:
        return None


def run_tesseract_ocr(
    image_input: Union[Image.Image, str, Path],
    lang: str = "eng",
    apply_preprocessing: bool = False,
    preprocessing_profile: str = "adaptive_full",
    confidence_threshold: float = 0.7,
    item_id: Optional[str] = None,
    attachment_id: Optional[str] = None,
    tesseract_cmd: Optional[str] = None,
) -> OCRResult:
    """
    Execute OCR using Tesseract and return a validated OCRResult.
    
    Confidence semantics:
    - Raw: Mean word confidence from image_to_data (0-100 range).
    - Normalized: raw / 100.0 (0.0-1.0 range).
    - Limitations: Represents character distances from font prototypes, not calibrated probabilities.
    """
    cmd = tesseract_cmd or find_tesseract_cmd()
    if not cmd or not os.path.isfile(cmd):
        raise TesseractNotFoundError(
            "Tesseract OCR executable not found. Install Tesseract (e.g. winget install UB-Mannheim.TesseractOCR) "
            "or set TESSERACT_CMD environment variable."
        )
    
    pytesseract.pytesseract.tesseract_cmd = cmd
    engine_ver = get_tesseract_version(cmd)

    try:
        pil_img = to_pil_image(image_input)
    except Exception as e:
        return OCRResult(
            item_id=item_id,
            attachment_id=attachment_id,
            engine="tesseract",
            engine_version=engine_ver,
            text="",
            raw_confidence=0.0,
            normalized_confidence=0.0,
            confidence_semantics="Tesseract image load failed; confidence 0.0",
            language=lang,
            needs_second_opinion=True,
            second_opinion_reason=f"Failed to load image: {e}",
            errors=[f"ImageLoadError: {e}"],
        )

    # Compute quality signals on original image
    quality_signals = assess_image_quality(pil_img)
    img_dim = (quality_signals["width"], quality_signals["height"])
    
    applied_ops: List[str] = []
    processed_img = pil_img
    if apply_preprocessing:
        processed_img, applied_ops = preprocess_image(pil_img, profile=preprocessing_profile)

    warnings: List[str] = []
    errors: List[str] = []

    try:
        # Extract word data with confidence
        data = pytesseract.image_to_data(
            processed_img,
            lang=lang,
            output_type=pytesseract.Output.DICT
        )
        confidences = []
        words = []
        for i, conf_str in enumerate(data.get("conf", [])):
            try:
                c = float(conf_str)
                w = data["text"][i].strip()
                if c >= 0 and w:
                    confidences.append(c)
                    words.append(w)
            except (ValueError, TypeError):
                continue
                
        extracted_text = " ".join(words)
        # If words list is empty, also try image_to_string directly
        if not extracted_text:
            direct_text = pytesseract.image_to_string(processed_img, lang=lang).strip()
            if direct_text:
                extracted_text = direct_text

        if confidences:
            raw_conf = float(round(sum(confidences) / len(confidences), 2))
            norm_conf = float(round(raw_conf / 100.0, 4))
        else:
            raw_conf = 0.0
            norm_conf = 0.0

    except pytesseract.TesseractError as te:
        errors.append(f"TesseractExecutionError: {te}")
        extracted_text = ""
        raw_conf = 0.0
        norm_conf = 0.0
    except Exception as e:
        errors.append(f"UnexpectedError: {e}")
        extracted_text = ""
        raw_conf = 0.0
        norm_conf = 0.0

    # Decision on second opinion
    needs_second = False
    second_reason = None
    if errors:
        needs_second = True
        second_reason = f"Engine error: {'; '.join(errors)}"
    elif not extracted_text:
        needs_second = True
        second_reason = "No text extracted by Tesseract"
    elif norm_conf < confidence_threshold:
        needs_second = True
        second_reason = f"Normalized confidence ({norm_conf:.2f}) below threshold ({confidence_threshold:.2f})"
    elif quality_signals.get("is_blurry") or quality_signals.get("is_low_contrast"):
        needs_second = True
        second_reason = "Visual degradation signals detected (blur/low contrast)"

    confidence_semantics = (
        "Mean word-level confidence reported by Tesseract (0-100 scale), normalized to 0.0-1.0. "
        "Represents character distance from prototype shapes, not a calibrated posterior probability."
    )

    return OCRResult(
        item_id=item_id,
        attachment_id=attachment_id,
        engine="tesseract",
        engine_version=engine_ver,
        text=extracted_text,
        raw_confidence=raw_conf,
        normalized_confidence=norm_conf,
        confidence_semantics=confidence_semantics,
        language=lang,
        image_dimensions=img_dim,
        quality_signals=quality_signals,
        preprocessing_applied=apply_preprocessing,
        preprocessing_operations=applied_ops,
        preprocessing=preprocessing_profile if apply_preprocessing else None,
        needs_second_opinion=needs_second,
        second_opinion_reason=second_reason,
        errors=errors,
        warnings=warnings,
        metadata={
            "tesseract_cmd": cmd,
            "word_count": len(extracted_text.split()) if extracted_text else 0,
        }
    )
