"""Manual test harness for the customer-onboarding endpoint.

Runs real files through the same code path POST /onboarding/extract uses
(load_documents -> extract_from_document_set -> to_onboarding_schema) without
going through HTTP or a browser -- handy since Swagger UI's file picker
doesn't render for this FastAPI version's OpenAPI output (see the
`contentMediaType` vs `format: binary` note in onboarding.py's router, or just
ask -- it's a docs-page quirk, not a bug in the endpoint).

    python -m app.cli.run_onboarding_extraction "Cancelled Cheque.pdf" "GST CERTIFICATE.PDF" "UdyamRegistrationCertificate.pdf"
    python -m app.cli.run_onboarding_extraction path/to/a/folder --out outputs/onboarding_dump

Does not commit or require any sample documents in the repo -- point it at
files anywhere on disk.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from app.services.extraction_pipeline.ingest.document_loader import IMAGE_SUFFIXES, load_documents
from app.services.extraction_pipeline.ingest.ocr_engine import OCREngine
from app.services.extraction_pipeline.pipeline import extract_from_document_set
from app.services.onboarding_mapper import to_onboarding_schema

SUPPORTED = {".pdf"} | IMAGE_SUFFIXES


def collect_inputs(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            out.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED))
        elif p.suffix.lower() in SUPPORTED:
            out.append(p)
        else:
            print(f"  (skipping {p.name}: unsupported type, expected PDF/PNG/JPG/TIFF/BMP/WEBP)")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the onboarding extraction pipeline over real files")
    parser.add_argument("inputs", nargs="+", help="Files and/or directories (cheque, GST/Udyam cert, PAN card, ...)")
    parser.add_argument("--out", help="Directory to also write onboarding_result.json into")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    import logging
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                         format="%(levelname)s %(name)s: %(message)s")

    files = collect_inputs(args.inputs)
    if not files:
        parser.error(f"No supported documents found in: {args.inputs}")

    print(f"Documents ({len(files)}):")
    for f in files:
        print(f"  - {f.name}")

    engine = OCREngine()
    print(f"\nLoading {engine.backend} models (first run only)...")
    warm = engine.warmup()
    print(f"  engine ready in {warm:.1f}s")

    t0 = time.perf_counter()
    doc_set = load_documents(files, engine=engine)
    result = extract_from_document_set(doc_set)
    onboarding = to_onboarding_schema(result)
    elapsed = time.perf_counter() - t0

    print("\n" + "=" * 78)
    print("DOCUMENT CLASSIFICATION")
    print("=" * 78)
    for doc in result.documents:
        print(f"  {doc['document']:<40} -> {doc['doc_type']:<20} score={doc['classification_score']}")

    print("\n" + "=" * 78)
    print("ONBOARDING JSON")
    print("=" * 78)
    print(json.dumps(onboarding, indent=2, ensure_ascii=False))

    print("\n" + "=" * 78)
    print(f"{len(onboarding['fields_needing_review'])} field(s) need review: "
          f"{onboarding['fields_needing_review'] or 'none'}")
    print(f"Done in {elapsed:.1f}s")

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "onboarding_result.json"
        out_path.write_text(json.dumps(onboarding, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  -> {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
