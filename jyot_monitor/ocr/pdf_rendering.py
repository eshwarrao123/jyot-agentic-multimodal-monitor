"""
PyMuPDF (fitz) page rendering and validation for scanned/image-only PDFs.

Renders pages at documented DPI (default 200 DPI), validates file size,
page count, and encryption, and retains page-level provenance.
"""

from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
from typing import List, Optional, Tuple, Union
from PIL import Image
import pymupdf


class PDFValidationError(ValueError):
    """Base exception for PDF validation failures."""
    pass


class PDFTooLargeError(PDFValidationError):
    """Raised when PDF exceeds maximum allowed byte size."""
    pass


class PDFTooManyPagesError(PDFValidationError):
    """Raised when PDF exceeds maximum allowed page count."""
    pass


class PDFEncryptedError(PDFValidationError):
    """Raised when PDF is encrypted or password-protected."""
    pass


class PDFCorruptError(PDFValidationError):
    """Raised when PDF cannot be opened or parsed."""
    pass


@dataclass
class RenderedPDFPage:
    """Provenance and image representation of a rendered PDF page."""
    page_number: int  # 1-indexed
    image: Image.Image
    width: int
    height: int
    page_hash: str  # SHA-256 of rendered PNG bytes
    dpi: int


def validate_pdf_file(
    file_path: Union[str, Path],
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    max_pages: int = 20,
) -> int:
    """
    Validate PDF size, encryption status, and page count before rendering.
    Returns page count if valid.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF file not found: {path}")

    file_size = path.stat().st_size
    if file_size > max_bytes:
        raise PDFTooLargeError(
            f"PDF file size ({file_size} bytes) exceeds limit ({max_bytes} bytes)"
        )

    try:
        doc = pymupdf.open(str(path))
    except Exception as e:
        raise PDFCorruptError(f"Failed to open PDF (corrupt or invalid format): {e}") from e

    try:
        if doc.is_encrypted:
            raise PDFEncryptedError(f"PDF is encrypted: {path.name}")

        page_count = len(doc)
        if page_count == 0:
            raise PDFCorruptError(f"PDF contains 0 pages: {path.name}")
        if page_count > max_pages:
            raise PDFTooManyPagesError(
                f"PDF has {page_count} pages, exceeding max limit of {max_pages}"
            )
        return page_count
    finally:
        doc.close()


def render_pdf_pages(
    file_path: Union[str, Path],
    dpi: int = 200,
    max_bytes: int = 10 * 1024 * 1024,
    max_pages: int = 20,
) -> List[RenderedPDFPage]:
    """
    Render all eligible pages of a PDF to PIL images at the specified DPI.
    
    Retains page-level provenance (page number, dimensions, content hash).
    """
    validate_pdf_file(file_path, max_bytes=max_bytes, max_pages=max_pages)
    
    doc = pymupdf.open(str(file_path))
    rendered_pages: List[RenderedPDFPage] = []
    
    # Calculate scale factor from standard 72 DPI
    zoom = dpi / 72.0
    mat = pymupdf.Matrix(zoom, zoom)

    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # Convert to PIL Image
            img_bytes = pix.tobytes("png")
            page_hash = hashlib.sha256(img_bytes).hexdigest()
            pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            
            rendered_pages.append(
                RenderedPDFPage(
                    page_number=page_idx + 1,
                    image=pil_img,
                    width=pix.width,
                    height=pix.height,
                    page_hash=page_hash,
                    dpi=dpi,
                )
            )
    finally:
        doc.close()

    return rendered_pages
