"""Regex patterns and validators for structured Indian business-document fields.

We never ask OCR/LLM to "guess" a structured value like a GSTIN or IFSC code --
we regex it out of raw text and validate against the known format. Free text
(names, addresses) still goes through label-anchored parsing (see
app/extraction/address.py) rather than a generic regex.
"""
from __future__ import annotations

import re

GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}\b")
PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]{1}\b")
IFSC_RE = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
PIN_RE = re.compile(r"\b\d{6}\b")
MOBILE_RE = re.compile(r"\b[6-9]\d{9}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
ACCT_NO_RE = re.compile(r"\b\d{9,18}\b")  # bank account numbers -- length varies by bank
UDYAM_RE = re.compile(r"\bUDYAM-[A-Z]{2}-\d{2}-\d{7}\b")

# MICR line: 9 digits, often isolated at the bottom of a cheque.
MICR_RE = re.compile(r"\b\d{9}\b")


def find_gstin(text: str) -> str | None:
    m = GSTIN_RE.search(text.upper())
    return m.group(0) if m else None


def find_pan(text: str, *, exclude: str | None = None) -> str | None:
    """Find a PAN. If `exclude` is given (e.g. a GSTIN already found), skip a
    PAN-shaped match that merely sits *inside* that GSTIN's own span in the
    text (chars 3-12 of a GSTIN happen to look like a PAN). This is
    positional, not value-based: a PAN that is genuinely printed elsewhere
    in the document -- even one that (correctly) has the same value as the
    one embedded in the GSTIN, which is the normal case -- is still found."""
    upper = text.upper()
    exclude_span = None
    if exclude:
        m = re.search(re.escape(exclude.upper()), upper)
        if m:
            exclude_span = m.span()
    for m in PAN_RE.finditer(upper):
        if exclude_span and exclude_span[0] <= m.start() and m.end() <= exclude_span[1]:
            continue
        return m.group(0)
    return None


def pan_from_gstin(gstin: str) -> str | None:
    """A GSTIN embeds the holder's PAN in characters 3-12 (0-indexed 2:12)."""
    if gstin and GSTIN_RE.fullmatch(gstin):
        return gstin[2:12]
    return None


def find_ifsc(text: str) -> str | None:
    m = IFSC_RE.search(text.upper())
    return m.group(0) if m else None


def find_pin(text: str) -> str | None:
    m = PIN_RE.search(text)
    return m.group(0) if m else None


def find_mobile(text: str) -> str | None:
    m = MOBILE_RE.search(text)
    return m.group(0) if m else None


def find_email(text: str) -> str | None:
    m = EMAIL_RE.search(text)
    return m.group(0) if m else None


def find_all_emails(text: str) -> list[str]:
    seen: list[str] = []
    for m in EMAIL_RE.finditer(text):
        val = m.group(0)
        if val not in seen:
            seen.append(val)
    return seen


def find_udyam(text: str) -> str | None:
    m = UDYAM_RE.search(text.upper())
    return m.group(0) if m else None


def find_account_number(text: str, *, exclude: set[str] | None = None) -> str | None:
    """Find a plausible bank account number: a 9-18 digit run that is not a
    PIN code, mobile number, or other already-claimed numeric token."""
    exclude = exclude or set()
    for m in ACCT_NO_RE.finditer(text):
        candidate = m.group(0)
        if candidate in exclude:
            continue
        return candidate
    return None


def is_valid_gstin(value: str) -> bool:
    return bool(GSTIN_RE.fullmatch(value or ""))


def is_valid_pan(value: str) -> bool:
    return bool(PAN_RE.fullmatch(value or ""))


def is_valid_ifsc(value: str) -> bool:
    return bool(IFSC_RE.fullmatch(value or ""))


def is_valid_pin(value: str) -> bool:
    return bool(PIN_RE.fullmatch(value or ""))


def is_valid_mobile(value: str) -> bool:
    return bool(MOBILE_RE.fullmatch(value or ""))


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_RE.fullmatch(value or ""))


def is_valid_udyam(value: str) -> bool:
    return bool(UDYAM_RE.fullmatch(value or ""))


def looks_like_structured_code(value: str) -> bool:
    """True if `value` is (or is entirely) a GSTIN/PAN/IFSC/UDYAM-shaped
    token. Used to sanity-check label-anchored "name" extractions on messy
    real-world OCR'd tables: when a label's neighboring-line lookahead lands
    on the wrong cell, it tends to land on a *different* field's ID-shaped
    value rather than a name -- e.g. "Owner Name" accidentally capturing the
    PAN "AABCM7980K" instead of a person's name. A real name never matches
    one of these formats, so rejecting such a capture is a cheap, safe way
    to fail closed (leave the field blank for human entry) instead of
    confidently returning something wrong."""
    candidate = (value or "").strip().upper()
    if not candidate:
        return False
    return any(
        pattern.fullmatch(candidate)
        for pattern in (GSTIN_RE, PAN_RE, IFSC_RE, UDYAM_RE)
    )
