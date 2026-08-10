"""
PaddleOCR 3.x Wrapper
=====================
The ONLY module in V2 that imports paddleocr. Everything downstream consumes
`TextSpan` objects, so swapping OCR backends later means rewriting this file
and nothing else.

Targets the installed PaddleOCR 3.7 API (`PaddleOCR.predict`). The 2.x style
`PaddleOCR(use_angle_cls=True).ocr(img, cls=True)` is NOT used -- those kwargs
no longer exist.

Model loading is expensive (seconds) and the models are stateless across
calls, so engines are cached per configuration and reused for the whole batch.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import numpy as np

from .models import BBox, SpanSource, TextSpan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# oneDNN WORKAROUND -- must run before paddlex is imported anywhere.
# ---------------------------------------------------------------------------
# PaddlePaddle 3.3.1 on CPU defaults to the oneDNN/MKL-DNN run mode, whose new
# PIR executor cannot convert some op attributes, and detection dies with:
#     NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute
#     not support [pir::ArrayAttribute<pir::DoubleAttribute>]
#     (onednn_instruction.cc:118)
# Forcing the plain "paddle" run mode avoids that code path entirely. paddlex
# reads this flag at import time, so setting it later has no effect -- hence
# module scope. An explicit value from the environment always wins, so this
# can be re-enabled from outside once upstream fixes the executor.
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")

# PaddleOCR is imported lazily so that importing v2.models / document_loader
# (e.g. for a DOCX-only run, or in tests) does not pay the paddle import cost.
_ENGINE_CACHE: dict[tuple, Any] = {}

# Model selection is the dominant cost/accuracy lever on CPU. Measured on a
# 1592x723 cheque render, oneDNN disabled (see workaround above):
#
#   PP-OCRv6_medium   93.3s   mean conf 0.962   <- PaddleOCR's default
#   PP-OCRv6_small    10.7s   mean conf 0.948
#   PP-OCRv6_tiny      3.8s   mean conf 0.875   (hallucinated CJK glyphs)
#
# `small` is the default here: ~9x faster than the stock medium models for a
# marginal confidence cost, which is what makes multi-document batches
# practical. `tiny` is not recommended -- it invented characters that were not
# on the page, which is far more dangerous than a low score, because a
# confident wrong GSTIN silently passes validation. Override per call site.
DEFAULT_DET_MODEL = "PP-OCRv6_small_det"
DEFAULT_REC_MODEL = "PP-OCRv6_small_rec"


class OCREngine:
    """Thin, cached wrapper over PaddleOCR.

    Parameters mirror the few PaddleOCR 3.x knobs that actually matter for
    scanned Indian certificates and cheques:

    - `use_textline_orientation`: rotates individual text lines. Cheques and
      phone-camera scans often have rotated lines; certificates rarely do.
    - `use_doc_orientation_classify` / `use_doc_unwarping`: whole-page
      deskew/dewarp. Both are off by default because they add a lot of
      latency and can distort already-flat renders of digital PDFs.
    - `text_det_limit_side_len`: detection input size. Larger recovers more
      small print (cheque account numbers) at the cost of speed.
    """

    def __init__(
        self,
        lang: str = "en",
        det_model: Optional[str] = DEFAULT_DET_MODEL,
        rec_model: Optional[str] = DEFAULT_REC_MODEL,
        use_textline_orientation: bool = False,
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
        text_det_limit_side_len: Optional[int] = None,
        text_rec_score_thresh: float = 0.0,
        drop_score: float = 0.30,
    ):
        self.lang = lang
        self.det_model = det_model
        self.rec_model = rec_model
        self.use_textline_orientation = use_textline_orientation
        self.use_doc_orientation_classify = use_doc_orientation_classify
        self.use_doc_unwarping = use_doc_unwarping
        self.text_det_limit_side_len = text_det_limit_side_len
        self.text_rec_score_thresh = text_rec_score_thresh
        # Spans below this recognition score are discarded outright -- they are
        # almost always watermark bleed or scan noise, and letting them through
        # pollutes spatial matching later.
        self.drop_score = drop_score
        self._ocr = None

    # -- engine lifecycle ---------------------------------------------------

    @property
    def _cache_key(self) -> tuple:
        return (
            self.lang,
            self.det_model,
            self.rec_model,
            self.use_textline_orientation,
            self.use_doc_orientation_classify,
            self.use_doc_unwarping,
            self.text_det_limit_side_len,
        )

    def _load(self):
        """Instantiate (or reuse) the PaddleOCR pipeline."""
        if self._ocr is not None:
            return self._ocr

        key = self._cache_key
        if key in _ENGINE_CACHE:
            self._ocr = _ENGINE_CACHE[key]
            return self._ocr

        from paddleocr import PaddleOCR  # imported lazily, see module docstring

        kwargs: dict[str, Any] = {
            "lang": self.lang,
            "use_textline_orientation": self.use_textline_orientation,
            "use_doc_orientation_classify": self.use_doc_orientation_classify,
            "use_doc_unwarping": self.use_doc_unwarping,
        }
        if self.det_model:
            kwargs["text_detection_model_name"] = self.det_model
        if self.rec_model:
            kwargs["text_recognition_model_name"] = self.rec_model
        if self.text_det_limit_side_len is not None:
            kwargs["text_det_limit_side_len"] = self.text_det_limit_side_len

        t0 = time.perf_counter()
        engine = PaddleOCR(**kwargs)
        logger.info("PaddleOCR engine loaded in %.1fs (%s)", time.perf_counter() - t0, key)

        _ENGINE_CACHE[key] = engine
        self._ocr = engine
        return engine

    def warmup(self) -> float:
        """Force model load up-front so the first real page isn't charged for
        it. Returns seconds spent."""
        t0 = time.perf_counter()
        self._load()
        return time.perf_counter() - t0

    # -- inference ----------------------------------------------------------

    def read_image(
        self,
        image: np.ndarray,
        source_document: str,
        page: int,
        span_source: SpanSource = SpanSource.OCR,
        order_offset: int = 0,
    ) -> list[TextSpan]:
        """Run OCR on one RGB image and return spans in reading order."""
        engine = self._load()

        # PaddleOCR expects BGR (OpenCV convention); our renders are RGB.
        if image.ndim == 3 and image.shape[2] == 3:
            image = image[:, :, ::-1]
        elif image.ndim == 3 and image.shape[2] == 4:
            image = image[:, :, [2, 1, 0]]

        results = engine.predict(np.ascontiguousarray(image))
        spans: list[TextSpan] = []
        for result in results or []:
            spans.extend(
                _result_to_spans(
                    result,
                    source_document=source_document,
                    page=page,
                    span_source=span_source,
                    drop_score=self.drop_score,
                )
            )

        spans = sort_reading_order(spans)
        for i, span in enumerate(spans):
            span.order = order_offset + i
        return spans


# ---------------------------------------------------------------------------
# RESULT ADAPTER
# ---------------------------------------------------------------------------

def _result_to_spans(
    result: Any,
    source_document: str,
    page: int,
    span_source: SpanSource,
    drop_score: float,
) -> list[TextSpan]:
    """Normalize one PaddleOCR 3.x result into TextSpans.

    The 3.x result is a dict-like `OCRResult` carrying parallel arrays
    (`rec_texts`, `rec_scores`, and polygons under one of several keys
    depending on pipeline configuration). We read it defensively so a minor
    PaddleOCR point release renaming a key degrades rather than crashes.
    """
    data = result if isinstance(result, dict) else getattr(result, "json", None)
    if isinstance(data, dict) and "res" in data:  # some versions nest under "res"
        data = data["res"]
    if not isinstance(data, dict):
        logger.warning("Unrecognized PaddleOCR result type: %r", type(result))
        return []

    texts = data.get("rec_texts") or []
    scores = data.get("rec_scores") or []
    polys = (
        data.get("rec_polys")
        if data.get("rec_polys") is not None
        else data.get("rec_boxes")
        if data.get("rec_boxes") is not None
        else data.get("dt_polys")
    )
    if polys is None:
        polys = []

    spans: list[TextSpan] = []
    for i, text in enumerate(texts):
        text = (text or "").strip()
        if not text:
            continue
        score = float(scores[i]) if i < len(scores) else 1.0
        if score < drop_score:
            continue

        bbox = _to_bbox(polys[i]) if i < len(polys) else None
        if bbox is None:
            continue

        spans.append(
            TextSpan(
                text=text,
                page=page,
                bbox=bbox,
                source_document=source_document,
                confidence=score,
                source=span_source,
            )
        )
    return spans


def _to_bbox(poly) -> Optional[BBox]:
    """Accept either a 4-point polygon [[x,y]*4] or a flat [x1,y1,x2,y2] box."""
    arr = np.asarray(poly, dtype=float)
    if arr.ndim == 2 and arr.shape[0] >= 3:
        return BBox.from_polygon(arr)
    flat = arr.reshape(-1)
    if flat.size == 4:
        x1, y1, x2, y2 = flat
        return BBox(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    return None


# ---------------------------------------------------------------------------
# READING ORDER
# ---------------------------------------------------------------------------

def sort_reading_order(spans: list[TextSpan]) -> list[TextSpan]:
    """Sort top-to-bottom, left-to-right, grouping spans into visual lines.

    Grouping is by vertical-centre distance against the *median* span height,
    not by raw box overlap. Real documents contain tall outliers -- rotated
    sidebar text, watermarks, a stamp -- and a single one of those overlaps
    many genuine lines at once. Keying off overlap lets one such box swallow
    several rows and scramble their order; keying off centre distance with a
    median-derived tolerance keeps outliers on their own line and leaves the
    real rows intact.

    Order matters because the semantic engine reads label/value adjacency: a
    label on the left and its value on the right must stay on one line, and a
    naive sort by y alone would interleave neighbouring columns.
    """
    if not spans:
        return []

    heights = [s.bbox.height for s in spans if s.bbox.height > 0]
    median_h = float(np.median(heights)) if heights else 1.0
    tolerance = max(median_h * 0.6, 1.0)

    lines: list[list[TextSpan]] = []
    line_centres: list[float] = []
    for span in sorted(spans, key=lambda s: (s.bbox.y1, s.bbox.x1)):
        cy = span.bbox.cy
        placed = False
        for i, centre in enumerate(line_centres):
            if abs(cy - centre) <= tolerance:
                lines[i].append(span)
                # Track the line's running centre so it drifts with the row
                # rather than being pinned to whichever span arrived first.
                line_centres[i] = float(np.mean([s.bbox.cy for s in lines[i]]))
                placed = True
                break
        if not placed:
            lines.append([span])
            line_centres.append(cy)

    ordered: list[TextSpan] = []
    for _, line in sorted(zip(line_centres, lines), key=lambda pair: pair[0]):
        ordered.extend(sorted(line, key=lambda s: s.bbox.x1))
    return ordered
