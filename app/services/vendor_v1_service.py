"""
V1 service layer -- orchestrates the Gemini pipeline for the FastAPI routes.

Wraps vendor_v1_gemini.py / vendor_v1_verify.py (both left as-is) so
app/routes/vendor_v1.py only deals with HTTP concerns: reading the upload,
returning a redirect/response. All business logic (calling Gemini, filling
Excel, verifying) stays in the wrapped modules.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.vendor_v1_gemini import build_vendor_json, fill_vendor_xlsx
from app.services.vendor_v1_verify import verify_vendor_excel


def run_v1_pipeline(
    cheque_path: Path,
    gst_path: Path,
    udyam_path: Path,
    template_path: Path,
    sheet_names: list[str],
    run_output_dir: Path,
) -> dict:
    """Runs extraction, fills each requested sheet, verifies, and returns
    everything the route needs to render the results page."""
    data = build_vendor_json(str(cheque_path), str(gst_path), str(udyam_path))

    json_path = run_output_dir / "result.json"
    json_path.write_text(json.dumps(data, indent=2))

    xlsx_path = run_output_dir / "vendor_filled.xlsx"
    source_path = template_path
    for sheet_name in sheet_names:
        fill_vendor_xlsx(data, str(source_path), sheet_name, str(xlsx_path))
        source_path = xlsx_path

    report: list[dict] = []
    for sheet_name in sheet_names:
        sheet_report = verify_vendor_excel(
            data, str(xlsx_path), sheet_name,
            report_path=str(run_output_dir / f"verification_report_{sheet_name}.json"),
        )
        for entry in sheet_report:
            entry["sheet"] = sheet_name
        report.extend(sheet_report)

    report_path = run_output_dir / "verification_report.json"
    report_path.write_text(json.dumps(report, indent=2))

    total = len(report)
    passed = sum(1 for e in report if e["status"] == "PASS")
    failed = total - passed
    success_rate = round((passed / total * 100) if total else 0)

    return {
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
