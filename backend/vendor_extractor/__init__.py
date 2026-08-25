"""
Fully local, offline vendor document extraction.

No cloud APIs and no network calls: document understanding is PaddleOCR plus
native parsers, and field identification is a deterministic local engine driven
by YAML configuration rather than hardcoded per-document logic.

Modules are grouped by the stage they belong to, following the data flow:

    models.py, config_loader.py   shared by every stage
    pipeline.py                   orchestration, end to end
    ingest/                       documents -> common representation
    extract/                      spans -> judged field values
    excel/                        result -> filled and verified workbook

The package carries no web-framework dependencies, so the web app, the CLI
entry points and the eval harness all drive it the same way.
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
from .ingest.document_loader import load_document, load_documents
from .ingest.ocr_engine import OCREngine
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
