"""Builds the merged GET/PUT .../extraction response: current best value per
field, which document/method it came from, and the document checklist."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.crud import list_documents, list_fields
from app.enums import (
    BANK_FIELD_LABELS, BANK_FIELD_ORDER, EXCEL_FIELD_LABELS, EXCEL_FIELD_ORDER,
    DocumentStatus, DocumentType, VendorStatus,
)
from app.models import Vendor
from app.schemas import DocumentChecklistItem, ExtractionOut, FieldValue

_CHECKLIST_TYPES = [
    (DocumentType.GST_CERTIFICATE, "GST Registration Certificate"),
    (DocumentType.PAN_CARD, "PAN Card"),
    (DocumentType.CANCELLED_CHEQUE, "Cancelled Cheque"),
    (DocumentType.UDYAM_CERTIFICATE, "Udyam Registration Certificate"),
]


def build_extraction_response(db: Session, vendor: Vendor) -> ExtractionOut:
    fields_by_name = {f.field_name: f for f in list_fields(db, vendor.id)}
    documents = list_documents(db, vendor.id)
    docs_by_id = {d.id: d for d in documents}

    def to_field_value(field_name, label) -> FieldValue:
        record = fields_by_name.get(field_name.value)
        if record is None:
            return FieldValue(
                field_name=field_name, label=label, value=None, source_document_id=None,
                source_document_filename=None, extraction_method=None, confidence=None,
                is_human_edited=False, updated_at=None,
            )
        source_doc = docs_by_id.get(record.source_document_id) if record.source_document_id else None
        return FieldValue(
            field_name=field_name, label=label, value=record.value,
            source_document_id=record.source_document_id,
            source_document_filename=source_doc.filename if source_doc else None,
            extraction_method=record.extraction_method, confidence=record.confidence,
            is_human_edited=record.is_human_edited, updated_at=record.updated_at,
        )

    fields = [to_field_value(fn, EXCEL_FIELD_LABELS[fn]) for fn in EXCEL_FIELD_ORDER]
    bank_details = [to_field_value(fn, BANK_FIELD_LABELS[fn]) for fn in BANK_FIELD_ORDER]

    uploaded_types = {d.document_type for d in documents}
    checklist = [
        DocumentChecklistItem(
            document_type=doc_type, label=label,
            uploaded=doc_type.value in uploaded_types,
            document_id=next((d.id for d in documents if d.document_type == doc_type.value), None),
        )
        for doc_type, label in _CHECKLIST_TYPES
    ]

    total = len(documents)
    by_status = {s: sum(1 for d in documents if d.status == s.value) for s in DocumentStatus}
    processing = {
        "documents_total": total,
        "documents_uploaded": by_status[DocumentStatus.UPLOADED],
        "documents_processing": by_status[DocumentStatus.PROCESSING],
        "documents_done": by_status[DocumentStatus.DONE],
        "documents_failed": by_status[DocumentStatus.FAILED],
        "is_complete": total > 0 and (by_status[DocumentStatus.DONE] + by_status[DocumentStatus.FAILED] == total),
    }

    notes = [
        "None of the uploaded documents constitutes a signed Customer Agreement / "
        "Contract / PO / SO -- confirm that separately with the vendor before approval.",
    ]
    if vendor.status == VendorStatus.APPROVED.value:
        notes.append("Vendor has already been approved.")

    return ExtractionOut(
        vendor_id=vendor.id, vendor_status=vendor.status, processing=processing,
        fields=fields, bank_details=bank_details, document_checklist=checklist, notes=notes,
    )
