"""Shared types for per-document field parsers."""
from __future__ import annotations

from dataclasses import dataclass

from app.enums import ExtractionMethod, FieldName


@dataclass
class FieldResult:
    field_name: FieldName
    value: str
    method: ExtractionMethod
    confidence: float


def results_to_dict(results: list[FieldResult]) -> dict[FieldName, FieldResult]:
    out: dict[FieldName, FieldResult] = {}
    for r in results:
        if r.value:
            out[r.field_name] = r
    return out
