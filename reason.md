# RapidOCR vs PaddleOCR ("Baidu OCR") — comparison for the vendor‑extractor pipeline

## 0. Terminology — what "the two engines" actually are

| Name in this repo | What it is | Where it lives |
|---|---|---|
| **PaddleOCR** (a.k.a. "Baidu OCR") | Baidu's OCR toolkit. Ships the **PP‑OCR** model family (here: **PP‑OCRv6** det+rec). Runs on the **PaddlePaddle** deep‑learning framework. | `paddleocr==3.7.0` + `paddlepaddle==3.3.1` in [backend/requirements.txt](backend/requirements.txt). Execution path **preserved but commented out** in [ocr_engine.py](backend/app/services/extraction_pipeline/ingest/ocr_engine.py) under the "PRESERVED FALLBACK" banners. |
| **RapidOCR** | A community wrapper that takes **the same PP‑OCR models** (PP‑OCRv4 mobile det/rec, 6623‑glyph charset) and runs them on **ONNX Runtime** instead of PaddlePaddle. No new model architecture — same lineage, different runtime. | `rapidocr-onnxruntime==1.4.4` + `onnxruntime==1.20.1`. **ACTIVE default** (`OCR_BACKEND=rapidocr`) since 2026‑09‑01. |

So this is **not** "a lightweight OCR vs an unlimited Baidu OCR." Both are Baidu PP‑OCR models. The real axis of comparison is **runtime + packaged model size + tuning**, not model family.

The switch is controlled by one env var: `OCR_BACKEND` in [ocr_engine.py:119](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L119). Everything downstream consumes backend‑neutral `TextSpan` objects, so the engine is swappable without touching classification, extraction, validation or Excel mapping.

---

## 1. Metrics used to evaluate OCR performance

OCR quality is normally judged on the following. This doc scores both engines on each, using **what the codebase actually measures** (the project's own acceptance tool, `app/eval/eval_extraction.py`, scoring extracted fields against a **human‑verified ground truth**), plus globally‑known properties of the two runtimes.

| # | Metric | Definition | Why it matters here |
|---|---|---|---|
| M1 | **Character / recognition accuracy** (1 − CER) | Of the characters read, how many are right. | A single wrong char in a GSTIN/PAN/IFSC/account‑number = a `wrong` field on a form a human signs. |
| M2 | **Word / field accuracy** | Whole tokens correct. | The pipeline matches label→value tokens; a broken token breaks the field. |
| M3 | **Detection recall** (span recall) | Fraction of true text regions the detector finds. | A value that is never detected can never be extracted (`missed`). |
| M4 | **Detection precision** | Fraction of detected boxes that are real text. | Junk boxes (watermark bleed, scan noise) pollute spatial matching. |
| M5 | **Hallucination rate** | Confident output for text that isn't on the page. | **The worst failure mode** — a confident wrong GSTIN silently passes validation. Explicitly called out in [ocr_engine.py:61-67](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L61-L67). |
| M6 | **End‑to‑end field score** | `correct / wrong / missed / hallucinated / correctly_absent`, plus recall / precision / accuracy. | This is the project's real acceptance metric — [eval_extraction.py](backend/app/eval/eval_extraction.py). |
| M7 | **Latency (throughput)** | Seconds per scanned page. | "Known limitations" in [README.md](README.md) — scanned pages run ~10–35 s/page on CPU; this gates batch use. |
| M8 | **Latency stability** (P90 / stdev / CV) | Variance across repeated runs. | A run that spikes 26 s → 70 s (measured for one config) makes the UI feel broken. |
| M9 | **Determinism / reproducibility** | Same input → same output across runs/threads. | Needed for the verification report and for regression testing. |
| M10 | **Operational cost** (install, model download, Python/ABI constraints) | Footprint and fragility of the dependency. | PaddlePaddle here needs a CPU‑executor workaround and pins Python 3.12. |
| M11 | **Privacy / locality** | Does data leave the machine. | Hard requirement — "documents never leave the machine" ([README.md](README.md)). Both engines are fully local; noted for completeness. |

---

## 2. Head‑to‑head on each metric

### M1 — Character / recognition accuracy
- **Measured, this codebase:** On the `mb_control_systems` ground truth (3 real vendor documents, 24 fields, verified 2026‑09‑01), **identical** result: mean recognition confidence and per‑field correctness match. Both engines produce **19 correct / 1 wrong / 0 missed / 0 hallucinated** — see [mb_control_systems.SCORE.md](backend/app/eval/ground_truth/mb_control_systems.SCORE.md).
- **The one `wrong` field (`nature_of_business`) is shared** — both engines independently pick the same truncated "Manufactur" span on Udyam page 3. Root cause is a **field‑selection / search‑radius bug**, not an OCR defect ([ocr_engine.py:99-118](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L99-L118)).
- **Global knowledge:** PaddleOCR's stock **PP‑OCRv6** recogniser is a newer generation than the **PP‑OCRv4 mobile** recogniser RapidOCR ships by default, so on hard/degraded text PP‑OCRv6 has a modest edge in principle. Not observed on this vendor's docs.
- **Verdict:** **Tie on measured data.** Slight theoretical edge to PaddleOCR/PP‑OCRv6 on adversarial scans, unproven here.

### M2 — Word / field accuracy
- Native PDF text‑layer fields (GSTIN, PAN on the GST certificate) don't go through OCR at all — [document_loader.py:13-19](backend/app/services/extraction_pipeline/ingest/document_loader.py#L13-L19) — so they're identical regardless of engine.
- OCR‑only fields (cheque account number, IFSC, bank branch) scored identically on the ground truth.
- **Verdict:** **Tie on measured data.**

### M3 — Detection recall
- **RapidOCR's known weak spot.** Measured on the same 3‑document set: **RapidOCR 489 spans vs PaddleOCR 511 spans** — ~4% fewer text regions detected ([ocr_engine.py:112-118](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L112-L118)).
- On *this* vendor the 22 missing spans didn't touch any of the 24 target fields (field score unaffected). But the code comment is explicit: **"a different vendor's scan quality could expose that gap."**
- Mitigations already applied to close the gap (see `RapidOCRTuning` in [ocr_engine.py:164-265](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L164-L265)):
  - `max_side_len` raised 2000 → **3508** (RapidOCR's stock 2000 silently downscaled every A4 page ≥ ~150 DPI, hurting both detection and the recognition crops).
  - `text_score` lowered 0.5 → **inherits `drop_score` 0.30** (RapidOCR's stock 0.5 was a second, stricter filter stacked on top of the pipeline's own — it filtered ~67% harder than the PaddleOCR path).
  - `use_cls` forced **False** to match the PaddleOCR path (fairness, not accuracy).
- **Verdict:** **PaddleOCR wins** on raw detection recall. Gap is narrowed by tuning and irrelevant on the one vendor tested, but **unvalidated at scale**.

### M4 — Detection precision
- Post‑processing (`_rapid_result_to_spans` vs `_result_to_spans`) is **deliberately identical** — same filtering, same bbox collapse — so "the only variable between backends is the OCR itself" ([ocr_engine.py:771-777](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L771-L777)).
- No precision problem observed for either engine on the ground truth (0 hallucinated, 4 correctly‑absent both).
- **Verdict:** **Tie.**

### M5 — Hallucination rate
- **Both: 0 hallucinated** on the ground truth.
- Both engines default to the **full Chinese charset mobile recogniser**; the codebase deliberately keeps English‑only / `tiny` recognisers **opt‑in** because a past PP‑OCRv6_tiny test **invented CJK glyphs on Latin text** ([ocr_engine.py:223-231](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L223-L231)). That risk applies equally to both backends and is avoided the same way.
- **Verdict:** **Tie**, and both are configured conservatively.

### M6 — End‑to‑end field score (the project's real acceptance metric)

| correct | wrong | missed | hallucinated | correctly absent | recall | precision | accuracy |
|---|---|---|---|---|---|---|---|
| 19 | 1 | 0 | 0 | 4 | 95.0% | 95.0% | **95.8%** |

**Identical for `rapidocr` and `paddleocr`** ([mb_control_systems.SCORE.md](backend/app/eval/ground_truth/mb_control_systems.SCORE.md)). This is the single piece of evidence the codebase cites for making RapidOCR the default: *RapidOCR is not worse than PaddleOCR on this vendor's documents* — not that either is fully correct.

- **Caveat, stated in the code:** this ground truth covers **one vendor's three documents**. Multi‑vendor divergence testing (`plan.md` task 2.1) is **still open**.
- **Verdict:** **Tie on the evidence that exists.**

### M7 — Latency / throughput
- **RapidOCR wins.** It is "measured faster and more latency‑stable at its tuned operating point (100 DPI / 8 threads)" ([ocr_engine.py:108-110](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L108-L110)).
- Measured RapidOCR sweet spot: **DPI=100, threads=8 → 19.72 s median** per the 3‑document set, "the fastest AND most stable config measured" ([ocr_engine.py:240-262](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L240-L262)).
- PaddleOCR context: PP‑OCRv6 **medium** = 93.3 s on a single cheque render; **small** = 10.7 s — and PaddlePaddle's **oneDNN acceleration is disabled** here to work around a CPU‑executor crash in PaddlePaddle 3.3.1 ([ocr_engine.py:38-50](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L38-L50), [README.md](README.md) "Known limitations"), so the Paddle path runs without its main CPU speedup.
- ONNX Runtime also gives RapidOCR **easy DirectML/GPU** paths (`det_use_dml`, `rec_use_dml` kwargs) without the CUDA‑toolkit DLL fragility the Paddle GPU path has ([ocr_engine.py:638-661](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L638-L661)).
- **Verdict:** **RapidOCR wins**, clearly, at its tuned operating point.

### M8 — Latency stability
- RapidOCR at its **tuned** point is very stable: P90 within 1% of median, **CV = 0.01**, zero identifier mismatches across 12 reps ([ocr_engine.py:243-248](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L243-L248)).
- **But RapidOCR is tuning‑sensitive:** at DPI=125 / threads=8 it was **the single least stable config in the whole grid** (CV=0.40, one rep spiked to 70 s). The safe point (DPI=100 / threads=8) and the paired `RAPID_RENDER_DPI=100` default exist specifically to avoid that ([config.py:99-103](backend/app/config/config.py#L99-L103)). On this machine's hybrid P‑core/E‑core CPU, `intra_op_num_threads=-1` ("every core") is far slower/noisier than any pinned count.
- PaddleOCR stability wasn't swept as exhaustively in‑repo, but its byte‑identical canonical output across thread counts is noted ([ocr_engine.py:71-75](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L71-L75)).
- **Verdict:** **RapidOCR wins at its pinned config**, with the caveat that it must stay pinned; a homogeneous‑core server should be re‑measured.

### M9 — Determinism / reproducibility
- Both produce stable canonical output on this set. RapidOCR identifier fields were checked for self‑consistency across 12 reps **and** agreement with a PaddleOCR reference — clean at the tuned point.
- Engines are cached per configuration; `backend` leads the cache key so a PaddleOCR engine can never be served to a RapidOCR caller ([ocr_engine.py:532-555](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L532-L555)).
- **Verdict:** **Tie** (RapidOCR conditional on staying at its tuned config).

### M10 — Operational cost / dependency footprint
- **RapidOCR wins.**
  - ONNX Runtime is a light, well‑behaved CPU dependency. Models ship with the wheel (PP‑OCRv4 mobile).
  - PaddlePaddle: **pins the whole project to Python 3.12** (no 3.14 wheel — [requirements.txt:1-9](backend/requirements.txt#L1-L9), [README.md](README.md) "Quick start"), needs the `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0` workaround to not crash on CPU, downloads ~100 MB of models to `~/.paddlex/` on first run, and version bumps are "not guaranteed compatible without re‑testing."
- PaddleOCR packages are **kept installed anyway** so the fallback restore is code‑only, no reinstall.
- **Verdict:** **RapidOCR wins.**

### M11 — Privacy / locality
- **Tie.** Both are 100% local, no network, no API key. Non‑differentiating but a hard requirement, so any cloud OCR ("Azure Document Intelligence", "Google Vision", "GPT‑4o vision") is **disqualified regardless of accuracy**.

---

## 3. Scorecard

| Metric | RapidOCR (active) | PaddleOCR / PP‑OCRv6 (Baidu, fallback) | Winner |
|---|---|---|---|
| M1 Char accuracy | 19/24, mean conf parity | 19/24, PP‑OCRv6 newer gen | **Tie** (theoretical edge Paddle) |
| M2 Field accuracy | identical | identical | **Tie** |
| M3 Detection recall | 489 spans | **511 spans** | **PaddleOCR** |
| M4 Detection precision | clean | clean | **Tie** |
| M5 Hallucination | 0 | 0 | **Tie** |
| M6 End‑to‑end field score | **95.8%** | **95.8%** | **Tie** |
| M7 Latency | **~20 s / 3 docs (tuned)** | oneDNN disabled, slower | **RapidOCR** |
| M8 Latency stability | CV 0.01 (tuned) / fragile off‑config | not fully swept | **RapidOCR** (conditional) |
| M9 Determinism | stable (tuned) | stable | **Tie** |
| M10 Ops cost | light (ONNX) | Py3.12 lock, CPU workaround, 100 MB dl | **RapidOCR** |
| M11 Privacy | local | local | **Tie** |

**Tally:** RapidOCR 3 clear wins (M7, M8, M10) + tie on everything that's actually been measured for accuracy. PaddleOCR 1 clear win (M3, detection recall) + a small unproven theoretical edge on M1.

---

## 4. Which is better, and which is best for our use case

### Which is "better" in the abstract
**PaddleOCR / PP‑OCRv6 is the marginally stronger OCR engine** on paper — newer recogniser generation, ~4% higher detection recall, and it's the upstream source of the models RapidOCR reuses. If the only axis were "raw OCR capability on an arbitrary degraded scan," PaddleOCR edges it.

### Which is best for **this** use case — **RapidOCR**

The use case is: **a fully‑local, CPU‑only, single‑to‑low‑volume vendor onboarding pipeline** where the OCR feeds a deterministic label→value matching engine, and the metrics that actually decide outcomes are **M5 (no hallucinations)** and **M6 (end‑to‑end field score)**, with **M7 (latency)** gating usability.

1. **On the metrics that determine form correctness (M1, M2, M5, M6), the two are a measured dead heat** — identical 95.8% accuracy, 0 hallucinations, same single shared `wrong` field (which is a matcher bug, not an OCR bug). PaddleOCR's theoretical accuracy edge **did not show up** on real vendor documents.
2. **RapidOCR wins the tie‑breakers that matter operationally** — faster and more latency‑stable at its tuned point (M7, M8), and a much lighter, less fragile dependency (M10: no Python‑3.12 lock, no CPU‑executor workaround, no 100 MB model download, ONNX GPU/DML path available).
3. **PaddleOCR's one real advantage (M3, detection recall) is currently a non‑issue** — the 22 extra spans it finds don't touch any target field on the tested vendor, and RapidOCR's `max_side_len` / `text_score` tuning was done specifically to narrow that gap.
4. **The residual risk is contained.** PaddleOCR is not deleted — its execution path, packages, tests and restore steps are all preserved ([ocr_engine.py:598-675](backend/app/services/extraction_pipeline/ingest/ocr_engine.py#L598-L675)). If a future vendor's low‑quality scans expose the recall gap, flipping back is `OCR_BACKEND=paddleocr` plus uncommenting one block — no reinstall.

### Conditions under which the recommendation flips to PaddleOCR
- Multi‑vendor divergence testing (`plan.md` 2.1) shows RapidOCR **missing fields** (`missed` > 0) on real documents due to the detection‑recall gap.
- The document mix shifts toward **low‑DPI / heavily degraded / photographed** scans, where PP‑OCRv6's stronger detector and recogniser earn their keep.
- Deployment moves to a **homogeneous‑core server with a working GPU + oneDNN**, neutralising RapidOCR's CPU latency advantage (the thread/DPI tuning above is explicitly "a measurement of THIS machine," not a law).
- Batch throughput becomes a hard requirement — at which point re‑benchmark **both** with page‑level parallelism before deciding.

### Bottom line
> **Keep RapidOCR as the active engine.** It matches Baidu's PaddleOCR on every accuracy metric that has actually been measured against verified ground truth, beats it on latency, stability and operational cost, and its one weakness (detection recall) is both narrowed by tuning and currently harmless. PaddleOCR stays as a one‑env‑var fallback for the specific scenario — multi‑vendor scans exposing missed fields — where its higher recall would pay off.
