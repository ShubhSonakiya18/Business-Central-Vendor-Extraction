"""
V2: fully local, offline vendor document extraction.

No cloud APIs. Document understanding is PaddleOCR + native parsers, and
field identification (added in later steps) is a deterministic local engine
driven by YAML configuration rather than hardcoded per-document logic.

Implemented so far: Steps 1-4 -- common document representation, PaddleOCR
wrapper, multi-document loading, and the YAML-driven field dictionary.
"""

from .models import (
    RENDER_DPI,
    BBox,
    Document,
    DocumentSet,
    DocumentType,
    Page,
    SpanSource,
    TableRef,
    TextSpan,
)
from .document_loader import load_document, load_documents
from .ocr_engine import OCREngine
from .config_loader import (
    ConfigError,
    FieldDictionary,
    FieldSpec,
    ValidationRules,
    ValidatorSpec,
    load_config,
    load_field_dictionary,
    load_validation_rules,
)

__all__ = [
    "RENDER_DPI",
    "BBox",
    "Document",
    "DocumentSet",
    "DocumentType",
    "Page",
    "SpanSource",
    "TableRef",
    "TextSpan",
    "load_document",
    "load_documents",
    "OCREngine",
    "ConfigError",
    "FieldDictionary",
    "FieldSpec",
    "ValidationRules",
    "ValidatorSpec",
    "load_config",
    "load_field_dictionary",
    "load_validation_rules",
]
