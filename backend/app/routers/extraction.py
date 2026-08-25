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
from fastapi.responses import FileResponse, RedirectResponse
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
    from extraction_pipeline.excel.excel_mapper import ExcelMapper

    return templates.TemplateResponse(
        request,
        "index.html",
        {"mappings": ExcelMapper.available() or [DEFAULT_MAPPING]},
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
    from extraction_pipeline.config_loader import load_config
    from extraction_pipeline.excel.excel_mapper import ExcelMapper

    dictionary, rules = load_config()
    return {
        "status": "ok",
        "mode": "local",
        "fields": len(dictionary),
        "validators": len(rules.validators),
        "excel_mappings": ExcelMapper.available(),
    }
