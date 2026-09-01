"""Document text acquisition: native PDF text-layer extraction first, OCR
rasterization fallback second, direct OCR for plain images.

Order of operations, per the spec:
  1. PDF: try direct text extraction (pymupdf, cross-checked with pdfplumber
     when available) since GST/Udyam certs are usually digitally generated,
     not scanned.
  2. Only if that text layer is empty/sparse, rasterize the page(s)
     (pymupdf at PDF_RASTER_DPI, pdf2image as a fallback rasterizer if
     pymupdf can't render for some reason) and run PP-OCRv6 over the image.
  3. Plain images (cheque photos/screenshots) always go straight to OCR.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.ocr.engine import OCRUnavailableError, run_ocr

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


@dataclass
class PageResult:
    page_number: int
    text: str
    source: str  # "text_layer" | "ocr"
    confidence: float | None = None


@dataclass
class DocumentTextResult:
    raw_text: str
    extraction_source: str  # "text_layer" | "ocr" | "mixed"
    ocr_confidence: float | None
    pages: list[PageResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _text_layer_for_pdf(path: Path) -> list[str]:
    """Native text layer per page via pymupdf, the primary extractor."""
    import pymupdf

    texts: list[str] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            texts.append(page.get_text("text") or "")
    return texts


def _text_layer_cross_check(path: Path, page_index: int) -> str | None:
    """Best-effort secondary extraction via pdfplumber, used only to sanity
    check / patch a sparse pymupdf result. Never fatal if unavailable."""
    try:
        import pdfplumber
    except Exception:
        return None
    try:
        with pdfplumber.open(path) as pdf:
            if page_index < len(pdf.pages):
                return pdf.pages[page_index].extract_text() or ""
    except Exception:
        return None
    return None


def _rasterize_pdf_page(path: Path, page_index: int, dpi: int) -> Path:
    """Render one PDF page to a PNG for OCR fallback. Prefers pymupdf
    (no system deps); falls back to pdf2image (needs poppler) if that fails."""
    tmp_dir = Path(tempfile.gettempdir())
    out_path = tmp_dir / f"vdi_raster_{path.stem}_{page_index}.png"
    try:
        import pymupdf

        with pymupdf.open(path) as doc:
            page = doc[page_index]
            zoom = dpi / 72.0
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            pix.save(out_path)
        return out_path
    except Exception:
        pass

    # Fallback: pdf2image (requires poppler on PATH -- see README).
    from pdf2image import convert_from_path

    images = convert_from_path(str(path), dpi=dpi, first_page=page_index + 1, last_page=page_index + 1)
    images[0].save(out_path)
    return out_path


def _is_sufficient(text: str) -> bool:
    return len((text or "").strip()) >= settings.MIN_TEXT_LAYER_CHARS


def extract_pdf(path: Path) -> DocumentTextResult:
    warnings: list[str] = []
    pages: list[PageResult] = []
    try:
        native_pages = _text_layer_for_pdf(path)
    except Exception as exc:
        native_pages = []
        warnings.append(f"native text-layer extraction failed: {exc}")

    any_ocr = False
    confidences: list[float] = []

    if native_pages:
        for i, text in enumerate(native_pages):
            if _is_sufficient(text):
                # Cross-check with pdfplumber; prefer whichever is longer (denser).
                alt = _text_layer_cross_check(path, i)
                if alt and len(alt.strip()) > len(text.strip()):
                    text = alt
                pages.append(PageResult(page_number=i + 1, text=text, source="text_layer"))
            else:
                pages.append(_ocr_pdf_page(path, i, warnings, confidences))
                any_ocr = True
    else:
        # No native pages at all (e.g. extraction totally failed) -- OCR every page.
        page_count = _pdf_page_count(path)
        for i in range(page_count):
            pages.append(_ocr_pdf_page(path, i, warnings, confidences))
            any_ocr = True

    raw_text = "\n\n".join(p.text for p in pages)
    if not pages:
        source = "text_layer"
    elif any_ocr and any(p.source == "text_layer" for p in pages):
        source = "mixed"
    elif any_ocr:
        source = "ocr"
    else:
        source = "text_layer"

    mean_conf = sum(confidences) / len(confidences) if confidences else None
    return DocumentTextResult(
        raw_text=raw_text, extraction_source=source, ocr_confidence=mean_conf,
        pages=pages, warnings=warnings,
    )


def _pdf_page_count(path: Path) -> int:
    try:
        import pymupdf
        with pymupdf.open(path) as doc:
            return doc.page_count
    except Exception:
        return 1


def _ocr_pdf_page(path: Path, index: int, warnings: list[str], confidences: list[float]) -> PageResult:
    try:
        image_path = _rasterize_pdf_page(path, index, settings.PDF_RASTER_DPI)
        result = run_ocr(str(image_path))
        if result.mean_confidence is not None:
            confidences.append(result.mean_confidence)
        return PageResult(
            page_number=index + 1, text=result.text, source="ocr",
            confidence=result.mean_confidence,
        )
    except OCRUnavailableError as exc:
        warnings.append(f"page {index + 1}: {exc}")
        return PageResult(page_number=index + 1, text="", source="ocr", confidence=None)
    except Exception as exc:
        warnings.append(f"page {index + 1}: OCR rasterization/recognition failed: {exc}")
        return PageResult(page_number=index + 1, text="", source="ocr", confidence=None)


def extract_image(path: Path) -> DocumentTextResult:
    result = run_ocr(str(path))
    return DocumentTextResult(
        raw_text=result.text,
        extraction_source="ocr",
        ocr_confidence=result.mean_confidence,
        pages=[PageResult(page_number=1, text=result.text, source="ocr", confidence=result.mean_confidence)],
    )


def extract_document_text(path: Path) -> DocumentTextResult:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return extract_pdf(path)
    if ext in IMAGE_EXTENSIONS:
        return extract_image(path)
    raise ValueError(f"Unsupported file extension: {ext}")
