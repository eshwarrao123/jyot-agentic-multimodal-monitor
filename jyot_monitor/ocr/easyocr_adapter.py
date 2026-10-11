"""
EasyOCR engine adapter with lazy initialization, language caching,
and structured confidence/error reporting.
"""

from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
from PIL import Image

from jyot_monitor.models import OCRResult
from jyot_monitor.ocr.preprocessing import preprocess_image, to_pil_image
from jyot_monitor.ocr.quality import assess_image_quality

# Global reader cache keyed by languages tuple
_READER_CACHE: Dict[Tuple[str, ...], Any] = {}
_READER_LOCK = threading.Lock()


class EasyOCRNotAvailableError(ImportError):
    """Raised when EasyOCR cannot be imported or initialized."""
    pass


class EasyOCRExecutionError(RuntimeError):
    """Raised when EasyOCR fails during text extraction."""
    pass


def get_easyocr_reader(languages: List[str], gpu: bool = False) -> Any:
    """
    Get or lazily initialize an EasyOCR Reader instance.
    Uses cached instances to avoid reloading multi-hundred-MB PyTorch weights.
    """
    key = tuple(sorted(languages))
    with _READER_LOCK:
        if key not in _READER_CACHE:
            try:
                import sys
                _curr_ver = f"python{sys.version_info.major}{sys.version_info.minor}"
                sys.path = [p for p in sys.path if not ("python3" in p.lower() and _curr_ver not in p.lower())]
                import easyocr
            except ImportError as ie:
                raise EasyOCRNotAvailableError(
                    f"EasyOCR is not installed or available: {ie}"
                ) from ie
            
            try:
                reader = easyocr.Reader(languages, gpu=gpu, verbose=False)
                _READER_CACHE[key] = reader
            except Exception as e:
                raise EasyOCRExecutionError(
                    f"Failed to initialize EasyOCR reader for languages {languages}: {e}"
                ) from e
        return _READER_CACHE[key]


def run_easyocr_ocr(
    image_input: Union[Image.Image, str, Path],
    languages: Optional[List[str]] = None,
    apply_preprocessing: bool = False,
    preprocessing_profile: str = "adaptive_full",
    confidence_threshold: float = 0.7,
    item_id: Optional[str] = None,
    attachment_id: Optional[str] = None,
    gpu: bool = False,
) -> OCRResult:
    """
    Execute OCR using EasyOCR and return a validated OCRResult.
    
    Confidence semantics:
    - Raw: Mean recognition confidence (0.0-1.0) reported across detected bounding boxes.
    - Normalized: Same as raw (0.0-1.0).
    - Limitations: Represents recognizer CTC beam confidence; uncalibrated.
    """
    if languages is None:
        languages = ["en"]

    lang_str = "+".join(languages)

    try:
        pil_img = to_pil_image(image_input)
    except Exception as e:
        return OCRResult(
            item_id=item_id,
            attachment_id=attachment_id,
            engine="easyocr",
            engine_version="1.7.2",
            text="",
            raw_confidence=0.0,
            normalized_confidence=0.0,
            confidence_semantics="EasyOCR image load failed; confidence 0.0",
            language=lang_str,
            needs_second_opinion=True,
            second_opinion_reason=f"Failed to load image: {e}",
            errors=[f"ImageLoadError: {e}"],
        )

    quality_signals = assess_image_quality(pil_img)
    img_dim = (quality_signals["width"], quality_signals["height"])

    applied_ops: List[str] = []
    processed_img = pil_img
    if apply_preprocessing:
        processed_img, applied_ops = preprocess_image(pil_img, profile=preprocessing_profile)

    errors: List[str] = []
    warnings: List[str] = []

    try:
        reader = get_easyocr_reader(languages, gpu=gpu)
        np_img = np.array(processed_img)
        # readtext returns [(bbox, text, prob), ...]
        detections = reader.readtext(np_img)

        text_pieces = []
        confidences = []
        for det in detections:
            if len(det) >= 3:
                text = str(det[1]).strip()
                prob = float(det[2])
                if text:
                    text_pieces.append(text)
                    confidences.append(prob)

        extracted_text = " ".join(text_pieces)
        if confidences:
            raw_conf = float(round(sum(confidences) / len(confidences), 4))
            norm_conf = float(round(raw_conf, 4))
        else:
            raw_conf = 0.0
            norm_conf = 0.0

    except EasyOCRNotAvailableError as ena:
        errors.append(f"EasyOCRNotAvailableError: {ena}")
        extracted_text = ""
        raw_conf = 0.0
        norm_conf = 0.0
    except Exception as e:
        errors.append(f"EasyOCRExecutionError: {e}")
        extracted_text = ""
        raw_conf = 0.0
        norm_conf = 0.0

    needs_second = False
    second_reason = None
    if errors:
        needs_second = True
        second_reason = f"Engine error: {'; '.join(errors)}"
    elif not extracted_text:
        needs_second = True
        second_reason = "No text extracted by EasyOCR"
    elif norm_conf < confidence_threshold:
        needs_second = True
        second_reason = f"Normalized confidence ({norm_conf:.2f}) below threshold ({confidence_threshold:.2f})"

    confidence_semantics = (
        "Mean detection confidence reported by EasyOCR CRNN recognizer (0.0-1.0 scale). "
        "Reflects recognizer softmax confidence along CTC beam search paths; uncalibrated."
    )

    return OCRResult(
        item_id=item_id,
        attachment_id=attachment_id,
        engine="easyocr",
        engine_version="1.7.2",
        text=extracted_text,
        raw_confidence=raw_conf,
        normalized_confidence=norm_conf,
        confidence_semantics=confidence_semantics,
        language=lang_str,
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
            "detection_count": len(confidences) if 'confidences' in locals() else 0,
            "languages": languages,
        }
    )
