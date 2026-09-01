"""Field parser for a Udyam Registration Certificate."""
from __future__ import annotations

from app.enums import ExtractionMethod, FieldName
from app.extraction.address import extract_label_value, parse_address
from app.extraction.common import FieldResult
from app.patterns import find_all_emails, find_email, find_mobile, find_pan, looks_like_structured_code

ENTERPRISE_NAME_LABELS = ["Name of Enterprise", "Name of Enterprise, if any", "Enterprise Name"]
OWNER_NAME_LABELS = ["Name of Owner", "Owner Name", "Name of the Owner"]
PAN_LABELS = ["PAN", "PAN No", "PAN Number"]
EMAIL_LABELS = ["Email", "E-mail", "Email ID", "Email Id"]
MOBILE_LABELS = ["Mobile", "Mobile No", "Mobile Number"]


def parse_udyam_certificate(text: str) -> list[FieldResult]:
    results: list[FieldResult] = []

    enterprise_name = extract_label_value(text, ENTERPRISE_NAME_LABELS)
    if enterprise_name and looks_like_structured_code(enterprise_name):
        enterprise_name = None
    if enterprise_name:
        # Lower confidence than GST "Legal Name" so GST wins on merge when both exist.
        results.append(FieldResult(FieldName.COMPANY_NAME, enterprise_name, ExtractionMethod.TEXT_LAYER, 0.7))

    owner_name = extract_label_value(text, OWNER_NAME_LABELS)
    if owner_name and not looks_like_structured_code(owner_name):
        results.append(FieldResult(FieldName.CONTACT_NAME, owner_name, ExtractionMethod.TEXT_LAYER, 0.75))

    pan_field = extract_label_value(text, PAN_LABELS)
    pan = None
    if pan_field:
        m = find_pan(pan_field)
        pan = m or (pan_field.strip() if len(pan_field.strip()) == 10 else None)
    if not pan:
        pan = find_pan(text)
    if pan:
        results.append(FieldResult(FieldName.PAN_CARD, pan, ExtractionMethod.REGEX, 0.85))

    email_field = extract_label_value(text, EMAIL_LABELS)
    email = find_email(email_field) if email_field else None
    email = email or find_email(text)
    if email:
        results.append(FieldResult(FieldName.EMAIL_ID_TO, email, ExtractionMethod.REGEX, 0.85))

        # Spec: Email ID CC has no document source of its own -- leave it
        # for human entry *unless* a second, genuinely distinct email
        # address turns up somewhere in the document (e.g. a company email
        # plus a separate accounts/finance email). A repeat of the same
        # address (common -- Udyam certs print the email on multiple pages)
        # does not count as a second email.
        other_emails = [e for e in find_all_emails(text) if e.lower() != email.lower()]
        if other_emails:
            results.append(FieldResult(FieldName.EMAIL_ID_CC, other_emails[0], ExtractionMethod.REGEX, 0.5))

    mobile_field = extract_label_value(text, MOBILE_LABELS)
    mobile = find_mobile(mobile_field) if mobile_field else None
    mobile = mobile or find_mobile(text)
    if mobile:
        results.append(FieldResult(FieldName.PHONE_NUMBER, mobile, ExtractionMethod.REGEX, 0.85))

    addr = parse_address(text)
    conf = 0.5 if addr.used_generic_fallback else 0.8
    if addr.billing_address:
        results.append(FieldResult(FieldName.BILLING_ADDRESS, addr.billing_address, ExtractionMethod.REGEX, conf))
    if addr.city:
        results.append(FieldResult(FieldName.CITY, addr.city, ExtractionMethod.REGEX, conf))
    if addr.state:
        results.append(FieldResult(FieldName.STATE, addr.state, ExtractionMethod.REGEX, conf))
    if addr.zip_code:
        results.append(FieldResult(FieldName.ZIP_CODE, addr.zip_code, ExtractionMethod.REGEX, 0.85))

    results.append(FieldResult(FieldName.COUNTRY, "India", ExtractionMethod.RULE, 0.9))

    return results
