"""Classifier correctness against the synthetic fixture documents (all go
through the real text-layer extraction path, no OCR/model download needed)."""
from pathlib import Path

import pytest

from app.classification import classify_document
from app.enums import DocumentType
from app.ocr.text_extraction import extract_document_text


def _text_for(fixtures_dir: Path, name: str) -> str:
    return extract_document_text(fixtures_dir / name).raw_text


@pytest.mark.parametrize(
    "filename,expected_type",
    [
        ("sample_gst_certificate.pdf", DocumentType.GST_CERTIFICATE),
        ("sample_udyam_certificate.pdf", DocumentType.UDYAM_CERTIFICATE),
        ("sample_pan_card.pdf", DocumentType.PAN_CARD),
        ("sample_cancelled_cheque.pdf", DocumentType.CANCELLED_CHEQUE),
        ("sample_other.pdf", DocumentType.OTHER),
    ],
)
def test_classification(fixtures_dir, filename, expected_type):
    text = _text_for(fixtures_dir, filename)
    result = classify_document(text)
    assert result.document_type == expected_type
    if expected_type != DocumentType.OTHER:
        assert result.confidence >= 0.4


def test_cheque_extra_flags_carry_low_confidence_cancelled_marker(fixtures_dir):
    text = _text_for(fixtures_dir, "sample_cancelled_cheque.pdf")
    result = classify_document(text)
    assert result.extra_flags["is_cancelled"] is True
    assert result.extra_flags["is_cancelled_confidence"] == "low"


def test_extraction_source_is_text_layer_not_ocr(fixtures_dir):
    # These fixtures are digitally generated PDFs with a real text layer --
    # the pipeline must prefer that over OCR rasterization.
    result = extract_document_text(fixtures_dir / "sample_gst_certificate.pdf")
    assert result.extraction_source == "text_layer"
    assert result.ocr_confidence is None
