"""
V2 Image Preprocessing (opt-in, evidence-gated)
=================================================
A denoise/contrast/sharpen chain to run on a rendered page before OCR, meant
to help on genuinely noisy input (scanner speckle, underexposed phone
photos, heavy JPEG artifacts).

NOT wired into the default pipeline. Measured against this project's real
sample documents plus a synthetic degraded cheque (Gaussian noise +
underexposure + blur, simulating a bad phone photo), `clean_for_ocr()` never
improved recognition and was slightly *worse* on every sample:

    document                    spans (raw -> preprocessed)   mean_conf
    cheque (clean digital PDF)      29 -> 28                  0.948 -> 0.941
    Udyam cert (real scan)         104 -> 104                 0.973 -> 0.973 (identical)
    cheque + synthetic noise        27 -> 26                  0.925 -> 0.916

PP-OCRv6's recognizer is already trained on noisy/real-world text and is
more robust to compression artifacts and sensor noise than this classical
pipeline is helpful -- CLAHE's local contrast boost in particular tends to
amplify injected noise rather than suppress it. Reproduce with
scratch_eval/eval_preprocessing.py in the repo history (or re-derive: render
a sample at 200 DPI, compare `clean_for_ocr(img)` vs `img` through the same
OCREngine and diff span count / mean confidence / known ground truth).

Kept as an opt-in call (`OCREngine(..., preprocess=True)` or call
`clean_for_ocr` directly before `read_image`) for a document source not
covered by the current samples -- e.g. a genuinely low-quality scanner with
visible speckle, which none of the sample documents exhibit. Do not enable
it by default without re-measuring against the actual failing input first;
"looks like it should help" was already tried here and didn't.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def clean_for_ocr(
    image: np.ndarray,
    denoise: bool = True,
    enhance_contrast: bool = True,
    sharpen: bool = True,
) -> np.ndarray:
    """Reduce scan/photo noise in an RGB image before OCR. Returns an array
    of the same shape as the input (safe to swap in before OCREngine.read_image
    without touching downstream bbox geometry).

    See the module docstring before enabling this by default -- it measured
    neutral-to-negative on every sample document tried so far.
    """
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        return image

    rgb = image[:, :, :3]
    out = rgb

    if denoise:
        out = _denoise(out)
    if enhance_contrast:
        out = _enhance_contrast(out)
    if sharpen:
        out = _unsharp_mask(out)

    return out


def _denoise(rgb: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoisingColored(rgb, None, h=6, hColor=6,
                                            templateWindowSize=7, searchWindowSize=21)


def _enhance_contrast(rgb: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    lab = cv2.merge((l, a, b))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


def _unsharp_mask(rgb: np.ndarray, amount: float = 0.6, radius: int = 3) -> np.ndarray:
    blurred = cv2.GaussianBlur(rgb, (0, 0), sigmaX=radius)
    sharpened = cv2.addWeighted(rgb, 1 + amount, blurred, -amount, 0)
    return np.clip(sharpened, 0, 255).astype(np.uint8)
