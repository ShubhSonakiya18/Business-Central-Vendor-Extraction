"""Per-document background processing pipeline.

Runs as a FastAPI BackgroundTask after upload, in its own DB session (it
outlives the request). One bad file must never crash the batch or the
process -- every stage is wrapped so failures land on that one Document as
status="failed" + error_message.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.classification import classify_document
from app.crud import get_document, refresh_vendor_status, sync_vendor_company_name
from app.database import SessionLocal
from app.enums import DocumentStatus, DocumentType
from app.extraction.cheque import parse_cancelled_cheque
from app.extraction.gst import parse_gst_certificate
from app.extraction.merge import apply_derived_rules, merge_field_results
from app.extraction.pan import parse_pan_card
from app.extraction.udyam import parse_udyam_certificate
from app.models import Document
from app.ocr.text_extraction import extract_document_text

logger = logging.getLogger("vendor_intake.pipeline")

_PARSERS = {
    DocumentType.GST_CERTIFICATE: parse_gst_certificate,
    DocumentType.PAN_CARD: parse_pan_card,
    DocumentType.UDYAM_CERTIFICATE: parse_udyam_certificate,
    DocumentType.CANCELLED_CHEQUE: parse_cancelled_cheque,
}


def process_document(document_id: str) -> None:
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is None:
            logger.warning("process_document: document %s no longer exists", document_id)
            return

        vendor_id = document.vendor_id
        document.status = DocumentStatus.PROCESSING.value
        db.commit()

        try:
            text_result = extract_document_text(Path(document.file_path))
            document.raw_text = text_result.raw_text
            document.extraction_source = text_result.extraction_source
            document.ocr_confidence = text_result.ocr_confidence
            db.commit()

            classification = classify_document(text_result.raw_text)
            document.document_type = classification.document_type.value
            document.subtype = classification.subtype
            document.classification_confidence = classification.confidence
            document.extra_flags = json.dumps(classification.extra_flags) if classification.extra_flags else None
            db.commit()

            parser = _PARSERS.get(classification.document_type)
            if parser is not None:
                field_results = parser(text_result.raw_text)
                merge_field_results(db, vendor_id, document.id, field_results)
                apply_derived_rules(db, vendor_id)

            document.status = DocumentStatus.DONE.value
            if text_result.warnings:
                document.error_message = "; ".join(text_result.warnings)
            db.commit()

        except Exception as exc:  # noqa: BLE001 - a bad file must never crash the batch
            logger.exception("processing failed for document %s", document_id)
            document.status = DocumentStatus.FAILED.value
            document.error_message = str(exc)
            db.commit()

        sync_vendor_company_name(db, vendor_id)
        refresh_vendor_status(db, vendor_id)
    finally:
        db.close()
