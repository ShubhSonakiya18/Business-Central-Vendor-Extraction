# CLAUDE.md — operating guide for Claude Code sessions

Read this first, then `PROJECT_STATE.md`, `DECISIONS.md`, `MIGRATION_HANDOFF.md`.

---

## What this project is

Reads a vendor's onboarding documents — GST certificate, Udyam (MSME) registration,
cancelled cheque — and auto-fills a **Vendor Creation Request Form** in Excel, then
verifies every written cell. Replaces manual copy-typing of ~24 fields including
statutory identifiers (GSTIN, PAN) and bank details (IFSC, account number).

**There are two extraction engines**, both shipped, both live in one FastAPI app:

| | Engine | Route | Needs |
|---|---|---|---|
| **V1** | Google Gemini (multimodal cloud API) | `/` | `GEMINI_API_KEY`, internet |
| **V2** | PaddleOCR + local config-driven engine | `/v2` | nothing — fully offline |

V2 exists because vendor documents contain PAN and bank account numbers that in many
deployments cannot leave the machine. It is not a replacement for V1; both are maintained.

---

## The single most important architectural fact

**Both engines emit an identical 24-key dictionary** (the "canonical record"). Everything
downstream of that point — Excel writing, write-back verification — is shared code that
does not know which engine produced the data.

Do not break this contract. `app/pipelines/v2/check_config.py` enforces it at config-load
time by AST-parsing `XLSX_CELL_MAP` out of V1's source.

---

## Directory map

```
app/
├── main.py                   entry point; mounts routers, decides if V1 exists
├── core/
│   ├── config.py             loads .env into a typed Settings object (load_dotenv lives here)
│   └── logging.py            configures the root logger
├── routes/                   HTTP layer ONLY — no business logic
│   ├── vendor_v1.py          /  /generate  /results/{id}  /download/{id}/{kind}
│   └── vendor_v2.py          /v2/*  including /v2/health
├── services/                 business logic, framework-agnostic
│   ├── vendor_v1_gemini.py   V1 engine + XLSX_CELL_MAP + fill_vendor_xlsx
│   ├── vendor_v1_verify.py   V1 Excel write-back check
│   ├── vendor_v1_service.py  orchestrates V1 for its route
│   └── vendor_v2_service.py  orchestrates V2 for its route; raises V2ServiceError
├── schemas/vendor.py         pydantic response shapes
├── utils/uploads.py          save an UploadFile to disk
├── pipelines/v2/             the local engine (see PROJECT_STATE.md for module table)
│   └── eval/                 accuracy / SAHI / preprocessing harnesses + ground truth
├── config/                   ALL V2 field knowledge, as YAML — edit this, not Python
├── templates/  static/       Jinja2 pages, CSS
legacy/                       superseded Tesseract+regex prototype, reference only
uploads/  outputs/            per-run data — GITIGNORED, contains real PII
```

---

## How to run

```bash
# V1 environment (any Python; needs google-genai)
python -m uvicorn app.main:app --reload          # → http://127.0.0.1:8000/

# V2 environment (MUST be Python 3.12 — see constraints)
.venv-paddle\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload          # → http://127.0.0.1:8000/v2
```

**Always `python -m uvicorn`, never bare `uvicorn`** — the script is not on PATH here.

### CLI tools

```bash
python -m app.pipelines.v2.check_config          # validate all YAML, no OCR — fast sanity check
python -m app.pipelines.v2.dump_ocr <docs> --out outputs/inspect
python -m app.pipelines.v2.pipeline <docs> --template form.xlsx --sheet NSIND --out outputs/run
python -m app.pipelines.v2.eval.eval_extraction \
    --ground-truth app/pipelines/v2/eval/ground_truth/<vendor>.yaml \
    --documents <docs> --pipeline v2 --cache outputs/ocr_cache.json
```

---

## Tests

**There is no test suite.** No `tests/` directory, pytest not installed. This is a known
gap, not an oversight to be surprised by — see `PROJECT_STATE.md` → Known Bugs.

What exists instead:

- `python -m app.pipelines.v2.check_config` — validates all YAML config and asserts V1/V2
  field-key compatibility. Treat this as the smoke test; run it after any config change.
- `app/pipelines/v2/eval/eval_extraction.py` — integration-level accuracy scoring against
  human-verified ground truth. This is the closest thing to a correctness test.

If you add tests, `pytest` + the scoring/validation engines are the highest-value target.

---

## Environment variables

Copy `.env.example` → `.env`. Never commit `.env`.

| Var | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | for V1 only | Gemini API key |
| `GEMINI_MODEL` | no | defaults to `gemini-flash-lite-latest` |
| `DEFAULT_PIPELINE` | no | `auto` \| `v1` \| `v2` |
| `APP_TITLE`, `DEBUG` | no | cosmetic / log level |
| `UPLOAD_DIR`, `OUTPUT_DIR` | no | path overrides |
| `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT` | no | oneDNN escape hatch, see constraints |

**Anything that reads `GEMINI_API_KEY` must import `app.core.config` first** — that import
is what calls `load_dotenv()`. This has already caused one real bug in the eval harness.

---

## Coding conventions

- **Routes contain no business logic.** They read the upload, call a service, return a
  response. Everything else belongs in `app/services/`.
- **V2 field behaviour lives in YAML, never in Python.** No field name should appear in
  `app/pipelines/v2/*.py`. If you find yourself writing `if field == "ifsc"`, stop — add a
  config key instead.
- **`app/pipelines/v2/ocr_engine.py` is the only module that may import `paddleocr`.**
  Everything downstream consumes `TextSpan` objects, so the OCR backend stays swappable.
- **Comments explain *why*, and cite the real failure that motivated the code.** The
  existing codebase does this consistently; match it. Several non-obvious guards exist
  because of specific documents — removing them will silently regress those cases.
- Config loading is deliberately **strict**: unknown keys, unresolvable validator names,
  bad regexes, and confidence weights not summing to 1.0 all fail at load time, naming the
  field. Keep it that way; the silent alternative is a permanently blank Excel cell.

---

## Hard constraints

1. **V2 requires Python 3.12.** PaddlePaddle publishes no 3.14 wheel. The repo keeps a
   separate `.venv-paddle` for it. Do not "upgrade" this without checking wheel availability.
2. **oneDNN is force-disabled** at module scope in `ocr_engine.py`, working around a
   PaddlePaddle 3.3.1 CPU executor crash (`ConvertPirAttribute2RuntimeAttribute`). It must be
   set *before* `paddlex` is imported anywhere, which is why it sits at module scope. An
   env var overrides it, so it can be re-tested after an upstream fix.
3. **`uploads/`, `outputs/`, `.env`, and real ground-truth YAML are gitignored** because they
   hold live GSTINs, PANs and bank account numbers. Only the fabricated
   `ground_truth/example_synthetic.yaml` is committed. Never commit real vendor data.
4. **Windows console encoding** will crash on OCR output containing CJK glyphs (PaddleOCR
   occasionally hallucinates them). CLI entry points call
   `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`.
5. **Ground truth must never be generated by running the pipeline.** That makes evaluation
   circular and reports ~100% regardless of real accuracy. The loader refuses files not
   marked `verified: true`.

---

## Known issues you will hit

See `PROJECT_STATE.md` → Known Bugs for the full ranked list. The four that matter most:

1. **The Gemini key is on a free tier** whose terms say not to submit personal information,
   and state that content is used for product improvement with possible human review.
   Vendor PII is going through it. Highest-risk open item.
2. **V1 never deletes uploaded files** from the Gemini File API, which retains them
   independently of any Zero Data Retention setting.
3. **V2 mixes bank details across documents** — takes `bank_name` from the Udyam certificate
   while `ifsc`/`account_number` come from the cheque, producing a record that would fail a
   real payment. Root cause is understood; see `PROJECT_STATE.md`.
4. **The in-app "verification report" does not measure accuracy.** It reopens the saved Excel
   and diffs it against the extracted JSON — both sides come from the same extraction, so it
   proves write integrity only. It reported 100% PASS on a run containing four real errors.
   Do not cite it as an accuracy figure.

---

## Do not change these without reading `DECISIONS.md` first

- **The 24-key canonical record.** Both engines and all downstream code depend on it.
- **`expected_documents` semantics.** Currently a ±0.05 score nudge plus a tie-break. There
  is a known proposal to make it a filter (D-14) — that is a deliberate pending change, not
  a bug to fix casually.
- **The two-pass validation order** in `semantic_engine.py`. Validators run *before*
  selection as scoring signal and *again* after. Collapsing this to one pass reintroduces a
  fixed bug (OCR debris beating a genuine value).
- **Image-coverage-based OCR decision** in `document_loader.py`. Reverting to a character-count
  test silently corrupts the cancelled cheque, which carries a mangled baked-in text layer.
- **SAHI tiling and image preprocessing.** Both were measured on real documents and rejected
  with numbers (D-12, D-13). Do not enable them because they sound like best practice.
- **The strict config loader.** Loosening it trades a loud startup error for a silent blank cell.

---

## Where state is documented

| File | Contains |
|---|---|
| `CLAUDE.md` | this file — how to work in the repo |
| `PROJECT_STATE.md` | current snapshot: features, bugs, deps, git state, next steps |
| `DECISIONS.md` | chronological decision record, including rejected approaches |
| `MIGRATION_HANDOFF.md` | account-migration handoff, resume instructions |
| `PROJECT_FILE_INVENTORY.md` | per-file purpose / tracked / generated / sensitive |
| `ENVIRONMENT_SETUP.md` | how to recreate both environments from scratch |
| `README.md` | user-facing project documentation, architecture, CLI reference |
