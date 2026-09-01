"""Label-anchored address parsing for structured government forms.

We deliberately do NOT try to regex a free-form address out of noisy OCR
text. GST/Udyam certificates lay their address out as consistent
label: value pairs (often in a table), so we:

  1. Find each known label ("Building No./Flat No.", "Road/Street",
     "City/Town/Village", "District", "State", "PIN Code") in the text and
     take the value on the same line / immediately following line.
  2. Assemble Building + Road/Street -> Billing Address, City/Town/Village
     -> City, State -> State (validated against the static state/UT list),
     PIN Code -> Zip code via PIN_RE.
  3. Only when nothing labeled is found at all do we fall back to a generic
     "look for a 6-digit PIN and a known state name anywhere in the text"
     pass, for unlabeled free text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.patterns import PIN_RE
from app.states import ALL_STATES_AND_UTS, normalize_state

BUILDING_LABELS = [
    "Building No./Flat No.", "Building No. / Flat No.", "Building No/Flat No",
    "Building/Flat No", "Flat/Door/Block No", "Door No", "Building No",
]
ROAD_LABELS = [
    "Road/Street/Lane", "Road/Street", "Street/Road", "Road / Street", "Street",
]
CITY_LABELS = [
    "City/Town/Village", "City / Town / Village", "Town/Village",
    "Village/Town", "City",
]
DISTRICT_LABELS = ["District"]
STATE_LABELS = ["State"]
PIN_LABELS = ["PIN Code", "PIN code", "Pincode", "PIN", "Postal Code", "Postal code"]
GENERIC_ADDRESS_LABELS = [
    "Official Address of Enterprise", "Address of Enterprise",
    "Registered Office Address", "Principal Place of Business", "Address",
]

# Labels that, if they appear inside a captured value, mean OCR/text-layer
# ran two label:value pairs together on one line -- trim the value there.
# Also used to recognize when a lookahead candidate line (see
# extract_label_value) is actually a *different* field's label rather than
# a real value -- deliberately broader than just the address labels above,
# since real-world OCR'd forms interleave labels from every section
# (Mobile/Email/PAN/bank/name fields, plus assorted table headers) onto
# adjacent lines with no layout cue distinguishing them from a value.
_CROSS_DOC_LABELS = [
    "Mobile", "Mobile No", "Mobile No.", "Mobile Number", "Email", "E-mail",
    "Email ID", "Email Id", "PAN", "PAN No", "PAN Number", "GSTIN",
    "Owner Name", "Name of Owner", "Name of the Owner", "Name of Enterprise",
    "Name of Enterprise, if any", "Enterprise Name", "Legal Name",
    "Legal Name of Business", "Trade Name", "Trade Name, if any",
    "Name of the Person", "Name of Person", "Director's Name",
    "Name of Director", "Name of Proprietor", "Name of Karta", "Name",
    "IFSC", "IFS Code", "IFSC Code", "Account No", "A/C No", "Account No.",
    "Account Number", "A/C Number", "Account Holder Name", "A/C Holder Name",
    "Account Holder", "Bank Name", "Bank", "Branch", "Branch Name",
    "Branch Address", "Bank Details", "Type of Organisation",
    "Type of Enterprise", "Major Activity", "Do you have GSTIN",
    "Social Category", "Gender", "Specially Abled", "Specially Abled(DIVYANG)",
    "Date of Incorporation", "Date of Commencement",
    "Date of Commencement of Production/Business", "Employment Details",
    "Block", "Name of Premises/ Building", "Name of Premises/Building",
    "Name of Premises", "Latitude", "Longitude", "Unit Name",
]

ALL_KNOWN_LABELS = (
    BUILDING_LABELS + ROAD_LABELS + CITY_LABELS + DISTRICT_LABELS
    + STATE_LABELS + PIN_LABELS + GENERIC_ADDRESS_LABELS + _CROSS_DOC_LABELS
)
# Backwards-compatible alias (used as the default `stop_labels` for trimming).
_ALL_LABELS_FOR_TRIM = ALL_KNOWN_LABELS

# Exact-match (not substring) lookup for the "is this OCR line itself just a
# label, not a value?" check -- normalized to lowercase with trailing
# punctuation stripped, since OCR/text-layer output is inconsistent about
# whether a label line carries its own colon/period (e.g. "Mobile No." vs
# "Mobile No" vs "PAN").
_KNOWN_LABEL_SET = {lbl.strip().lower().rstrip(".:-") for lbl in ALL_KNOWN_LABELS}


def _looks_like_a_label(line: str) -> bool:
    return line.strip().lower().rstrip(".:-") in _KNOWN_LABEL_SET


def _has_content(value: str) -> bool:
    """A captured value is only meaningful if it has at least one
    alphanumeric character -- guards against a lone leftover separator
    (e.g. a label like "Flat/Door/Block No." captured as just "." when its
    real value landed on the next OCR line instead of the same one)."""
    return bool(re.search(r"[A-Za-z0-9]", value))


def _trim_at_next_label(value: str, stop_labels: list[str]) -> str:
    cut = len(value)
    for label in stop_labels:
        m = re.search(re.escape(label), value, re.IGNORECASE)
        if m and m.start() < cut and m.start() > 0:
            cut = m.start()
    return value[:cut].strip(" ,:-\t")


def extract_label_value(text: str, labels: list[str], stop_labels: list[str] | None = None) -> str | None:
    """Find the first of `labels` in `text` and return the associated value,
    whether it's on the same line ("Label: value") or the next non-empty
    line (common in table-like OCR/text-layer output)."""
    if not text:
        return None
    stop_labels = stop_labels if stop_labels is not None else _ALL_LABELS_FOR_TRIM
    lines = [l.strip() for l in text.splitlines()]
    label_alt = "|".join(re.escape(l) for l in sorted(labels, key=len, reverse=True))
    line_pattern = re.compile(rf"^(?:{label_alt})\s*[:\-]?\s*(.*)$", re.IGNORECASE)

    for i, line in enumerate(lines):
        m = line_pattern.match(line)
        if not m:
            continue
        value = m.group(1).strip(" :-\t")
        if value and _has_content(value):
            return _trim_at_next_label(value, stop_labels)
        # Same-line capture was empty (or just leftover punctuation, e.g. the
        # "." left behind by a label like "Flat/Door/Block No.") -- the real
        # value is almost always the very next OCR line in these table-style
        # forms. Skip over any candidate line that is itself a recognized
        # label (a neighboring field's label, or a table column header that
        # happens to match one of our labels) rather than returning it as if
        # it were this label's value.
        for j in range(i + 1, min(i + 5, len(lines))):
            nxt = lines[j].strip()
            if not nxt or not _has_content(nxt) or _looks_like_a_label(nxt):
                continue
            return _trim_at_next_label(nxt, stop_labels)

    # Fallback: label might not be line-anchored (OCR merged multiple
    # label:value pairs onto one physical line). Separator is mandatory and
    # whitespace is restricted to horizontal-only here, specifically so this
    # can never bleed across a newline into the next label/line (e.g. a bare
    # word like "Bank" appearing at the end of a letterhead line such as
    # "HDFC BANK" must NOT swallow the following line as its value).
    full_pattern = re.compile(rf"(?:{label_alt})[ \t]*[:\-][ \t]*([^\n]+)", re.IGNORECASE)
    m = full_pattern.search(text)
    if m:
        return _trim_at_next_label(m.group(1).strip(), stop_labels)
    return None


@dataclass
class ParsedAddress:
    billing_address: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    used_generic_fallback: bool = False


def _find_state_anywhere(text: str) -> str | None:
    for candidate in ALL_STATES_AND_UTS:
        if re.search(rf"\b{re.escape(candidate)}\b", text, re.IGNORECASE):
            return candidate
    return None


def parse_address(text: str) -> ParsedAddress:
    building = extract_label_value(text, BUILDING_LABELS)
    road = extract_label_value(text, ROAD_LABELS)
    city = extract_label_value(text, CITY_LABELS)
    state_raw = extract_label_value(text, STATE_LABELS)
    pin_raw = extract_label_value(text, PIN_LABELS)

    billing_parts = [p for p in (building, road) if p]
    billing_address = ", ".join(billing_parts) if billing_parts else None

    # State and Zip both have a hard-validatable shape (a fixed name list /
    # a 6-digit pattern), so -- like Mobile/Email/PAN elsewhere in this
    # package -- they get their own whole-text fallback whenever the
    # label-anchored attempt didn't land on something valid, independent of
    # whether Building/Road/City happened to match. This matters a lot on
    # real-world OCR'd table layouts: a label can land next to the *wrong*
    # neighboring cell's text (see extract_label_value's lookahead), so
    # "State" might capture "District" or a stray table header instead of
    # the actual state name -- normalize_state() rejects that garbage and
    # we fall back to finding the real state name wherever it landed in the
    # document instead of trusting the (possibly mismatched) label position.
    state = normalize_state(state_raw) if state_raw else None
    if not state:
        state = _find_state_anywhere(text)

    zip_code = None
    if pin_raw:
        m = PIN_RE.search(pin_raw)
        zip_code = m.group(0) if m else None
    if not zip_code:
        m = PIN_RE.search(text)
        zip_code = m.group(0) if m else None

    used_generic = False
    if not billing_address and not city and not state and not zip_code:
        # Nothing labeled matched at all -- generic fallback for unlabeled free text.
        used_generic = True
        generic_block = extract_label_value(text, GENERIC_ADDRESS_LABELS, stop_labels=[])
        if generic_block:
            billing_address = generic_block
    elif not billing_address:
        # We got some structured fields but no building/road -- try the
        # generic "Address" label as a whole-block fallback for the street part.
        generic_block = extract_label_value(text, GENERIC_ADDRESS_LABELS)
        if generic_block:
            billing_address = generic_block

    return ParsedAddress(
        billing_address=billing_address, city=city, state=state,
        zip_code=zip_code, used_generic_fallback=used_generic,
    )
