"""Lazy-loaded, process-wide PaddleOCR singleton (PP-OCRv6_mobile, CPU only).

PaddleOCR/PaddlePaddle are large, optional dependencies (see requirements.txt).
We only import them the first time OCR is actually needed -- most digitally
generated GST/Udyam PDFs never touch this module at all because their native
text layer is used instead (see app/ocr/text_extraction.py). This also means
the rest of the app imports and runs fine even in an environment where
paddleocr hasn't been installed yet; OCR-dependent calls just raise a clear
OCRUnavailableError instead of crashing at import time.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from app.config import settings


class OCRUnavailableError(RuntimeError):
    """Raised when OCR is needed but paddleocr/paddlepaddle isn't installed."""


@dataclass
class OCRLine:
    text: str
    confidence: float
    box: list[list[float]] | None = None


@dataclass
class OCRResult:
    lines: list[OCRLine] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def mean_confidence(self) -> float | None:
        if not self.lines:
            return None
        return sum(l.confidence for l in self.lines) / len(self.lines)


_lock = threading.Lock()
_engine = None
_load_failed_reason: str | None = None


def is_loaded() -> bool:
    return _engine is not None


def is_available() -> bool:
    """Whether paddleocr can even be imported, without triggering a full model load."""
    try:
        import paddleocr  # noqa: F401
        return True
    except Exception:
        return False


def get_engine():
    """Lazily construct (once) and return the PaddleOCR engine, CPU-only,
    using the small/mobile PP-OCRv6 detection + recognition models."""
    global _engine, _load_failed_reason
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        try:
            from paddleocr import PaddleOCR
        except Exception as exc:  # pragma: no cover - exercised only when dep missing
            _load_failed_reason = str(exc)
            raise OCRUnavailableError(
                "paddleocr is not installed. Install it with "
                "`pip install paddlepaddle==3.2.0 \"paddleocr[all]\"` (CPU build, "
                "no GPU/CUDA needed) to enable OCR fallback for scanned documents."
            ) from exc

        _engine = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_detection_model_name=settings.OCR_DET_MODEL,
            text_recognition_model_name=settings.OCR_REC_MODEL,
            lang=settings.OCR_LANG,
            device="cpu",
        )
        return _engine


def run_ocr(image_path: str) -> OCRResult:
    """Run OCR over a single raster image and return recognized lines with
    per-line confidence, top-to-bottom / left-to-right (PaddleOCR's default
    reading order)."""
    engine = get_engine()
    raw = engine.predict(image_path)

    result = OCRResult()
    for page in raw:
        texts = page.get("rec_texts", []) if hasattr(page, "get") else getattr(page, "rec_texts", [])
        scores = page.get("rec_scores", []) if hasattr(page, "get") else getattr(page, "rec_scores", [])
        polys = page.get("rec_polys", None) if hasattr(page, "get") else getattr(page, "rec_polys", None)
        for i, txt in enumerate(texts):
            conf = float(scores[i]) if i < len(scores) else 0.0
            box = None
            if polys is not None and i < len(polys):
                try:
                    box = [[float(x), float(y)] for x, y in polys[i]]
                except Exception:
                    box = None
            result.lines.append(OCRLine(text=txt, confidence=conf, box=box))
    return result
