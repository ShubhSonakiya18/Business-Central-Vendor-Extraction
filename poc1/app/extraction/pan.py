"""Field parser for a PAN Card."""
from __future__ import annotations

from app.enums import ExtractionMethod, FieldName
from app.extraction.address import extract_label_value
from app.extraction.common import FieldResult
from app.patterns import find_pan

NAME_LABELS = ["Name"]


def parse_pan_card(text: str) -> list[FieldResult]:
    results: list[FieldResult] = []

    pan = find_pan(text)
    if pan:
        results.append(FieldResult(FieldName.PAN_CARD, pan, ExtractionMethod.REGEX, 0.95))
        results.append(FieldResult(FieldName.COUNTRY, "India", ExtractionMethod.RULE, 0.9))

    # PAN cards print the individual/company name near the top, above "Name".
    name = extract_label_value(text, NAME_LABELS)
    if name:
        results.append(FieldResult(FieldName.CONTACT_NAME, name, ExtractionMethod.TEXT_LAYER, 0.5))

    return results
