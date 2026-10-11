"""
OCR subsystem for jyot_monitor.

Provides:
- Tesseract adapter
- EasyOCR adapter
- Image quality assessment
- Documented preprocessing operations and profiles
- PDF page rendering and validation
- Deterministic multi-engine router
- Structured product safety notice extraction
"""

from jyot_monitor.ocr.easyocr_adapter import run_easyocr_ocr
from jyot_monitor.ocr.pdf_rendering import (
    PDFEncryptedError,
    PDFTooLargeError,
    PDFTooManyPagesError,
    PDFValidationError,
    RenderedPDFPage,
    render_pdf_pages,
    validate_pdf_file,
)
from jyot_monitor.ocr.preprocessing import preprocess_image
from jyot_monitor.ocr.quality import assess_image_quality
from jyot_monitor.ocr.router import OCRRouter
from jyot_monitor.ocr.structured_extraction import extract_safety_notice
from jyot_monitor.ocr.tesseract_adapter import run_tesseract_ocr

__all__ = [
    "run_tesseract_ocr",
    "run_easyocr_ocr",
    "assess_image_quality",
    "preprocess_image",
    "render_pdf_pages",
    "validate_pdf_file",
    "RenderedPDFPage",
    "PDFValidationError",
    "PDFTooLargeError",
    "PDFTooManyPagesError",
    "PDFEncryptedError",
    "OCRRouter",
    "extract_safety_notice",
]
