"""Pydantic v2 request/response schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import DocumentStatus, DocumentType, FieldName, VendorStatus


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------
class VendorCreate(BaseModel):
    company_name: str | None = Field(default=None, description="Optional initial name; usually filled in by extraction.")


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_name: str | None
    status: VendorStatus
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------
class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    vendor_id: str
    filename: str
    document_type: DocumentType
    subtype: str | None
    ocr_confidence: float | None
    classification_confidence: float | None
    extraction_source: str | None
    status: DocumentStatus
    error_message: str | None
    extra_flags: dict | None = None
    created_at: datetime


class DocumentUploadResult(BaseModel):
    uploaded: list[DocumentOut]
    rejected: list[dict] = Field(default_factory=list, description="Files rejected before processing (bad extension, too large, ...).")


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
class FieldValue(BaseModel):
    field_name: FieldName
    label: str
    value: str | None
    source_document_id: str | None
    source_document_filename: str | None = None
    extraction_method: str | None
    confidence: float | None
    is_human_edited: bool
    updated_at: datetime | None = None


class DocumentChecklistItem(BaseModel):
    document_type: DocumentType
    label: str
    uploaded: bool
    document_id: str | None = None


class ExtractionOut(BaseModel):
    vendor_id: str
    vendor_status: VendorStatus
    processing: dict
    fields: list[FieldValue]
    bank_details: list[FieldValue]
    document_checklist: list[DocumentChecklistItem]
    notes: list[str] = Field(default_factory=list)


class FieldUpdate(BaseModel):
    value: str | None = None


class ExtractionUpdate(BaseModel):
    """PUT body: partial map of field_name -> new value (human correction)."""

    fields: dict[FieldName, str | None]


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------
class ApproveRequest(BaseModel):
    approved_by: str | None = None
    notes: str | None = None


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    vendor_id: str
    approved_by: str | None
    approved_at: datetime
    notes: str | None


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------
class SystemStatus(BaseModel):
    status: str
    ocr_engine_loaded: bool
    ocr_backend: str
    government_verification_enabled: bool
    database_url: str
    vendor_count: int
    document_count: int
