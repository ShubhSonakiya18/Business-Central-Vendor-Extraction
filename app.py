"""
FastAPI wrapper around the existing vendor extraction / Excel-fill /
verification pipeline. Does not modify vendor_form_extractor_gemini.py or
verify_vendor_excel.py -- just calls their public functions.

Run with:
    uvicorn app:app --reload
"""

import json
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form
from typing import List
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from vendor_form_extractor_gemini import build_vendor_json, fill_vendor_xlsx
from verify_vendor_excel import verify_vendor_excel

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Vendor Form Extractor")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# In-memory store of the latest run's results, keyed by run_id.
RUNS: dict[str, dict] = {}


def _save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    dest = dest_dir / upload.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.post("/generate")
def generate(
    gst_cert: UploadFile = File(...),
    cancelled_cheque: UploadFile = File(...),
    udyam_cert: UploadFile = File(...),
    vendor_template: UploadFile = File(...),
    sheet_names: List[str] = Form(...),
):
    run_id = uuid.uuid4().hex[:10]
    run_upload_dir = UPLOAD_DIR / run_id
    run_output_dir = OUTPUT_DIR / run_id
    run_upload_dir.mkdir(parents=True, exist_ok=True)
    run_output_dir.mkdir(parents=True, exist_ok=True)

    gst_path = _save_upload(gst_cert, run_upload_dir)
    cheque_path = _save_upload(cancelled_cheque, run_upload_dir)
    udyam_path = _save_upload(udyam_cert, run_upload_dir)
    template_path = _save_upload(vendor_template, run_upload_dir)

    data = build_vendor_json(str(cheque_path), str(gst_path), str(udyam_path))

    json_path = run_output_dir / "result.json"
    json_path.write_text(json.dumps(data, indent=2))

    xlsx_path = run_output_dir / "vendor_filled.xlsx"
    source_path = template_path
    for sheet_name in sheet_names:
        fill_vendor_xlsx(data, str(source_path), sheet_name, str(xlsx_path))
        source_path = xlsx_path

    report_path = run_output_dir / "verification_report.json"
    report = []
    for sheet_name in sheet_names:
        sheet_report = verify_vendor_excel(
            data, str(xlsx_path), sheet_name,
            report_path=str(run_output_dir / f"verification_report_{sheet_name}.json"),
        )
        for entry in sheet_report:
            entry["sheet"] = sheet_name
        report.extend(sheet_report)
    report_path.write_text(json.dumps(report, indent=2))

    total = len(report)
    passed = sum(1 for e in report if e["status"] == "PASS")
    failed = total - passed
    success_rate = round((passed / total * 100) if total else 0)

    RUNS[run_id] = {
        "data": data,
        "report": report,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "success_rate": success_rate,
        },
        "files": {
            "xlsx": str(xlsx_path),
            "json": str(json_path),
            "report": str(report_path),
        },
    }

    return RedirectResponse(url=f"/results/{run_id}", status_code=303)


@app.get("/results/{run_id}")
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


@app.get("/download/{run_id}/{kind}")
def download(run_id: str, kind: str):
    run = RUNS.get(run_id)
    if not run or kind not in run["files"]:
        return RedirectResponse(url="/")
    path = run["files"][kind]
    return FileResponse(path, filename=Path(path).name)
