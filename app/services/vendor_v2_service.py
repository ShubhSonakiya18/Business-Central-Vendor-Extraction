"""
V2 service layer -- orchestrates the local (PaddleOCR + YAML engine) pipeline
for the FastAPI routes.

Wraps app/pipelines/v2 so app/routes/vendor_v2.py only deals with HTTP
concerns. Raises V2ServiceError with a user-facing message on failure; the
route turns that into the error_v2.html page instead of a bare 500.
"""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Optional


class V2ServiceError(Exception):
    """A failure the route should show to the user, not a raw traceback."""

    def __init__(self, message: str, detail: str = "", hint: str = "", sheets: Optional[list[str]] = None):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.hint = hint
        self.sheets = sheets or []


def probe_template_sheets(template_path: Path) -> list[str]:
    import openpyxl

    try:
        probe = openpyxl.load_workbook(template_path, read_only=True)
        sheets = list(probe.sheetnames)
        probe.close()
        return sheets
    except Exception as exc:
        raise V2ServiceError(
            "That Excel template could not be opened.",
            detail=f"{type(exc).__name__}: {exc}",
            hint="The file must be a valid .xlsx workbook.",
        ) from exc


def run_v2_pipeline(
    saved_documents: list[Path],
    template_path: Optional[Path],
    sheet_names: list[str],
    mapping: str,
    models: str,
    run_output_dir: Path,
) -> dict:
    """Load, OCR, extract, fill, and verify. Raises V2ServiceError on any
    failure that should be shown to the user rather than crashing the route."""
    from app.pipelines.v2.document_loader import load_documents
    from app.pipelines.v2.excel_mapper import ExcelMapper
    from app.pipelines.v2.ocr_engine import OCREngine
    from app.pipelines.v2.pipeline import extract_from_document_set
    from app.pipelines.v2.verifier import summarize, verify_excel

    if not saved_documents:
        raise V2ServiceError(
            "No documents were uploaded.",
            hint="Select at least one PDF, DOCX or image file.",
        )

    available_sheets: list[str] = []
    if template_path is not None:
        available_sheets = probe_template_sheets(template_path)
        missing = [s for s in sheet_names if s not in available_sheets]
        if missing:
            raise V2ServiceError(
                f"The template does not contain the sheet(s) you selected: {', '.join(missing)}.",
                hint="Tick only sheets that exist in your template, or tick none to fill the first sheet.",
                sheets=available_sheets,
            )

    t0 = time.perf_counter()
    try:
        engine = OCREngine(
            det_model=f"PP-OCRv6_{models}_det",
            rec_model=f"PP-OCRv6_{models}_rec",
        )
        doc_set = load_documents(saved_documents, engine=engine)
        load_seconds = time.perf_counter() - t0
    except Exception:
        traceback.print_exc()
        raise V2ServiceError(
            "Failed while reading the uploaded documents.",
            detail=traceback.format_exc(limit=6),
            hint="Check the terminal running uvicorn for the full traceback.",
        )

    if not doc_set.documents:
        raise V2ServiceError(
            "None of the uploaded files could be read.",
            hint="Supported types are PDF, DOCX, PNG, JPG, TIFF, BMP and WEBP.",
        )

    doc_set.save_json(run_output_dir / "document_set.json")

    result = extract_from_document_set(doc_set)
    canonical = result.canonical()

    result.save_json(run_output_dir / "extraction.json")
    json_path = run_output_dir / "result.json"
    json_path.write_text(json.dumps(canonical, indent=2, ensure_ascii=False), encoding="utf-8")

    files = {
        "json": str(json_path),
        "extraction": str(run_output_dir / "extraction.json"),
        "spans": str(run_output_dir / "document_set.json"),
    }
    report: list[dict] = []
    verification = None

    if template_path is not None:
        try:
            mapper = ExcelMapper.load(mapping)
            xlsx_path = run_output_dir / "vendor_filled.xlsx"

            targets = sheet_names or [None]
            source = template_path
            for sheet in targets:
                mapper.fill(canonical, str(source), str(xlsx_path), sheet_name=sheet)
                source = xlsx_path

            for sheet in targets:
                sheet_report = verify_excel(
                    canonical, str(xlsx_path), mapper, sheet_name=sheet,
                    report_path=str(run_output_dir / f"verification_{sheet or 'default'}.json"),
                )
                report.extend(sheet_report)

            report_path = run_output_dir / "verification_report.json"
            report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

            verification = summarize(report)
            files["xlsx"] = str(xlsx_path)
            files["report"] = str(report_path)
        except Exception as exc:
            traceback.print_exc()
            raise V2ServiceError(
                f"Documents were extracted successfully, but filling the Excel template failed: {exc}",
                detail=traceback.format_exc(limit=6),
                hint=f"The extracted data was still saved to {json_path}",
                sheets=available_sheets,
            ) from exc

    return {
        "fields": {k: v.to_dict() for k, v in result.fields.items()},
        "needs_review": result.needs_review,
        "documents": result.documents,
        "summary": result.summary(),
        "report": report,
        "verification": verification,
        "files": files,
        "timings": {
            "load": round(load_seconds, 1),
            "extract": round(result.duration_s, 2),
            "total": round(time.perf_counter() - t0, 1),
        },
    }
