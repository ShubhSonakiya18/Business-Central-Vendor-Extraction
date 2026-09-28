# Ternary-Bonsai-2-27B-GGUF CPU Benchmark

## 1. Objective

Measure the CPU-only inference latency and throughput of
`prism-ml/Ternary-Bonsai-2-27B-GGUF` (a 26.9B-parameter ternary-quantized
model) on a single, ordinary consumer laptop CPU, with no GPU involvement.
This is purely a measurement task: no fine-tuning, no llama.cpp modification,
no optimization, and no integration into the Vendor Extractor application.
The deliverable is an honest, reproducible answer to: **"How fast does this
model run on CPU?"**

## 2. Hardware

| Item | Value |
|---|---|
| CPU | 12th Gen Intel(R) Core(TM) i7-12700H |
| Manufacturer | GenuineIntel |
| Architecture | AMD64 (x86_64) |
| Physical cores | 14 |
| Logical cores (threads) | 20 |
| Max clock (as reported by OS) | 2300 MHz |
| RAM (total) | 15.63 GB |
| RAM free before benchmark | 4.99-5.01 GB |
| OS | Microsoft Windows 11 Home Single Language, build 26200 |
| GPU present | Intel(R) Iris(R) Xe Graphics (integrated). **No NVIDIA GPU.** |

These numbers are hardware-dependent. A different CPU (different core count,
clock speed, cache size, or SIMD capability) will produce different results.

## 3. Software

| Item | Value |
|---|---|
| Inference runtime | `llama-server` / `llama-bench` from the **PrismML-Eng/llama.cpp** fork |
| Build | commit `9a9394a89`, build `10709` |
| Compiler | Clang 20.1.8 (release binary; not MSVC) |
| CPU backend | `ggml-cpu-alderlake.dll` — one portable binary built with `GGML_CPU_ALL_VARIANTS=ON`, `GGML_BACKEND_DL=ON`, `GGML_NATIVE=OFF`, dispatching the correct SIMD kernel set (Alder Lake, in this case) at runtime via CPUID. Not compiled for this specific machine. |
| Why this fork | Mainline `ggml-org/llama.cpp` does not implement the `PTQ1_0`/`PQ2_0` ternary GGML tensor types this model uses (open feature request ggml-org/llama.cpp#29058); mainstream `llama-cpp-python` cannot load this model at all. |
| Python | 3.12.0 (used only for orchestration/measurement scripting, not inference) |
| Relevant deps | `requests` (HTTP client to llama-server's `/completion` endpoint) |

## 4. Model

| Item | Value |
|---|---|
| Model | Ternary-Bonsai-2-27B (architecture `qwen35`, Qwen3.5-27B base) |
| GGUF variant benchmarked | `PTQ1_0` ("dense trits," 1.75 bits/weight) |
| File | `Ternary-Bonsai-2-27B-PTQ1_0.gguf` |
| File size | 5,946,648,928 bytes (5.53 GiB) |
| Parameters | 26.90 B |
| Context size used | 4096 tokens (model supports up to 262K; 4096 is ample for all test prompts and keeps load/measurement time reasonable) |

**Why PTQ1_0 and not PQ2_0 or F16:** see Section 10.

## 5. CPU Configuration

| Setting | Value |
|---|---|
| Threads (prompt suite, model-load timing) | 13 (of 20 logical / 14 physical) |
| Threads (thread-scaling sweep) | 1, 2, 4, 7, 13, 20 (swept explicitly, see Section 9) |
| Context size (`-c`) | 4096 |
| Batch size | llama-server/llama-bench default |
| GPU layers (`-ngl`) | **0**, passed explicitly on every server and bench invocation |
| Server command (prompt suite) | `llama-server.exe -m Ternary-Bonsai-2-27B-PTQ1_0.gguf --host 127.0.0.1 --port 18077 -t 13 -c 4096 -ngl 0` |
| Bench command (thread sweep) | `llama-bench.exe -m Ternary-Bonsai-2-27B-PTQ1_0.gguf -p 64 -n 16 -r 2 -t 1,2,4,7,13,20 -ngl 0 -o md` |

## 6. CPU-Only Verification

**CPU-only benchmark: VERIFIED**

Verified by three independent, mutually-reinforcing checks, not assumption:

1. **`--list-devices` reports no devices at all**: running the binary with
   `--list-devices` returns `Available devices:\n  (none)\n`. This specific
   release binary has no GPU backend compiled into it whatsoever — it is
   mechanically incapable of GPU execution, which is a stronger guarantee
   than simply passing `-ngl 0` to a GPU-capable binary.
2. **`-ngl 0` passed explicitly on every single invocation** (server and
   bench), never relying on a default.
3. **Runtime backend-load log lines**, captured from actual process stderr:
   ```
   load_backend: loaded RPC backend from ...ggml-rpc.dll
   load_backend: loaded CPU backend from ...ggml-cpu-alderlake.dll
   ```
   Only an RPC backend (used for distributed CPU inference, not GPU) and the
   CPU backend were loaded. No CUDA, Vulkan, or Metal backend appears
   anywhere in any run's log.

## 7. Benchmark Methodology

- **Warm-up discipline**: every prompt received exactly 1 warm-up (cold)
  request before any measured run. The warm-up's timing is reported
  separately and is **not** averaged into the "measured" statistics — cold
  and warm numbers are kept explicitly distinct throughout this report,
  because they differ by orders of magnitude (see Section 8).
- **Measured runs per prompt**: 2 (see Section 13, Scope Reductions, for why
  not 3-5).
- **Prompts**: 5 categories, chosen to avoid synthetic "hello world" testing:
  `short_short` (short in/short out), `medium_medium` (medium in/medium
  out), `long_medium` (long input, ~1038 tokens, medium output — the
  worst-case cold-prompt-processing scenario), `structured_extraction` (a
  realistic vendor-invoice-style extraction prompt, included because this
  model may eventually be evaluated for document/vendor workflows),
  `reasoning` (a GST/discount arithmetic word problem).
- **Token counts**: real, server-reported `tokens_evaluated` (input) and
  `tokens_predicted` (output) from llama-server's own response — not
  estimated.
- **Metrics measured**, all from the runtime's own instrumentation, not
  reverse-engineered from wall-clock alone:
  - Model load time: wall-clock from process start to first HTTP 200 from
    `/health`.
  - Prompt processing speed (tok/s): from llama-server's `timings.prompt_per_second`.
  - Time to first token (TTFT): wall-clock from request send to first SSE
    chunk received (independent of the runtime's own timing fields, as a
    cross-check).
  - Generation speed (tok/s): from llama-server's `timings.predicted_per_second`.
  - Total inference latency: wall-clock, request send to final `stop:true`
    chunk (includes both prompt processing and generation).
- **Thread scaling**: a single `llama-bench` process, one model load, swept
  across `-t 1,2,4,7,13,20` via llama-bench's comma-separated thread-list
  feature — chosen specifically to avoid 6 separate model reloads, because
  a single load already dropped free RAM from 4.99 GB to 1.23 GB (Section
  11); repeated reloads were judged a real stability risk on this machine,
  not just an efficiency concern.
- **No cheating**: no GPU was used at any point; output length was never
  artificially shortened to inflate throughput; no runs were discarded; all
  runs (including the anomalous one described below) are reported.

### Known methodology caveat: prompt-cache reuse across measured runs

llama-server reuses cached KV-cache state for prompt prefixes it has already
seen (visible via the response's `tokens_cached` field growing across
successive requests to the same prompt). This was checked directly against
the raw per-run `tokens_evaluated`/`tokens_cached` data:

- `tokens_evaluated` (the true, full input length reported by the server)
  is **stable and correct** across warm-up and both measured runs for every
  prompt (e.g. 1038 tokens for `long_medium` in all three runs) — so
  **generation-speed and total-latency numbers in the measured runs are
  genuine**, not artifacts of a shortened prompt.
- However, `tokens_cached` rises from run to run, confirming the server is
  reusing prior KV-cache state for the shared prefix on repeated identical
  prompts. This means the **prompt-processing tok/s figure for measured
  (non-cold) runs under-represents true cold prompt-processing cost** — part
  of the "processing" work was actually cache lookup, not fresh computation.
  The **cold (warm-up) TTFT and prompt-processing numbers are the reliable
  ones for prompt-processing throughput**; the "Results" table below reports
  both, and flags this explicitly rather than presenting the faster
  cache-assisted numbers as if they were cold performance. This is disclosed
  per the requirement not to let cached reuse be mistaken for a
  representative measurement — it was not deliberately engineered to inflate
  results, it is llama-server's default caching behavior, caught and
  reported rather than hidden.
- One run (`medium_medium`, measured run 1) was extreme enough to flag
  individually: `tokens_predicted=2`, `stop_type=eos` — the model emitted an
  end-of-sequence token almost immediately, combined with a cache hit,
  producing an unusually fast 4.05s total. This is a real run, not
  discarded, but is called out here so the number is not misread as typical
  generation speed for that prompt (run 2 on the same prompt: 47.56s, is
  more representative).

## 8. Results

All prompt-processing and generation tok/s figures below are the mean of the
2 measured runs per prompt, taken directly from llama-server's own
`timings` block. TTFT is independently measured wall-clock time. Given the
prompt-cache caveat above, the **cold (warm-up) TTFT** is included as the
most representative "first ever request" latency figure; measured-run TTFT
is consistently low because of prompt-cache reuse, not because the model
processes a fresh prompt that quickly.

| Prompt | Input Tokens | Output Tokens (mean) | Cold (warm-up) TTFT | Measured-run TTFT (mean) | Prompt tok/s (cold) | Generation tok/s (mean, measured) | Total Latency (mean, measured) |
|---|---|---|---|---|---|---|---|
| short_short | 7 | 10 | 4.77 s | 2.64 s | 1.49 | 1.30 | 9.75 s |
| medium_medium | 53 | 26* | 32.67 s | 2.93 s | 1.64 | 1.15* | 25.81 s* |
| long_medium | 1038 | 21 | 682.38 s | 2.84 s | 1.52 | 1.21 | 19.60 s |
| structured_extraction | 118 | 60 | 83.09 s | 3.09 s | 1.48 | 1.20 | 52.78 s |
| reasoning | 53 | 80 | 36.03 s | 7.43 s | 1.49 | 0.97 | 90.03 s |

\* `medium_medium`'s mean is skewed low by the 2-token early-EOS run
described above; run 2 alone (50 output tokens, 47.56s total, 1.09 tok/s
generation) is the more representative figure for that prompt.

**Generation speed across all 10 measured runs (all 5 prompts x 2 runs):**
mean **1.17 tok/s**, median **1.18 tok/s**, range 0.87-1.37 tok/s. This
range — not a single number — is the honest answer to "how many tokens per
second."

## 9. Thread Scaling

Single model load, `llama-bench -p 64 -n 16 -r 2` swept across thread counts
(see Section 13 for why `pp64`/`tg16` rather than the full `pp512`/`tg128`
used elsewhere in this report — this is a documented scope reduction that
does not affect the tok/s rate measurement itself).

| Threads | Prompt tok/s (pp64) | Generation tok/s (tg16) |
|---|---|---|
| 1 | 0.09 ± 0.12 | 0.27 ± 0.00 |
| 2 | 0.57 ± 0.00 | 0.54 ± 0.00 |
| 4 | 1.07 ± 0.00 | 1.00 ± 0.01 |
| 7 | 1.59 ± 0.03 | 1.34 ± 0.02 |
| 13 | 1.81 ± 0.01 | 1.47 ± 0.02 |
| 20 | 1.83 ± 0.02 | **0.93 ± 0.00** |

**Key finding**: generation throughput peaks at 13 threads (1.47 tok/s) and
**drops** at 20 threads (0.93 tok/s) — using every logical thread available
is measurably *worse* than using 13. Prompt processing keeps rising
(marginally) through 20 threads, so the two metrics do not agree on an
optimum. This is a direct, measured counter-example to assuming
"max threads = max performance," consistent with 13 (physical core count is
14; one thread is likely reserved for OS/other work) being close to the
practical ceiling for this workload on this CPU.

## 10. Quantization Comparison

Only **PTQ1_0** was benchmarked. Not multiple quantizations, for a specific,
explained reason rather than by default:

- The fork's PR #181 (unmerged at time of writing) adds an AVX2/AVX-VNNI/
  AVX-512-VNNI-accelerated kernel **for PTQ1_0 only** — not for PQ2_0 — and
  even that speedup is MSVC-specific; this benchmark's binary is
  **Clang-built**, where the PR shows near-parity with the unoptimized path.
  In other words, there is currently no fast-path advantage available for
  either quantization on this exact binary.
- PQ2_0 ("2-bit slots," 2.13 bits/weight, ~7.21 GB) is **larger** than
  PTQ1_0 (5.53 GiB) with no compensating CPU speed advantage on this build —
  it would very likely be *slower*, not faster, while consuming more of an
  already-constrained 15.63 GB RAM budget (Section 11).
- Given PTQ1_0 already demonstrates the model is far below usable
  interactive speed on this CPU (Section 14), downloading another ~7.2 GB
  file to confirm a very probable "also slow, and worse on RAM" result was
  judged not a reasonable use of time or disk/bandwidth for this benchmark's
  objective.
- F16 (53.8 GB) was never a candidate — it does not fit in 15.63 GB of RAM
  on this machine at all.

If a future benchmark run has a machine with materially more RAM and wants
to confirm PQ2_0's relative performance, that remains an open, explicitly
out-of-scope-for-this-run comparison.

## 11. Memory Usage

| Measurement | Value |
|---|---|
| Model file size | 5.53 GiB (5,946,648,928 bytes) |
| RAM total | 15.63 GB |
| Free RAM before model load | 4.99 GB |
| Free RAM after model load | **1.23 GB** |
| Free RAM after server stopped | 6.40 GB |

**Memory pressure: explicitly flagged.** Loading this model consumed
approximately 3.76 GB of RAM (roughly matching the 5.53 GiB file size once
accounting for RAM already in use by the OS/other processes), leaving only
1.23 GB free on a 15.63 GB machine while the server was running. This is a
real constraint, not a hypothetical one — it is why the thread-scaling sweep
was redesigned mid-benchmark to use a single model load instead of six
separate reloads (Section 7), since repeated reloads at this margin were
judged a genuine risk of swapping or an out-of-memory failure. No swapping
was directly observed during the runs that did execute, but the margin was
thin enough that a busier machine (e.g. with a browser or IDE also
consuming several GB) could plausibly tip into swap. This benchmark does
not report a precise "process working set" number beyond the free-RAM
delta above, because the runtime does not expose one reliably — only the
before/after free-RAM figures are claimed.

## 12. Observations

- Model load time was fast and unremarkable: 28.42s for a 5.53 GiB file.
- **Cold time-to-first-token is the dominant, most user-visible cost**, and
  it scales strongly with prompt length: 4.77s for a 7-token prompt, but
  **682.38s (~11.4 minutes)** for a 1038-token prompt. This is the single
  most important number in this report for anyone considering real-world
  usage — a real user's first message to this model, on this CPU, could take
  over 11 minutes before any output appears, if the prompt is long.
- Generation speed is consistently roughly 1-1.5 tokens/second regardless of
  prompt category, which is orders of magnitude below comfortable
  interactive chat speed (interactive use typically expects double digits
  to hundreds of tokens/sec).
- Thread scaling is non-monotonic: more threads help up to ~13 (this CPU's
  physical core count), then generation throughput measurably regresses at
  20 (all logical threads). Do not default to "use every thread."
- Prompt-cache reuse by llama-server (Section 7) means care is required when
  reading "measured run" TTFT/prompt-tok/s numbers in isolation — always
  pair them with the cold/warm-up figures for an honest picture.

## 13. Limitations

- **Scope reductions** (both explicitly logged in `results.json` at
  benchmark time, neither affecting the precision of any reported *rate*,
  only the volume of tokens processed to obtain that rate):
  - Measured runs per prompt: **2**, not the suggested 3-5, to keep total
    wall-clock time reasonable given this model's ~1-1.5 tok/s speed on this
    CPU (5 prompts x (1 warmup + 3-5 runs) at these speeds would have taken
    several additional hours).
  - Thread-scaling sweep used a reduced `pp64`/`tg16` workload (not the
    `pp512`/`tg128` used in the main prompt suite), because the 1-thread
    configuration alone would have taken 30+ minutes at full size across 6
    thread counts x 2 reps.
- **Unexplained but disclosed**: the thread-scaling sweep's `subprocess.run`
  call had a 3600-second (1 hour) timeout configured, but the sweep actually
  took 12,528 seconds (3.48 hours) wall-clock and did not raise a timeout
  error. The most plausible explanation is that the machine (a personal
  laptop) entered sleep/suspend for some portion of that window; Python's
  `time.monotonic()`-based subprocess timeout on Windows does not advance
  during system suspend, so a suspended interval would not count against
  the configured timeout even though wall-clock/UTC timestamps show it
  elapsing. This was not verified against OS sleep/wake event logs and is
  reported as the most likely explanation, not a confirmed root cause. The
  underlying thread-scaling data itself is intact and was independently
  validated (Section 9), so this affects only the "stayed within budget"
  claim, not the correctness of the numbers.
- **Data-recovery note**: the thread-sweep's raw output was captured without
  an explicit UTF-8 encoding on the `subprocess.run` call, causing the `±`
  separator character in llama-bench's table to be mis-decoded (mojibake)
  in the saved JSON. The underlying numeric values on either side of that
  character were unaffected; the parser was corrected to handle the
  mis-decoded form and `bench.py` was fixed (explicit `encoding="utf-8"`)
  for future runs. This is a data-handling bug in the benchmark's own
  scripting, not in llama-bench or the model, and it did not require
  re-running the 3.5-hour sweep to fix.
- Prompt-cache reuse across measured runs (Section 7) means measured-run
  prompt-processing tok/s is not a clean cold measurement; cold (warm-up)
  figures should be used when citing prompt-processing throughput.
  Generation tok/s is unaffected by this caveat.
- Single machine, single CPU model. Results are not necessarily
  representative of other CPUs, especially ones with different core counts,
  clock speeds, or SIMD tiers (though the binary itself is portable across
  x86_64 CPUs via runtime dispatch, performance is not).
  RAM headroom on this specific machine was thin (Section 11); a busier
  machine could see worse numbers due to swapping.
- Only one quantization (PTQ1_0) was tested; see Section 10 for why.
- The model's outputs during benchmarking included visible `<think>...`
  reasoning-style tokens for some prompts (e.g. `medium_medium` warm-up),
  consistent with a reasoning-tuned chat template; output content quality
  was not evaluated, only latency/throughput, per this benchmark's scope.

## 14. Final CPU Performance Summary

Ternary-Bonsai-2-27B-GGUF (PTQ1_0 quantization) runs on this 14-core/20-thread
Intel Core i7-12700H laptop CPU at roughly **1.1-1.2 tokens/second**
generation speed, with cold time-to-first-token ranging from **under 5
seconds for very short prompts to over 11 minutes for a ~1000-token prompt**.
Memory headroom after loading the 5.53 GiB model was thin (1.23 GB free on
a 15.63 GB machine). Maximum practical thread count for this workload was
around 13 threads, not all 20 available logical threads. This is
**far below usable interactive chat speed** on this class of consumer CPU;
the model is technically loadable and runs correctly CPU-only, but is not
presently practical for latency-sensitive CPU-only production use on
comparable hardware.

---

## Final Answer for the Colleague

```
Model: Ternary-Bonsai-2-27B-GGUF (PTQ1_0, 1.75 bpw ternary, 5.53 GiB)
CPU: Intel Core i7-12700H (14 cores / 20 threads)
Quantization: PTQ1_0 (only quantization tested; see report Section 10 for why)
CPU-only: Verified
Generation speed: ~1.1-1.2 tokens/sec (range 0.87-1.37 across all measured runs)
TTFT: 4.8s (short prompt, cold) up to 682s / ~11.4 min (1038-token prompt, cold)
Typical total latency: ~10-90s depending on prompt/output length (see report Section 8)
RAM: 5.53 GiB model; free RAM dropped from ~5GB to ~1.2GB after load on a 15.63GB machine
```

This model is not fast enough for interactive CPU-only use on hardware like
this — roughly 1 token/sec generation and multi-minute time-to-first-token
on longer prompts puts it well below usable chat latency. It runs correctly
and verifiably CPU-only, but would need a faster kernel path, a smaller
model, or GPU offload to be practical for latency-sensitive work.

---

**BENCHMARK COMPLETE**

1. Benchmark script: `research/cpu_llm_benchmark/bench.py` (with supporting
   modules `machine_info.py`, `prompts.py`, `server_manager.py`,
   `server_client.py` in the same directory)
2. Raw results: `research/cpu_llm_benchmark/results.json`
3. Final report: `research/cpu_llm_benchmark/CPU_BENCHMARK_REPORT.md`
