"""
V2 Common Document Representation
=================================
Every input format (searchable PDF, scanned PDF, image, DOCX) is reduced to
the same structure so the downstream layout/semantic engines never need to
know where a span of text came from.

Coordinate convention
---------------------
All bboxes are (x1, y1, x2, y2) with a TOP-LEFT origin and y increasing
downward -- the convention PaddleOCR uses. PDF native text is bottom-left
origin, so document_loader flips it on the way in.

All bboxes for a page are expressed in the SAME pixel space, defined by
`Page.width` / `Page.height` (the page rendered at `RENDER_DPI`). That means a
page read from the PDF text layer and a page read via OCR are directly
comparable, which matters because a single PDF can mix both.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Optional


# Everything is normalized into this pixel space. 200 DPI is a good tradeoff:
# high enough for PaddleOCR to read small print on cheques, low enough to keep
# per-page render + inference time reasonable.
RENDER_DPI = 200
PDF_POINTS_PER_INCH = 72.0


class SpanSource(str, Enum):
    """How a given text span was obtained. The semantic engine uses this to
    weight evidence -- native text is exact, OCR text can be misread, and
    DOCX geometry is synthesized rather than measured."""

    PDF_TEXT = "pdf_text"          # native PDF text layer (exact characters)
    OCR = "ocr"                    # PaddleOCR over a rendered/scanned page
    DOCX_PARAGRAPH = "docx_paragraph"
    DOCX_TABLE = "docx_table"
    DOCX_IMAGE_OCR = "docx_image_ocr"  # OCR of an image embedded in a DOCX


class DocumentType(str, Enum):
    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"


# ---------------------------------------------------------------------------
# GEOMETRY
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BBox:
    """Axis-aligned box, top-left origin."""

    x1: float
    y1: float
    x2: float
    y2: float

    @classmethod
    def from_polygon(cls, poly) -> "BBox":
        """PaddleOCR returns 4-point (possibly rotated) polygons; collapse to
        the axis-aligned bounds, which is what spatial matching needs."""
        xs = [float(p[0]) for p in poly]
        ys = [float(p[1]) for p in poly]
        return cls(min(xs), min(ys), max(xs), max(ys))

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0

    def as_list(self) -> list[float]:
        return [self.x1, self.y1, self.x2, self.y2]

    def vertical_overlap(self, other: "BBox") -> float:
        """Fraction of the shorter box's height that overlaps vertically.
        1.0 means the two boxes sit on the same text line."""
        top = max(self.y1, other.y1)
        bottom = min(self.y2, other.y2)
        overlap = max(0.0, bottom - top)
        shorter = min(self.height, other.height)
        return overlap / shorter if shorter > 0 else 0.0

    def horizontal_overlap(self, other: "BBox") -> float:
        left = max(self.x1, other.x1)
        right = min(self.x2, other.x2)
        overlap = max(0.0, right - left)
        shorter = min(self.width, other.width)
        return overlap / shorter if shorter > 0 else 0.0


# ---------------------------------------------------------------------------
# TEXT SPANS
# ---------------------------------------------------------------------------

@dataclass
class TableRef:
    """Where a span sits inside a table, when the source format tells us."""

    table_index: int
    row: int
    col: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TextSpan:
    """One atomic piece of text with its position on the page.

    `text`, `page`, `bbox`, `source_document` and `confidence` are the
    contract the downstream engines rely on; the rest is provenance that makes
    debugging and audit possible.
    """

    text: str
    page: int
    bbox: BBox
    source_document: str
    confidence: float = 1.0
    source: SpanSource = SpanSource.OCR
    # Index of the span within its page, in natural reading order.
    order: int = 0
    table: Optional[TableRef] = None
    # True when geometry was invented (DOCX) rather than measured. Spatial
    # scores derived from these boxes are directional, not metric.
    synthetic_bbox: bool = False

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "text": self.text,
            "page": self.page,
            "bbox": [round(v, 2) for v in self.bbox.as_list()],
            "source_document": self.source_document,
            "confidence": round(float(self.confidence), 4),
            "source": self.source.value,
            "order": self.order,
        }
        if self.table is not None:
            out["table"] = self.table.to_dict()
        if self.synthetic_bbox:
            out["synthetic_bbox"] = True
        return out


@dataclass
class Page:
    """A single page worth of spans, plus the pixel space they live in."""

    number: int
    width: float
    height: float
    spans: list[TextSpan] = field(default_factory=list)
    # "pdf_text", "ocr", "docx", "docx_image_ocr" -- how this page was read.
    extraction_method: str = "ocr"
    # Why OCR was chosen over the text layer ("no_text_layer",
    # "scanned_page(...)"), kept so an audit can explain the decision.
    ocr_reason: str = ""
    # Seconds spent extracting this page, for profiling large batches.
    duration_s: float = 0.0

    @property
    def text(self) -> str:
        return "\n".join(s.text for s in self.spans)

    def to_dict(self) -> dict:
        out = {
            "page": self.number,
            "width": round(self.width, 2),
            "height": round(self.height, 2),
            "extraction_method": self.extraction_method,
            "duration_s": round(self.duration_s, 3),
            "span_count": len(self.spans),
        }
        if self.ocr_reason:
            out["ocr_reason"] = self.ocr_reason
        out["spans"] = [s.to_dict() for s in self.spans]
        return out


@dataclass
class Document:
    """One input file, fully read."""

    path: str
    doc_type: DocumentType
    pages: list[Page] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def spans(self) -> list[TextSpan]:
        return [s for p in self.pages for s in p.spans]

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def duration_s(self) -> float:
        return sum(p.duration_s for p in self.pages)

    def iter_spans(self) -> Iterator[TextSpan]:
        for page in self.pages:
            yield from page.spans

    def to_dict(self) -> dict:
        return {
            "document": self.name,
            "path": self.path,
            "doc_type": self.doc_type.value,
            "page_count": len(self.pages),
            "span_count": len(self.spans),
            "duration_s": round(self.duration_s, 3),
            "metadata": self.metadata,
            "pages": [p.to_dict() for p in self.pages],
        }


@dataclass
class DocumentSet:
    """All documents supplied for one vendor. The semantic engine merges
    candidates across these, so each span keeps its source_document."""

    documents: list[Document] = field(default_factory=list)

    def __iter__(self) -> Iterator[Document]:
        return iter(self.documents)

    def __len__(self) -> int:
        return len(self.documents)

    @property
    def spans(self) -> list[TextSpan]:
        return [s for d in self.documents for s in d.spans]

    @property
    def duration_s(self) -> float:
        return sum(d.duration_s for d in self.documents)

    def to_dict(self) -> dict:
        return {
            "document_count": len(self.documents),
            "span_count": len(self.spans),
            "duration_s": round(self.duration_s, 3),
            "documents": [d.to_dict() for d in self.documents],
        }

    def save_json(self, path: str | Path, indent: int = 2) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=indent, ensure_ascii=False), encoding="utf-8")
        return p

    # -- round-trip ---------------------------------------------------------
    # Re-reading a saved document set lets the semantic engine be developed and
    # re-run in milliseconds against real OCR output, instead of paying ~3
    # minutes of inference for every iteration.

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentSet":
        documents: list[Document] = []
        for d in data.get("documents", []):
            pages: list[Page] = []
            for p in d.get("pages", []):
                spans = [
                    TextSpan(
                        text=s["text"],
                        page=s["page"],
                        bbox=BBox(*s["bbox"]),
                        source_document=s["source_document"],
                        confidence=s.get("confidence", 1.0),
                        source=SpanSource(s.get("source", "ocr")),
                        order=s.get("order", 0),
                        table=TableRef(**s["table"]) if s.get("table") else None,
                        synthetic_bbox=s.get("synthetic_bbox", False),
                    )
                    for s in p.get("spans", [])
                ]
                pages.append(
                    Page(
                        number=p["page"],
                        width=p["width"],
                        height=p["height"],
                        spans=spans,
                        extraction_method=p.get("extraction_method", "ocr"),
                        ocr_reason=p.get("ocr_reason", ""),
                        duration_s=p.get("duration_s", 0.0),
                    )
                )
            documents.append(
                Document(
                    path=d.get("path", d["document"]),
                    doc_type=DocumentType(d.get("doc_type", "pdf")),
                    pages=pages,
                    metadata=d.get("metadata", {}),
                )
            )
        return cls(documents=documents)

    @classmethod
    def load_json(cls, path: str | Path) -> "DocumentSet":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# EXTRACTION RESULTS
# ---------------------------------------------------------------------------

@dataclass
class FieldResult:
    """The chosen value for one field, plus everything needed to defend it.

    The pipeline exposes a flat canonical dict for the Excel layer, but keeps
    this alongside it so any cell can be traced back to the document, page and
    caption it came from.
    """

    key: str
    value: Optional[str] = None
    confidence: float = 0.0
    source_document: Optional[str] = None
    source_page: Optional[int] = None
    matched_label: Optional[str] = None
    match_kind: Optional[str] = None
    validation_status: str = "not_validated"   # valid | invalid | warning | missing
    validation_messages: list[str] = field(default_factory=list)
    consistency: str = "not_checked"           # consistent | inconsistent | single_source
    alternatives: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_present(self) -> bool:
        return bool(self.value)

    def to_dict(self) -> dict:
        return {
            "field": self.key,
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "source_document": self.source_document,
            "source_page": self.source_page,
            "matched_label": self.matched_label,
            "match_kind": self.match_kind,
            "validation_status": self.validation_status,
            "validation_messages": self.validation_messages,
            "consistency": self.consistency,
            "alternatives": self.alternatives,
            "notes": self.notes,
        }


@dataclass
class ExtractionResult:
    """Everything the V2 pipeline produces for one vendor."""

    fields: dict[str, FieldResult] = field(default_factory=dict)
    needs_review: list[dict] = field(default_factory=list)
    documents: list[dict] = field(default_factory=list)
    duration_s: float = 0.0

    def canonical(self) -> dict:
        """The flat vendor JSON, shaped exactly like V1's so the Excel writer
        and verifier need no changes. `needs_review` is carried along for
        parity with V1's output."""
        out: dict[str, Any] = {k: (r.value or None) for k, r in self.fields.items()}
        out["needs_review"] = [item["field"] for item in self.needs_review]
        return out

    def to_dict(self) -> dict:
        return {
            "canonical": self.canonical(),
            "fields": {k: r.to_dict() for k, r in self.fields.items()},
            "needs_review": self.needs_review,
            "documents": self.documents,
            "duration_s": round(self.duration_s, 3),
            "summary": self.summary(),
        }

    def summary(self) -> dict:
        total = len(self.fields)
        filled = sum(1 for r in self.fields.values() if r.is_present)
        valid = sum(1 for r in self.fields.values() if r.validation_status == "valid")
        return {
            "total_fields": total,
            "filled": filled,
            "empty": total - filled,
            "valid": valid,
            "needs_review": len(self.needs_review),
            "fill_rate": round(filled / total * 100) if total else 0,
        }

    def save_json(self, path: str | Path, indent: int = 2) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=indent, ensure_ascii=False), encoding="utf-8")
        return p
