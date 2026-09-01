"""HTTP endpoints.

Handlers stay thin: parse the request, call services, render. Anything that
knows the order of the pipeline work lives in app/services/extraction.py.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config.settings import DEFAULT_MAPPING, DEFAULT_OCR_MODELS, TEMPLATE_DIR
from ..services import extraction as services
from ..services import run_state
from ..services.extraction import PipelineError

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATE_DIR)


def render_error(request: Request, error: PipelineError):
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "message": error.message,
            "detail": error.detail,
            "hint": error.hint,
            "available_sheets": error.sheets,
        },
        status_code=400,
    )


@router.get("/")
def home(request: Request):
    from app.services.extraction_pipeline.excel.excel_mapper import ExcelMapper
    from app.services.extraction_pipeline.ingest.ocr_engine import OCREngine

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "mappings": ExcelMapper.available() or [DEFAULT_MAPPING],
            # The OCR Model selector (small/medium/tiny) only affects
            # PaddleOCR's det/rec model size -- RapidOCR ignores it entirely.
            # Hide it while RapidOCR is active rather than show a control
            # that silently does nothing (see ocr_engine.py PRESERVED
            # FALLBACK). Comes back automatically if paddleocr is restored.
            "ocr_backend": OCREngine().backend,
        },
    )


@router.post("/process-vendor")
def process_vendor(
    request: Request,
    documents: List[UploadFile] = File(...),
    vendor_template: Optional[UploadFile] = File(None),
    sheet_names: List[str] = Form(default=[]),
    mapping: str = Form(DEFAULT_MAPPING),
    models: str = Form(DEFAULT_OCR_MODELS),
):
    """Run the local pipeline over an arbitrary set of vendor documents.

    Everything happens in-process: no queue, no external service. Uploads and
    outputs are kept per run so a result can be re-downloaded and audited.
    """
    try:
        run_id = services.process(documents, vendor_template, sheet_names, mapping, models)
    except PipelineError as error:
        return render_error(request, error)
    return RedirectResponse(url=f"/results/{run_id}", status_code=303)


@router.post("/extract")
def extract(
    documents: List[UploadFile] = File(...),
    vendor_template: Optional[UploadFile] = File(None),
    sheet_names: List[str] = Form(default=[]),
    mapping: str = Form(DEFAULT_MAPPING),
    models: str = Form(DEFAULT_OCR_MODELS),
):
    """Same pipeline as /process-vendor, but answers in JSON in one call.

    /process-vendor exists for the browser: it 303s to an HTML page, so an
    API client has to follow the redirect and scrape a run_id back out to
    reach the data. This runs the identical work and returns the result
    directly. The run is still persisted, so `run_id` in the response can
    be used with /results/{run_id}/json and /download/{run_id}/{kind}
    afterwards -- nothing here is a throwaway.
    """
    try:
        run_id = services.process(documents, vendor_template, sheet_names, mapping, models)
    except PipelineError as error:
        return JSONResponse(
            {
                "error": error.message,
                "detail": error.detail,
                "hint": error.hint,
                "available_sheets": error.sheets,
            },
            status_code=400,
        )
    return _run_as_json(run_id)


@router.get("/results/{run_id}")
def results(request: Request, run_id: str):
    run = run_state.load(run_id)
    if not run:
        return RedirectResponse(url="/")
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "run_id": run_id,
            "fields": run["fields"],
            "needs_review": run["needs_review"],
            "documents": run["documents"],
            "summary": run["summary"],
            "report": run["report"],
            "verification": run["verification"],
            "downloads": run["files"],
            "timings": run["timings"],
        },
    )


def _run_as_json(run_id: str):
    """Shape a persisted run for API callers.

    `values` is a flattened field -> value map: a caller dropping the
    extraction into another system rarely wants the per-field provenance
    that `fields` carries alongside each value, but both are here so the
    confidence/source of any single value can still be inspected.
    """
    run = run_state.load(run_id)
    if not run:
        return JSONResponse({"error": "unknown run_id", "run_id": run_id}, status_code=404)

    fields = run.get("fields", {})
    return {
        "run_id": run_id,
        "values": {name: field.get("value") for name, field in fields.items()},
        "fields": fields,
        "needs_review": run.get("needs_review"),
        "documents": run.get("documents"),
        "summary": run.get("summary"),
        "verification": run.get("verification"),
        "timings": run.get("timings"),
        "files": sorted(run.get("files", {})),
    }


@router.get("/results/{run_id}/json")
def results_json(run_id: str):
    """A run that has already been processed, as JSON.

    Read-only: it reloads from disk, so calling it never re-runs OCR and
    never changes anything. Use /extract to process documents in the first
    place.
    """
    return _run_as_json(run_id)


@router.get("/download/{run_id}/{kind}")
def download(run_id: str, kind: str):
    run = run_state.load(run_id)
    if not run or kind not in run["files"]:
        return RedirectResponse(url="/")
    path = run["files"][kind]
    return FileResponse(path, filename=Path(path).name)


@router.post("/template-sheets")
async def template_sheets(vendor_template: UploadFile = File(...)):
    """Return the sheet names inside an uploaded workbook.

    Lets the upload form offer the tabs that actually exist in the user's
    template instead of a hardcoded list. Reads from memory; nothing is kept.
    """
    import openpyxl

    try:
        content = await vendor_template.read()
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        sheets = list(workbook.sheetnames)
        workbook.close()
        return {"sheets": sheets}
    except Exception as exc:
        logger.warning("could not read sheet names: %s", exc)
        return {"sheets": [], "error": f"{type(exc).__name__}: {exc}"}


@router.get("/health")
def health():
    """Confirms the local stack is importable and reports what is configured."""
    from app.services.extraction_pipeline.config_loader import load_config
    from app.services.extraction_pipeline.excel.excel_mapper import ExcelMapper

    dictionary, rules = load_config()
    return {
        "status": "ok",
        "mode": "local",
        "fields": len(dictionary),
        "validators": len(rules.validators),
        "excel_mappings": ExcelMapper.available(),
    }
