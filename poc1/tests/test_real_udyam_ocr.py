"""Regression test against REAL PaddleOCR output from an actual Udyam
Registration Certificate PDF (a genuine scanned/image-based government PDF
with no text layer at all -- OCR is not optional for this document).

`tests/fixtures/sample_udyam_real_ocr.txt` is a frozen capture of
`app.ocr.text_extraction.extract_document_text(...)` run once against that
real PDF (mean OCR confidence ~0.98). We test against the frozen text
rather than re-running OCR in every test run because (a) paddleocr/
paddlepaddle are large optional dependencies not every dev/CI environment
will have installed, and (b) CPU OCR over 5 pages takes ~45s -- this test
suite should stay fast. What we're actually testing here is the *parser's*
robustness against real OCR line-ordering quirks (PaddleOCR emits one text
box per line, and multi-column table rows on real government PDFs often
come out with labels and values interleaved/out of order), not OCR itself.

This exists because a real sample document surfaced concrete bugs the
synthetic single-column fixtures never would have: a lookahead grabbing a
neighboring field's *label* as if it were a value (e.g. "PIN" -> "State"),
a lookahead grabbing a neighboring field's *value* instead of its own
(Owner Name -> the PAN), and a lone leftover separator being treated as a
real (if punctuation-only) value.
"""
from pathlib import Path

from app.classification import classify_document
from app.enums import FieldName
from app.extraction.common import results_to_dict
from app.extraction.udyam import parse_udyam_certificate

FIXTURE = Path(__file__).parent / "fixtures" / "sample_udyam_real_ocr.txt"


def _raw_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_real_udyam_pdf_classifies_correctly():
    result = classify_document(_raw_text())
    assert result.document_type.value == "udyam_certificate"
    assert result.confidence >= 0.9


def test_real_udyam_pdf_mobile_and_email_extract_correctly():
    """The literal original ask: mobile number and email must come out of a
    real Udyam certificate, not just a clean synthetic fixture."""
    fields = results_to_dict(parse_udyam_certificate(_raw_text()))
    assert fields[FieldName.PHONE_NUMBER].value == "9748478004"
    assert fields[FieldName.EMAIL_ID_TO].value == "amitava@mbcontrol.com"
    # This document's only email address is printed twice (page 1 and page
    # 3) -- a repeat of the same address is not "a second email", so
    # Email ID CC must stay unset for human entry, not get filled with a
    # duplicate of Email ID TO.
    assert FieldName.EMAIL_ID_CC not in fields


def test_real_udyam_pdf_other_fields():
    fields = results_to_dict(parse_udyam_certificate(_raw_text()))
    assert fields[FieldName.COMPANY_NAME].value == "M.B. CONTROL & SYSTEMS PVT LTD"
    assert fields[FieldName.PAN_CARD].value == "AABCM7980K"
    assert fields[FieldName.STATE].value == "West Bengal"
    assert fields[FieldName.ZIP_CODE].value == "700019"
    assert fields[FieldName.CITY].value == "Kolkata"
    assert fields[FieldName.COUNTRY].value == "India"


def test_real_udyam_pdf_never_puts_a_structured_code_in_contact_name():
    # On this document's page-3 table, "Owner Name"'s neighboring OCR lines
    # are genuinely interleaved with the PAN label/value pair (a scrambled
    # multi-column reading order). We can't always recover the right name
    # from line-sequence alone, but we must never confidently return
    # something ID-shaped (like the PAN itself) as if it were a person's
    # name -- better to leave it blank for human entry.
    fields = results_to_dict(parse_udyam_certificate(_raw_text()))
    contact = fields.get(FieldName.CONTACT_NAME)
    if contact is not None:
        assert contact.value != "AABCM7980K"
