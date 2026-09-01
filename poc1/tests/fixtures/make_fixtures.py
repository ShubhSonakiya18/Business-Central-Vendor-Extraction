"""Synthesize sample GST / Udyam / PAN / cancelled-cheque documents for
tests, as simple text-layer PDFs (via reportlab) laid out the way the real
government forms are: one "Label: value" pair per line. We deliberately do
NOT use real production documents -- everything here is fictional.

Run directly (`python tests/fixtures/make_fixtures.py`) to regenerate the
.pdf files on disk, or import `build_all()` from a test/conftest fixture.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

FIXTURES_DIR = Path(__file__).parent

SAMPLE_COMPANY = "Bharat Textiles Private Limited"
SAMPLE_TRADE_NAME = "Bharat Textiles"
SAMPLE_DIRECTOR = "Rajesh Kumar Sharma"
SAMPLE_GSTIN = "27AAACB1234C1Z5"
SAMPLE_PAN = "AAACB1234C"
SAMPLE_UDYAM_NO = "UDYAM-MH-03-1234567"
SAMPLE_MOBILE = "9876543210"
SAMPLE_EMAIL = "accounts@bharattextiles.example.com"
SAMPLE_PIN = "400072"
SAMPLE_STATE = "Maharashtra"
SAMPLE_CITY = "Mumbai"
SAMPLE_IFSC = "HDFC0001234"
SAMPLE_ACCOUNT_NO = "123456789012"

GST_CERT_LINES = [
    "Form GST REG-06",
    "Registration Certificate",
    "Legal Name: " + SAMPLE_COMPANY,
    "Trade Name, if any: " + SAMPLE_TRADE_NAME,
    "GSTIN: " + SAMPLE_GSTIN,
    "Constitution of Business: Private Limited Company",
    "",
    "Address of Principal Place of Business",
    "Building No./Flat No.: Plot 14, MIDC Industrial Area",
    "Road/Street: Andheri Kurla Road",
    "City/Town/Village: " + SAMPLE_CITY,
    "District: Mumbai Suburban",
    "State: " + SAMPLE_STATE,
    "PIN Code: " + SAMPLE_PIN,
    "",
    "Annexure B",
    "Details of Proprietor/Partners/Directors/Karta",
    "Name of the Person: " + SAMPLE_DIRECTOR,
    "Designation/Status: Director",
]

UDYAM_CERT_LINES = [
    "UDYAM REGISTRATION CERTIFICATE",
    "Udyam Registration Number: " + SAMPLE_UDYAM_NO,
    "Name of Enterprise: " + SAMPLE_COMPANY,
    "Name of Owner: " + SAMPLE_DIRECTOR,
    "PAN: " + SAMPLE_PAN,
    "Official Address of Enterprise: Plot 14, MIDC Industrial Area, Andheri Kurla Road",
    "City/Town/Village: " + SAMPLE_CITY,
    "State: " + SAMPLE_STATE,
    "PIN Code: " + SAMPLE_PIN,
    "Mobile: " + SAMPLE_MOBILE,
    "Email: " + SAMPLE_EMAIL,
    "Date of Incorporation: 12/04/2016",
    "Major Activity: Manufacturing",
]

PAN_CARD_LINES = [
    "INCOME TAX DEPARTMENT",
    "GOVT. OF INDIA",
    "Permanent Account Number Card",
    SAMPLE_PAN,
    "Name",
    SAMPLE_COMPANY.upper(),
]

CHEQUE_LINES = [
    "HDFC BANK",
    "Branch: Andheri East, Mumbai",
    "Pay ________________________________ or Bearer",
    "A/C No: " + SAMPLE_ACCOUNT_NO,
    "IFSC: " + SAMPLE_IFSC,
    "MICR: 400240002",
    "Account Holder Name: " + SAMPLE_COMPANY.upper(),
    "CANCELLED",
]

OTHER_DOC_LINES = [
    "Miscellaneous cover letter",
    "This document does not match any known vendor onboarding form.",
    "Reference: MISC-2024-001",
]


def _write_text_pdf(lines: list[str], out_path: Path) -> Path:
    c = canvas.Canvas(str(out_path), pagesize=A4)
    width, height = A4
    c.setFont("Helvetica", 11)
    y = height - 60
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.save()
    return out_path


def build_all(out_dir: Path | None = None) -> dict[str, Path]:
    out_dir = out_dir or FIXTURES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "gst_certificate": _write_text_pdf(GST_CERT_LINES, out_dir / "sample_gst_certificate.pdf"),
        "udyam_certificate": _write_text_pdf(UDYAM_CERT_LINES, out_dir / "sample_udyam_certificate.pdf"),
        "pan_card": _write_text_pdf(PAN_CARD_LINES, out_dir / "sample_pan_card.pdf"),
        "cancelled_cheque": _write_text_pdf(CHEQUE_LINES, out_dir / "sample_cancelled_cheque.pdf"),
        "other": _write_text_pdf(OTHER_DOC_LINES, out_dir / "sample_other.pdf"),
    }
    return paths


if __name__ == "__main__":
    built = build_all()
    for name, path in built.items():
        print(f"wrote {name} -> {path}")
