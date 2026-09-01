"""Small DB helper functions used by the API routes and the pipeline."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.enums import DocumentStatus, DocumentType, VendorStatus
from app.models import ApprovalRecord, Document, ExtractedField, Vendor


def create_vendor(db: Session, company_name: str | None) -> Vendor:
    vendor = Vendor(company_name=company_name, status=VendorStatus.DRAFT.value)
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    return vendor


def get_vendor(db: Session, vendor_id: str) -> Vendor | None:
    return db.get(Vendor, vendor_id)


def create_document(
    db: Session, vendor_id: str, filename: str, file_path: str,
) -> Document:
    doc = Document(
        vendor_id=vendor_id, filename=filename, file_path=file_path,
        document_type=DocumentType.OTHER.value, status=DocumentStatus.UPLOADED.value,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def get_document(db: Session, vendor_id: str, document_id: str) -> Document | None:
    return (
        db.query(Document)
        .filter(Document.id == document_id, Document.vendor_id == vendor_id)
        .one_or_none()
    )


def list_documents(db: Session, vendor_id: str) -> list[Document]:
    return (
        db.query(Document)
        .filter(Document.vendor_id == vendor_id)
        .order_by(Document.created_at.asc())
        .all()
    )


def delete_document(db: Session, document: Document) -> None:
    db.delete(document)
    db.commit()


def list_fields(db: Session, vendor_id: str) -> list[ExtractedField]:
    return db.query(ExtractedField).filter(ExtractedField.vendor_id == vendor_id).all()


def create_approval(db: Session, vendor_id: str, approved_by: str | None, notes: str | None) -> ApprovalRecord:
    record = ApprovalRecord(vendor_id=vendor_id, approved_by=approved_by, notes=notes)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def refresh_vendor_status(db: Session, vendor_id: str) -> Vendor:
    """Auto-advance draft -> processing -> review once all of a vendor's
    documents have finished processing (successfully or not). Never
    downgrades a vendor that's already been approved."""
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        return vendor
    if vendor.status == VendorStatus.APPROVED.value:
        return vendor

    docs = list_documents(db, vendor_id)
    if not docs:
        if vendor.status != VendorStatus.DRAFT.value:
            vendor.status = VendorStatus.DRAFT.value
            db.commit()
        return vendor

    statuses = {d.status for d in docs}
    if statuses <= {DocumentStatus.DONE.value, DocumentStatus.FAILED.value}:
        new_status = VendorStatus.REVIEW.value
    elif DocumentStatus.PROCESSING.value in statuses or DocumentStatus.UPLOADED.value in statuses:
        new_status = VendorStatus.PROCESSING.value
    else:
        new_status = vendor.status

    if new_status != vendor.status:
        vendor.status = new_status
        db.commit()
        db.refresh(vendor)
    return vendor


def sync_vendor_company_name(db: Session, vendor_id: str) -> None:
    """Keep Vendor.company_name in sync with the merged extraction's
    Company Name field, purely so GET /vendors/{id} is useful on its own."""
    from app.enums import FieldName

    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        return
    field = (
        db.query(ExtractedField)
        .filter(ExtractedField.vendor_id == vendor_id, ExtractedField.field_name == FieldName.COMPANY_NAME.value)
        .one_or_none()
    )
    if field and field.value and field.value != vendor.company_name:
        vendor.company_name = field.value
        db.commit()
