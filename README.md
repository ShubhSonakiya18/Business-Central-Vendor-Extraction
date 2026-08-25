# Vendor Form Extractor

Reads a vendor's onboarding documents — GST certificate, Udyam registration, cancelled cheque — and auto-fills a Vendor Creation Request Form in Excel, then verifies every written cell against the source data.

Fully local: PaddleOCR plus a config-driven matching engine. No LLM, no API key, no network calls — documents never leave the machine. Field knowledge — labels, patterns, validators, Excel cell mappings — lives entirely in YAML, not Python, so extending it to new fields or document types doesn't require touching the extraction code.

---

## Contents

- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Project layout](#project-layout)
- [The pipeline](#the-pipeline)
- [Configuration](#configuration)
- [CLI tools](#cli-tools)
- [Known limitations](#known-limitations)

---

## How it works

```
documents → load / OCR → layout analysis → field matching → validation
          → canonical JSON → Excel fill → read-back verification → report
```

Everything converges on a single **canonical JSON** shape (24 fields — vendor name, GSTIN, PAN, IFSC, bank account number, address, etc.), produced deterministically by OCR + a local matching engine — no LLM involved at any point.

---

## Quick start

PaddlePaddle currently has no wheel for Python 3.14 — **use Python 3.12** for this environment. Build the venv with the 3.12 launcher explicitly; a bare `python -m venv` picks up whichever interpreter is first on PATH and the install then fails.

From the repository root:

```bash
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1            # or: source .venv/bin/activate
python -V                             # expect 3.12.x
pip install -r backend/requirements.txt
```

Then run the server from `backend/`:

```bash
cd backend
uvicorn main:app --reload
```
Open `http://127.0.0.1:8000/`.

**First run** downloads the OCR models (~100 MB) to `~/.paddlex/official_models/` — a one-time cost.

---

## Project layout

The Python half lives under `backend/`, the Jinja templates and CSS under `frontend/`. Within the backend, modules are grouped by the pipeline stage they belong to.

```
.venv/                              Local dev environment, Python 3.12 (gitignored)

frontend/
├── templates/                      Jinja2 templates (upload/results/error pages)
└── static/style.css                Shared CSS

backend/
├── main.py                         Entrypoint — app factory; `uvicorn main:app`
├── requirements.txt
├── pytest.ini
└── .env                            Local config, gitignored

backend/app/                        HTTP layer
├── config/settings.py              Paths, defaults, logging config
├── routers/extraction.py           Endpoints (thin: parse, call services, render)
├── services/extraction.py          Pipeline orchestration and user-facing failures
├── services/run_state.py           Per-run persistence under app/outputs/<run_id>/
├── models/  database/  schemas/    Reserved for the auth layer — not yet implemented
└── uploads/  outputs/  logs/       Runtime data, gitignored

backend/vendor_extractor/           The pipeline
├── models.py                       Common document representation (spans, bboxes, pages)
├── config_loader.py                Strict YAML loader for the field dictionary & rules
├── pipeline.py                     Wires the stages end to end; CLI entry point
├── ingest/                         Documents → common representation
│   ├── ocr_engine.py               PaddleOCR 3.x wrapper — only module that imports paddleocr
│   ├── document_loader.py          PDF / image / DOCX → common representation
│   └── layout_engine.py            Spatial queries: visual lines, label→value neighbours
├── extract/                        Spans → judged field values
│   ├── field_matcher.py            Scores candidates (label + position + pattern + OCR confidence)
│   ├── semantic_engine.py          Classifies documents, merges candidates across them
│   ├── normalizer.py               Value cleanup ops (uppercase, digit fixes, etc.)
│   └── validator.py                Generic rule executor — regex / length / enum / cross-field
└── excel/                          Result → workbook
    ├── excel_mapper.py             Fills a template from a YAML cell map
    └── verifier.py                 Reopens the saved file, diffs every cell, colours PASS/FAIL

backend/cli/                        Command-line entry points
├── check_config.py                 Validate the YAML config, no OCR needed
└── dump_ocr.py                     Inspect raw OCR/document output

backend/eval/                       Accuracy measurement against human-verified ground truth
backend/tests/                      Unit tests (no OCR — fast)

backend/config/                     The pipeline's field knowledge — edit this, not Python, to change behaviour
├── field_dictionary.yaml           24 fields: labels, regex patterns, validators, search rules
├── validation_rules.yaml           15 validators (format + cross-document consistency)
├── document_profiles.yaml          How a document is classified (GST cert vs cheque vs ...)
└── excel_mappings/
    └── vendor_creation_v1.yaml     Field → Excel cell mapping
```

---

## The pipeline

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

## Configuration

Everything below is data, not code. The loader is strict on purpose: an unresolvable validator reference, an invalid regex, or confidence weights that don't sum to `1.0` fail at load time — naming the exact field — rather than silently producing a blank Excel cell later.

**Add a field** by adding a block to `backend/config/field_dictionary.yaml`:
```yaml
ifsc:
  labels: [IFSC, IFSC Code, IFS Code, RTGS/NEFT/IFS Code]
  patterns: ['[A-Z]{4}0[A-Z0-9]{6}']
  normalization: [uppercase, remove_spaces, fix_ifsc_confusions]
  validators: [ifsc_format]
  expected_documents: [cancelled_cheque]
  required: true
```

**Add a validator** in `backend/config/validation_rules.yaml`:
```yaml
pin_format:
  type: regex
  pattern: '[1-9][0-9]{5}'
  severity: error
  message: Not a valid 6-digit Indian PIN code
```

**Add an Excel template** by adding a file under `backend/config/excel_mappings/`.

No Python changes are required for any of the above.

---

## CLI tools

Run these from `backend/`, with the venv activated.

```bash
# Validate the YAML config (fast, no OCR)
python -m cli.check_config

# Inspect raw OCR/document output for a file or folder
python -m cli.dump_ocr path/to/documents --out outputs/inspect

# Run the full pipeline end to end
python -m vendor_extractor.pipeline path/to/documents \
  --template "Vendor Form.xlsx" --sheet Sheet1 --out outputs/run

# Re-run extraction against a previously saved document set (skips OCR entirely)
python -m vendor_extractor.pipeline --cache outputs/inspect/document_set.json --out outputs/run

# Unit tests (no OCR — fast)
pip install -r requirements-dev.txt
pytest
```

---

## Known limitations

- **Throughput**: scanned pages run ~10–35s each on CPU (PaddlePaddle's oneDNN acceleration is disabled to work around a CPU executor crash in PaddlePaddle 3.3.1 — see `backend/vendor_extractor/ingest/ocr_engine.py`). Fine for single-vendor use; page-level parallelism would be the next step for batch processing.
- **Bank name** is not reliably extractable from a cheque scan alone — cheques don't caption their own bank name, and OCR reads the logo as garbled text. An IFSC-prefix → bank-name lookup table is the planned fix, not yet implemented.
- **DOCX geometry is synthetic**: since Word documents carry no pixel coordinates, the pipeline lays text out on a synthesized canvas to preserve caption/value adjacency. This works for the matching engine but bounding boxes in DOCX output aren't real page positions.
- `backend/requirements.txt` pins the versions this was built and tested against; PaddleOCR/PaddlePaddle version bumps are not guaranteed compatible without re-testing.
