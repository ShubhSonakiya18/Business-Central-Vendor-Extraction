# Environment Setup

How to recreate a working development environment from a fresh clone.

**No secrets appear in this file.** Where a credential is required, only the variable name and
where to obtain a value are given.

---

## Overview: two environments, deliberately separate

| | V1 (Gemini) | V2 (local OCR) |
|---|---|---|
| Python | 3.14 works (any modern 3.x) | **3.12 required** |
| Venv used here | system Python / `.venv` | `.venv-paddle` |
| Requirements | `requirements.txt` | `requirements.txt` + `requirements-v2.txt` |
| Needs internet at runtime | yes | no (after first model download) |
| Needs an API key | yes | no |

**Why two:** PaddlePaddle publishes **no wheel for Python 3.14**, so V2 cannot run on the
newer interpreter. Keeping them separate also lets V2 be deployed with no cloud dependency at
all. You can run just one if you only need that engine.

Because `google-genai` happens to be installed in `.venv-paddle` on the original machine, that
environment serves **both** engines — `/v2/health` reports `v1_available: true` there. That is
convenient but not required.

---

## Prerequisites

- **Git**
- **Python 3.12** — required for V2. On Windows, install so that `py -3.12` resolves.
- **Python 3.x** (3.14 fine) — optional, only if you want a separate V1-only environment.
- ~2 GB free disk: PaddlePaddle and its dependencies are large, plus ~100 MB of OCR models.
- No database. No external services beyond the Gemini API (V1 only).

---

## 1. Clone and configure

```bash
git clone https://github.com/ShubhSonakiya18/vendor-extractor-v1.git
cd vendor-extractor-v1
cp .env.example .env
```

Then edit `.env`. **`.env` is gitignored — never commit it.**

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | **V1 only** | — | Gemini API key. Obtain from <https://aistudio.google.com/>. Leave blank to run V2 only |
| `GEMINI_MODEL` | no | `gemini-flash-lite-latest` | Model id for V1 |
| `DEFAULT_PIPELINE` | no | `auto` | `auto` \| `v1` \| `v2`. *Currently read into `Settings` but not yet consumed by routing* |
| `APP_TITLE` | no | `Vendor Form Extractor` | Shown in the FastAPI title |
| `DEBUG` | no | `false` | `true` raises log level to DEBUG |
| `UPLOAD_DIR` | no | `<repo>/uploads` | Where uploads are written |
| `OUTPUT_DIR` | no | `<repo>/outputs` | Where artefacts are written |
| `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT` | no | forced to `0` in code | oneDNN escape hatch — see *Known environment issues* |

> **Important:** `load_dotenv()` is called by importing `app.core.config`. Any entry point that
> reads `GEMINI_API_KEY` must import that module first. This caused a real bug in the
> evaluation harness (fixed by an explicit import in `eval_extraction.py::extract_v1`) — keep
> it in mind when adding new CLI entry points.

---

## 2. V2 environment (local OCR) — Python 3.12

```powershell
# Windows PowerShell
py -3.12 -m venv .venv-paddle
.venv-paddle\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-v2.txt
```

```bash
# macOS / Linux
python3.12 -m venv .venv-paddle
source .venv-paddle/bin/activate
pip install -r requirements.txt -r requirements-v2.txt
```

Verify:

```bash
python -m app.pipelines.v2.check_config
# expect: "RESULT: ALL CHECKS PASSED" — 24 fields, 17 validators
```

Run:

```bash
python -m uvicorn app.main:app --reload      # → http://127.0.0.1:8000/v2
```

**First run downloads ~100 MB of OCR models** to `~/.paddlex/official_models/`
(`PP-OCRv6_small_det`, `PP-OCRv6_small_rec`). One-time cost; subsequent runs are offline.

### Installed versions confirmed working (Python 3.12.0)

```
paddlepaddle 3.3.1     paddleocr 3.7.0      paddlex 3.7.2
pypdfium2 5.12.1       rapidfuzz 3.14.5     python-docx 1.2.0    pyyaml 6.0.2
numpy 2.3.5            opencv-contrib-python 4.10.0.84
fastapi 0.141.1        uvicorn 0.52.1       jinja2 3.1.6         python-multipart 0.0.32
python-dotenv 1.2.2    pydantic 2.13.4      openpyxl 3.1.5       google-genai 2.17.0
```

> **Undeclared direct dependency:** `app/pipelines/v2/preprocessing.py` imports `cv2`, satisfied
> transitively by `opencv-contrib-python` (a PaddleOCR dependency). It is **not** listed in
> `requirements-v2.txt`. If PaddleOCR ever stops pulling OpenCV in, preprocessing breaks —
> add `opencv-python-headless` explicitly at that point. Tracked as an open question in
> `DECISIONS.md`.

---

## 3. V1 environment (Gemini) — optional, any modern Python

Only needed if you want a separate cloud-only environment; `.venv-paddle` already covers V1
when `google-genai` is installed there.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload      # → http://127.0.0.1:8000/
```

### Installed versions confirmed working (Python 3.14.2)

```
fastapi 0.135.3    uvicorn 0.44.0     jinja2 3.1.6     python-multipart 0.0.26
python-dotenv 1.2.2   pydantic 2.13.0   google-genai 2.17.0
openpyxl 3.1.5     tenacity 9.1.4
```

If `GEMINI_API_KEY` is unset or `google-genai` is missing, V1's routes are simply not mounted
and `/` redirects to `/v2`. The app still starts — that is by design.

---

## 4. Verify the installation

```bash
# everything compiles
python -m compileall -q app legacy               # expect exit 0, no output

# app imports; reports whether V1 is available
python -c "import app.main as m; print('V1_AVAILABLE =', m.V1_AVAILABLE)"

# all YAML config valid, and V1/V2 field keys compatible
python -m app.pipelines.v2.check_config          # expect "ALL CHECKS PASSED"

# live check — start the server, then in another shell:
curl -s http://127.0.0.1:8000/v2/health
# expect: {"status":"ok","mode":"local","v1_available":...,"fields":24,
#          "validators":17,"excel_mappings":["vendor_creation_v1"]}
```

**There is no test suite.** No `tests/` directory and pytest is not installed in either
environment. `check_config` is the de facto smoke test. See `PROJECT_STATE.md` → Testing.

---

## 5. Running the CLI tools

All are `python -m` module invocations from the repository root, in the V2 environment:

```bash
# validate config — fast, no OCR
python -m app.pipelines.v2.check_config

# see exactly what OCR read, and cache it for reuse
python -m app.pipelines.v2.dump_ocr <docs-dir> --out outputs/inspect

# full pipeline end to end
python -m app.pipelines.v2.pipeline <docs-dir> \
    --template "VENDOR CREATION REQUEST FORM.xlsx" --sheet NSIND --out outputs/run

# re-run extraction against cached OCR (skips OCR entirely — much faster)
python -m app.pipelines.v2.pipeline --cache outputs/inspect/document_set.json --out outputs/run

# score a pipeline against human-verified ground truth
python -m app.pipelines.v2.eval.eval_extraction \
    --ground-truth app/pipelines/v2/eval/ground_truth/<vendor>.yaml \
    --documents <docs-dir> --pipeline v2 --cache outputs/ocr_cache.json

# re-run the two rejected-technique evaluations
python -m app.pipelines.v2.eval.eval_sahi <doc.pdf> --gt ifsc=<expected>
python -m app.pipelines.v2.eval.eval_preprocessing <doc.pdf> --gt ifsc=<expected>
```

---

## Known environment issues

### 1. `uvicorn` is not on PATH
Always use `python -m uvicorn app.main:app`. The bare `uvicorn` command fails on the original
machine because the console script directory is not on PATH.

### 2. PaddlePaddle 3.3.1 oneDNN crash — already worked around
`app/pipelines/v2/ocr_engine.py` sets `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0` at **module
scope** (before `paddlex` can import), avoiding:

```
NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute
not support [pir::ArrayAttribute<pir::DoubleAttribute>] (onednn_instruction.cc:118)
```

An explicit environment value overrides the default, so oneDNN can be re-enabled and re-tested
after an upstream fix — that would be a free speedup. Re-test on every PaddlePaddle upgrade.

### 3. Windows console encoding
PaddleOCR occasionally emits CJK glyphs it hallucinated from noise, which crashes the default
Windows console codec with `UnicodeEncodeError`. CLI entry points call
`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`. If you add a new CLI that prints
OCR output, do the same, or run with `python -X utf8`.

### 4. `len(app.routes)` differs between environments
7 in the V2 venv, 15 in the V1 venv — a FastAPI/Starlette version difference in how
`include_router` is represented (`_IncludedRouter` wrappers vs flattened routes). Both serve
identically; verified by live HTTP. Not a bug.

### 5. First V2 run is slow
Model download (~100 MB) plus per-page OCR at 7–22s on CPU. A three-document vendor takes
~105s end to end. Digital PDFs with a real text layer are near-instant because OCR is skipped.

---

## External services

| Service | Used by | Notes |
|---|---|---|
| Google Gemini API | V1 only | Requires `GEMINI_API_KEY`. **Enable billing** — the free tier's terms state submitted content may be used for product improvement and human-reviewed, and explicitly say not to submit personal information. See `PROJECT_STATE.md` → Known Bugs 1 |
| PaddleOCR model CDN | V2, first run only | Downloads model weights to `~/.paddlex/official_models/`. Offline afterwards |

**No database.** All state is either on disk (`uploads/`, `outputs/`) or in module-level
dictionaries that are lost on restart (a known limitation — `PROJECT_STATE.md` Bug 9).

---

## Data you must supply separately

Not in the repository:

1. **Sample vendor documents** — a GST certificate, cancelled cheque, Udyam certificate, and a
   Vendor Creation Request Form `.xlsx`. Needed to run or evaluate anything. On the original
   machine these live at
   `C:\Users\shubh\Downloads\Sample vendor documents (4)\Sample vendor documents\`,
   with copies under gitignored `uploads/<run_id>/`.
2. **A ground-truth file** if you want to run accuracy evaluation. Real ones are gitignored;
   build from `app/pipelines/v2/eval/ground_truth/example_synthetic.yaml` and follow
   `ground_truth/README.md`. **Never generate it by running the pipeline** — that makes the
   evaluation circular.
3. **A Gemini API key** for V1.
