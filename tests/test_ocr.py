"""
Automated test suite for Phase 2 OCR subsystem.

Tests cover:
- Tesseract adapter contract and confidence semantics
- EasyOCR adapter contract and Hindi/English support
- Image quality signals extraction
- Preprocessing operations and profiles
- Router deterministic decisions across 3 trajectories
- Multi-page scanned PDF rendering and provenance
- Malformed and oversized PDF handling
- Missing binary and error handling
- Structured notice extraction and uncertain field flags
- CER / WER metrics and Unicode normalisation
"""

import io
from pathlib import Path
import tempfile
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from jyot_monitor.evaluation.ocr_eval import (
    compute_cer,
    compute_wer,
    levenshtein_distance,
    normalize_text_for_eval,
)
from jyot_monitor.models import OCRResult, ProductSafetyNotice, RoutedOCRResult
from jyot_monitor.ocr.easyocr_adapter import (
    EasyOCRNotAvailableError,
    get_easyocr_reader,
    run_easyocr_ocr,
)
from jyot_monitor.ocr.pdf_rendering import (
    PDFCorruptError,
    PDFTooLargeError,
    PDFTooManyPagesError,
    render_pdf_pages,
    validate_pdf_file,
)
from jyot_monitor.ocr.preprocessing import (
    binarize_otsu,
    deskew_image,
    enhance_contrast_clahe,
    preprocess_image,
    upscale_if_low_resolution,
)
from jyot_monitor.ocr.quality import assess_image_quality, estimate_skew_angle
from jyot_monitor.ocr.router import OCRRouter, contains_devanagari
from jyot_monitor.ocr.structured_extraction import extract_safety_notice
from jyot_monitor.ocr.tesseract_adapter import (
    TesseractNotFoundError,
    find_tesseract_cmd,
    run_tesseract_ocr,
)


@pytest.fixture
def clean_english_image() -> Image.Image:
    """Create a high-contrast clean English image."""
    img = Image.new("RGB", (700, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    font = None
    if Path(r"C:\Windows\Fonts\arial.ttf").is_file():
        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 32)
        except Exception:
            pass
    draw.text((30, 70), "RECALL NOTICE: MODEL 100", fill=(0, 0, 0), font=font)
    return img


@pytest.fixture
def hindi_text_image() -> Image.Image:
    """Create a Hindi text image using Windows Nirmala UI font if available."""
    img = Image.new("RGB", (500, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    font = None
    if Path(r"C:\Windows\Fonts\Nirmala.ttc").is_file():
        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\Nirmala.ttc", 28)
        except Exception:
            pass
    draw.text((20, 25), "खाद्य सुरक्षा सूचना", fill=(0, 0, 0), font=font)
    return img


# --- 1. Quality Signals Tests ---

def test_assess_image_quality(clean_english_image: Image.Image):
    signals = assess_image_quality(clean_english_image)
    assert signals["width"] == 700
    assert signals["height"] == 200
    assert signals["min_dimension"] == 200
    assert signals["is_low_resolution"] is False
    assert "blur_score" in signals
    assert "contrast_score" in signals
    assert "mean_brightness" in signals
    assert "estimated_skew_angle" in signals


def test_quality_signals_on_blurry_image():
    # Blurry image
    img = Image.new("RGB", (400, 100), color=(200, 200, 200))
    signals = assess_image_quality(img)
    # Uniform color has 0 blur variance and 0 contrast
    assert signals["blur_score"] < 5.0
    assert signals["is_blurry"] is True
    assert signals["contrast_score"] < 5.0
    assert signals["is_low_contrast"] is True


# --- 2. Preprocessing Tests ---

def test_preprocessing_original_profile(clean_english_image: Image.Image):
    out_img, ops = preprocess_image(clean_english_image, profile="original")
    assert ops == []
    assert out_img.size == clean_english_image.size


def test_preprocessing_clahe(clean_english_image: Image.Image):
    out_img, ops = preprocess_image(clean_english_image, profile="contrast_enhanced")
    assert "clahe_contrast" in ops
    assert out_img.size == clean_english_image.size


def test_preprocessing_binarization(clean_english_image: Image.Image):
    out_img, ops = preprocess_image(clean_english_image, profile="binarized")
    assert "otsu_binarization" in ops


def test_preprocessing_upscaling():
    small_img = Image.new("RGB", (200, 100), color=(255, 255, 255))
    out_img, ops = preprocess_image(small_img, profile="upscaled")
    assert "bicubic_upscale" in ops
    assert out_img.width > small_img.width
    assert out_img.height > small_img.height


def test_deskew_image_correction():
    # Create an image, rotate it by 10 degrees
    base = Image.new("RGB", (400, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(base)
    draw.rectangle([50, 40, 350, 60], fill=(0, 0, 0))
    rotated = base.rotate(10, expand=True, fillcolor=(255, 255, 255))
    cv_rot = np.array(rotated)
    corrected, angle = deskew_image(cv_rot)
    assert isinstance(corrected, np.ndarray)


# --- 3. Engine Adapter Tests ---

def test_tesseract_adapter_contract(clean_english_image: Image.Image):
    cmd = find_tesseract_cmd()
    if not cmd:
        pytest.skip("Tesseract executable not installed on this system")

    result = run_tesseract_ocr(
        clean_english_image,
        lang="eng",
        apply_preprocessing=False,
        item_id="test_tess_01",
    )
    assert isinstance(result, OCRResult)
    assert result.engine == "tesseract"
    assert result.item_id == "test_tess_01"
    assert result.engine_version is not None
    assert result.normalized_confidence is not None
    assert 0.0 <= result.normalized_confidence <= 1.0
    assert result.confidence_semantics is not None
    assert "prototype" in result.confidence_semantics
    assert result.image_dimensions == (700, 200)
    assert result.quality_signals is not None
    assert "RECALL" in result.text.upper() or "MODEL" in result.text.upper()


def test_tesseract_missing_binary_raises():
    with pytest.raises(TesseractNotFoundError):
        run_tesseract_ocr(
            Image.new("RGB", (100, 100)),
            tesseract_cmd=r"C:\nonexistent\path\to\tesseract.exe"
        )


def test_easyocr_adapter_contract(clean_english_image: Image.Image):
    result = run_easyocr_ocr(
        clean_english_image,
        languages=["en"],
        apply_preprocessing=False,
        item_id="test_easy_01",
    )
    assert isinstance(result, OCRResult)
    assert result.engine == "easyocr"
    assert result.item_id == "test_easy_01"
    assert result.engine_version == "1.7.2"
    assert result.normalized_confidence is not None
    assert 0.0 <= result.normalized_confidence <= 1.0
    assert result.confidence_semantics is not None
    assert "CTC" in result.confidence_semantics
    assert result.image_dimensions == (700, 200)
    assert "RECALL" in result.text.upper() or "MODEL" in result.text.upper()


def test_easyocr_hindi_support(hindi_text_image: Image.Image):
    result = run_easyocr_ocr(
        hindi_text_image,
        languages=["hi", "en"],
        item_id="test_hi_01",
    )
    assert isinstance(result, OCRResult)
    assert result.engine == "easyocr"
    assert "hi" in result.language
    assert result.normalized_confidence >= 0.0


# --- 4. Explicit Router Tests (3 Trajectories) ---

def test_router_clean_english_trajectory(clean_english_image: Image.Image):
    router = OCRRouter(confidence_threshold=0.5)
    res = router.route_and_extract(clean_english_image, language_hint="en")
    assert isinstance(res, RoutedOCRResult)
    assert res.trajectory_name == "clean_english_direct"
    assert res.selected_engine == "tesseract"
    assert res.second_opinion_result is None
    assert "clean" in res.decision_rationale.lower()


def test_router_difficult_second_opinion_trajectory():
    router = OCRRouter(confidence_threshold=0.7)
    # Degraded image: low contrast gray text on dark gray
    degraded = Image.new("RGB", (400, 100), color=(100, 100, 100))
    draw = ImageDraw.Draw(degraded)
    draw.text((20, 30), "BLURRY UNCERTAIN NOTICE", fill=(115, 115, 115))
    
    res = router.route_and_extract(degraded, language_hint="en")
    assert isinstance(res, RoutedOCRResult)
    assert res.trajectory_name == "difficult_low_confidence_second_opinion"
    assert res.second_opinion_result is not None
    assert res.routing_signals["is_low_contrast"] is True or res.initial_result.needs_second_opinion is True
    assert "second opinion" in res.decision_rationale.lower()


def test_router_hindi_trajectory(hindi_text_image: Image.Image):
    router = OCRRouter()
    res = router.route_and_extract(hindi_text_image, language_hint="hi")
    assert isinstance(res, RoutedOCRResult)
    assert res.trajectory_name == "hindi_specialized_engine"
    assert res.selected_engine == "easyocr"
    assert "Hindi" in res.decision_rationale


# --- 5. PDF Rendering and Validation Tests ---

def test_pdf_rendering_multipage():
    pdf_path = Path("fixtures/gold/pdfs/sample_recall_notice_scanned.pdf")
    if not pdf_path.is_file():
        pytest.skip("Gold PDF fixture not generated yet")

    pages = render_pdf_pages(pdf_path, dpi=200)
    assert len(pages) == 3
    for p in pages:
        assert p.page_number in (1, 2, 3)
        assert p.dpi == 200
        assert p.width > 0
        assert p.height > 0
        assert len(p.page_hash) == 64  # SHA-256


def test_pdf_validation_oversized(tmp_path: Path):
    dummy_pdf = tmp_path / "oversized.pdf"
    # Create 2KB file and test with 1KB limit
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy bytes" * 200)
    with pytest.raises(PDFTooLargeError):
        validate_pdf_file(dummy_pdf, max_bytes=500)


def test_pdf_validation_corrupt(tmp_path: Path):
    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_text("NOT A REAL PDF FILE")
    with pytest.raises(PDFCorruptError):
        validate_pdf_file(corrupt_pdf)


# --- 6. Structured Notice Extraction Tests ---

def test_structured_notice_extraction_confident():
    sample_ocr = (
        "CONSUMER PRODUCT SAFETY COMMISSION RECALL\n"
        "Product Name: Infant Bassinet Sleeper Deluxe\n"
        "Manufacturer: BabyCare Global Industries Ltd.\n"
        "Recall Date: 2026-03-15\n"
        "Hazard: Suffocation and entrapment risk.\n"
        "Remedy: Immediately stop using and contact manufacturer.\n"
        "Recall Number: CPSC-26-089\n"
    )
    notice = extract_safety_notice(sample_ocr)
    assert isinstance(notice, ProductSafetyNotice)
    assert notice.product_name == "Infant Bassinet Sleeper Deluxe"
    assert notice.manufacturer == "BabyCare Global Industries Ltd."
    assert notice.notice_date == "2026-03-15"
    assert "Suffocation" in notice.hazard
    assert "stop using" in notice.recommended_action
    assert notice.recall_identifier == "CPSC-26-089"
    assert notice.uncertain_fields == []
    assert notice.confidence_score == 1.0


def test_structured_notice_extraction_missing_fields():
    # Only product name and date present
    sparse_ocr = (
        "Recall Announcement:\n"
        "Product: Deluxe Smart Toaster\n"
        "Date: 2026-09-12\n"
    )
    notice = extract_safety_notice(sparse_ocr)
    assert notice.product_name == "Deluxe Smart Toaster"
    assert notice.notice_date == "2026-09-12"
    assert notice.manufacturer is None
    assert notice.hazard is None
    assert notice.recommended_action is None
    assert "manufacturer" in notice.uncertain_fields
    assert "hazard" in notice.uncertain_fields
    assert "recommended_action" in notice.uncertain_fields
    assert notice.confidence_score < 0.60


# --- 7. Evaluation Metrics & Normalization Tests ---

def test_normalize_text_for_eval():
    raw = "  Product:  SMART  TOASTER  2026  \n"
    norm = normalize_text_for_eval(raw)
    assert norm == "product: smart toaster 2026"

    # Hindi normalization preserves Devanagari characters
    hindi_raw = "खाद्य   सुरक्षा   सूचना"
    hindi_norm = normalize_text_for_eval(hindi_raw)
    assert hindi_norm == "खाद्य सुरक्षा सूचना"
    assert contains_devanagari(hindi_norm) is True


def test_levenshtein_distance():
    assert levenshtein_distance("kitten", "sitting") == 3
    assert levenshtein_distance([], ["a", "b"]) == 2
    assert levenshtein_distance(["hello", "world"], ["hello", "world"]) == 0


def test_compute_cer():
    ref = "recall notice"
    hyp_exact = "recall notice"
    hyp_sub = "recal1 notice"  # 1 substitution
    assert compute_cer(ref, hyp_exact) == 0.0
    assert compute_cer(ref, hyp_sub) > 0.0
    assert compute_cer(ref, "") == 1.0


def test_compute_wer():
    ref = "voluntary product safety recall"
    hyp_exact = "voluntary product safety recall"
    hyp_sub = "voluntary item safety recall"  # 1 word substitution out of 4 words
    assert compute_wer(ref, hyp_exact) == 0.0
    assert compute_wer(ref, hyp_sub) == 0.25
    assert compute_wer(ref, "") == 1.0
