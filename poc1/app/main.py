"""FastAPI app: Vendor Document Intake & Verification API.

Fully local, CPU-only. No document content is ever sent to an external
service. Government/provider verification is a separate, disabled-by-default
capability gated by ENABLE_GOVERNMENT_VERIFICATION (see app/config.py) -- it
is not implemented/called anywhere in this build.
"""
from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import crud
from app.config import settings
from app.database import get_db, init_db
from app.enums import DocumentStatus, VendorStatus
from app.excel_export import export_vendor_excel
from app.extraction_view import build_extraction_response
from app.models import Document, ExtractedField, Vendor
from app.ocr.engine import is_available as ocr_is_available, is_loaded as ocr_is_loaded
from app.pipeline import process_document
from app.schemas import (
    ApprovalOut, ApproveRequest, DocumentOut, DocumentUploadResult, ExtractionOut,
    ExtractionUpdate, SystemStatus, VendorCreate, VendorOut,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vendor_intake")

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Vendor Document Intake & Verification API",
    version="1.0.0",
    description=(
        "Extracts vendor onboarding fields from GST/PAN/Udyam/cheque documents, "
        "fully locally and CPU-only. No document content leaves the machine."
    ),
    lifespan=_lifespan,
)


def _patch_binary_upload_schema(node) -> None:
    """FastAPI generates OpenAPI 3.1, which describes a file-upload field
    (`files: list[UploadFile]`) using the JSON-Schema `contentMediaType`
    keyword. The Swagger UI build FastAPI's /docs pulls from its CDN doesn't
    reliably turn that into a file-picker widget -- it falls back to a plain
    text box (visible as "array<string>" with a text input in /docs). Every
    Swagger UI version *does* render a real file chooser for the older
    OAS-3.0-style `format: "binary"` keyword, so we patch every such node to
    carry both, recursively, since this is a generic fix for any UploadFile
    field in the schema, not just /documents."""
    if isinstance(node, dict):
        if node.get("type") == "string" and "contentMediaType" in node:
            node.setdefault("format", "binary")
        for value in node.values():
            _patch_binary_upload_schema(value)
    elif isinstance(node, list):
        for item in node:
            _patch_binary_upload_schema(item)


def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version, description=app.description,
        routes=app.routes,
    )
    _patch_binary_upload_schema(schema)
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _custom_openapi


# ---------------------------------------------------------------------------
# Health / system
# ---------------------------------------------------------------------------
@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


@app.get("/api/system/status", response_model=SystemStatus, tags=["system"])
def system_status(db: Session = Depends(get_db)):
    return SystemStatus(
        status="ok",
        ocr_engine_loaded=ocr_is_loaded(),
        ocr_backend="paddleocr (PP-OCRv6, CPU)" if ocr_is_available() else "paddleocr not installed",
        government_verification_enabled=settings.ENABLE_GOVERNMENT_VERIFICATION,
        database_url=settings.DATABASE_URL,
        vendor_count=db.query(Vendor).count(),
        document_count=db.query(Document).count(),
    )


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------
@app.post("/api/vendors", response_model=VendorOut, status_code=201, tags=["vendors"])
def create_vendor(body: VendorCreate, db: Session = Depends(get_db)):
    vendor = crud.create_vendor(db, body.company_name)
    return vendor


@app.get("/api/vendors/{vendor_id}", response_model=VendorOut, tags=["vendors"])
def get_vendor(vendor_id: str, db: Session = Depends(get_db)):
    vendor = crud.get_vendor(db, vendor_id)
    if vendor is None:
        raise HTTPException(404, "vendor not found")
    return vendor


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def _document_to_out(doc) -> DocumentOut:
    extra_flags = None
    if doc.extra_flags:
        try:
            extra_flags = json.loads(doc.extra_flags)
        except (TypeError, ValueError):
            extra_flags = None
    return DocumentOut(
        id=doc.id, vendor_id=doc.vendor_id, filename=doc.filename,
        document_type=doc.document_type, subtype=doc.subtype,
        ocr_confidence=doc.ocr_confidence, classification_confidence=doc.classification_confidence,
        extraction_source=doc.extraction_source, status=doc.status,
        error_message=doc.error_message, extra_flags=extra_flags, created_at=doc.created_at,
    )


@app.post(
    "/api/vendors/{vendor_id}/documents", response_model=DocumentUploadResult,
    status_code=201, tags=["documents"],
)
async def upload_documents(
    vendor_id: str, background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...), db: Session = Depends(get_db),
):
    vendor = crud.get_vendor(db, vendor_id)
    if vendor is None:
        raise HTTPException(404, "vendor not found")

    uploaded: list[DocumentOut] = []
    rejected: list[dict] = []
    vendor_dir = settings.UPLOAD_DIR / vendor_id
    vendor_dir.mkdir(parents=True, exist_ok=True)

    for upload in files:
        ext = Path(upload.filename or "").suffix.lower()
        if ext not in settings.ALLOWED_EXTENSIONS:
            rejected.append({"filename": upload.filename, "reason": f"unsupported extension '{ext}'"})
            continue

        content = await upload.read()
        size_mb = len(content) / (1024 * 1024)
        if size_mb > settings.MAX_UPLOAD_MB:
            rejected.append({
                "filename": upload.filename,
                "reason": f"file too large ({size_mb:.1f}MB > {settings.MAX_UPLOAD_MB}MB limit)",
            })
            continue
        if not content:
            rejected.append({"filename": upload.filename, "reason": "empty file"})
            continue

        stored_name = f"{uuid.uuid4().hex}{ext}"
        dest = vendor_dir / stored_name
        dest.write_bytes(content)

        doc = crud.create_document(db, vendor_id, upload.filename or stored_name, str(dest))
        uploaded.append(_document_to_out(doc))
        background_tasks.add_task(process_document, doc.id)

    if uploaded:
        crud.refresh_vendor_status(db, vendor_id)

    return DocumentUploadResult(uploaded=uploaded, rejected=rejected)


@app.get("/api/vendors/{vendor_id}/documents", response_model=list[DocumentOut], tags=["documents"])
def list_documents(vendor_id: str, db: Session = Depends(get_db)):
    vendor = crud.get_vendor(db, vendor_id)
    if vendor is None:
        raise HTTPException(404, "vendor not found")
    return [_document_to_out(d) for d in crud.list_documents(db, vendor_id)]


@app.delete("/api/vendors/{vendor_id}/documents/{document_id}", status_code=204, tags=["documents"])
def delete_document(vendor_id: str, document_id: str, db: Session = Depends(get_db)):
    doc = crud.get_document(db, vendor_id, document_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    try:
        Path(doc.file_path).unlink(missing_ok=True)
    except OSError:
        logger.warning("could not delete file on disk for document %s", document_id)
    crud.delete_document(db, doc)
    crud.refresh_vendor_status(db, vendor_id)
    return None


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
@app.get("/api/vendors/{vendor_id}/extraction", response_model=ExtractionOut, tags=["extraction"])
def get_extraction(vendor_id: str, db: Session = Depends(get_db)):
    vendor = crud.get_vendor(db, vendor_id)
    if vendor is None:
        raise HTTPException(404, "vendor not found")
    return build_extraction_response(db, vendor)


@app.put("/api/vendors/{vendor_id}/extraction", response_model=ExtractionOut, tags=["extraction"])
def update_extraction(vendor_id: str, body: ExtractionUpdate, db: Session = Depends(get_db)):
    from app.extraction.common import FieldResult
    from app.extraction.merge import apply_derived_rules
    from app.enums import ExtractionMethod

    vendor = crud.get_vendor(db, vendor_id)
    if vendor is None:
        raise HTTPException(404, "vendor not found")

    for field_name, value in body.fields.items():
        existing = (
            db.query(ExtractedField)
            .filter(ExtractedField.vendor_id == vendor_id, ExtractedField.field_name == field_name.value)
            .one_or_none()
        )
        if existing is None:
            existing = ExtractedField(vendor_id=vendor_id, field_name=field_name.value)
            db.add(existing)
        existing.value = value
        existing.source_document_id = None
        existing.extraction_method = ExtractionMethod.MANUAL.value
        existing.confidence = 1.0
        existing.is_human_edited = True
    db.commit()

    apply_derived_rules(db, vendor_id)
    crud.sync_vendor_company_name(db, vendor_id)
    return build_extraction_response(db, vendor)


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------
@app.post("/api/vendors/{vendor_id}/approve", response_model=ApprovalOut, tags=["approval"])
def approve_vendor(vendor_id: str, body: ApproveRequest, db: Session = Depends(get_db)):
    vendor = crud.get_vendor(db, vendor_id)
    if vendor is None:
        raise HTTPException(404, "vendor not found")
    if not crud.list_documents(db, vendor_id):
        raise HTTPException(400, "cannot approve a vendor with no uploaded documents")

    record = crud.create_approval(db, vendor_id, body.approved_by, body.notes)
    vendor.status = VendorStatus.APPROVED.value
    db.commit()
    return record


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------
@app.get("/api/vendors/{vendor_id}/excel", tags=["export"])
def get_excel(vendor_id: str, db: Session = Depends(get_db)):
    vendor = crud.get_vendor(db, vendor_id)
    if vendor is None:
        raise HTTPException(404, "vendor not found")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in (vendor.company_name or vendor.id)).strip() or vendor.id
    out_path = settings.EXCEL_DIR / f"{vendor_id}_{safe_name}.xlsx"
    export_vendor_excel(db, vendor, out_path)
    return FileResponse(
        path=out_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"{safe_name}_vendor_onboarding.xlsx",
    )
