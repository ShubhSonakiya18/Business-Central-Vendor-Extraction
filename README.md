# Vendor Form Extractor — ver1

Snapshot branch. This is the state of the project right after V2 (the local, offline PaddleOCR pipeline) first landed alongside the original V1 (Gemini) pipeline — kept as a checkpoint for future reference.

For the actively maintained version with a full README, dependency pinning for V2, and further fixes, see the **`ver2`** branch (or `master`, which is kept identical to `ver2`).

---

## What's here

Two extraction pipelines, one FastAPI app:

| | Pipeline | Route | Requires |
|---|---|---|---|
| **V1** | Google Gemini (multimodal cloud API) | `/` | `GEMINI_API_KEY`, internet access |
| **V2** | PaddleOCR + a local, config-driven engine | `/v2` | Nothing — fully offline |

```
app.py                             FastAPI app — serves both V1 (/) and V2 (/v2)
vendor_form_extractor_gemini.py    V1: Gemini extraction + Excel fill
verify_vendor_excel.py             V1: Excel read-back verification
legacy/                            Superseded OCR/regex prototype (kept for reference)

v2/                                V2: fully local pipeline (10 modules — loader, OCR
                                    wrapper, layout engine, semantic matcher, validator,
                                    Excel mapper/verifier, CLI tools)
config/                            V2's field knowledge as YAML — labels, patterns,
                                    validators, document profiles, Excel cell mappings
templates/                         Jinja2 templates for both pipelines
```

## Running it

**V1 (Gemini):**
```bash
pip install -r requirements.txt
set GEMINI_API_KEY=your-key
uvicorn app:app --reload
```

**V2 (local, Python 3.12 required — PaddlePaddle has no 3.14 wheel):**
```bash
py -3.12 -m venv .venv-paddle
.venv-paddle\Scripts\Activate.ps1
pip install -r requirements.txt
pip install paddlepaddle==3.3.1 paddleocr==3.7.0 pypdfium2 rapidfuzz python-docx pyyaml
uvicorn app:app --reload
```
Open `http://127.0.0.1:8000/v2`.

CLI tools: `python -m v2.check_config` (validate YAML config, no OCR) and `python -m v2.pipeline <documents> --template <xlsx> --sheet <name>` (run end to end).

---

*See the `ver2` branch for the full project README, a pinned `requirements-v2.txt`, and subsequent bug fixes.*
