# Decision Record

Chronological engineering/architecture decisions. Every entry below is grounded in the
repository — code, config, commit history, or a measurement recorded in it. Where evidence for
a decision's *original motivation* is limited to a code comment, that is stated.

Ordering follows the repository's own history: initial commit → V2 landing → restructure →
current work.

---

## D-01 · Automate the vendor form rather than hand-copy it
**When:** initial commit `0730fa3`
**Decision:** read the vendor's GST certificate, Udyam certificate and cancelled cheque, and
auto-fill the Vendor Creation Request Form's ~24 fields.
**Why:** manual copy-typing of statutory identifiers and bank details is slow and the errors
are expensive — a mistyped account number misdirects a payment.
**Evidence:** repository purpose; `XLSX_CELL_MAP` maps 24 fields to cells `B37`–`B63` of the
real template.

---

## D-02 · First implementation used Tesseract OCR + hand-written regexes — REJECTED
**When:** before/at initial commit; superseded within the first phase
**Decision:** abandoned in favour of a multimodal LLM (D-03). Kept at
`legacy/vendor_form_extractor_ocr.py`, imported by nothing.
**Why rejected:** stated in that file's own header — *"Tesseract accuracy on
scanned/watermarked certificates was inconsistent and every new layout needed another
hand-written regex."* Two distinct failures: unreliable recognition, and unbounded
per-layout maintenance.
**Note:** V2 later returned to local OCR, but with a different OCR engine (PaddleOCR) and,
critically, a **config-driven** matcher instead of per-layout regexes — the maintenance
problem, not OCR itself, was the reason for abandoning this approach.

---

## D-03 · V1 uses Gemini with per-document response schemas
**When:** initial commit `0730fa3`
**Decision:** one API call per document, each constrained by a JSON `response_schema`
(`GST_SCHEMA`, `UDYAM_SCHEMA`, `CHEQUE_SCHEMA`).
**Why:** the schema makes the reply parseable without free-text parsing, and per-document
prompts let each prompt name exactly the fields that document carries.
**Consequence discovered later:** each call sees only one document. This turned out to be
*accidentally protective* — V1 structurally cannot pull a bank name off the Udyam certificate,
which is exactly the mistake V2 makes (see D-14).

---

## D-04 · GST certificate is the authority when documents disagree on PAN
**When:** initial commit
**Decision:** characters 3–12 of the GSTIN are the holder's PAN; compare against the Udyam
certificate's PAN field. On conflict the **GST certificate wins**, and
`pan_mismatch_between_gst_and_udyam` is appended to `needs_review`.
**Why:** the GST certificate is the statutory source of record.
**Evidence:** `build_vendor_json()`; later generalised into V2's `gstin_contains_pan`
`derived` validator.

---

## D-05 · Build V2 as a fully local/offline pipeline, alongside V1 rather than replacing it
**When:** commit `8db272e`
**Decision:** V2 performs all reading on the local machine — no network, no API key. V1 remains
available and maintained; both are served from one app.
**Why:** vendor documents carry PAN and bank account numbers which in many deployments cannot
leave the machine. Keeping V1 preserves a working path where cloud use is acceptable and gives
a comparison baseline.
**Evidence:** `README.md` states V2 is *"a ground-up rebuild for environments where vendor
documents (PAN, GSTIN, bank details) can't leave the machine"*; both routers exist in
`app/main.py`.

---

## D-06 · Both engines converge on one 24-key canonical record
**When:** `8db272e`
**Decision:** V1 and V2 emit an identical dictionary; the Excel writer and verifier are shared
and engine-agnostic.
**Why:** makes the engines interchangeable and prevents downstream duplication.
**Enforcement:** `check_config.py` asserts every key in V1's `XLSX_CELL_MAP` exists in V2's
field dictionary — reading it by **AST-parsing V1's source rather than importing it**, so the
offline V2 environment never has to load `google-genai`.
**Status:** load-bearing. Do not break.

---

## D-07 · PaddleOCR is V2's OCR engine, with PP-OCRv6 `small` as default
**When:** `8db272e`
**Decision:** PaddleOCR 3.x, `PP-OCRv6_small_det` / `_rec`. `ocr_engine.py` is the only module
permitted to import `paddleocr`.
**Why:** measured, recorded in `ocr_engine.py`:

| Model | Time | Mean confidence |
|---|---|---|
| `PP-OCRv6_medium` (PaddleOCR default) | 93.3s | 0.962 |
| `PP-OCRv6_small` ← chosen | 10.7s | 0.948 |
| `PP-OCRv6_tiny` | 3.8s | 0.875 |

~9× faster than stock `medium` for a marginal confidence cost.
**`tiny` explicitly rejected:** it *hallucinated CJK glyphs that were not on the page*. A
confidently wrong GSTIN is far more dangerous than a slow one.
**Isolation rationale:** everything downstream consumes `TextSpan`, so swapping OCR backends
means rewriting one file.

---

## D-08 · Field knowledge lives in YAML, not Python
**When:** `8db272e`
**Decision:** captions, regex patterns, normalisation chains, validator references, search
directions, document profiles and Excel cell maps are all data in `app/config/`. No field name
appears in `app/pipelines/v2/*.py`.
**Why:** this is the direct answer to D-02's failure mode. Adding a field or a document type
must not require touching extraction code. Explicitly aimed at scaling toward far more fields
than the current 24 — `config_loader.py`'s own docstring reasons about *"someone adding their
500th field"*.
**Consequence:** the loader is deliberately **strict** — unknown keys, unresolvable validator
names, invalid regexes, unknown normalisation ops, and confidence weights not summing to 1.0
all fail at load time naming the field. Rationale in the docstring: the silent alternative is
that a field never matches and *"nobody notices until an Excel cell is blank."*

---

## D-09 · Validation is centralised and referenced by name
**When:** `8db272e`
**Decision:** all rules live once in `validation_rules.yaml`, referenced by name from
`field_dictionary.yaml`. Six rule types: `regex`, `length`, `enum`, `non_empty`, `derived`,
`dictionary`.
**Why:** stated in that file's header — V1 duplicated the same six regexes across
`vendor_form_extractor_gemini.py` and the legacy OCR prototype, *"so they could drift apart."*
**`derived` rules** exist so cross-field checks ("the PAN inside the GSTIN must equal the PAN
field") can be expressed **without either field name appearing in Python**.

---

## D-10 · Trust a PDF text layer based on image coverage, not character count
**When:** `8db272e`
**Decision:** per **page**: OCR if text-layer characters < 40, **or if raster image coverage
≥ 50%** even when a text layer is populated.
**Why:** a real failure recorded in `document_loader.py`. The sample cancelled cheque is a
100%-image page carrying a **536-character** baked-in text layer that is mangled — "ICICI Bank"
arrives as `"Otctctean"`, "Hindustan Road" as `"Hlndu.tan Rord"`. A character-count test trusts
it and silently corrupts exactly the fields that matter most. Genuine digital pages sit around
1% coverage (logo + signature), so the margin is wide.
**Status:** do not revert to a character-count test.

---

## D-11 · Force-disable oneDNN for PaddlePaddle on CPU
**When:** `8db272e`
**Decision:** `os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")` at **module
scope** in `ocr_engine.py`.
**Why:** PaddlePaddle 3.3.1's oneDNN run mode crashes in the PIR executor —
`NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute not support
[pir::ArrayAttribute<pir::DoubleAttribute>] (onednn_instruction.cc:118)`.
**Why module scope:** `paddlex` reads the flag at import time; setting it later has no effect.
**Deliberately overridable:** an explicit environment value wins, so oneDNN can be re-enabled
and re-tested after an upstream fix — that would be a free speedup.

---

## D-12 · SAHI (Slicing Aided Hyper Inference): evaluated, REJECTED as default
**When:** current work phase
**Decision:** not adopted. Evaluation harness kept at `eval/eval_sahi.py`.
**Measured** on the cancelled cheque at the pipeline's real 200 DPI (1592×723 px):

| Configuration | Spans | Target fields recovered | Time |
|---|---|---|---|
| Baseline (current default) | 29 | all | 7.4s |
| Upscaled `text_det_limit_side_len=1920` | 28 | all | 21.3s |
| Tiled 2×2, 15% overlap | 43 raw | all | 10.9s |

**Why rejected:** the baseline already recovered every target field. Upscaling was 3× slower
with no gain. Tiling's extra 14 spans are duplicates from overlap regions that would require
NMS-style merge logic, plus boundary-split risk — real complexity for zero measured recall.
SAHI's premise is that whole-image downscaling loses small objects; at 200 DPI an A4 page is
~1650×2340 px, nowhere near that regime.
**Revisit if:** a document source appears with genuinely higher resolution or much denser small
text. Re-measure with the harness before enabling.

---

## D-13 · Image preprocessing (denoise + CLAHE + unsharp): evaluated, REJECTED as default
**When:** current work phase
**Decision:** implemented at `preprocessing.py`, exposed as `OCREngine(preprocess=True)`,
**off by default**.
**Measured:**

| Document | Spans raw → processed | Mean confidence |
|---|---|---|
| Cheque (clean digital render) | 29 → 28 | 0.948 → 0.941 |
| Udyam certificate (real scan) | 104 → 104 | 0.973 → 0.973 |
| Cheque + synthetic noise (blur, underexposure, Gaussian) | 27 → 26 | 0.925 → 0.916 |

**Why rejected as default:** neutral-to-negative on every sample, including one deliberately
degraded to simulate a bad phone photo. PP-OCRv6 is already trained on noisy real-world text;
CLAHE's local contrast boost amplifies injected noise rather than suppressing it.
**Also rejected — binarisation:** adaptive thresholding dropped spans 29 → 21 on the cheque.
PP-OCRv6 expects continuous-tone input; hard thresholding clips thin strokes and anti-aliased
glyph edges the recogniser uses.
**Kept because:** a genuinely low-quality source (visible scanner speckle, heavy JPEG
artefacts) is not represented in the current samples. Re-measure before enabling.

---

## D-14 · `expected_documents` should become a filter, not only a tie-break — PROPOSED, NOT IMPLEMENTED
**When:** current work phase
**Status:** **open proposal.** Do not treat the current behaviour as an accidental bug.
**Current behaviour:** `expected_documents` contributes ±0.05 to a candidate's score and acts
as the first tie-break in `_choose()`, but only among candidates within a 0.05 score window.
**Problem it fails to prevent:** `bank_name` is taken from the Udyam certificate while `ifsc`
and `account_number` come from the cheque, producing a record pairing one bank's name with
another bank's account number — which would fail a real payment. The vendor's documents
genuinely list two different accounts (Udyam: Bank of India / BKID0004035 / 403530100000002;
cheque: ICICI Bank / ICIC0006278 / 627851000539).
**Confirmed root cause** (verified by dumping the candidate list — every candidate, winner and
all five alternatives, came from the Udyam certificate; the cheque contributed **none**):
1. A cheque never captions its own bank name — it is a logo, OCR'd as `'AICICIBank'`.
2. `bank_name` has `patterns: []`, and the pattern-only fallback is guarded by
   `if spec.patterns:` — so for this field there is no fallback.
3. The caption "Bank" is 4 characters, so the short-caption rule requires 0.97 similarity;
   `'AICICIBank'` misses.
4. `'Payable at par at all branches of ICiCI Bank Limited in India'` contains "Bank", but
   captions must start a span (`alignment.dest_start <= 2`) and here it is ~40 characters in.

Zero candidates from the cheque means the tie-break never runs — Udyam wins uncontested.
**An earlier hypothesis that the 0.05 window was too narrow was WRONG and has been corrected.**
**Proposed fix:** where a field declares `expected_documents`, if *any* candidate came from an
expected document, discard candidates from other documents. Then `bank_name` yields nothing and
is correctly flagged missing for a human, instead of a confident wrong value.

---

## D-15 · `dictionary` validator type, with two modes and two different scorers
**When:** current work phase
**Decision:** added a sixth validator type performing fuzzy membership against curated word
lists in `app/config/dictionaries/`. Wired to `bank_name` (`membership` vs ~50 RBI-scheduled
banks) and `vendor_name` (`contains` vs legal-entity suffixes).
**Why:** regex validates *shape*, but `vendor_name`, `bank_name` and `city` have
`patterns: []` — nothing was checking them at all, so OCR garbage passed silently.
**Why two scorers** (empirical, not stylistic):
- `membership` uses RapidFuzz **`ratio`**. `WRatio` gives partial credit for substrings, which
  scored the invented `"Xyzabc Fake Bank Corp"` at **85/100** against "ICICI Bank" purely for
  containing "Bank" — over threshold. Plain `ratio` scores it **45**, correctly rejecting it.
- `contains` uses **`WRatio`**, because there the length mismatch is wanted: `"PVT LTD"`
  genuinely is inside `"M B CONTROL & SYSTEMS PVT LTD"`, and `ratio` penalises that.
**Case-folding** happens inside the validator, independent of each field's normalisation chain,
because `ratio` is case-sensitive and `bank_name` is deliberately title-cased for Excel output.
**Both are `severity: warning`, not `error`:** a bank outside the curated list, or a sole
proprietor with a bare name, is legitimate. The check flags for review, it does not block.
**Verified against:** `'Otctctean'` (the real OCR garbage) → fails; `'STATE BANK 0F INDIA'`
(zero-for-O) → passes; `'Xyzabc Fake Bank Corp'` → fails.

---

## D-16 · Validators run twice — as selection signal, then as reported status
**When:** `8db272e` (bias pass added during V2 development)
**Decision:** in `semantic_engine.py`, validators run on **each candidate before selection**
(fail-error ×0.35, fail-warning ×0.75, pass +0.10), and again after selection to set the
reported status.
**Why:** recorded in `_apply_validation_bias`'s docstring — validation used to run only after
selection, so a value that *could never be correct* still won on layout evidence alone: the
`state` field picked OCR debris (`"Rvic"`) over the genuine `"West Bengal"` a few points lower.
Turning the rules into selection signal uses the knowledge they already encode.
**`derived` rules are skipped in the first pass** — they compare fields against each other and
nothing is decided yet.
**Status:** do not collapse to a single pass.

---

## D-17 · Layered FastAPI structure; `v2/` and `config/` moved under `app/`
**When:** commit `314675e`
**Decision:** restructured from a flat layout (`app.py`, `v2/`, `config/`, `templates/`,
`static/` at repo root) into `app/` with `core/`, `routes/`, `services/`, `schemas/`, `utils/`,
`pipelines/v2/`, `config/`, `templates/`, `static/`. Entry point became `app.main:app`.
**Why:** requested separation of routes / business logic / configuration / schemas. Routes now
contain HTTP concerns only.
**Path consequences handled:** `config_loader.CONFIG_DIR` gained a `.parent`;
`check_config.V1_SOURCE` was repointed at `app/services/vendor_v1_gemini.py`; all
`python -m v2.*` CLI references became `python -m app.pipelines.v2.*`. All internal V2 imports
were already relative, so they survived unchanged.
**Deliberately NOT created:** `models/`, `repositories/`, `core/security.py`, `tests/`. The
requested template included them, but this app has no database and no auth, so they would have
been empty scaffolding. `core/logging.py` *was* created, because V2 modules already called
`logging.getLogger` with nothing configuring the root logger under uvicorn.
**Snapshot preserved:** the pre-restructure layout survives on branch `ver1` (`a732744`).

---

## D-18 · The in-app verification check measures write integrity, not extraction accuracy
**When:** clarified during current work phase (behaviour dates to the initial commit)
**Decision:** keep the write-back check, but stop treating it as a quality metric; build a
separate ground-truth evaluation for accuracy.
**Why:** both sides of that comparison — the "expected" JSON and the "actual" cell — originate
from the *same* extraction. It catches Excel type coercion (a text PIN `"700019"` read back as
`700019.0`), merged-cell misdirection and failed writes. It cannot catch a misread value. On a
run containing four real errors it reported **24/24 PASS**.
**Follow-up:** rename in the UI to something like "Excel Write Check" (open, Bug 8).

---

## D-19 · Ground truth must be human-transcribed, never pipeline-generated
**When:** current work phase
**Decision:** ground-truth files record what a **person** read off the documents. The loader
refuses any file not marked `verified: true` unless `--allow-unverified` is passed, which prints
a warning.
**Why:** populating ground truth by running the extractor makes the evaluation circular and
reports ~100% regardless of real accuracy — it would grade the extractor against its own answers.
**Schema decisions:**
- `absent: true` is distinct from a missing value. It means *a correct extractor returns null*,
  which makes `hallucinated` a measurable outcome — important for the LLM path.
- Fields where documents disagree are recorded under `conflicts` **with the reasoning**, because
  choosing between two genuine values is a *business* decision, not a transcription one.
- For bank details the **cancelled cheque wins** over the Udyam certificate: the form is
  collecting the account to be paid into and the cheque is the proof-of-ownership artefact; a
  Udyam bank block can be years stale. This call is recorded so it is not silently reversed.
**PII handling:** real ground-truth files are gitignored; only the fabricated
`example_synthetic.yaml` is committed.

---

## D-20 · Vendor PII never enters version control
**When:** initial commit, extended during current work phase
**Decision:** `.gitignore` excludes `/uploads/`, `/outputs/`, `.env`, `*.log`, `.venv*/`,
`.vscode/`, and `app/pipelines/v2/eval/ground_truth/*.yaml` with a negation for
`example_synthetic.yaml`.
**Why:** these hold live GSTINs, PANs and bank account numbers.
**Verified at checkpoint:** the Gemini key exists only in gitignored `.env`; `git log --all -S`
finds it in no commit on any branch; `.env` was never tracked.

---

## Open questions for the next owner

1. **Run both engines and diff them?** Their failures are largely *uncorrelated* — V1 got
   `bank_name` and `website` right where V2 failed; V2 got `account_type` right where V1
   structurally cannot. Flagging disagreements would likely catch most single-engine errors,
   at the cost of cloud exposure on every run. The 24-key contract already makes this cheap to
   build. Not yet decided.
2. **Is the cheque the right authority for bank details in *your* process?** D-19 assumed yes.
   If your process treats the Udyam certificate as authoritative, ground truth flips and the
   `bank_name` score inverts.
3. **Should `DEFAULT_PIPELINE` actually drive routing?** It is read into `Settings` but
   `app/main.py` routes purely on the import guard. Either wire it up or remove it.
4. **`opencv-contrib-python` is an undeclared direct dependency** of `preprocessing.py`,
   currently satisfied transitively via PaddleOCR. Add it to `requirements-v2.txt` or drop the
   import.
