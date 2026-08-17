# Project State

Snapshot taken at the migration checkpoint. Everything here was verified against the
working tree, not recalled from memory.

---

## Project

| | |
|---|---|
| **Name** | Vendor Form Extractor |
| **Local path** | `C:\Users\shubh\OneDrive\Documents\vendor-extractor` |
| **GitHub remote** | `https://github.com/ShubhSonakiya18/vendor-extractor-v1.git` (`origin`) |
| **Current branch** | `master` (tracks `origin/master`) |
| **HEAD before this checkpoint** | `314675e` — *Restructure into layered FastAPI app (routes/services/schemas/core)* |
| **Other branches** | `ver1` → `a732744`, `ver2` → `9f02edc` (both pushed to origin) |

### Branch topology

```
0730fa3  Initial commit: vendor form extractor
   │
8db272e  Add V2: fully local vendor extraction pipeline (PaddleOCR + config-driven engine)
   ├──────────► a732744  (ver1)  Add snapshot README for ver1     ← UNIQUE commit, not on master
   │
9f02edc  (ver2)  Add README and V2 requirements file
   │
314675e  (master, origin/master, HEAD)  Restructure into layered FastAPI app
```

- **`ver1`** is a snapshot of the **pre-restructure flat layout** (`app.py`, `v2/`, `config/`
  all at repo root) plus a README marking it as a checkpoint. Its commit `a732744` exists on
  **no other branch** — it is preserved on `origin/ver1` and must not be deleted.
- **`ver2`** points at `9f02edc`, which is an ancestor of `master`. Fully contained; kept as a
  marker of the state just before the layered restructure.

---

## Current Objective

Two working extraction engines exist and both produce correct output on the sample vendor.
The current phase is **not** feature work — it is **establishing measured quality** and
**closing data-handling risk** before the system is used on real vendors at volume:

1. Build a defensible accuracy baseline (ground-truth evaluation exists; needs verification
   and more vendors).
2. Close the critical data-privacy items on the V1 cloud path.
3. Fix the one known correctness defect that produces an unusable record (`bank_name`).

---

## Current Architecture

### End-to-end flow

```
upload (3+ documents + Excel template)
   │
   ├── V1 ── Gemini File API upload ── 3 schema-bound generate calls ── PAN reconcile ── 6 regexes
   │
   └── V2 ── per-page text-layer-vs-OCR decision ── PaddleOCR ── spans
              ── layout (lines + neighbours) ── candidate scoring ── classify documents
              ── pool + select across documents ── validate (2 passes) ── cross-doc consistency
   │
   ▼
CANONICAL RECORD — 24 keys (the interface both engines satisfy)
   │
   ├── Excel fill  (V1: hardcoded XLSX_CELL_MAP │ V2: YAML excel_mappings/)
   ▼
write-back verification — reopen saved file, diff every mapped cell, colour PASS/FAIL
   │
   ▼
results page + downloads (xlsx, result.json, verification_report.json)
```

### Document ingestion (V2)

Per **page**, not per file, because one PDF can mix both kinds:

- text-layer characters < 40 → treat as scanned, OCR it
- **image coverage ≥ 50% → OCR it even if a text layer exists.** This is the important rule.
  The sample cancelled cheque is a 100%-image page carrying a 536-character baked-in text
  layer that renders "ICICI Bank" as `"Otctctean"`. A character-count test trusts it and
  silently corrupts the bank fields.
- DOCX: native paragraph/table parsing; embedded images OCR'd individually. Geometry is
  synthesised on an A4 canvas (`synthetic_bbox=True`) since Word carries no pixel coordinates.

### Document classification (V2)

`app/config/document_profiles.yaml` — 5 profiles (`gst_certificate`, `udyam_certificate`,
`cancelled_cheque`, `pan_card`, `bank_statement`). Content keywords weigh `2.0`, filename
keywords `1.0`, below `min_score: 1.0` a document stays `other` (never an error).

### Extraction / field matching (V2)

Three match kinds per field:

| Kind | Shape | Bonus |
|---|---|---|
| `inline` | caption + value in one span — `'PIN Code: 700019'` | `+0.30` |
| `adjacent` | caption alone, value beside/below | `+0.18` same line, `0` otherwise |
| `pattern_only` | shape match, no caption nearby | `−0.10` |

Score:

```
0.35 × label_similarity + 0.30 × pattern_match
+ 0.25 × spatial_proximity + 0.10 × ocr_confidence     (weights enforced to sum to 1.0)

adjustments:  ±0.05 expected_documents
              ×0.55 value is itself a known caption
              ×0.40 value has another field's exact shape
              ×0.35 / ×0.75 / +0.10  failed-error / failed-warning / passed validation
```

Short-caption escalation: captions ≤4 chars must clear 0.97 similarity (≤6 chars → 0.92),
because a 4-character fuzzy match like "Bank" or "Town" otherwise hits unrelated text.

All layout distances are in **multiples of the reference span's height**, never pixels, so one
YAML threshold works on a 723px cheque and a 2339px certificate alike.

### Validation

17 rules in `app/config/validation_rules.yaml`, 6 types: `regex`, `length`, `enum`,
`non_empty`, `derived` (cross-field, e.g. GSTIN[2:12] == PAN), `dictionary` (fuzzy word-list).

**Runs twice, deliberately** — before selection as scoring signal, and after selection to set
reported status. `derived` rules only run in the second pass (nothing is decided yet in the
first). Collapsing this to one pass reintroduces a fixed bug where OCR debris (`"Rvic"`) beat
the genuine `"West Bengal"` for `state`.

### Form population & verification

- V1: `XLSX_CELL_MAP` dict in `vendor_v1_gemini.py`, 24 keys → `B37`–`B63`.
- V2: `app/config/excel_mappings/vendor_creation_v1.yaml`; loader rejects two fields mapping
  to one cell.
- Both: multi-sheet fill re-reads the previous output so all selected sheets land in one workbook.
- Verification reopens the **saved file from disk** and diffs each mapped cell, colouring
  PASS green / FAIL red. Handles openpyxl returning `"700019.0"` for a text PIN.

### UI / API

| Route | Engine | Purpose |
|---|---|---|
| `GET /` | V1 | upload form (redirects to `/v2` if V1 unavailable) |
| `POST /generate` | V1 | run pipeline |
| `GET /results/{run_id}` | V1 | results page |
| `GET /download/{run_id}/{kind}` | V1 | `xlsx` \| `json` \| `report` |
| `GET /v2` | V2 | upload form |
| `POST /v2/process-vendor` | V2 | run pipeline |
| `GET /v2/results/{run_id}` | V2 | results page |
| `GET /v2/download/{run_id}/{kind}` | V2 | `xlsx` \| `json` \| `report` \| `extraction` \| `spans` |
| `POST /v2/template-sheets` | V2 | read sheet names from an uploaded workbook (AJAX) |
| `GET /v2/health` | V2 | config + availability probe |

**How the engines are connected:** an **import guard**, not a setting. `app/main.py` wraps
`from app.routes import vendor_v1` in `try/except ImportError`. V1's chain imports
`google-genai`; the offline V2 environment omits it, so there V1 is never mounted and `/`
redirects to `/v2`. The flag lands on `app.state.v1_available`, reported by `/v2/health`.

---

## Implemented Features

**Both engines**
- 24-field canonical record; shared Excel fill + write-back verification
- Multi-sheet fill (all selected tabs into one workbook)
- Per-run isolation: `uploads/<run_id>/`, `outputs/<run_id>/`
- Results page with extracted table, verification table, downloads
- Processing spinner; friendly error page for V2

**V1 (Gemini)**
- 3 schema-constrained calls (`GST_SCHEMA`, `UDYAM_SCHEMA`, `CHEQUE_SCHEMA`)
- `tenacity` retry: 4 attempts, exponential 2s→60s, on `ServerError` (503) / code 429
- PAN reconciliation between GSTIN[2:12] and the Udyam PAN; GST wins on conflict
- 6 regex validators feeding a `needs_review` list

**V2 (local)**
- PaddleOCR 3.7 / PP-OCRv6 `small`; engine cache; `drop_score = 0.30`; 200 DPI render
- Per-page text-layer-vs-OCR decision on image coverage
- PDF / image / DOCX ingestion into one span representation
- Layout engine: visual lines, directional neighbours, DPI-independent distances
- Config-driven matching, 24 fields, 17 validators, 5 document profiles
- Two-pass validation with validators as selection signal
- Cross-document candidate pooling, precedence, consistency flagging
- Full audit trail per field: score components, matched caption, page, bbox, 5 alternatives
- `dictionary` validator type + curated word lists (scheduled banks, entity suffixes)
- CLI: `check_config`, `dump_ocr`, `pipeline` (with `--cache` to skip OCR)
- Evaluation harnesses: `eval_extraction` (accuracy vs ground truth), `eval_sahi`,
  `eval_preprocessing`

**Handoff / ops**
- `.env` based config via `app/core/config.py`; `.env.example` template
- Centralised logging setup (`app/core/logging.py`)
- Ground-truth schema + anti-circularity guard + synthetic fixture

---

## Partially Implemented Features

| Feature | State | Gap |
|---|---|---|
| Ground-truth dataset | Harness done; one vendor scaffolded | `mb_control_systems.yaml` is `verified: false` — values transcribed from an OCR dump, not confirmed against the PDFs. Needs human sign-off, then more vendors. |
| Image preprocessing | Implemented, opt-in, measured | Measured neutral-to-negative on all samples; wired to `OCREngine(preprocess=True)` but **off by default on purpose**. |
| `app/schemas/vendor.py` | pydantic models defined | Not actually used to validate/serialise route responses; currently documentation-only. |
| V1 field coverage | 20 of 24 fields | `tan`, `esic_number`, `account_type`, `website` are hardcoded `None` and appear in no schema/prompt. |
| V1 validation | 6 regexes | `dictionary` validators built for V2 were never ported to V1. |
| `DEFAULT_PIPELINE` setting | Read into `Settings` | Not consumed by `app/main.py` routing yet — routing is import-guard based only. |

---

## Known Bugs

Ranked by business consequence. Severity reflects impact, not difficulty.

| # | Sev | Issue | Status | Location |
|---|---|---|---|---|
| 1 | **critical** | Gemini key is on the **free tier**, whose terms state submitted content is used for product improvement, may be human-reviewed, and explicitly say not to submit personal information. Vendor PANs and account numbers pass through it. | Open — fix is to enable billing | `.env` |
| 2 | **critical** | API key was pasted into a terminal session and chat transcript. | Open — must rotate | `.env` |
| 3 | **critical** | V1 never deletes files from the Gemini File API, which retains them until expiry independently of any Zero Data Retention setting. | Open | `vendor_v1_gemini.py::_upload` |
| 4 | **critical** | **V2 mixes bank details across documents.** Returns `bank_name` from the Udyam certificate while `ifsc`/`account_number` come from the cheque → a record that would fail a real payment. **Root cause confirmed:** the cheque yields *zero* `bank_name` candidates (a cheque never captions its own bank name; `bank_name` has `patterns: []` so the pattern-only fallback is guarded off; the 4-char caption "Bank" needs 0.97 similarity and `'AICICIBank'` misses; `'Payable at par…ICICI Bank Limited'` has "Bank" 40 chars in, and captions must start a span). Udyam wins uncontested — the `expected_documents` tie-break never fires because there is nothing to tie with. | Open — fix proposed as D-14 | `semantic_engine.py::_choose` |
| 5 | high | All accuracy figures rest on **n=1 vendor** and an **unverified** ground-truth file. | Open | `eval/ground_truth/` |
| 6 | high | V1 silently cannot extract 4 fields (hardcoded `None`); operator sees a blank cell indistinguishable from "vendor has no TAN". | Open | `vendor_v1_gemini.py:195–206` |
| 7 | high | **No automated tests.** No `tests/`, pytest not installed. | Open | — |
| 8 | high | The in-app "verification report" is routinely misread as an accuracy measure. It compares the extraction against itself and reported **100% PASS on a run containing 4 real errors**. | Open — rename proposed | `vendor_v1_verify.py`, `verifier.py` |
| 9 | medium | Results held in module-level `RUNS` / `V2_RUNS` dicts: lost on restart, unbounded growth. | Open | `routes/vendor_v1.py`, `vendor_v2.py` |
| 10 | medium | `uploads/` and `outputs/` are never pruned; real vendor PII accumulates (currently ~48 upload runs, ~40 output runs on this machine). | Open | — |
| 11 | medium | No authentication on any route. | Open | `app/main.py` |
| 12 | medium | V2 hallucinated `website` = `https://udyamregistration.gov.in`, scraped from the Udyam page-2 "Printed from…" disclaimer. | Open | `field_dictionary.yaml::website` |
| 13 | medium | V1 validation much weaker than V2's (no dictionary checks, no cross-document consistency). | Open | `vendor_v1_gemini.py::validate` |
| 14 | low | OCR truncation on table cells — `nature_of_business` came out `"Manufactur"`. | Open | `ocr_engine.py` |
| 15 | low | `branch_address` missed entirely by V2 (present on the cheque). | Open | `field_dictionary.yaml` |

### Measured accuracy (provisional — n=1, unverified ground truth)

| | Recall | Precision | Accuracy | correct / wrong / missed / hallucinated / correctly-absent |
|---|---|---|---|---|
| **V1 Gemini** | 89.5% | 94.4% | 91.7% | 17 / 1 / 1 / 0 / 5 |
| **V2 local** | 84.2% | 84.2% | 83.3% | 16 / 2 / 1 / 1 / 4 |

Raw results: `outputs/eval/v1_accuracy.json`, `outputs/eval/v2_accuracy.json` (gitignored).

**Important caveat:** V1's higher score is partly an artefact of its rigidity, not superior
reading. (a) Its three calls each see only one document, so it *structurally cannot* pull a
bank name off the Udyam certificate — the mistake that cost V2. (b) All five of its
"correctly absent" scores are the four hardcoded `None` fields plus unmapped address lines —
it scores well by never attempting them, and the same hardcoding is why it missed
`account_type`, which *is* printed on the cheque. The two engines have **different failure
shapes, not different quality levels**: V1 fails by omission, V2 by commission.

---

## Current Dependencies

Two environments, deliberately separate.

### V1 environment — Python 3.14.2 (system)
```
fastapi 0.135.3   uvicorn 0.44.0    jinja2 3.1.6      python-multipart 0.0.26
python-dotenv 1.2.2   pydantic 2.13.0   google-genai 2.17.0
openpyxl 3.1.5    tenacity 9.1.4
```
Pinned in `requirements.txt`.

### V2 environment — Python 3.12.0 (`.venv-paddle`)
```
paddlepaddle 3.3.1   paddleocr 3.7.0   paddlex 3.7.2
pypdfium2 5.12.1     rapidfuzz 3.14.5  python-docx 1.2.0   pyyaml 6.0.2
numpy 2.3.5          opencv-contrib-python 4.10.0.84
fastapi 0.141.1      uvicorn 0.52.1    jinja2 3.1.6        python-multipart 0.0.32
python-dotenv 1.2.2  pydantic 2.13.4   openpyxl 3.1.5      google-genai 2.17.0
```
Pinned in `requirements-v2.txt`. Note `google-genai` happens to be installed here too, so
V1 routes are also available in this environment (`/v2/health` reports `v1_available: true`).

**`opencv-contrib-python` is a transitive PaddleOCR dependency** that
`app/pipelines/v2/preprocessing.py` also imports directly (`cv2`). It is not listed in
`requirements-v2.txt` — preprocessing will fail if PaddleOCR ever stops pulling it in.

---

## Configuration

`.env` (gitignored) from `.env.example`. Required for V1 only: `GEMINI_API_KEY`.
Optional: `GEMINI_MODEL`, `DEFAULT_PIPELINE`, `APP_TITLE`, `DEBUG`, `UPLOAD_DIR`,
`OUTPUT_DIR`, `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT`. V2 needs no configuration at all.

**Gotcha:** `load_dotenv()` is called by importing `app.core.config`. Any entry point that
reads `GEMINI_API_KEY` must import it first — this caused a real bug in the eval harness,
now fixed by an explicit import in `eval_extraction.py::extract_v1`.

---

## Important Files

### Application
| File | Purpose |
|---|---|
| `app/main.py` | ASGI entry point; import-guards V1, mounts routers, static, logging |
| `app/core/config.py` | `.env` → typed `Settings`; the only `load_dotenv()` call |
| `app/core/logging.py` | root logger config (V2 modules log via `getLogger`) |
| `app/routes/vendor_v1.py` | V1 HTTP layer; owns the `RUNS` dict |
| `app/routes/vendor_v2.py` | V2 HTTP layer; owns `V2_RUNS`; health + sheet-probe endpoints |
| `app/services/vendor_v1_gemini.py` | V1 engine, `XLSX_CELL_MAP`, `fill_vendor_xlsx`, `validate` |
| `app/services/vendor_v1_verify.py` | V1 write-back check |
| `app/services/vendor_v1_service.py` | V1 orchestration for the route |
| `app/services/vendor_v2_service.py` | V2 orchestration; `V2ServiceError` for user-facing failures |
| `app/schemas/vendor.py` | pydantic shapes (currently documentation-only) |
| `app/utils/uploads.py` | `save_upload()` helper |

### V2 pipeline (`app/pipelines/v2/`)
| File | Purpose |
|---|---|
| `models.py` | `BBox`, `TextSpan`, `Page`, `Document`, `DocumentSet`, `FieldResult`, `ExtractionResult`; `RENDER_DPI = 200` |
| `document_loader.py` | any format → spans; the image-coverage OCR decision |
| `ocr_engine.py` | **only** module importing `paddleocr`; oneDNN workaround; engine cache |
| `layout_engine.py` | spans → visual lines + directional neighbours |
| `field_matcher.py` | scored candidates; three match kinds; penalties |
| `semantic_engine.py` | classify, pool, select, validate, cross-document consistency |
| `validator.py` | generic rule executor, 6 rule types |
| `dictionaries.py` | loads word lists for `dictionary` validators |
| `normalizer.py` | normalisation ops incl. `fix_ifsc_confusions` |
| `excel_mapper.py` | YAML-driven cell writing |
| `verifier.py` | write-back diff + cell colouring |
| `preprocessing.py` | opt-in denoise/CLAHE/sharpen — **evaluated and not default** |
| `pipeline.py` | wiring + CLI |
| `dump_ocr.py` | CLI: inspect raw OCR |
| `check_config.py` | CLI: validate YAML + assert V1/V2 key compatibility (AST-parses V1 source) |
| `eval/eval_extraction.py` | accuracy vs ground truth; 5 outcome classes |
| `eval/eval_sahi.py` | tiled-vs-baseline detection comparison |
| `eval/eval_preprocessing.py` | preprocessing-vs-raw comparison |
| `eval/ground_truth/` | schema, README, synthetic fixture, (gitignored) real files |

### Config (`app/config/`)
| File | Purpose |
|---|---|
| `field_dictionary.yaml` | 24 fields: captions, patterns, normalisation, validators, search, priority |
| `validation_rules.yaml` | 17 named validators |
| `document_profiles.yaml` | 5 document-type profiles |
| `dictionaries/scheduled_banks.txt` | ~50 RBI-scheduled bank names |
| `dictionaries/entity_suffixes.txt` | legal-entity suffixes (Pvt Ltd, LLP, …) |
| `excel_mappings/vendor_creation_v1.yaml` | field → cell map |

### Docs
`README.md` (user-facing), `CLAUDE.md`, `PROJECT_STATE.md`, `DECISIONS.md`,
`MIGRATION_HANDOFF.md`, `PROJECT_FILE_INVENTORY.md`, `ENVIRONMENT_SETUP.md`.

### Other
`legacy/vendor_form_extractor_ocr.py` — superseded Tesseract+regex prototype, reference only,
imported by nothing.

---

## Testing

**No test suite exists.** Verified: no `tests/` directory; `pytest` not installed in either
environment.

### Verification commands actually available, and their results at checkpoint

| Command | Result |
|---|---|
| `python -m compileall -q app legacy` | **PASS** (exit 0) |
| `python -c "import app.main"` | **PASS** — `V1_AVAILABLE = True` |
| `python -m app.pipelines.v2.check_config` | **PASS** — "ALL CHECKS PASSED"; 24 fields, 17 validators, 12 fields with patterns, 5 cross-doc checks; all 8 pattern cases accept/reject correctly |
| Live startup (`uvicorn app.main:app --port 8010`) | **PASS** — `/` 200, `/v2` 200, `/v2/health` 200, `/static/style.css` 200, `/docs` 200 |
| `/v2/health` body | `{"status":"ok","mode":"local","v1_available":true,"fields":24,"validators":17,"excel_mappings":["vendor_creation_v1"]}` |
| `pytest --collect-only` | **N/A** — pytest not installed |

**Known failing/skipped:** none failing. The gap is that nothing is *automated* — every check
above is manual, and there are no unit tests around the scoring or validation engines.

**Note on route counting:** in the V2 environment `len(app.routes)` is 7 because that
FastAPI/Starlette version keeps `_IncludedRouter` wrappers; in the V1 (3.14) environment the
same app reports 15 flattened routes. Both serve identically — verified by live HTTP. Do not
treat the count difference as a bug.

---

## Git State

```
branch:            master  (tracks origin/master)
HEAD at checkpoint: 314675e  Restructure into layered FastAPI app (routes/services/schemas/core)
remote:            origin  https://github.com/ShubhSonakiya18/vendor-extractor-v1.git
other branches:    ver1 → a732744 (unique commit, snapshot of pre-restructure layout)
                   ver2 → 9f02edc (ancestor of master)
secrets in history: NONE — verified with `git log --all -S<key>` and `git log --all -- .env`
```

Uncommitted at the time this document was written (all committed by the checkpoint commit
that follows): modified `.gitignore`, `README.md`, `app/config/field_dictionary.yaml`,
`app/config/validation_rules.yaml`, `app/pipelines/v2/{config_loader,ocr_engine,validator}.py`;
new `app/config/dictionaries/`, `app/pipelines/v2/dictionaries.py`,
`app/pipelines/v2/preprocessing.py`, `app/pipelines/v2/eval/`.

---

## Immediate Next Steps

In priority order. Estimates assume familiarity with the codebase.

1. **Rotate the Gemini API key.** (5 min) Bug 2. Independent of everything else.
2. **Enable billing on the Google Cloud project.** (15 min) Bug 1 — moves to Paid Services,
   where Google contractually does not train on submitted data. Optionally request Zero Data
   Retention.
3. **Delete uploaded files after each V1 run.** (30 min) Bug 3 — `client.files.delete()` in a
   `finally` block in `build_vendor_json`.
4. **Verify `mb_control_systems.yaml` against the source PDFs**, then set `verified: true`.
   (1 h) Bug 5 — makes every existing accuracy number trustworthy. Check PAN, IFSC, account
   number and telephone character by character; those came from OCR.
5. **Make `expected_documents` a filter for banking fields.** (2–4 h) Bug 4 — see D-14. After
   the fix `bank_name` should return *nothing* (flagged for review) rather than the wrong
   bank, and the mixed-record failure disappears.
6. **Rename the UI's "Verification Report" → "Excel Write Check".** (15 min) Bug 8.
7. **Add the 4 missing fields to V1's schemas/prompts.** (2 h) Bug 6.
8. **Add 10–20 more vendors to the ground-truth set.** (1–2 days) Bug 5 — first defensible
   accuracy figure; also shows which fields fail *systematically* vs incidentally.
9. **Introduce pytest + unit tests** for `field_matcher` scoring, `validator` rule types, and
   `normalizer` ops. (1–2 days) Bug 7.
10. **Persist runs and add a retention policy** for `uploads/`/`outputs/`. (1 day) Bugs 9, 10.
11. **Add authentication.** (1 day) Bug 11.
12. **Port `dictionary` validators to V1.** (3 h) Bug 13.

---

## Do Not Repeat

Work already completed. Do not redo it.

- **The layered restructure** (`app/` with core/routes/services/schemas/utils/pipelines) is
  done and pushed as `314675e`. The flat layout survives on `ver1` for reference only.
- **`dictionary` validator type** is implemented, wired to `bank_name` and `vendor_name`, and
  tuned. The two-scorer choice (`ratio` for membership, `WRatio` for contains) was arrived at
  empirically — plain `WRatio` scored the invented "Xyzabc Fake Bank Corp" at 85/100 against
  "ICICI Bank". Case-folding inside the validator was also necessary. Do not "simplify" to
  one scorer.
- **SAHI tiled inference: evaluated and rejected**, with numbers (D-12). Baseline recovered
  every target field at 7.4s; upscaling was 3× slower with no gain; tiling produced 14
  duplicate spans and found nothing new. Harness kept at `eval/eval_sahi.py`.
- **Image preprocessing (denoise + CLAHE + unsharp): evaluated and rejected as default**,
  with numbers (D-13). Neutral-to-negative on a clean render, a real scan, and a
  synthetically degraded image. Kept opt-in.
- **The `bank_name` root cause is fully diagnosed.** An earlier hypothesis — that the
  `expected_documents` tie-break failed because scores were not within 0.05 — was **wrong**
  and has been corrected. The cheque produces *zero* candidates. Do not re-investigate;
  implement D-14.
- **Ground-truth harness and schema** are built, including the anti-circularity guard and a
  committed synthetic fixture. Only *verification and expansion* remain.
- **Both engines have been scored** against the same ground truth; numbers are in this
  document and in `outputs/eval/*.json`.
- **Secrets audit** is done: the key exists only in gitignored `.env`, and was never
  committed on any branch.
- **The stale `v2/ocr_engine.py` path** in README's limitations section is fixed to
  `app/pipelines/v2/ocr_engine.py`.
