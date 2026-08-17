# Claude Account Migration Handoff

This repository is being handed from one Claude account to another. Everything needed to
resume development is in the repository. Read this file, then the three others listed at the
bottom, then inspect the code before changing anything.

---

## Current Project

**Vendor Form Extractor** — reads a supplier's onboarding documents (GST certificate, Udyam
/ MSME registration, cancelled cheque) and auto-fills a Vendor Creation Request Form in Excel,
then verifies every written cell.

Two extraction engines are shipped and both maintained:

| | Engine | Route | Requires |
|---|---|---|---|
| **V1** | Google Gemini, multimodal cloud API | `/` | `GEMINI_API_KEY`, internet |
| **V2** | PaddleOCR + local config-driven engine | `/v2` | nothing — fully offline |

Both emit an identical **24-key canonical record**; the Excel writer and verifier are shared
and engine-agnostic. That contract is the load-bearing design decision — do not break it.

V2 exists because vendor documents contain PAN and bank account numbers that in many
deployments cannot leave the machine.

---

## Current Repository

```
local path:   C:\Users\shubh\OneDrive\Documents\vendor-extractor
remote:       origin  https://github.com/ShubhSonakiya18/vendor-extractor-v1.git
```

Top-level layout:

```
app/                 the application (see CLAUDE.md for the directory map)
  core/ routes/ services/ schemas/ utils/ pipelines/v2/ config/ templates/ static/
legacy/              superseded Tesseract+regex prototype, imported by nothing
requirements.txt     V1 environment pins
requirements-v2.txt  V2 environment pins (Python 3.12 only)
.env.example         config template — copy to .env
CLAUDE.md  PROJECT_STATE.md  DECISIONS.md  MIGRATION_HANDOFF.md
PROJECT_FILE_INVENTORY.md  ENVIRONMENT_SETUP.md  README.md
uploads/  outputs/   per-run data — GITIGNORED, real vendor PII
```

---

## Current Git State

```
branch:  master  (tracks origin/master)
HEAD before this checkpoint:  314675e  Restructure into layered FastAPI app (routes/services/schemas/core)
```

### Branches — all three pushed to origin

```
0730fa3  Initial commit: vendor form extractor
   │
8db272e  Add V2: fully local vendor extraction pipeline (PaddleOCR + config-driven engine)
   ├──────────► a732744  (ver1)  Add snapshot README for ver1   ← UNIQUE, not on master
   │
9f02edc  (ver2)  Add README and V2 requirements file
   │
314675e  (master)  Restructure into layered FastAPI app
   │
<this checkpoint commit>
```

- **`ver1` contains a commit that exists on no other branch** (`a732744`). It snapshots the
  **pre-restructure flat layout** (`app.py`, `v2/`, `config/` at repo root). Preserved on
  `origin/ver1`. **Do not delete this branch.**
- **`ver2`** points at `9f02edc`, an ancestor of `master`. Fully contained; a marker of the
  state just before the layered restructure.

### Secrets audit result

Clean. Verified at checkpoint:
- The Gemini API key exists **only** in gitignored `.env`.
- `git log --all -S<key>` → no matches on any branch.
- `git log --all -- .env` → `.env` was never tracked.

---

## What Was Being Worked On Immediately Before Migration

A **quality-measurement phase**, not feature work. Concretely, in order:

1. **Added a `dictionary` validator type** to V2 to cover fields with no regex
   (`vendor_name`, `bank_name`), backed by curated word lists. Tuned empirically — see D-15
   for why two different fuzzy scorers are used.
2. **Evaluated SAHI tiled inference** against the existing detector settings. Measured, and
   **rejected** — the baseline already recovered every target field (D-12).
3. **Evaluated image preprocessing** (denoise + CLAHE + unsharp, plus binarisation).
   Measured, and **rejected as default** — neutral-to-negative on every sample (D-13).
4. **Built a ground-truth evaluation harness** (`eval/eval_extraction.py`) because the
   existing in-app verification check measures Excel write integrity, not extraction accuracy
   (D-18). Scored **both** engines against the same ground truth.
5. **Diagnosed the `bank_name` defect** to root cause, correcting an earlier wrong hypothesis
   along the way (D-14).

None of this work is half-finished in the working tree — it is complete and committed by the
checkpoint commit. What remains is listed under *What Is In Progress*.

---

## What Is Complete

- Both pipelines run end to end and produce correct Excel output on the sample vendor.
- Layered `app/` structure; entry point `app.main:app`; import-guard routing between engines.
- V2 config system: 24 fields, 17 validators, 5 document profiles, 1 Excel mapping, 2 word
  lists — all YAML/text, strictly validated at load time.
- `dictionary` validator type, implemented, wired, and empirically tuned.
- Ground-truth schema, anti-circularity guard, committed synthetic fixture, and a working
  accuracy harness supporting **both** `--pipeline v1` and `--pipeline v2`.
- SAHI and image preprocessing evaluated with recorded numbers; harnesses kept for re-testing.
- `.env`-based configuration; centralised logging.
- Secrets audit across the working tree and all git history.
- Six handoff documents (this file plus five others).

### Measured accuracy at checkpoint — provisional

| | Recall | Precision | Accuracy | correct/wrong/missed/hallucinated/correctly-absent |
|---|---|---|---|---|
| **V1 Gemini** | 89.5% | 94.4% | 91.7% | 17 / 1 / 1 / 0 / 5 |
| **V2 local** | 84.2% | 84.2% | 83.3% | 16 / 2 / 1 / 1 / 4 |

**Do not quote these as system accuracy.** n = 1 vendor, and the ground-truth file is still
`verified: false`. Also note V1's higher score is partly an artefact of its rigidity, not
better reading — see `PROJECT_STATE.md` → Measured accuracy for the full caveat.

---

## What Is In Progress

| Item | State | What remains |
|---|---|---|
| Ground-truth dataset | 1 vendor scaffolded, `verified: false` | Human verification against the PDFs, then 10–20 more vendors |
| `bank_name` cross-document fix | Root cause confirmed, fix designed (D-14) | Implementation |
| V1 field coverage | 20 of 24 | Add `tan`, `esic_number`, `account_type`, `website` to schemas/prompts |
| V1 validation parity | 6 regexes | Port `dictionary` validators from V2 |
| `app/schemas/vendor.py` | Models defined | Not used by routes; either wire up or document as reference-only |
| `DEFAULT_PIPELINE` | Read into `Settings` | Not consumed by routing; wire up or remove |

---

## What Must NOT Be Changed

Without reading `DECISIONS.md` first:

1. **The 24-key canonical record.** Both engines and all downstream code depend on it.
   `check_config.py` enforces it by AST-parsing V1's `XLSX_CELL_MAP` (deliberately *not*
   importing it, so the offline environment never loads `google-genai`).
2. **The image-coverage OCR decision** (`document_loader.py`, D-10). Reverting to a
   character-count test silently corrupts the cancelled cheque, which carries a mangled
   536-character baked-in text layer.
3. **The two-pass validation order** (`semantic_engine.py`, D-16). Collapsing it reintroduces
   a fixed bug where OCR debris beat a genuine value.
4. **The oneDNN disable at module scope** (`ocr_engine.py`, D-11). It must be set before
   `paddlex` imports. Overridable by env var for re-testing after an upstream fix.
5. **SAHI and image preprocessing staying off** (D-12, D-13). Both were measured on real
   documents and rejected with numbers. Do not enable because they sound like best practice.
6. **The two different fuzzy scorers** in the `dictionary` validator (D-15). Unifying them
   lets an invented bank name score 85/100.
7. **The strict config loader** (D-08). Loosening it trades a loud startup error for a
   silent blank Excel cell.
8. **Branch `ver1`** — it holds a commit present nowhere else.
9. **`.gitignore` coverage of `uploads/`, `outputs/`, `.env`, real ground-truth YAML** (D-20).
   These contain live PII.
10. **`ocr_engine.py` as the sole importer of `paddleocr`** (D-07). Keeps the backend swappable.

---

## Important Historical Context

- **The project has already been through one full technology reversal.** The first
  implementation used Tesseract + hand-written regexes; it was abandoned because Tesseract was
  unreliable on watermarked scans and *every new layout needed another regex*. V1 (Gemini)
  replaced it. V2 then returned to local OCR — but with a different engine and, critically, a
  **config-driven** matcher rather than per-layout regexes. The rejected thing was the
  maintenance model, not OCR itself. The prototype survives at
  `legacy/vendor_form_extractor_ocr.py` and its header states the reasoning.
- **Several non-obvious guards exist because of specific real documents.** The 50%
  image-coverage rule, the 0.97 similarity floor for ≤4-character captions, the
  caption-must-start-the-span rule, the boundary-wrapped scan patterns, and
  `fix_ifsc_confusions` all trace to concrete failures on the sample vendor's documents.
  Removing them will silently regress those cases. The code comments name the failures.
- **One earlier diagnosis was wrong and has been corrected in writing.** The `bank_name`
  defect was first attributed to the `expected_documents` tie-break's 0.05 score window being
  too narrow. Dumping the actual candidate list disproved this: the cheque contributes **zero**
  `bank_name` candidates, so no tie-break could ever have run. D-14 records the correct cause.
  Do not re-derive from the earlier explanation if you encounter it elsewhere.

### Context that exists only outside the repository

Recorded here explicitly rather than left implicit:

- **The measured accuracy JSON files** (`outputs/eval/v1_accuracy.json`,
  `v2_accuracy.json`) are in gitignored `outputs/`. The **numbers** are preserved in
  `PROJECT_STATE.md` and above; the raw per-field files are not in git and will not transfer
  with a clone. Re-generate with the harness if needed.
- **The real ground-truth file** `app/pipelines/v2/eval/ground_truth/mb_control_systems.yaml`
  is gitignored (it transcribes real PAN/IFSC/account numbers). **It will not transfer with a
  clone.** It must be copied across manually or re-created from the schema. Its content is
  described in `PROJECT_FILE_INVENTORY.md`.
- **The sample vendor documents** live outside the repository at
  `C:\Users\shubh\Downloads\Sample vendor documents (4)\Sample vendor documents\`
  (GST certificate, cancelled cheque, Udyam certificate, and the
  `VENDOR CREATION REQUEST FORM.xlsx` template with 6 entity sheets: NSIND, NSITSL, SEBIZ,
  Smarter, NSV, CSIND). Copies also exist under gitignored `uploads/<run_id>/`. These are not
  in git and must be transferred separately.
- **The Gemini API key** is in gitignored `.env` and must be re-created in the new account —
  and should be **rotated** regardless, since it was exposed in a terminal session and chat
  transcript.
- **The PaddleOCR model weights** (~100 MB) download on first run to
  `~/.paddlex/official_models/`. Not in the repo; will re-download automatically.

No other significant context is believed to exist outside the repository. Design rationale
that was previously only in conversation has been written into `DECISIONS.md`.

---

## Architecture Decisions

Full record in `DECISIONS.md` (20 entries, D-01 … D-20, plus open questions). The decisions
most likely to affect your next change:

| ID | Decision |
|---|---|
| D-05 | V2 is fully local/offline and coexists with V1 rather than replacing it |
| D-06 | Both engines converge on one 24-key canonical record |
| D-07 | PaddleOCR PP-OCRv6 `small`; `tiny` rejected for hallucinating glyphs |
| D-08 | Field knowledge is YAML, not Python; loader is strict on purpose |
| D-09 | Validation centralised and referenced by name; `derived` rules keep field names out of Python |
| D-10 | Text-layer trust decided by image coverage, not character count |
| D-12 | SAHI evaluated and rejected, with numbers |
| D-13 | Image preprocessing evaluated and rejected as default, with numbers |
| D-14 | **`expected_documents` → filter: proposed, not implemented** |
| D-15 | `dictionary` validator with two modes and two deliberately different scorers |
| D-16 | Validators run twice — as selection signal, then as status |
| D-18 | The in-app verification check measures write integrity, not accuracy |
| D-19 | Ground truth must be human-transcribed, never pipeline-generated |

---

## Known Problems

Full ranked list in `PROJECT_STATE.md` → Known Bugs (15 items). The critical four:

1. **The Gemini key is on a free tier** whose terms state submitted content is used for
   product improvement, may be human-reviewed, and explicitly say not to submit personal
   information — while vendor PANs and account numbers pass through it. Fix: enable billing.
2. **The key was exposed** in a terminal session and chat transcript. Fix: rotate.
3. **V1 never deletes uploaded files** from the Gemini File API, which retains them until
   expiry independently of any Zero Data Retention setting. Fix: `client.files.delete()`.
4. **V2 mixes bank details across documents**, producing a record that would fail a real
   payment. Root cause confirmed; fix designed as D-14.

Then: unverified ground truth and n=1 (5), V1's four silently-unextractable fields (6), no
test suite (7), and the verification report being misread as accuracy (8).

---

## Next Task

**Implement D-14 — make `expected_documents` a filter for fields that declare it.**

Chosen because it is the highest-severity *code* defect (the three above it are configuration
and credential actions the user must perform), the root cause is already confirmed, and the
fix is well-scoped.

Where: `app/pipelines/v2/semantic_engine.py`, `_choose()` — and possibly earlier, at the
pooling step in `extract()`.

Behaviour to implement: for a field whose config declares `expected_documents`, if **any**
candidate originated from a document classified as one of those types, discard candidates from
other document types before selecting. Where no candidate comes from an expected document, the
field should end up **absent and flagged for review** rather than silently taking a value from
an unexpected document.

Expected outcome on the sample vendor: `bank_name` becomes empty-and-flagged instead of
`"Bank of India"`, eliminating the mixed-bank record. Verify with:

```bash
python -m app.pipelines.v2.eval.eval_extraction \
  --ground-truth app/pipelines/v2/eval/ground_truth/mb_control_systems.yaml \
  --documents "<sample docs dir>" --pipeline v2 --allow-unverified \
  --cache outputs/ocr_cache.json
```

`bank_name` should move from `wrong` to `missed`. That is an improvement: a blank flagged for
review is safe, a confident wrong bank is not. Note this will slightly *lower* recall while
*raising* precision — expected and correct.

Do not also try to fix `website`, `nature_of_business` or `branch_address` in the same change.

---

## How To Start The Project

```bash
git clone https://github.com/ShubhSonakiya18/vendor-extractor-v1.git
cd vendor-extractor-v1
cp .env.example .env        # then set GEMINI_API_KEY if V1 is wanted
```

### V2 (local, offline) — needs Python 3.12
```bash
py -3.12 -m venv .venv-paddle
.venv-paddle\Scripts\Activate.ps1          # or: source .venv-paddle/bin/activate
pip install -r requirements.txt -r requirements-v2.txt
python -m uvicorn app.main:app --reload    # → http://127.0.0.1:8000/v2
```
First run downloads ~100 MB of OCR models to `~/.paddlex/official_models/`.

### V1 (Gemini) — any supported Python
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload    # → http://127.0.0.1:8000/
```

**Always `python -m uvicorn`, never bare `uvicorn`** — the script is not on PATH in this setup.

Full details in `ENVIRONMENT_SETUP.md`.

---

## How To Validate The Current State

Run these in order. Results below are what they produced at the checkpoint — anything
different means something changed.

```bash
# 1. everything compiles
python -m compileall -q app legacy
#    expect: exit 0, no output

# 2. app imports and V1 availability is detected
python -c "import app.main as m; print('V1_AVAILABLE =', m.V1_AVAILABLE)"
#    expect: V1_AVAILABLE = True   (False is also valid if google-genai isn't installed)

# 3. all YAML config valid + V1/V2 field-key compatibility
python -m app.pipelines.v2.check_config
#    expect: "RESULT: ALL CHECKS PASSED"
#            24 fields, 17 validators, 12 fields with patterns, 5 cross-doc checks

# 4. live startup
python -m uvicorn app.main:app --port 8010
#    then, in another shell:
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8010/v2
curl -s http://127.0.0.1:8010/v2/health
#    expect: 200, and
#    {"status":"ok","mode":"local","v1_available":true,"fields":24,
#     "validators":17,"excel_mappings":["vendor_creation_v1"]}
```

**There is no test suite** — no `tests/`, pytest not installed. `check_config` is the smoke
test. Adding pytest is open work item 9 in `PROJECT_STATE.md`.

Note: `len(app.routes)` differs between environments (7 in the V2 venv, 15 in the V1 venv) due
to a FastAPI/Starlette version difference in how `include_router` is represented. Both serve
identically — verified by live HTTP. Not a bug.

---

## First Things A New Claude Code Session Should Read

1. `CLAUDE.md`
2. `PROJECT_STATE.md`
3. `DECISIONS.md`
4. `MIGRATION_HANDOFF.md`

Then `PROJECT_FILE_INVENTORY.md` and `ENVIRONMENT_SETUP.md` as needed, and `README.md` for the
user-facing architecture write-up.

---

## Resume Instructions

1. Read the four documents above **before** running or changing anything.
2. Inspect the repository — at minimum `app/main.py`, `app/pipelines/v2/semantic_engine.py`,
   `app/pipelines/v2/field_matcher.py`, and `app/config/field_dictionary.yaml`.
3. Run the four validation commands under *How To Validate The Current State* and confirm they
   match the recorded results.
4. Confirm with the user which of the three credential/configuration actions (rotate key,
   enable billing, delete uploaded files) have been done — they are outside this repository
   and cannot be verified from it.
5. Obtain the items listed under *Context that exists only outside the repository* — in
   particular the sample documents and, if it is to be reused, the real ground-truth file.
6. Only then start on *Next Task*.
7. Do not redo anything under `PROJECT_STATE.md` → **Do Not Repeat**.
