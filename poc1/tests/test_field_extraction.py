"""Per-document-type field parsers against the synthetic fixtures."""
from pathlib import Path

from app.enums import FieldName
from app.extraction.cheque import parse_cancelled_cheque
from app.extraction.common import results_to_dict
from app.extraction.gst import parse_gst_certificate
from app.extraction.pan import parse_pan_card
from app.extraction.udyam import parse_udyam_certificate
from app.ocr.text_extraction import extract_document_text


def _text(fixtures_dir: Path, name: str) -> str:
    return extract_document_text(fixtures_dir / name).raw_text


def test_gst_certificate_fields(fixtures_dir):
    fields = results_to_dict(parse_gst_certificate(_text(fixtures_dir, "sample_gst_certificate.pdf")))
    assert fields[FieldName.GST_REGISTRATION_CERTIFICATE].value == "27AAACB1234C1Z5"
    assert fields[FieldName.PAN_CARD].value == "AAACB1234C"
    assert fields[FieldName.COMPANY_NAME].value == "Bharat Textiles Private Limited"
    assert fields[FieldName.CONTACT_NAME].value == "Rajesh Kumar Sharma"
    assert fields[FieldName.BILLING_ADDRESS].value == "Plot 14, MIDC Industrial Area, Andheri Kurla Road"
    assert fields[FieldName.CITY].value == "Mumbai"
    assert fields[FieldName.STATE].value == "Maharashtra"
    assert fields[FieldName.ZIP_CODE].value == "400072"
    assert fields[FieldName.COUNTRY].value == "India"


def test_udyam_certificate_fields(fixtures_dir):
    fields = results_to_dict(parse_udyam_certificate(_text(fixtures_dir, "sample_udyam_certificate.pdf")))
    assert fields[FieldName.COMPANY_NAME].value == "Bharat Textiles Private Limited"
    assert fields[FieldName.CONTACT_NAME].value == "Rajesh Kumar Sharma"
    assert fields[FieldName.PAN_CARD].value == "AAACB1234C"
    assert fields[FieldName.EMAIL_ID_TO].value == "accounts@bharattextiles.example.com"
    assert fields[FieldName.PHONE_NUMBER].value == "9876543210"
    assert fields[FieldName.STATE].value == "Maharashtra"
    assert fields[FieldName.ZIP_CODE].value == "400072"
    # Only one distinct email address anywhere in this fixture -- Email ID
    # CC has no document source of its own, so it must stay unset here.
    assert FieldName.EMAIL_ID_CC not in fields

    # GST "Legal Name" must outrank Udyam "Name of Enterprise" on merge.
    gst_fields = results_to_dict(parse_gst_certificate(_text(fixtures_dir, "sample_gst_certificate.pdf")))
    assert gst_fields[FieldName.COMPANY_NAME].confidence > fields[FieldName.COMPANY_NAME].confidence


def test_udyam_certificate_second_distinct_email_fills_cc():
    # Spec: "Email ID CC -- manual field (no doc source) -- leave blank for
    # human entry unless a second email is found." A repeated occurrence of
    # the *same* address (common -- Udyam certs print the email on multiple
    # pages) must not count; only a genuinely different second address should.
    text = (
        "UDYAM REGISTRATION CERTIFICATE\n"
        "Name of Enterprise: Bharat Textiles Private Limited\n"
        "Email: accounts@bharattextiles.example.com\n"
        "Mobile: 9876543210\n"
        "Alternate contact: finance@bharattextiles.example.com\n"
    )
    fields = results_to_dict(parse_udyam_certificate(text))
    assert fields[FieldName.EMAIL_ID_TO].value == "accounts@bharattextiles.example.com"
    assert fields[FieldName.EMAIL_ID_CC].value == "finance@bharattextiles.example.com"


def test_pan_card_fields(fixtures_dir):
    fields = results_to_dict(parse_pan_card(_text(fixtures_dir, "sample_pan_card.pdf")))
    assert fields[FieldName.PAN_CARD].value == "AAACB1234C"
    assert fields[FieldName.COUNTRY].value == "India"


def test_cancelled_cheque_fields(fixtures_dir):
    fields = results_to_dict(parse_cancelled_cheque(_text(fixtures_dir, "sample_cancelled_cheque.pdf")))
    assert fields[FieldName.BANK_IFSC_CODE].value == "HDFC0001234"
    assert fields[FieldName.BANK_ACCOUNT_NUMBER].value == "123456789012"
    assert fields[FieldName.BANK_NAME].value == "HDFC BANK"
    assert fields[FieldName.BANK_ACCOUNT_HOLDER_NAME].value == "BHARAT TEXTILES PRIVATE LIMITED"
    # Company name from a cheque payee is a weak signal -- must be low confidence.
    assert fields[FieldName.COMPANY_NAME].confidence <= 0.5
