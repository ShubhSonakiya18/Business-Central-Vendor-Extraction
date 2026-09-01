"""Upsert extracted fields into the DB, merging across documents and never
clobbering a human correction.

Rules:
  * A field the user has edited (`is_human_edited=True`) is never touched by
    a later extraction run, no matter how confident the new value is.
  * Otherwise, the highest-confidence value wins across all documents/runs
    for that vendor (this is how "prefer GST Legal Name over Udyam Enterprise
    Name over cheque payee name" naturally falls out -- each parser assigns
    its own confidence and the merge just takes the max).
  * A brand-new field (nothing stored yet) is always inserted.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.enums import ExtractionMethod, FieldName
from app.extraction.common import FieldResult
from app.models import ExtractedField
from app.states import suggest_region


def _get_field(db: Session, vendor_id: str, field_name: FieldName) -> ExtractedField | None:
    return (
        db.query(ExtractedField)
        .filter(ExtractedField.vendor_id == vendor_id, ExtractedField.field_name == field_name.value)
        .one_or_none()
    )


def upsert_field(
    db: Session, vendor_id: str, result: FieldResult, source_document_id: str | None,
) -> None:
    existing = _get_field(db, vendor_id, result.field_name)
    if existing is None:
        db.add(ExtractedField(
            vendor_id=vendor_id,
            field_name=result.field_name.value,
            value=result.value,
            source_document_id=source_document_id,
            extraction_method=result.method.value,
            confidence=result.confidence,
            is_human_edited=False,
        ))
        return

    if existing.is_human_edited:
        return  # never overwrite a human correction

    existing_conf = existing.confidence if existing.confidence is not None else -1.0
    if not existing.value or result.confidence > existing_conf:
        existing.value = result.value
        existing.source_document_id = source_document_id
        existing.extraction_method = result.method.value
        existing.confidence = result.confidence


def merge_field_results(
    db: Session, vendor_id: str, document_id: str, results: list[FieldResult],
) -> None:
    for result in results:
        if not result.value:
            continue
        upsert_field(db, vendor_id, result, document_id)
    db.flush()


def apply_derived_rules(db: Session, vendor_id: str) -> None:
    """Rules that depend on other already-merged fields rather than a single
    document (e.g. REGION suggested from State). Always low-confidence so any
    document-sourced or human-edited value takes precedence, and never
    overwrites a human edit."""
    state_field = _get_field(db, vendor_id, FieldName.STATE)
    if state_field and state_field.value:
        region_suggestion = suggest_region(state_field.value)
        if region_suggestion:
            upsert_field(
                db, vendor_id,
                FieldResult(FieldName.REGION, region_suggestion, ExtractionMethod.RULE, 0.3),
                source_document_id=None,
            )
    db.flush()
