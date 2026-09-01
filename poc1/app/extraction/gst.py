"""Field parser for a GST Registration Certificate (Form GST REG-06)."""
from __future__ import annotations

from app.enums import ExtractionMethod, FieldName
from app.extraction.address import extract_label_value, parse_address
from app.extraction.common import FieldResult
from app.patterns import find_gstin, looks_like_structured_code, pan_from_gstin

LEGAL_NAME_LABELS = ["Legal Name", "Legal Name of Business"]
TRADE_NAME_LABELS = ["Trade Name, if any", "Trade Name"]
DIRECTOR_NAME_LABELS = [
    "Name of the Person", "Name of Person", "Director's Name", "Name of Director",
    "Name of Proprietor", "Name of Karta", "Name",
]


def parse_gst_certificate(text: str) -> list[FieldResult]:
    results: list[FieldResult] = []

    gstin = find_gstin(text)
    if gstin:
        results.append(FieldResult(
            FieldName.GST_REGISTRATION_CERTIFICATE, gstin, ExtractionMethod.REGEX, 0.97,
        ))
        pan = pan_from_gstin(gstin)
        if pan:
            results.append(FieldResult(FieldName.PAN_CARD, pan, ExtractionMethod.REGEX, 0.9))

    legal_name = extract_label_value(text, LEGAL_NAME_LABELS)
    trade_name = extract_label_value(text, TRADE_NAME_LABELS)
    if legal_name and looks_like_structured_code(legal_name):
        legal_name = None
    if trade_name and looks_like_structured_code(trade_name):
        trade_name = None
    # Spec: prefer GST "Legal Name" for Company Name.
    company_name = legal_name or trade_name
    if company_name:
        method_conf = 0.9 if legal_name else 0.75
        results.append(FieldResult(FieldName.COMPANY_NAME, company_name, ExtractionMethod.TEXT_LAYER, method_conf))

    contact_name = extract_label_value(text, DIRECTOR_NAME_LABELS)
    if contact_name and not looks_like_structured_code(contact_name):
        results.append(FieldResult(FieldName.CONTACT_NAME, contact_name, ExtractionMethod.TEXT_LAYER, 0.6))

    addr = parse_address(text)
    conf = 0.55 if addr.used_generic_fallback else 0.85
    if addr.billing_address:
        results.append(FieldResult(FieldName.BILLING_ADDRESS, addr.billing_address, ExtractionMethod.REGEX, conf))
    if addr.city:
        results.append(FieldResult(FieldName.CITY, addr.city, ExtractionMethod.REGEX, conf))
    if addr.state:
        results.append(FieldResult(FieldName.STATE, addr.state, ExtractionMethod.REGEX, conf))
    if addr.zip_code:
        results.append(FieldResult(FieldName.ZIP_CODE, addr.zip_code, ExtractionMethod.REGEX, 0.9))

    if gstin or "GSTIN" in text.upper():
        results.append(FieldResult(FieldName.COUNTRY, "India", ExtractionMethod.RULE, 0.95))

    return results
