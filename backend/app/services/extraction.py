"""Pipeline orchestration for the web app.

Sits between the HTTP layer and vendor_extractor so the route stays a route:
this module knows the order of the work and what a failure means to a user,
and raises PipelineError rather than returning a response, which keeps
rendering decisions in one place.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import traceback
from pathlib import Path
from typing import Optional

from fastapi import UploadFile

from . import run_state
from ..config.settings import UPLOAD_DIR

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """A failure worth showing the user, with enough context to act on it."""

    def __init__(
        self,
        message: str,
        detail: str = "",
        hint: str = "",
        sheets: Optional[list[str]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.hint = hint
        self.sheets = sheets or []


def save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    dest = dest_dir / Path(upload.filename).name
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest


def read_sheet_names(path: Path) -> list[str]:
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(path, read_only=True)
        names = list(workbook.sheetnames)
        workbook.close()
        return names
    except Exception as exc:
        raise PipelineError(
            "That Excel template could not be opened.",
            detail=f"{type(exc).__name__}: {exc}",
            hint="The file must be a valid .xlsx workbook.",
        ) from exc


def store_uploads(
    run_id: str,
    documents: list[UploadFile],
    vendor_template: Optional[UploadFile],
) -> tuple[list[Path], Optional[Path]]:
    upload_dir = UPLOAD_DIR / run_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved = [save_upload(doc, upload_dir) for doc in documents if doc.filename]
    if not saved:
        raise PipelineError(
            "No documents were uploaded.",
            hint="Select at least one PDF, DOCX or image file.",
        )

    template = (
        save_upload(vendor_template, upload_dir)
        if vendor_template is not None and vendor_template.filename
        else None
    )
    return saved, template


def check_requested_sheets(template: Optional[Path], sheet_names: list[str]) -> list[str]:
    """Validate sheet selection before the expensive work.

    The sheet checkboxes are populated from the uploaded workbook, but a stale
    form or a swapped file can still ask for a tab that is not there. Finding
    that out after two minutes of OCR would waste the whole run.
    """
    if template is None:
        return []

    available = read_sheet_names(template)
    missing = [s for s in sheet_names if s not in available]
    if missing:
        raise PipelineError(
            f"The template does not contain the sheet(s) you selected: {', '.join(missing)}.",
            hint="Tick only sheets that exist in your template, or tick none to "
                 "fill the first sheet.",
            sheets=available,
        )
    return available


def extract(documents: list[Path], run_dir: Path, models: str):
    """OCR and extract. Returns (result, canonical, load_seconds, started_at)."""
    from vendor_extractor.ingest.document_loader import load_documents
    from vendor_extractor.ingest.ocr_engine import OCREngine
    from vendor_extractor.pipeline import extract_from_document_set

    started_at = time.perf_counter()
    try:
        engine = OCREngine(
            det_model=f"PP-OCRv6_{models}_det",
            rec_model=f"PP-OCRv6_{models}_rec",
        )
        doc_set = load_documents(documents, engine=engine)
        load_seconds = time.perf_counter() - started_at
    except Exception:
        logger.exception("document loading failed")
        raise PipelineError(
            "Failed while reading the uploaded documents.",
            detail=traceback.format_exc(limit=6),
            hint="Check the terminal running uvicorn for the full traceback.",
        )

    if not doc_set.documents:
        raise PipelineError(
            "None of the uploaded files could be read.",
            hint="Supported types are PDF, DOCX, PNG, JPG, TIFF, BMP and WEBP.",
        )

    doc_set.save_json(run_dir / "document_set.json")

    result = extract_from_document_set(doc_set)
    canonical = result.canonical()

    result.save_json(run_dir / "extraction.json")
    (run_dir / "result.json").write_text(
        json.dumps(canonical, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result, canonical, load_seconds, started_at


def fill_and_verify(
    canonical: dict,
    template: Path,
    run_dir: Path,
    mapping: str,
    sheet_names: list[str],
    available_sheets: list[str],
) -> tuple[list[dict], dict, Path]:
    """Fill the workbook, then read it back and compare against `canonical`.

    The comparison is a write-integrity check, not an accuracy one: both sides
    come from the same extraction, so a misread value passes. Accuracy is
    eval/eval_extraction.py's job.
    """
    from vendor_extractor.excel.excel_mapper import ExcelMapper
    from vendor_extractor.excel.verifier import summarize, verify_excel

    try:
        mapper = ExcelMapper.load(mapping)
        xlsx_path = run_dir / "vendor_filled.xlsx"

        # Each selected tab is filled in turn, re-reading the previous output
        # so every sheet ends up in one workbook.
        targets = sheet_names or [None]
        source = template
        for sheet in targets:
            mapper.fill(canonical, str(source), str(xlsx_path), sheet_name=sheet)
            source = xlsx_path

        report: list[dict] = []
        for sheet in targets:
            report.extend(
                verify_excel(
                    canonical, str(xlsx_path), mapper, sheet_name=sheet,
                    report_path=str(run_dir / f"verification_{sheet or 'default'}.json"),
                )
            )

        (run_dir / "verification_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return report, summarize(report), xlsx_path
    except Exception as exc:
        # Extraction already succeeded and cost real time; losing it to an Excel
        # problem would be the wrong trade. Report it and keep the JSON.
        logger.exception("Excel fill/verify failed")
        raise PipelineError(
            f"Documents were extracted successfully, but filling the Excel "
            f"template failed: {exc}",
            detail=traceback.format_exc(limit=6),
            hint=f"The extracted data was still saved to {run_dir / 'result.json'}",
            sheets=available_sheets,
        ) from exc


def process(
    documents: list[UploadFile],
    vendor_template: Optional[UploadFile],
    sheet_names: list[str],
    mapping: str,
    models: str,
) -> str:
    """Run everything for one submission and return the new run id."""
    run_id = run_state.new_run_id()
    run_dir = run_state.run_directory(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    saved, template = store_uploads(run_id, documents, vendor_template)
    available_sheets = check_requested_sheets(template, sheet_names)

    result, canonical, load_seconds, started_at = extract(saved, run_dir, models)

    files = {
        "json": str(run_dir / "result.json"),
        "extraction": str(run_dir / "extraction.json"),
        "spans": str(run_dir / "document_set.json"),
    }
    report: list[dict] = []
    verification = None

    if template is not None:
        report, verification, xlsx_path = fill_and_verify(
            canonical, template, run_dir, mapping, sheet_names, available_sheets
        )
        files["xlsx"] = str(xlsx_path)
        files["report"] = str(run_dir / "verification_report.json")

    summary = result.summary()
    run_state.save(run_id, {
        "fields": {k: v.to_dict() for k, v in result.fields.items()},
        "needs_review": result.needs_review,
        "documents": result.documents,
        "summary": summary,
        "report": report,
        "verification": verification,
        "files": files,
        "timings": {
            "load": round(load_seconds, 1),
            "extract": round(result.duration_s, 2),
            "total": round(time.perf_counter() - started_at, 1),
        },
    })

    logger.info(
        "run %s complete: %s/%s fields filled in %.1fs",
        run_id, summary.get("filled"), summary.get("total_fields"),
        time.perf_counter() - started_at,
    )
    return run_id
