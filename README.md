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
- [Extraction accuracy evaluation](#extraction-accuracy-evaluation)
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
│       ├── validator.py             Generic rule executor — regex / length / enum / dictionary / cross-field
│       ├── dictionaries.py          Loads the word lists a `dictionary` validator checks against
│       ├── preprocessing.py         Opt-in denoise/contrast/sharpen (evaluated, not default — see below)
│       ├── excel_mapper.py          Fills a template from a YAML cell map
│       ├── verifier.py              Reopens the saved file, diffs every cell, colours PASS/FAIL
│       ├── pipeline.py              Wires the above end to end; CLI entry point
│       ├── dump_ocr.py              CLI: inspect raw OCR/document output
│       ├── check_config.py          CLI: validate the YAML config, no OCR needed
│       └── eval/                    CLI: accuracy / SAHI / preprocessing evaluation (see below)
│           ├── eval_extraction.py    Scores a pipeline against human-verified ground truth
│           ├── eval_sahi.py          Tiled-vs-baseline detection comparison
│           ├── eval_preprocessing.py Denoise-vs-raw OCR comparison
│           └── ground_truth/         Ground truth YAML (real ones gitignored — PII)
│
├── config/                          V2's field knowledge — edit this, not Python, to change behaviour
│   ├── field_dictionary.yaml        24 fields: labels, regex patterns, validators, search rules
│   ├── validation_rules.yaml        17 validators (format + cross-document + dictionary)
│   ├── document_profiles.yaml       How a document is classified (GST cert vs cheque vs ...)
│   ├── dictionaries/                Word lists for `dictionary` validators (scheduled banks, entity suffixes)
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

#### Slicing Aided Hyper Inference (SAHI) — evaluated, not adopted

SAHI tiles a large image into overlapping crops, runs detection on each at full resolution, then merges the results back — it earns its keep when a single detector pass has to downscale the input so much that small objects fall below what the model can resolve (its classic use case is small objects in very large aerial/satellite imagery).

Before implementing it, three configurations were measured against the cancelled cheque (the smallest-print, highest-OCR-risk document in this pipeline, rendered at the pipeline's real 200 DPI, 1592×723px):

| Configuration | Spans found | GSTIN/IFSC/account no. recovered | Time |
|---|---|---|---|
| A. Baseline (current default) | 29 | ✅ all | 7.4s |
| B. Upscaled (`text_det_limit_side_len=1920`) | 28 | ✅ all | 21.3s (3× slower, no gain) |
| C. Tiled (2×2 overlapping, SAHI-style) | 43 raw* | ✅ all | 10.9s |

\* the 43 "spans" from tiling include duplicate/fragmented detections from the overlap regions that would need NMS-style merging to become 29-ish real spans — tiling adds real complexity (duplicate suppression, boundary-split values) for zero recall gain here.

**Verdict: not adopted.** At 200 DPI, an A4-sized document is ~1650×2340px — nowhere near the resolution where PaddleOCR's detector starts dropping small text. Every field, including the smallest print (the account number), was already recovered correctly by the baseline pass. SAHI's entire value proposition doesn't apply when nothing is being lost to downscaling in the first place.

**Implemented as an opt-in, not default,** in case a future document source (very high-DPI scans, oversized multi-column layouts) hits the regime where it would actually help: `app/pipelines/v2/preprocessing.py`'s docstring and `python -m app.pipelines.v2.eval.eval_sahi` / `eval_preprocessing` (see [CLI tools](#cli-tools-v2)) are the starting point for re-testing if that need arises. Re-measure against the actual failing input before enabling — don't assume it'll help just because the technique is a known best practice; it wasn't for this document type.

#### Image preprocessing — evaluated, not adopted by default

A denoise (fast non-local-means) + local contrast (CLAHE) + unsharp-mask chain was built and measured against: the clean digital cheque render, a genuinely scanned Udyam certificate, and a synthetically degraded cheque (Gaussian noise + underexposure + blur, simulating a bad phone photo). Result on every sample: neutral to slightly negative — mean OCR confidence and span count both dropped marginally after preprocessing, on all three. PP-OCRv6's recognizer is already trained on noisy real-world text and reacts better to it directly than to a classical denoise pass, whose CLAHE step in particular tends to amplify injected noise rather than suppress it.

Kept as `app/pipelines/v2/preprocessing.py::clean_for_ocr()`, wireable via `OCREngine(..., preprocess=True)`, for a genuinely low-quality source (visible scanner speckle, heavy JPEG artifacts) not represented in the current samples — but the honest result today is "measured, and it didn't help," not "implemented and assumed to help."

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

17 rules, defined once in `validation_rules.yaml`, referenced by name from field configs — including `derived` rules that check one field against another (e.g. the PAN embedded in a GSTIN must match the standalone PAN field), and `dictionary` rules that fuzzy-check a value against a curated word list.

#### Dictionary check

Regex validates *shape* (a GSTIN, an IFSC), but several fields have no fixed shape at all — `vendor_name`, `bank_name`, `city` carry `patterns: []` in the field dictionary, so nothing was catching a value that OCR mangled into plausible-looking garbage. Two `dictionary` validators close that gap, each backed by a plain-text word list under `app/config/dictionaries/`:

| Validator | Field | Dictionary | Mode | What it catches |
|---|---|---|---|---|
| `bank_name_known` | `bank_name` | `scheduled_banks.txt` (~50 RBI-scheduled banks) | `membership` — the whole value must fuzzy-match one entry | OCR noise that garbles a real bank name into something unrecognizable (measured example from this project's own dev history: `"ICICI Bank"` OCR'd as `"Otctctean"`) |
| `vendor_name_has_entity_suffix` | `vendor_name` | `entity_suffixes.txt` (Pvt Ltd, LLP, & Sons, ...) | `contains` — value must fuzzy-contain one entry as a substring | OCR damage to the legal-entity portion of a company name, without trying to validate the whole (non-enumerable) name |

Both are `severity: warning`, not `error` — a bank genuinely outside the curated list, or a sole-proprietor name with no suffix, is a legitimate value, not necessarily a mistake; the check exists to flag for review, not to block.

The two modes use different RapidFuzz scorers on purpose, tuned and verified against both real and deliberately-corrupted values (see `app/pipelines/v2/validator.py::_rule_dictionary` docstring for the measured numbers): `membership` uses plain `ratio` so a value that merely *contains* a dictionary-shaped word (`"Xyzabc Fake Bank Corp"` contains "Bank") still scores low overall; `contains` uses `WRatio`, which is expected to reward a short dictionary entry cleanly matching inside a longer value. Comparison is case-folded independently of each field's own normalization chain, since e.g. `bank_name` is deliberately title-cased for the Excel output but the fuzzy match needs to be case-insensitive regardless.

Add a new dictionary by dropping a `.txt` file (one entry per line, `#` comments allowed) under `app/config/dictionaries/`, adding its name to `KNOWN_DICTIONARIES` in `config_loader.py`, and referencing it from a `type: dictionary` validator in `validation_rules.yaml` — no other code changes required.

### Excel fill & verification

Loads the template, writes only non-empty values, saves — then **reopens the saved file** and re-reads every mapped cell to confirm it matches what was extracted, colouring each PASS (green) / FAIL (red) and writing a JSON report. This catches a value that silently failed to write or was coerced to a different type by Excel — not just trusting the in-memory write.

> **What this check does and does not prove.** Both sides of that comparison — the "expected" JSON and the "actual" cell — originate from the *same* extraction call. It therefore verifies **write integrity**, not extraction correctness: if the extractor misreads a GSTIN, the wrong value is written, read back identically, and reported as a confident green PASS. Measuring whether extraction is actually *right* requires an independent reference — see below.

---

## Extraction accuracy evaluation

The per-run verification report cannot catch a confidently-wrong extraction (see the note above). `app/pipelines/v2/eval/eval_extraction.py` closes that gap by scoring a pipeline against a **human-verified ground truth file** — values transcribed from the source documents by a person, not produced by the extractor.

```bash
python -m app.pipelines.v2.eval.eval_extraction \
  --ground-truth app/pipelines/v2/eval/ground_truth/<vendor>.yaml \
  --documents path/to/vendor/docs \
  --pipeline v2 --cache outputs/ocr_cache.json
```

Each field lands in one of five outcomes:

| Outcome | Meaning |
|---|---|
| `correct` | Extracted value matches ground truth |
| `wrong` | Ground truth has a value, extractor produced a **different** one |
| `missed` | Ground truth has a value, extractor produced nothing |
| `hallucinated` | Ground truth says the field is **absent from every document**, extractor produced a value anyway |
| `correctly_absent` | Ground truth says absent, extractor correctly produced nothing |

`wrong` and `hallucinated` are the ones that matter — they place a confident, well-formed, incorrect value on a form a human is likely to sign off.

**Ground truth must never be generated by running the pipeline.** Doing so makes the evaluation circular and reports ~100% regardless of real accuracy. The loader enforces this socially rather than technically: a file is refused unless a human has set `verified: true` (override with `--allow-unverified`, which prints a warning). See `app/pipelines/v2/eval/ground_truth/README.md`.

Ground truth files transcribe real GSTINs, PANs and account numbers, so `ground_truth/*.yaml` is gitignored; only the fabricated `example_synthetic.yaml` is committed.

### What it found on the sample document set

Running V2 against the sample vendor — the same run whose Excel verification report showed **100% PASS on all 24 fields** — scored **16 correct / 2 wrong / 1 missed / 1 hallucinated** (84.2% recall, 84.2% precision):

- **`bank_name` wrong** — returned "Bank of India" (from the Udyam certificate) while `ifsc` and `account_number` came from the cheque's ICICI account. The Udyam certificate genuinely lists a *different bank* from the cancelled cheque, and the merge logic took the name from one document and the account details from another, producing a **mixed record that would fail a real payment**. This is the single most valuable finding: it is invisible to both the format validators (both are well-formed bank names) and the write-back check.
- **`website` hallucinated** — returned `https://udyamregistration.gov.in`, scraped out of the Udyam page-2 disclaimer "Printed from …". That is the government portal, not the vendor's website.
- **`nature_of_business` wrong** — "Manufactur", truncated mid-word by OCR on the page-3 table.
- **`branch_address` missed** — present on the cheque, not extracted.

Fields where documents disagree require a *business* decision, not a transcription one; ground truth files record these under `conflicts` with the reasoning, and the harness prints them alongside the score.

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

# Re-run the SAHI-vs-baseline detection comparison against any document
python -m app.pipelines.v2.eval.eval_sahi path/to/doc.pdf --gt ifsc=ICIC0006278

# Re-run the preprocessing-vs-raw OCR comparison against any document
python -m app.pipelines.v2.eval.eval_preprocessing path/to/doc.pdf --gt ifsc=ICIC0006278

# Score extraction accuracy against a human-verified ground truth file
python -m app.pipelines.v2.eval.eval_extraction \
  --ground-truth app/pipelines/v2/eval/ground_truth/<vendor>.yaml \
  --documents path/to/vendor/docs --cache outputs/ocr_cache.json
```

---

## Improving PaddleOCR efficiency

What this pipeline already does, plus what's available but not (yet) adopted — SAHI and image preprocessing are covered above since both were evaluated against real data; this list is the rest of the lever set, roughly in order of expected payoff for this document type:

**Already implemented:**
- **Model size**: `PP-OCRv6_small` over the default `medium` — ~9× faster (10.7s vs 93.3s on a benchmark page) for a marginal confidence cost (0.948 vs 0.962). `tiny` was tried and rejected — it hallucinated characters that weren't on the page, which is worse than being slow.
- **oneDNN disabled**: works around a PaddlePaddle 3.3.1 CPU executor crash (see `ocr_engine.py`); re-enabling it once upstream fixes the issue would be a meaningful speedup, since oneDNN is normally faster than the fallback path — worth re-testing on each PaddlePaddle upgrade.
- **Text-layer-first PDF reading**: a digital PDF's native text is read directly (~1000× faster than OCR, and immune to OCR confusions) and OCR only runs on pages that genuinely need it — most of this pipeline's throughput win over a naive "OCR every page" design comes from this, not from OCR-side tuning.
- **Engine caching**: `OCREngine` caches the loaded PaddleOCR pipeline per configuration (`_ENGINE_CACHE`), so a multi-document batch pays the multi-second model load cost once, not per document.
- **`drop_score` threshold**: spans below 0.30 confidence are discarded before they reach the layout/semantic engines, so downstream matching isn't polluted by (and doesn't waste cycles scoring) watermark bleed and scan speckle.

**Available, not adopted — would need justification against real data first, the same way SAHI and preprocessing were evaluated above:**
- **Page-level parallelism**: pages/documents are processed serially. For a batch of many vendors (not the current single-vendor-per-run UI flow), running independent documents through separate `OCREngine` instances in a process pool would parallelize the CPU-bound inference — real payoff, real complexity (worker/model-memory management), only worth it once batch throughput is an actual bottleneck rather than the current per-vendor demo flow.
- **GPU inference**: this deployment targets a CPU-only, fully-offline environment by design (the entire point of V2 is documents that can't leave the machine, not documents that can't reach a GPU) — but if a GPU is available in a given deployment, PaddleOCR's `device="gpu"` would cut per-page inference time substantially. Not adopted because it's not a given in this project's target environment, not because it wouldn't help.
- **`text_det_limit_side_len` tuning**: the one knob actually tested against SAHI above (see the table) — raising it did not improve recall on this pipeline's documents and made inference 3× slower. Left at the PaddleOCR default. Worth revisiting only if a specific document type is shown to lose small text at the default limit.
- **Lower render DPI**: `RENDER_DPI=200` is a deliberate tradeoff already tuned for this document type (`models.py`); dropping it would speed up both rendering and inference but risks losing small print (account numbers) — untested below 200, and the existing choice already reflects that tradeoff being made once rather than left as an easy-looking lever no one checked.
- **Batched `predict()` calls**: PaddleOCR's `predict()` can accept a list of images in one call rather than one image per call, amortizing some fixed per-call overhead. Not adopted here because documents in this pipeline are processed one page at a time as they're loaded (interleaved with per-page text-layer-vs-OCR decisions), so batching would require restructuring the load loop to defer OCR until all pages needing it are known — a real change, not a flag flip, and not measured to be worth it at this pipeline's typical 1-5 pages per run.

---

## Known limitations

- **Throughput**: scanned pages run ~10–35s each on CPU (PaddlePaddle's oneDNN acceleration is disabled to work around a CPU executor crash in PaddlePaddle 3.3.1 — see `app/pipelines/v2/ocr_engine.py`). Fine for single-vendor use; page-level parallelism would be the next step for batch processing.
- **Bank name** is not reliably extractable from a cheque scan alone — cheques don't caption their own bank name, and OCR reads the logo as garbled text. An IFSC-prefix → bank-name lookup table is the planned fix, not yet implemented.
- **DOCX geometry is synthetic**: since Word documents carry no pixel coordinates, V2 lays text out on a synthesized canvas to preserve caption/value adjacency. This works for the matching engine but bounding boxes in DOCX output aren't real page positions.
- `requirements-v2.txt` pins the versions this was built and tested against; PaddleOCR/PaddlePaddle version bumps are not guaranteed compatible without re-testing.
