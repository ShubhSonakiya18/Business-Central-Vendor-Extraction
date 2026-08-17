"""
Evaluates preprocessing.py's clean_for_ocr() against raw input, to check
whether denoise+CLAHE+sharpen actually improves OCR before enabling it.

Runs three passes over one rendered page: raw, preprocessed, and (for
reference) adaptive-threshold binarized -- since "just binarize it" is the
other classical technique people reach for and is worth ruling out
explicitly rather than by assumption.

Usage:
    python -m app.pipelines.v2.eval.eval_preprocessing path/to/document.pdf \
        --gt ifsc=ICIC0006278 --gt account_number=627851000539
"""

from __future__ import annotations

import argparse
import os
import time

os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")

import cv2
import numpy as np
import pypdfium2 as pdfium

from ..models import PDF_POINTS_PER_INCH, RENDER_DPI
from ..preprocessing import clean_for_ocr


def render_page(path: str, dpi: int, page_index: int = 0) -> np.ndarray:
    scale = dpi / PDF_POINTS_PER_INCH
    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[page_index]
        bitmap = page.render(scale=scale)
        arr = bitmap.to_numpy()
    finally:
        pdf.close()
    if arr.ndim == 3 and arr.shape[2] == 4:
        arr = arr[:, :, :3]
    return arr


def binarize(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)
    return cv2.cvtColor(thresh, cv2.COLOR_GRAY2RGB)


def run_paddle(image: np.ndarray, label: str, ground_truth: dict[str, str]) -> dict:
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(
        lang="en",
        use_textline_orientation=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        text_detection_model_name="PP-OCRv6_small_det",
        text_recognition_model_name="PP-OCRv6_small_rec",
    )
    bgr = image[:, :, ::-1] if image.ndim == 3 else image
    t0 = time.perf_counter()
    results = ocr.predict(np.ascontiguousarray(bgr))
    infer_s = time.perf_counter() - t0

    texts, scores = [], []
    for r in results or []:
        data = r if isinstance(r, dict) else getattr(r, "json", None)
        if isinstance(data, dict) and "res" in data:
            data = data["res"]
        if isinstance(data, dict):
            t = [x for x in (data.get("rec_texts") or []) if x and x.strip()]
            s = data.get("rec_scores") or []
            texts.extend(t)
            scores.extend(s[: len(t)])

    joined = " ".join(texts).upper().replace(" ", "")
    found = {k: v.upper().replace(" ", "") in joined for k, v in ground_truth.items()}
    mean_conf = float(np.mean(scores)) if scores else 0.0

    print(f"\n=== {label} ===")
    print(f"  spans               : {len(texts)}")
    print(f"  mean confidence     : {mean_conf:.3f}")
    print(f"  ground truth found  : {found}")
    print(f"  inference time      : {infer_s:.1f}s")
    return {"label": label, "spans": len(texts), "mean_conf": mean_conf, "found": found}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("document", help="Path to a PDF to render and test (page 1 by default)")
    parser.add_argument("--page", type=int, default=0)
    parser.add_argument("--gt", action="append", default=[], metavar="field=value")
    args = parser.parse_args()

    ground_truth = dict(kv.split("=", 1) for kv in args.gt)

    print(f"Rendering {args.document} at {RENDER_DPI} DPI...")
    raw = render_page(args.document, RENDER_DPI, args.page)
    preprocessed = clean_for_ocr(raw)
    binarized = binarize(raw)

    results = [
        run_paddle(raw, "A. raw (no preprocessing)", ground_truth),
        run_paddle(preprocessed, "B. preprocessed (denoise+CLAHE+sharpen)", ground_truth),
        run_paddle(binarized, "C. binarized (adaptive threshold)", ground_truth),
    ]

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        all_found = all(r["found"].values()) if r["found"] else "n/a"
        print(f"  {r['label']:<45} spans={r['spans']:<4} conf={r['mean_conf']:.3f}  all_gt={all_found}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
