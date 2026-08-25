"""
Evaluates whether SAHI-style tiled inference would materially improve
PaddleOCR detection recall on this pipeline's documents, before implementing
it as anything more than an opt-in.

Renders one page at the pipeline's real RENDER_DPI, then compares:

    A. baseline   -- current OCREngine defaults
    B. upscaled   -- text_det_limit_side_len raised (the existing, cheap
                     knob PaddleOCR already offers for "recover more small
                     print")
    C. tiled      -- naive 2x2 overlapping-tile SAHI-style pass, spans
                     concatenated (no NMS merge -- if this doesn't even
                     recover more ground truth than the baseline, it's not
                     worth building the merge logic)

Reports span count, whether configured ground-truth substrings were
recovered, and wall-clock time for each.

Usage:
    python -m eval.eval_sahi path/to/cheque.pdf \
        --gt ifsc=ICIC0006278 --gt account_number=627851000539
"""

from __future__ import annotations

import argparse
import os
import time

os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")

import numpy as np
import pypdfium2 as pdfium

from vendor_extractor.models import PDF_POINTS_PER_INCH, RENDER_DPI


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


def _extract_texts(results) -> list[str]:
    texts: list[str] = []
    for r in results or []:
        data = r if isinstance(r, dict) else getattr(r, "json", None)
        if isinstance(data, dict) and "res" in data:
            data = data["res"]
        if isinstance(data, dict):
            texts.extend(t for t in (data.get("rec_texts") or []) if t and t.strip())
    return texts


def _found(texts: list[str], ground_truth: dict[str, str]) -> dict[str, bool]:
    joined = " ".join(texts).upper().replace(" ", "")
    return {k: v.upper().replace(" ", "") in joined for k, v in ground_truth.items()}


def run_single_pass(image: np.ndarray, label: str, ground_truth: dict[str, str],
                     det_limit_side_len: int | None = None) -> dict:
    from paddleocr import PaddleOCR

    kwargs = dict(
        lang="en",
        use_textline_orientation=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        text_detection_model_name="PP-OCRv6_small_det",
        text_recognition_model_name="PP-OCRv6_small_rec",
    )
    if det_limit_side_len is not None:
        kwargs["text_det_limit_side_len"] = det_limit_side_len

    ocr = PaddleOCR(**kwargs)
    bgr = image[:, :, ::-1] if image.ndim == 3 else image
    t0 = time.perf_counter()
    texts = _extract_texts(ocr.predict(np.ascontiguousarray(bgr)))
    infer_s = time.perf_counter() - t0

    found = _found(texts, ground_truth)
    print(f"\n=== {label} ===")
    print(f"  spans recognized    : {len(texts)}")
    print(f"  ground truth found  : {found}")
    print(f"  inference time      : {infer_s:.1f}s")
    return {"label": label, "spans": len(texts), "found": found, "infer_s": infer_s}


def _tile_image(image: np.ndarray, n: int = 2, overlap: float = 0.15) -> list[np.ndarray]:
    h, w = image.shape[:2]
    tile_h, tile_w = h // n, w // n
    ov_h, ov_w = int(tile_h * overlap), int(tile_w * overlap)
    tiles = []
    for i in range(n):
        for j in range(n):
            y0, y1 = max(0, i * tile_h - ov_h), min(h, (i + 1) * tile_h + ov_h)
            x0, x1 = max(0, j * tile_w - ov_w), min(w, (j + 1) * tile_w + ov_w)
            tiles.append(image[y0:y1, x0:x1])
    return tiles


def run_tiled(image: np.ndarray, ground_truth: dict[str, str]) -> dict:
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(
        lang="en",
        use_textline_orientation=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        text_detection_model_name="PP-OCRv6_small_det",
        text_recognition_model_name="PP-OCRv6_small_rec",
    )

    tiles = _tile_image(image)
    all_texts: list[str] = []
    t0 = time.perf_counter()
    for tile in tiles:
        bgr = tile[:, :, ::-1] if tile.ndim == 3 else tile
        all_texts.extend(_extract_texts(ocr.predict(np.ascontiguousarray(bgr))))
    infer_s = time.perf_counter() - t0

    found = _found(all_texts, ground_truth)
    print(f"\n=== C. tiled (2x2, 15% overlap) ===")
    print(f"  tiles               : {len(tiles)}")
    print(f"  spans (raw, dupes not merged) : {len(all_texts)}")
    print(f"  ground truth found  : {found}")
    print(f"  inference time (total) : {infer_s:.1f}s")
    return {"label": "tiled", "spans": len(all_texts), "found": found, "infer_s": infer_s}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("document", help="Path to a PDF to render and test (page 1 by default)")
    parser.add_argument("--page", type=int, default=0, help="0-indexed page to render")
    parser.add_argument("--gt", action="append", default=[], metavar="field=value",
                         help="Ground-truth substring expected to be recovered, e.g. --gt ifsc=ICIC0006278")
    args = parser.parse_args()

    ground_truth = dict(kv.split("=", 1) for kv in args.gt)
    if not ground_truth:
        print("Warning: no --gt provided, recall cannot be checked (span counts only).")

    print(f"Rendering {args.document} at {RENDER_DPI} DPI...")
    image = render_page(args.document, RENDER_DPI, args.page)
    print(f"Rendered shape: {image.shape}")

    results = [
        run_single_pass(image, "A. baseline (current defaults)", ground_truth),
        run_single_pass(image, "B. upscaled (text_det_limit_side_len=1920)", ground_truth, det_limit_side_len=1920),
        run_tiled(image, ground_truth),
    ]

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        all_found = all(r["found"].values()) if r["found"] else "n/a"
        print(f"  {r['label']:<50} spans={r['spans']:<4} all_gt_found={all_found}  time={r['infer_s']:.1f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
