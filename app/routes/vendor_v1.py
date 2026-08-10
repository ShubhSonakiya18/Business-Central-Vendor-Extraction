"""
V1 routes -- Gemini (cloud) pipeline.

Registered at "/" so existing links/bookmarks keep working. Falls back to V2
(via main.py) when google-genai isn't importable in this environment.
"""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.services.vendor_v1_service import run_v1_pipeline
from app.utils.uploads import save_upload

router = APIRouter()
templates = Jinja2Templates(directory=str(settings.templates_dir))

# In-memory store of each run's results, keyed by run_id.
RUNS: dict[str, dict] = {}


@router.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@router.post("/generate")
def generate(
    gst_cert: UploadFile = File(...),
    cancelled_cheque: UploadFile = File(...),
    udyam_cert: UploadFile = File(...),
    vendor_template: UploadFile = File(...),
    sheet_names: List[str] = Form(...),
):
    run_id = uuid.uuid4().hex[:10]
    run_upload_dir = settings.upload_dir / run_id
    run_output_dir = settings.output_dir / run_id
    run_upload_dir.mkdir(parents=True, exist_ok=True)
    run_output_dir.mkdir(parents=True, exist_ok=True)

    gst_path = save_upload(gst_cert, run_upload_dir)
    cheque_path = save_upload(cancelled_cheque, run_upload_dir)
    udyam_path = save_upload(udyam_cert, run_upload_dir)
    template_path = save_upload(vendor_template, run_upload_dir)

    RUNS[run_id] = run_v1_pipeline(
        cheque_path, gst_path, udyam_path, template_path, sheet_names, run_output_dir,
    )

    return RedirectResponse(url=f"/results/{run_id}", status_code=303)


@router.get("/results/{run_id}")
def results(request: Request, run_id: str):
    run = RUNS.get(run_id)
    if not run:
        return RedirectResponse(url="/")
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "run_id": run_id,
            "data": run["data"],
            "report": run["report"],
            "summary": run["summary"],
        },
    )


@router.get("/download/{run_id}/{kind}")
def download(run_id: str, kind: str):
    from pathlib import Path

    from fastapi.responses import FileResponse

    run = RUNS.get(run_id)
    if not run or kind not in run["files"]:
        return RedirectResponse(url="/")
    path = run["files"][kind]
    return FileResponse(path, filename=Path(path).name)
