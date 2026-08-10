"""
V2 routes -- fully local (PaddleOCR + config-driven) pipeline. Registered at
"/v2". No network calls, no API key.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.services.vendor_v2_service import V2ServiceError, run_v2_pipeline
from app.utils.uploads import save_upload

router = APIRouter(prefix="/v2")
templates = Jinja2Templates(directory=str(settings.templates_dir))

V2_RUNS: dict[str, dict] = {}


@router.get("")
def v2_home(request: Request):
    from app.pipelines.v2.excel_mapper import ExcelMapper

    return templates.TemplateResponse(
        request, "index_v2.html", {"mappings": ExcelMapper.available() or ["vendor_creation_v1"]}
    )


def _v2_error(request: Request, err: V2ServiceError):
    return templates.TemplateResponse(
        request,
        "error_v2.html",
        {"message": err.message, "detail": err.detail, "hint": err.hint, "available_sheets": err.sheets},
        status_code=400,
    )


@router.post("/process-vendor")
def v2_process(
    request: Request,
    documents: List[UploadFile] = File(...),
    vendor_template: Optional[UploadFile] = File(None),
    sheet_names: List[str] = Form(default=[]),
    mapping: str = Form("vendor_creation_v1"),
    models: str = Form("small"),
):
    run_id = uuid.uuid4().hex[:10]
    run_upload_dir = settings.upload_dir / run_id
    run_output_dir = settings.output_dir / run_id
    run_upload_dir.mkdir(parents=True, exist_ok=True)
    run_output_dir.mkdir(parents=True, exist_ok=True)

    saved = [save_upload(doc, run_upload_dir) for doc in documents if doc.filename]
    template_path = (
        save_upload(vendor_template, run_upload_dir)
        if vendor_template is not None and vendor_template.filename
        else None
    )

    try:
        run = run_v2_pipeline(saved, template_path, sheet_names, mapping, models, run_output_dir)
    except V2ServiceError as err:
        return _v2_error(request, err)

    V2_RUNS[run_id] = run
    return RedirectResponse(url=f"/v2/results/{run_id}", status_code=303)


@router.get("/results/{run_id}")
def v2_results(request: Request, run_id: str):
    run = V2_RUNS.get(run_id)
    if not run:
        return RedirectResponse(url="/v2")
    return templates.TemplateResponse(
        request,
        "results_v2.html",
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
def v2_download(run_id: str, kind: str):
    run = V2_RUNS.get(run_id)
    if not run or kind not in run["files"]:
        return RedirectResponse(url="/v2")
    path = run["files"][kind]
    return FileResponse(path, filename=Path(path).name)


@router.post("/template-sheets")
async def v2_template_sheets(vendor_template: UploadFile = File(...)):
    """Returns the sheet names inside an uploaded workbook so the form can
    offer the tabs that actually exist. Reads from memory; nothing is kept."""
    import openpyxl

    try:
        content = await vendor_template.read()
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        sheets = list(workbook.sheetnames)
        workbook.close()
        return {"sheets": sheets}
    except Exception as exc:
        return {"sheets": [], "error": f"{type(exc).__name__}: {exc}"}


@router.get("/health")
def v2_health(request: Request):
    """Confirms the local stack is importable and reports what is configured."""
    from app.pipelines.v2.config_loader import load_config
    from app.pipelines.v2.excel_mapper import ExcelMapper

    dictionary, rules = load_config()
    return {
        "status": "ok",
        "mode": "local",
        "v1_available": request.app.state.v1_available,
        "v1_import_error": request.app.state.v1_import_error or None,
        "fields": len(dictionary),
        "validators": len(rules.validators),
        "excel_mappings": ExcelMapper.available(),
    }
