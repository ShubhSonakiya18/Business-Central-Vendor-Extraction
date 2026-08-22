"""
Step 3 harness: run the loader over real documents and dump raw output.

    python -m v2.dump_ocr uploads/861b7dc254 --out outputs/v2_ocr
    python -m v2.dump_ocr a.pdf b.docx --out outputs/v2_ocr --force-ocr

Writes one JSON per document plus a combined `document_set.json`, and prints
a per-span table (text, bbox, page, confidence) so OCR quality can be eyeballed
before any field logic exists.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from .document_loader import IMAGE_SUFFIXES, load_documents
from .models import RENDER_DPI
from .ocr_engine import OCREngine

SUPPORTED = {".pdf", ".docx"} | IMAGE_SUFFIXES


def collect_inputs(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            out.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED))
        elif p.suffix.lower() in SUPPORTED:
            out.append(p)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 Step 3: dump raw document/OCR output")
    parser.add_argument("inputs", nargs="+", help="Files and/or directories")
    parser.add_argument("--out", default="outputs/v2_ocr", help="Output directory")
    parser.add_argument("--force-ocr", action="store_true", help="Ignore PDF text layers")
    parser.add_argument("--dpi", type=int, default=RENDER_DPI)
    parser.add_argument("--max-print", type=int, default=25, help="Spans to print per document")
    parser.add_argument(
        "--models",
        choices=["small", "medium", "tiny"],
        default="small",
        help="PP-OCRv6 size. small is ~9x faster than medium at similar confidence; "
        "tiny is fast but hallucinates characters (see ocr_engine.DEFAULT_DET_MODEL)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    # OCR of bilingual documents (e.g. the Devanagari header on a Udyam
    # certificate read by an English model) can emit glyphs outside the
    # Windows console's cp1252 codepage, which would otherwise abort the whole
    # run on a print(). The JSON output is always written as UTF-8 regardless.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):  # non-reconfigurable stream
        pass

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    files = collect_inputs(args.inputs)
    if not files:
        raise SystemExit(f"No supported documents found in: {args.inputs}")

    print(f"Documents to process ({len(files)}):")
    for f in files:
        print(f"  - {f.name}")

    engine = OCREngine(
        det_model=f"PP-OCRv6_{args.models}_det",
        rec_model=f"PP-OCRv6_{args.models}_rec",
    )
    needs_ocr = args.force_ocr or any(f.suffix.lower() in IMAGE_SUFFIXES for f in files)
    warm = 0.0
    if needs_ocr:
        print("\nLoading PaddleOCR models...")
        warm = engine.warmup()
        print(f"  engine ready in {warm:.1f}s")

    t0 = time.perf_counter()
    doc_set = load_documents(files, engine=engine, force_ocr=args.force_ocr, dpi=args.dpi)
    elapsed = time.perf_counter() - t0

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for doc in doc_set:
        print("\n" + "=" * 78)
        print(f"{doc.name}   [{doc.doc_type.value}]")
        print("=" * 78)
        print(
            f"pages={len(doc.pages)}  spans={len(doc.spans)}  "
            f"methods={','.join(doc.metadata.get('extraction_methods', []))}  "
            f"time={doc.duration_s:.2f}s"
        )

        for page in doc.pages:
            why = f" via {page.ocr_reason}" if page.ocr_reason else ""
            print(
                f"\n  -- page {page.number}  ({page.extraction_method}{why}, "
                f"{page.width:.0f}x{page.height:.0f}px, {len(page.spans)} spans, "
                f"{page.duration_s:.2f}s)"
            )
            print(f"     {'conf':>5}  {'bbox (x1,y1,x2,y2)':<30}  text")
            for span in page.spans[: args.max_print]:
                b = span.bbox
                box = f"({b.x1:.0f},{b.y1:.0f},{b.x2:.0f},{b.y2:.0f})"
                text = span.text if len(span.text) <= 60 else span.text[:57] + "..."
                print(f"     {span.confidence:5.3f}  {box:<30}  {text}")
            if len(page.spans) > args.max_print:
                print(f"     ... {len(page.spans) - args.max_print} more spans (see JSON)")

        path = out_dir / f"{Path(doc.name).stem}.json"
        path.write_text(json.dumps(doc.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  -> {path}")

    combined = doc_set.save_json(out_dir / "document_set.json")

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"Documents      : {len(doc_set)}")
    print(f"Pages          : {sum(len(d.pages) for d in doc_set)}")
    print(f"Spans          : {len(doc_set.spans)}")
    if warm:
        print(f"Model load     : {warm:.1f}s (one-off)")
    print(f"Processing time: {elapsed:.2f}s")
    print(f"Combined JSON  : {combined}")


if __name__ == "__main__":
    main()
