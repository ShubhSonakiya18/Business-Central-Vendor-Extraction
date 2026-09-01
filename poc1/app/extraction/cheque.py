"""Field parser for a cancelled cheque.

Bank letterhead / MICR layout is far less standardized across banks than the
government forms, so this parser leans harder on the regex-validated
IFSC/account-number/MICR patterns and treats printed labels as a bonus, not
a requirement. Per the spec, we do NOT rely on the handwritten "CANCELLED"
scrawl for anything -- that's handled purely as a classifier-level low-
confidence flag (see app/classification.py), never consumed here.
"""
from __future__ import annotations

from app.enums import ExtractionMethod, FieldName
from app.extraction.address import extract_label_value
from app.extraction.common import FieldResult
from app.patterns import MICR_RE, find_account_number, find_ifsc

BRANCH_LABELS = ["Branch", "Branch Name", "Branch Address"]
BANK_NAME_LABELS = ["Bank Name", "Bank"]
ACCOUNT_LABELS = ["A/C No", "A/c No", "Account No", "Account No.", "Account Number", "A/C Number"]
ACCOUNT_HOLDER_LABELS = ["Account Holder Name", "A/C Holder Name", "Account Holder", "Name"]


def _guess_bank_name(text: str) -> str | None:
    labeled = extract_label_value(text, BANK_NAME_LABELS)
    if labeled:
        return labeled
    # Heuristic: the bank's letterhead is almost always the first meaningful
    # line of a cheque scan/print (e.g. "STATE BANK OF INDIA"). Only use this
    # if that line looks like a plain name, not a label:value pair itself.
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line or len(line) > 60:
            return None
        return line
    return None


def parse_cancelled_cheque(text: str) -> list[FieldResult]:
    results: list[FieldResult] = []

    ifsc = find_ifsc(text)
    if ifsc:
        results.append(FieldResult(FieldName.BANK_IFSC_CODE, ifsc, ExtractionMethod.REGEX, 0.95))

    exclude: set[str] = set()
    micr = MICR_RE.search(text)
    if micr:
        exclude.add(micr.group(0))

    acct_field = extract_label_value(text, ACCOUNT_LABELS)
    account_number = None
    if acct_field:
        digits = "".join(ch for ch in acct_field if ch.isdigit())
        if 9 <= len(digits) <= 18:
            account_number = digits
    if not account_number:
        account_number = find_account_number(text, exclude=exclude)
    if account_number:
        results.append(FieldResult(FieldName.BANK_ACCOUNT_NUMBER, account_number, ExtractionMethod.REGEX, 0.75))

    branch = extract_label_value(text, BRANCH_LABELS)
    if branch:
        results.append(FieldResult(FieldName.BANK_BRANCH, branch, ExtractionMethod.TEXT_LAYER, 0.7))

    bank_name = _guess_bank_name(text)
    if bank_name:
        results.append(FieldResult(FieldName.BANK_NAME, bank_name, ExtractionMethod.TEXT_LAYER, 0.5))

    holder = extract_label_value(text, ACCOUNT_HOLDER_LABELS)
    if holder:
        results.append(FieldResult(FieldName.BANK_ACCOUNT_HOLDER_NAME, holder, ExtractionMethod.TEXT_LAYER, 0.6))
        # Payee/account-holder name is a weak signal for Company Name -- low
        # confidence so a GST/Udyam-sourced name always wins on merge.
        results.append(FieldResult(FieldName.COMPANY_NAME, holder, ExtractionMethod.TEXT_LAYER, 0.4))

    if ifsc:
        results.append(FieldResult(FieldName.COUNTRY, "India", ExtractionMethod.RULE, 0.6))

    return results
