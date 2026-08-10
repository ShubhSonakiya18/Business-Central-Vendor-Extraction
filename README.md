# Vendor Form Extractor

Reads a vendor's onboarding documents — GST certificate, Udyam registration, cancelled cheque — and auto-fills a Vendor Creation Request Form in Excel, then verifies every written cell against the source data.

Two extraction pipelines are included, served side by side from one FastAPI app:

| | Pipeline | Route | Requires |
|---|---|---|---|
| **V1** | Google Gemini (multimodal cloud API) | `/` | `GEMINI_API_KEY`, internet access |
| **V2** | PaddleOCR + a local, config-driven engine | `/v2` | Nothing — fully offline |

V2 is a ground-up rebuild for environments where vendor documents (PAN, GSTIN, bank details) can't leave the machine. Field knowledge — labels, patterns, validators, Excel cell mappings — lives entirely in YAML, not Python, so extending it to new fields or document types doesn't require touching the extraction code.

---

## Contents

- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Project layout](#project-layout)
- [V1 — Gemini pipeline](#v1--gemini-pipeline)
- [V2 — Local pipeline](#v2--local-pipeline)
- [Configuration](#configuration-v2)
- [CLI tools](#cli-tools-v2)
- [Known limitations](#known-limitations)

---

## How it works

```
documents → load / OCR → layout analysis → field matching → validation
          → canonical JSON → Excel fill → read-back verification → report
```

Both pipelines converge on the same **canonical JSON** shape (24 fields — vendor name, GSTIN, PAN, IFSC, bank account number, address, etc.), so the Excel writer and verifier are shared. V1 gets there via a single Gemini API call per document; V2 gets there via OCR + a deterministic local matching engine — no LLM involved at any point in V2.

---

## Quick start

### V1 — Gemini (cloud)

```bash
python -m venv .venv
.venv\Scripts\activate          # or: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # then edit .env and set GEMINI_API_KEY
uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000/`.

### V2 — Local (offline, no API key)

PaddlePaddle currently has no wheel for Python 3.14 — **use Python 3.12** for this environment.

```bash
py -3.12 -m venv .venv-paddle
.venv-paddle\Scripts\Activate.ps1     # or: source .venv-paddle/bin/activate
pip install -r requirements.txt -r requirements-v2.txt

uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000/v2`. If `google-genai` isn't installed in this environment, V1's routes automatically redirect to V2 rather than erroring.

**First run** downloads the OCR models (~100 MB) to `~/.paddlex/official_models/` — a one-time cost.

---

## Project layout

```
app/
├── main.py                         FastAPI entry point — wires routers, serves both V1 (/) and V2 (/v2)
│
├── core/
│   ├── config.py                   Loads .env into a typed Settings object; picks V1/V2 routing
│   └── logging.py                  Configures the root logger (V2's modules log via logging.getLogger)
│
├── routes/                         HTTP layer only — request in, response out
│   ├── vendor_v1.py                "/" and "/generate", "/results/*", "/download/*"  (Gemini)
│   └── vendor_v2.py                "/v2/*"  (local pipeline)
│
├── services/                       Business logic, framework-agnostic
│   ├── vendor_v1_gemini.py         V1: Gemini extraction + Excel fill (as originally written)
│   ├── vendor_v1_verify.py         V1: Excel read-back verification (as originally written)
│   ├── vendor_v1_service.py        V1: orchestrates the two modules above for the route
│   └── vendor_v2_service.py        V2: orchestrates app/pipelines/v2 for the route, typed errors
│
├── schemas/
│   └── vendor.py                   Canonical vendor JSON + verification report shapes (pydantic)
│
├── utils/
│   └── uploads.py                  Shared "save this UploadFile to disk" helper
│
├── pipelines/
│   └── v2/                         V2: fully local extraction pipeline
│       ├── models.py                Common document representation (spans, bboxes, pages)
│       ├── ocr_engine.py            PaddleOCR 3.x wrapper — only module that imports paddleocr
│       ├── document_loader.py       PDF / image / DOCX → common representation
│       ├── config_loader.py         Strict YAML loader for the field dictionary & rules
│       ├── layout_engine.py         Spatial queries: visual lines, label→value neighbours
│       ├── field_matcher.py         Scores candidate values per field (label + position + pattern + OCR confidence)
│       ├── semantic_engine.py       Classifies documents, merges candidates across them
│       ├── normalizer.py            Value cleanup ops (uppercase, digit fixes, etc.)
│       ├── validator.py             Generic rule executor — regex / length / enum / cross-field
│       ├── excel_mapper.py          Fills a template from a YAML cell map
│       ├── verifier.py              Reopens the saved file, diffs every cell, colours PASS/FAIL
│       ├── pipeline.py              Wires the above end to end; CLI entry point
│       ├── dump_ocr.py              CLI: inspect raw OCR/document output
│       └── check_config.py          CLI: validate the YAML config, no OCR needed
│
├── config/                          V2's field knowledge — edit this, not Python, to change behaviour
│   ├── field_dictionary.yaml        24 fields: labels, regex patterns, validators, search rules
│   ├── validation_rules.yaml        15 validators (format + cross-document consistency)
│   ├── document_profiles.yaml       How a document is classified (GST cert vs cheque vs ...)
│   └── excel_mappings/
│       └── vendor_creation_v1.yaml  Field → Excel cell mapping
│
├── templates/                       Jinja2 templates (V1 + V2 upload/results/error pages)
└── static/                          Shared CSS

legacy/                              Superseded OCR/regex prototype (kept for reference)
.env / .env.example                  Environment values / template — GEMINI_API_KEY, routing, paths
```

---

## V1 — Gemini pipeline

Three documents, three Gemini calls, each against a JSON schema:

1. **GST certificate** → GSTIN, legal name, address, PIN
2. **Udyam certificate** → Udyam number, company type, nature of business, contact info
3. **Cancelled cheque** → bank name, branch, IFSC, account number

Cross-checks the PAN embedded in the GSTIN against the Udyam certificate's PAN field (GST certificate wins on conflict — it's the legal source of record), then runs six regex validators (GSTIN, PAN, IFSC, Udyam number, PIN, account number) and collects failures into `needs_review`.

Transient Gemini errors (503/429) retry with exponential backoff via `tenacity`.

## V2 — Local pipeline

### Document loading

| Input | How it's read |
|---|---|
| PDF with a real text layer | Read directly — near-instant, no OCR |
| Scanned PDF / image | Rasterized and passed through PaddleOCR |
| DOCX | Native paragraph/table parsing via `python-docx`; embedded images are OCR'd individually, not the whole page |

A page is only trusted at face value if its text layer is genuine — **image coverage**, not character count, decides. A scanned page whose embedded text layer is corrupted (a real case encountered during development — a cheque scan with a mangled OCR'd text layer already baked into the PDF) is re-OCR'd instead of trusted.

### OCR engine

PaddleOCR 3.7, PP-OCRv6 **small** models by default — benchmarked at ~9× faster than the default `medium` models with near-identical field-level accuracy, and the `tiny` variant was rejected after it hallucinated characters that weren't on the page.

### Field matching

For every OCR text span, the engine:
1. Checks if it resembles one of a field's configured caption labels (fuzzy-matched via `rapidfuzz`, tolerant of OCR damage)
2. Looks for a value to the right of / below that caption, within a configurable distance
3. Checks whether the candidate value's shape matches the field's regex pattern (if any)
4. Scores the candidate:

   ```
   score = 0.35 × label_similarity
         + 0.25 × spatial_proximity
         + 0.30 × pattern_match
         + 0.10 × ocr_confidence
   ```

Candidates below the configured confidence threshold, or that fail validation, are down-weighted before a winner is picked — not just flagged afterward.

### Multi-document merge

The same field can appear on more than one document. Candidates are pooled, and the winner is chosen by: validated score → the field's own `expected_documents` preference → a configured document-trust order → how the value was found (inline > adjacent > bare pattern match). Fields marked `cross_document_consistency` in config are compared across their source documents and flagged if they disagree.

### Validation

15 rules, defined once in `validation_rules.yaml`, referenced by name from field configs — including `derived` rules that check one field against another (e.g. the PAN embedded in a GSTIN must match the standalone PAN field).

### Excel fill & verification

Loads the template, writes only non-empty values, saves — then **reopens the saved file** and re-reads every mapped cell to confirm it matches what was extracted, colouring each PASS (green) / FAIL (red) and writing a JSON report. This catches a value that silently failed to write or was coerced to a different type by Excel — not just trusting the in-memory write.

---

## Configuration (V2)

Everything below is data, not code. The loader is strict on purpose: an unresolvable validator reference, an invalid regex, or confidence weights that don't sum to `1.0` fail at load time — naming the exact field — rather than silently producing a blank Excel cell later.

**Add a field** by adding a block to `app/config/field_dictionary.yaml`:
```yaml
ifsc:
  labels: [IFSC, IFSC Code, IFS Code, RTGS/NEFT/IFS Code]
  patterns: ['[A-Z]{4}0[A-Z0-9]{6}']
  normalization: [uppercase, remove_spaces, fix_ifsc_confusions]
  validators: [ifsc_format]
  expected_documents: [cancelled_cheque]
  required: true
```

**Add a validator** in `app/config/validation_rules.yaml`:
```yaml
pin_format:
  type: regex
  pattern: '[1-9][0-9]{5}'
  severity: error
  message: Not a valid 6-digit Indian PIN code
```

**Add an Excel template** by adding a file under `app/config/excel_mappings/`.

No Python changes are required for any of the above.

---

## CLI tools (V2)

```bash
# Validate the YAML config (fast, no OCR)
python -m app.pipelines.v2.check_config

# Inspect raw OCR/document output for a file or folder
python -m app.pipelines.v2.dump_ocr path/to/documents --out outputs/inspect

# Run the full pipeline end to end
python -m app.pipelines.v2.pipeline path/to/documents \
  --template "Vendor Form.xlsx" --sheet Sheet1 --out outputs/run

# Re-run extraction against a previously saved document set (skips OCR entirely)
python -m app.pipelines.v2.pipeline --cache outputs/inspect/document_set.json --out outputs/run
```

---

## Known limitations

- **Throughput**: scanned pages run ~10–35s each on CPU (PaddlePaddle's oneDNN acceleration is disabled to work around a CPU executor crash in PaddlePaddle 3.3.1 — see `v2/ocr_engine.py`). Fine for single-vendor use; page-level parallelism would be the next step for batch processing.
- **Bank name** is not reliably extractable from a cheque scan alone — cheques don't caption their own bank name, and OCR reads the logo as garbled text. An IFSC-prefix → bank-name lookup table is the planned fix, not yet implemented.
- **DOCX geometry is synthetic**: since Word documents carry no pixel coordinates, V2 lays text out on a synthesized canvas to preserve caption/value adjacency. This works for the matching engine but bounding boxes in DOCX output aren't real page positions.
- `requirements-v2.txt` pins the versions this was built and tested against; PaddleOCR/PaddlePaddle version bumps are not guaranteed compatible without re-testing.
