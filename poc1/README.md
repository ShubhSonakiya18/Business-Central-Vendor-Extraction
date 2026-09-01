# Vendor Document Intake & Verification API

Fully local, CPU-only extraction of standard vendor onboarding documents
(GST Registration Certificate, PAN Card, Cancelled Cheque, Udyam
Registration Certificate) into a fixed 17-field vendor-onboarding sheet,
with a human-review/correction step and Excel export.

**No document content is ever sent to an external service.** OCR runs
locally via PaddleOCR (PP-OCRv6, CPU-only). Government/provider verification
(e.g. a GST portal lookup) is a separate capability, gated behind
`ENABLE_GOVERNMENT_VERIFICATION` and **off by default** — this build does
not call out anywhere.

## Architecture at a glance

```
Upload (multipart)
   -> Document(status=uploaded), saved to storage/uploads/<vendor_id>/
   -> BackgroundTask: app.pipeline.process_document(document_id)
        1. app.ocr.text_extraction  -- native PDF text layer first,
                                        OCR (PaddleOCR) rasterization fallback,
                                        direct OCR for images
        2. app.classification       -- rule-based doc-type classifier
        3. app.extraction.*         -- label-anchored + regex field parsers
                                        per document type (gst/udyam/pan/cheque)
        4. app.extraction.merge     -- upsert ExtractedField, highest
                                        confidence wins, human edits are
                                        never overwritten
        5. Document.status = done/failed; Vendor.status auto-advances
           draft -> processing -> review
GET  /api/vendors/{id}/extraction   -- current merged view, poll this while
                                        processing is in flight
PUT  /api/vendors/{id}/extraction   -- human corrections (always win)
POST /api/vendors/{id}/approve      -- review -> approved
GET  /api/vendors/{id}/excel        -- generate + download the .xlsx
```

## Setup

### 1. Python

Python 3.11–3.13 all work (paddleocr/paddlepaddle 3.x officially support
that range). Developed/tested here on 3.12.

```bash
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

`requirements.txt` installs the **CPU** build of PaddlePaddle
(`paddlepaddle==3.2.0`) — do **not** install `paddlepaddle-gpu`, it pulls
CUDA wheels this pipeline has no use for. Install `paddleocr` bare (no
`[all]` extra) — see the warning box below for why.

> The OCR stack (`paddlepaddle` + `paddleocr`) is a large download and is
> only imported lazily, the first time a document actually needs OCR
> fallback (i.e. a scanned, non-text-layer PDF or a plain image). Every
> other module — the API, classification, regex parsers, Excel export —
> imports and runs fine even before you've installed it. If it's missing,
> OCR-dependent processing fails that one document with a clear
> `OCRUnavailableError` message instead of crashing the app; text-layer PDFs
> (most digitally generated GST/Udyam certs) never touch it at all. **Many
> real-world Udyam/GST certificates downloaded from the government portal
> are scanned/rasterized PDFs with no text layer at all** — for those, OCR
> isn't a fallback, it's required, so install it if you want those
> documents to extract anything.

> **Don't use `paddleocr[all]`, and don't use `paddleocr`/`paddlepaddle`
> older than `paddleocr==3.7.0` / the `paddlex` it pulls in.** Older
> `paddleocr`/`paddlex` releases (anything pulling in `paddlex<3.7`,
> including the `[all]` extra on 3.2.x) eagerly import an unrelated
> doc-retrieval/RAG pipeline component at `import paddleocr` time that
> hard-imports `langchain.docstore` — a module removed from modern
> LangChain — so the import crashes with
> `ModuleNotFoundError: No module named 'langchain.docstore'` before OCR
> ever runs, even though this pipeline never touches that feature.
> `paddleocr==3.7.0` (pulling `paddlex==3.7.2`) fixed this; `requirements.txt`
> is pinned there. Also note PP-OCRv6's real model-name convention is
> `PP-OCRv6_{tiny,small,medium}_{det,rec}` — **not** `..._mobile_...` (that
> was the older PP-OCRv3/v4/v5 naming) — `app/config.py`'s
> `OCR_DET_MODEL`/`OCR_REC_MODEL` defaults are already set correctly
> (`PP-OCRv6_small_det`/`PP-OCRv6_small_rec`); if you override them via env
> vars, use the same naming.

### 2. System dependency: poppler (only needed for the pdf2image fallback path)

PDF rasterization for the OCR fallback normally uses `pymupdf`, which needs
no system dependencies. `pdf2image` is only invoked as a second-line
fallback if `pymupdf` rasterization itself fails, and it requires
[poppler](https://github.com/oschwartz10612/poppler-windows) on `PATH`:

- **Windows**: download a poppler release, unzip, add its `bin/` folder to `PATH`.
- **macOS**: `brew install poppler`
- **Debian/Ubuntu**: `sudo apt-get install poppler-utils`

### 3. Database

SQLite, zero config. The app bootstraps its schema automatically on startup
via `Base.metadata.create_all()` (see `app/database.py`) — no separate
migration step needed for v1. The DB file lives at
`storage/vendor_intake.db` by default.

### 4. Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger UI: http://localhost:8000/docs
- OpenAPI 3.1 schema: http://localhost:8000/openapi.json
- Health check: http://localhost:8000/health

> **Uploading multiple files from Swagger UI**: on `POST /documents`, click
> "Try it out" then "Add string item" once per file under `files` — each row
> gets its own "Choose File" button. (The raw OpenAPI 3.1 schema for a file
> field uses `contentMediaType`, which not every Swagger UI build renders as
> a file picker; `app/main.py` patches the served schema to also carry the
> older `format: binary` keyword so `/docs` always shows a real file chooser
> instead of a text box.)

### Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `STORAGE_DIR` | `./storage` | Uploaded files, generated Excel files, SQLite DB |
| `DATABASE_URL` | `sqlite:///./storage/vendor_intake.db` | SQLAlchemy URL — swap to Postgres later, no code changes needed |
| `OCR_DET_MODEL` | `PP-OCRv6_mobile_det` | PaddleOCR detection model |
| `OCR_REC_MODEL` | `PP-OCRv6_mobile_rec` | PaddleOCR recognition model |
| `OCR_LANG` | `en` | PaddleOCR recognition language |
| `PDF_RASTER_DPI` | `300` | Rasterization DPI when a PDF has no usable text layer |
| `MIN_TEXT_LAYER_CHARS` | `40` | Below this char count, a PDF page is treated as scanned and OCR'd |
| `ENABLE_GOVERNMENT_VERIFICATION` | `false` | Off by default; this build never calls any external verification service regardless |
| `MAX_UPLOAD_MB` | `25` | Per-file upload size cap |

## API

```
GET    /health
GET    /api/system/status

POST   /api/vendors
GET    /api/vendors/{vendor_id}

POST   /api/vendors/{vendor_id}/documents          bulk multipart upload -> async processing
GET    /api/vendors/{vendor_id}/documents           per-document status/classification
DELETE /api/vendors/{vendor_id}/documents/{document_id}

GET    /api/vendors/{vendor_id}/extraction          merged field state + processing status; poll this
PUT    /api/vendors/{vendor_id}/extraction          human corrections -- {"fields": {"payment_terms": "Net 30", ...}}

POST   /api/vendors/{vendor_id}/approve

GET    /api/vendors/{vendor_id}/excel                generate + download the .xlsx
```

`GET .../extraction` returns, per field: current value, which document/method
it came from, a confidence score, and whether a human has already edited it
— plus a document checklist (which of GST/PAN/Cheque/Udyam were uploaded)
and a `processing` block your client can poll (`documents_total`,
`..._done`, `..._failed`, `is_complete`) since OCR on CPU is slow and
uploads process asynchronously via `BackgroundTasks`.

A human edit made through `PUT .../extraction` is permanent: later
re-processing (re-uploading a document, reprocessing) will never overwrite
a field once `is_human_edited=true`.

## Target Excel layout

`GET /api/vendors/{vendor_id}/excel` produces a two-column sheet (bold
labels, bordered cells) with exactly this row order:

```
Company Name | Contact Name | Billing Address | City | State |
Zip code/Pin code | Country | GST(ABN,TRN) Registration Certificate |
PAN Card (Company/Individual) | Email ID TO | Email ID CC | Phone Number |
Payment Terms | SALESPERSON | REGION |
Customer Agreement / Contract/Purchase Order/Sale Order | Type
```

`Payment Terms`, `SALESPERSON`, `Customer Agreement...`, `Type`, and
`Email ID CC` are never populated from a document — they stay blank until a
human fills them in via `PUT .../extraction`. `REGION` gets a suggested
default derived from `State` (e.g. West Bengal → East) but stays fully
editable. Bank details extracted from a cancelled cheque (Bank Name,
Branch, IFSC Code, Account Number, Account Holder Name) are stored and
returned by `GET .../extraction` under `bank_details`, but are not part of
the literal 17-row Excel layout.

## Document classification

Purely rule-based (see `app/classification.py`), no ML model:

| Document | Signal |
|---|---|
| GST Certificate | "Form GST REG-06" / "Registration Certificate" + GSTIN pattern |
| PAN Card | "INCOME TAX DEPARTMENT" / "Permanent Account Number" + PAN pattern, short document |
| Udyam Certificate | "UDYAM REGISTRATION CERTIFICATE" + UDYAM number pattern |
| Cancelled Cheque | IFSC pattern + account-number/MICR signals. The handwritten "CANCELLED" scrawl is recorded only as a low-confidence `is_cancelled` flag — nothing in the pipeline depends on it. |
| Other | Anything unrecognized — still OCR'd and stored (`raw_text`) for manual review, no field extraction attempted |

## Testing

```bash
pytest tests/ -v
```

`tests/fixtures/make_fixtures.py` synthesizes fictional GST/Udyam/PAN/cheque
documents as text-layer PDFs (via `reportlab`) laid out the way the real
government forms are — no real production documents are used or needed.
Because these fixtures carry a genuine PDF text layer, the suite exercises
the primary (non-OCR) extraction path without requiring the PaddleOCR model
weights to be downloaded; OCR-fallback code paths are structured so they're
independently testable once you have `paddleocr` installed, by pointing
`extract_document_text` at a scanned/rasterized fixture.

Coverage: regex/validators (`test_patterns.py`), document classification
(`test_classification.py`), label-anchored address parsing
(`test_address_parsing.py`), per-document-type field parsers
(`test_field_extraction.py`), Excel row order/values
(`test_excel_export.py`), the full API flow — create vendor, upload, poll,
correct, approve, download — (`test_api.py`), and a regression suite run
against a **frozen capture of real PaddleOCR output from an actual scanned
Udyam certificate** (`test_real_udyam_ocr.py` / `fixtures/sample_udyam_real_ocr.txt`)
— real government-portal table layouts interleave labels and values across
OCR lines in ways the clean synthetic fixtures never exercise, and this
caught several real bugs (see Known limitations below) that the synthetic
fixtures alone didn't surface.

## Known limitations

- **Real-world multi-column table rows can still throw off label-anchored
  fields that don't have a validatable shape.** PaddleOCR emits one text
  box per detected line; on a real scanned government form, a 2-column
  table row's four cells (label, value, label, value) don't always come
  back in that logical order — sometimes a value lands *before* its own
  label. Fields with a hard-validatable format (GSTIN/PAN/IFSC/mobile/
  email/PIN/state name) have an independent whole-text regex/name-list
  fallback that recovers from this reliably (see `app/extraction/address.py`
  and each doc-type parser). Free-text fields without a validatable shape
  (Contact Name, and the finer-grained Road/Building sub-parts of Billing
  Address) can still occasionally pick up a plausible-looking but wrong
  neighboring cell on a badly-scrambled row. As a safety net, a "name"
  field is never allowed to end up looking like a structured ID code (see
  `looks_like_structured_code` in `app/patterns.py`) — it's left blank for
  human entry instead of confidently returning something wrong. Getting
  this fully right in the general case would need spatial (bounding-box
  coordinate) table reconstruction from the OCR engine's per-line polygons
  rather than pure line-sequence heuristics.
- **A PDF's native text layer can be present but corrupted (garbled/
  "mojibake") rather than absent** — observed on a real cancelled-cheque
  sample, where `pymupdf`/`pdfplumber` both report plenty of characters
  (so the current `MIN_TEXT_LAYER_CHARS` sufficiency check accepts it) but
  many letters are scrambled by what looks like a broken font ToUnicode
  CMap in the source PDF, while digits mostly survive intact. On that
  sample, digit-shaped fields (account number) still extract fine via
  regex, but the IFSC code — which needs 4 correct letters — doesn't, and
  the document misclassifies as `other` entirely (the classifier never
  gets a chance to see a valid IFSC or the account-label context it
  expects), so no cheque field extraction runs on it at all in the actual
  pipeline. Fixing this generally needs either a "does this text layer
  contain any of the structured patterns we'd expect" plausibility check
  (with the risk of false-triggering unnecessary OCR reruns on legitimate
  plain-text pages) or a manual "reprocess this document with OCR forced"
  escape hatch exposed to the reviewer. Not yet implemented.

## Notes / design decisions

- **SQLite now, Postgres-ready later**: models use plain SQLAlchemy types
  with no SQLite-specific column types, so changing `DATABASE_URL` is the
  only step needed to move to Postgres.
- **Merge strategy**: each field parser assigns its own confidence per
  value (e.g. GST "Legal Name" → 0.9 vs Udyam "Name of Enterprise" → 0.7 vs
  a cheque payee name → 0.4 for Company Name); the merge step just keeps
  the highest-confidence value across all of a vendor's documents, which is
  how "prefer GST Legal Name" falls out naturally without special-casing.
- **Never overwrite human edits**: `is_human_edited=true` locks a field
  against any future automated re-run, including re-uploads.
- **One bad file never crashes the batch**: every processing stage is
  wrapped per-document; a failure lands as `Document.status="failed"` +
  `error_message`, and the rest of the batch/vendor keeps going.
