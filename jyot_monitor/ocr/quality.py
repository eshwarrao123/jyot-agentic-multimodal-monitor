"""
Image quality inspection and signal extraction for OCR routing.

Measures objective signals:
- Resolution and aspect ratio
- Blur score (Laplacian variance)
- Contrast score (intensity standard deviation)
- Mean brightness
- Estimated text skew angle
"""

from pathlib import Path
from typing import Any, Dict, Union
import cv2
import numpy as np
from PIL import Image


def _load_cv2_image(image_input: Union[Image.Image, np.ndarray, str, Path]) -> np.ndarray:
    """Load or convert input into a BGR/RGB numpy array."""
    if isinstance(image_input, (str, Path)):
        path = str(image_input)
        img = cv2.imread(path)
        if img is None:
            raise ValueError(f"Could not load image from path: {path}")
        return img
    elif isinstance(image_input, Image.Image):
        return cv2.cvtColor(np.array(image_input), cv2.COLOR_RGB2BGR)
    elif isinstance(image_input, np.ndarray):
        return image_input
    else:
        raise TypeError(f"Unsupported image input type: {type(image_input)}")


def estimate_skew_angle(gray_image: np.ndarray) -> float:
    """
    Estimate text skew angle in degrees using minimum bounding box of foreground pixels.
    Returns angle in range [-45.0, 45.0].
    """
    try:
        # Binarize inverted so text is white on black
        thresh = cv2.threshold(gray_image, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) < 50:
            return 0.0
        rect = cv2.minAreaRect(coords)
        angle = rect[-1]
        if angle < -45.0:
            angle = -(90.0 + angle)
        elif angle > 45.0:
            angle = 90.0 - angle
        return float(round(angle, 2))
    except Exception:
        return 0.0


def assess_image_quality(image_input: Union[Image.Image, np.ndarray, str, Path]) -> Dict[str, Any]:
    """
    Compute objective quality signals for an image.
    
    Signals:
    - width, height, min_dimension
    - blur_score: variance of Laplacian (higher = sharper, < 100 indicates blur)
    - is_blurry: blur_score < 100.0
    - contrast_score: std dev of grayscale pixel intensities (< 35 indicates low contrast)
    - is_low_contrast: contrast_score < 35.0
    - mean_brightness: average pixel value (0-255)
    - estimated_skew_angle: detected rotation in degrees
    - is_skewed: abs(angle) > 2.0
    - is_low_resolution: min_dimension < 600
    """
    img = _load_cv2_image(image_input)
    height, width = img.shape[:2]
    
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()

    # Blur score via Laplacian variance
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    blur_score = float(round(laplacian.var(), 2))

    # Contrast score via intensity standard deviation and dynamic range
    contrast_score = float(round(float(np.std(gray)), 2))
    dynamic_range = float(round(float(np.max(gray) - np.min(gray)), 2))
    is_low_contrast = dynamic_range < 60.0 or (contrast_score < 8.0 and dynamic_range < 100.0)

    # Mean brightness
    mean_brightness = float(round(float(np.mean(gray)), 2))

    # Estimated skew
    skew_angle = estimate_skew_angle(gray)

    min_dim = min(width, height)
    aspect_ratio = float(round(width / max(height, 1), 2))

    return {
        "width": width,
        "height": height,
        "min_dimension": min_dim,
        "aspect_ratio": aspect_ratio,
        "blur_score": blur_score,
        "is_blurry": blur_score < 100.0,
        "contrast_score": contrast_score,
        "dynamic_range": dynamic_range,
        "is_low_contrast": is_low_contrast,
        "mean_brightness": mean_brightness,
        "estimated_skew_angle": skew_angle,
        "is_skewed": abs(skew_angle) > 2.0,
        "is_low_resolution": min_dim < 250 and max(width, height) < 600,
    }
