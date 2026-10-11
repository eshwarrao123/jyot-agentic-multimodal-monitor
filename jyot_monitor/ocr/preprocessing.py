"""
Image preprocessing module for OCR accuracy optimization and ablation testing.

Supports:
- Deskewing and rotation correction
- Grayscale conversion
- Contrast adjustment (CLAHE)
- Binarization (Otsu thresholding)
- Denoising (median / bilateral filter)
- Safe resolution upscaling for low-resolution inputs
- Documented profiles for ablation comparisons
"""

from pathlib import Path
from typing import List, Optional, Tuple, Union
import cv2
import numpy as np
from PIL import Image

from jyot_monitor.ocr.quality import assess_image_quality, estimate_skew_angle


def to_pil_image(img_input: Union[Image.Image, np.ndarray, str, Path]) -> Image.Image:
    """Ensure output is a PIL Image in RGB format."""
    if isinstance(img_input, Image.Image):
        return img_input.convert("RGB")
    elif isinstance(img_input, (str, Path)):
        return Image.open(str(img_input)).convert("RGB")
    elif isinstance(img_input, np.ndarray):
        if len(img_input.shape) == 2:
            return Image.fromarray(img_input).convert("RGB")
        elif img_input.shape[2] == 3:
            # Assume BGR if coming from OpenCV
            rgb = cv2.cvtColor(img_input, cv2.COLOR_BGR2RGB)
            return Image.fromarray(rgb)
        else:
            return Image.fromarray(img_input).convert("RGB")
    else:
        raise TypeError(f"Unsupported image type: {type(img_input)}")


def to_cv2_image(img_input: Union[Image.Image, np.ndarray, str, Path]) -> np.ndarray:
    """Ensure output is a BGR OpenCV numpy array."""
    if isinstance(img_input, (str, Path)):
        img = cv2.imread(str(img_input))
        if img is None:
            raise ValueError(f"Failed to load image from {img_input}")
        return img
    elif isinstance(img_input, Image.Image):
        rgb = np.array(img_input.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    elif isinstance(img_input, np.ndarray):
        return img_input.copy()
    else:
        raise TypeError(f"Unsupported image type: {type(img_input)}")


def deskew_image(img_bgr: np.ndarray, angle: Optional[float] = None) -> Tuple[np.ndarray, float]:
    """
    Correct skew rotation by angle degrees.
    If angle is not provided, estimate it from the image.
    """
    if angle is None:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if len(img_bgr.shape) == 3 else img_bgr
        angle = estimate_skew_angle(gray)

    if abs(angle) < 0.5:
        return img_bgr, 0.0

    h, w = img_bgr.shape[:2]
    center = (w // 2, h // 2)
    m = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        img_bgr,
        m,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )
    return rotated, angle


def enhance_contrast_clahe(img_bgr: np.ndarray, clip_limit: float = 2.5) -> np.ndarray:
    """Apply Contrast Limited Adaptive Histogram Equalization (CLAHE)."""
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    if len(img_bgr.shape) == 3:
        lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
        l_chan, a_chan, b_chan = cv2.split(lab)
        l_clahe = clahe.apply(l_chan)
        lab_enhanced = cv2.merge((l_clahe, a_chan, b_chan))
        return cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)
    else:
        return clahe.apply(img_bgr)


def binarize_otsu(img_bgr: np.ndarray) -> np.ndarray:
    """Convert to high-contrast binary black & white image using Otsu's thresholding."""
    if len(img_bgr.shape) == 3:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = img_bgr
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    return cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)


def denoise_image(img_bgr: np.ndarray) -> np.ndarray:
    """Apply median filter to remove speckle noise while preserving text edges."""
    return cv2.medianBlur(img_bgr, 3)


def upscale_if_low_resolution(img_bgr: np.ndarray, target_min_dim: int = 400) -> Tuple[np.ndarray, bool]:
    """Upscale image using bicubic interpolation if both dimensions are small."""
    h, w = img_bgr.shape[:2]
    min_dim = min(h, w)
    max_dim = max(h, w)
    if min_dim >= target_min_dim or max_dim >= 600:
        return img_bgr, False
    
    scale = target_min_dim / max(min_dim, 1)
    # Cap scale factor at 3x to avoid uncontrolled memory bloat
    scale = min(scale, 3.0)
    new_w = int(w * scale)
    new_h = int(h * scale)
    upscaled = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    return upscaled, True


def preprocess_image(
    image_input: Union[Image.Image, np.ndarray, str, Path],
    profile: str = "adaptive_full",
) -> Tuple[Image.Image, List[str]]:
    """
    Apply a documented preprocessing profile to an image.
    
    Profiles:
    - 'original': returns unchanged original image.
    - 'contrast_enhanced': applies CLAHE contrast equalization.
    - 'binarized': grayscale + CLAHE + Otsu thresholding.
    - 'deskewed': estimates and corrects rotational skew.
    - 'upscaled': bicubic scaling for small images.
    - 'adaptive_full': signal-directed selective pipeline (deskew if skewed,
      upscale if low-res, CLAHE if low contrast, denoise if noisy).
    
    Returns:
    (processed_pil_image, list_of_applied_operations)
    """
    if profile == "original":
        return to_pil_image(image_input), []

    cv_img = to_cv2_image(image_input)
    applied_ops: List[str] = []

    if profile == "contrast_enhanced":
        cv_img = enhance_contrast_clahe(cv_img)
        applied_ops.append("clahe_contrast")
    elif profile == "binarized":
        cv_img = binarize_otsu(cv_img)
        applied_ops.append("otsu_binarization")
    elif profile == "deskewed":
        cv_img, angle = deskew_image(cv_img)
        applied_ops.append(f"deskew_{angle:.1f}deg")
    elif profile == "upscaled":
        cv_img, did_upscale = upscale_if_low_resolution(cv_img)
        if did_upscale:
            applied_ops.append("bicubic_upscale")
    elif profile == "adaptive_full":
        signals = assess_image_quality(cv_img)
        
        # 1. Upscale if low resolution
        if signals.get("is_low_resolution", False):
            cv_img, did_upscale = upscale_if_low_resolution(cv_img)
            if did_upscale:
                applied_ops.append("bicubic_upscale")
        
        # 2. Deskew if skewed
        if signals.get("is_skewed", False):
            cv_img, angle = deskew_image(cv_img, signals.get("estimated_skew_angle"))
            applied_ops.append(f"deskew_{angle:.1f}deg")
            
        # 3. Enhance contrast if low contrast or blurry
        if signals.get("is_low_contrast", False) or signals.get("is_blurry", False):
            cv_img = enhance_contrast_clahe(cv_img)
            applied_ops.append("clahe_contrast")
            
        # 4. Light denoise
        cv_img = denoise_image(cv_img)
        applied_ops.append("median_denoise")
    else:
        raise ValueError(f"Unknown preprocessing profile: '{profile}'")

    return to_pil_image(cv_img), applied_ops
