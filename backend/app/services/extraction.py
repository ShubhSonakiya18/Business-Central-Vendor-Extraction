"""Pipeline orchestration for the web app.

Sits between the HTTP layer and extraction_pipeline so the route stays a route:
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


_ADDRESS_FIELD_KEYS = ("address_1", "address_2", "address_3", "address_4", "city", "state", "pin_code")


def _overwrite_address_from_registry(result, registry_address: str) -> None:
    """Replace the extracted address fields with the GST registry's own
    registered address, split the same way the vendor pipeline already
    splits any other address blob (address_resolver.resolve_address_blob,
    multiline=True -- the same function document extraction itself uses),
    so the registry address lands in address_1/address_2/city/state/pin_code
    with no separate splitting logic to maintain.

    Only touches fields the registry actually produced a value for -- a
    field the resolver left blank (e.g. address_3/4, which this resolver
    never populates) is left as whatever the documents already gave it
    rather than being blanked out."""
    from app.services.extraction_pipeline.extract.address_resolver import resolve_address_blob
    from app.services.extraction_pipeline.models import FieldResult

    resolved = resolve_address_blob(registry_address, multiline=True)
    values = resolved.as_dict_full()

    for key in _ADDRESS_FIELD_KEYS:
        value = values.get(key)
        if not value:
            continue
        field_result = result.fields.get(key)
        if field_result is None:
            field_result = FieldResult(key=key)
            result.fields[key] = field_result
        field_result.value = value
        field_result.source_document = "gst_registry"
        field_result.matched_label = None
        field_result.match_kind = "gstin_registry"
        field_result.confidence = 1.0
        field_result.notes.append("Overwritten from live GST registry address (GSTIN verification)")


def _apply_gstin_verification(result) -> None:
    """Live GST-registry check on the extracted `gst_number` field, surfaced
    through the SAME FieldResult the vendor Compare page already renders
    (VendorComparePage.jsx's buildRows() reads `.notes` / `.validation_messages`
    off each field's to_dict() -- no new response shape, no frontend change
    needed). Also replaces the extracted address fields with the registry's
    own registered address -- see _overwrite_address_from_registry -- since
    the registry is a more reliable source for the vendor's legal address
    than OCR off a scanned certificate.

    A no-op when GSTIN_API_ENABLED is off, no gst_number was extracted, or
    the live call fails/is disabled -- never blocks or alters extraction
    itself, only annotates/overwrites the existing fields."""
    from app.services.gstin_verification import verify_gstin

    field = result.fields.get("gst_number")
    if field is None or not field.value:
        return

    verification = verify_gstin(field.value)
    if not verification.checked:
        return  # disabled / no key / call failed -- nothing to add

    # Normalized result (principal + additional places, KYB data, provider
    # diagnostics) for the validation layer; persisted with raw_extraction.
    result.gst_verification = verification.to_dict()

    if not verification.record_found:
        field.notes.append("GST registry: NOT active (GSTIN not found in the registry)")
        field.validation_messages.append("GSTIN was not found in the live GST registry")
        if field.validation_status == "valid":
            field.validation_status = "warning"
    elif verification.active:
        field.notes.append("GST registry: active")
    else:
        label = f" ({verification.status})" if verification.status else ""
        field.notes.append(f"GST registry: NOT active{label}")
        field.validation_messages.append("GSTIN is registered but not active per the live GST registry")
        if field.validation_status == "valid":
            field.validation_status = "warning"

    if verification.provider == "gstinapi" and verification.primary_error:
        # The fallback answered: say so, so it is never mistaken for Decentro working.
        field.notes.append(
            f"GST registry checked via fallback (gstinapi.in); primary provider: {verification.primary_error}"
        )
    if verification.additional_places_unrecognized:
        field.notes.append(
            f"{verification.additional_places_unrecognized} additional place(s) of business "
            "not recognised; review the GST registry"
        )

    if verification.address:
        _overwrite_address_from_registry(result, verification.address)


def extract(documents: list[Path], run_dir: Path, models: str):
    """OCR and extract. Returns (result, canonical, load_seconds, started_at)."""
    from app.services.extraction_pipeline.ingest.document_loader import load_documents
    from app.services.extraction_pipeline.ingest.ocr_engine import OCREngine
    from app.services.extraction_pipeline.pipeline import extract_from_document_set

    started_at = time.perf_counter()
    try:
        # det_model/rec_model are PaddleOCR-specific; load_documents()/OCREngine
        # ignore them under the active RapidOCR backend (see RapidOCRTuning for
        # its own knobs, tuned via OCR_RAPID_* instead of the `models` form field).
        engine = OCREngine(
            det_model=f"PP-OCRv6_{models}_det",
            rec_model=f"PP-OCRv6_{models}_rec",
        )
        # dpi=None resolves to whichever DPI matches engine.backend -- see
        # document_loader._default_dpi_for(). RapidOCR's default (100) is
        # paired with OCREngine's own max_side_len so the resolution it
        # renders at isn't silently downscaled away before detection sees it.
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
    _apply_gstin_verification(result)
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
) -> tuple[list[dict], dict, Path, dict[str, str]]:
    """Fill the workbook, then read it back and compare against `canonical`.

    The write-integrity report (`report`/`verification`) compares OUR OWN
    output against itself -- both sides come from the same extraction, so a
    misread value passes; it catches a write/read-back bug, not an OCR
    accuracy problem (that is eval/eval_extraction.py's job).

    Separately, `original_excel_values` captures what the VENDOR actually
    filled into the uploaded workbook, read BEFORE `mapper.fill()` overwrites
    those same mapped cells with our extracted values below. This is the
    only point in the pipeline where the vendor's original entries still
    exist on disk -- once `fill()` runs, they are gone. Returned so the
    caller can put a genuine PDF-vs-Excel comparison in front of a reviewer,
    instead of comparing our output against itself.
    """
    from app.services.extraction_pipeline.excel.excel_mapper import ExcelMapper
    from app.services.extraction_pipeline.excel.verifier import summarize, verify_excel

    try:
        mapper = ExcelMapper.load(mapping)
        xlsx_path = run_dir / "vendor_filled.xlsx"

        # Capture the vendor's own values first -- fill() below overwrites
        # every mapped cell unconditionally, so this is a one-time read.
        # Merged across sheets: a later sheet's value for the same field
        # (there shouldn't normally be one) wins, matching fill()'s own
        # last-sheet-wins behaviour when re-reading its own prior output.
        original_excel_values: dict[str, str] = {}
        for sheet in (sheet_names or [None]):
            original_excel_values.update(mapper.read_values(str(template), sheet_name=sheet))

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
        return report, summarize(report), xlsx_path, original_excel_values
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
    # {field: value-as-originally-filled-in-by-the-vendor}, read from the
    # UPLOADED Excel before fill_and_verify() overwrites those cells with
    # our own extracted values. Empty/absent when no Excel was uploaded, or
    # a field simply wasn't filled in on it -- see excel_mapper.read_values.
    original_excel_values: dict[str, str] = {}

    if template is not None:
        report, verification, xlsx_path, original_excel_values = fill_and_verify(
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
        "excel_uploaded": template is not None,
        "original_excel_values": original_excel_values,
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
