# cpu_llm_inference

A hardware-agnostic inference harness for `prism-ml/Ternary-Bonsai-2-27B-gguf`
(and, unchanged, for any other model on the same PrismML-Eng llama.cpp fork).
Runs on CPU when that's all a machine has, and automatically uses a GPU
backend when one is actually present and real — never the other way around,
and never assuming a specific CPU model, instruction set, or vendor.

**Status: isolated research module, not wired into the FastAPI app.** No
production code was touched to build this. See "Integrating into
vendor-extractor" below for what that would involve later.

## Why this exists, and why it's structured this way

The project's dev/deploy machine for this task is CPU-only, but the code was
explicitly asked to be **capability-based, not machine-based** — it must give
the same correct behavior on a different CPU, a machine with a GPU, or a
machine with none, without being edited per-machine. Concretely:

- `device_capabilities.py` is the **only** file allowed to ask "what does
  this machine have." It probes for real hardware (`nvidia-smi`, `rocm-smi`,
  `vulkaninfo`, OS-level Metal availability) and explicitly rejects **software
  Vulkan renderers** (Mesa llvmpipe/lavapipe, SwiftShader, Windows' "Basic
  Render Driver") that would otherwise masquerade as a real GPU and route
  inference through something slower than the CPU path.
- **CPU-level SIMD dispatch is deliberately NOT reimplemented here.** The
  PrismML-Eng fork's own release build (`release-prism.yml`) compiles with
  `GGML_CPU_ALL_VARIANTS=ON` + `GGML_BACKEND_DL=ON` + `GGML_NATIVE=OFF` — a
  single binary containing every SIMD tier (scalar baseline through AVX-512),
  which ggml itself selects via CPUID **at process startup**. Writing our own
  AVX/AVX-VNNI detection on top of that would be exactly the "hardcode to one
  CPU" mistake this module exists to avoid, and would fight the tool doing
  the job correctly already. Confirmed against the fork's actual CI workflow,
  not assumed.
- `binary_catalog.py` maps (OS, arch, backend) → the release asset name to
  fetch, and locates it locally. **It never downloads anything itself** —
  fetching a multi-hundred-MB binary or a multi-GB model file is a real,
  consequential cost, so this module tells you exactly what to get and where
  to put it, and raises a clear, actionable error otherwise.
- `runtime_manager.py` launches the resolved `llama-server` binary as a
  subprocess with capability-derived flags (`-t <threads>`, `-ngl <layers>`)
  and talks to it over HTTP. **No llama.cpp source is modified** — this is
  orchestration and configuration only, per the explicit constraint to use
  the existing implementation correctly rather than patch it.
- `client.py` is a thin OpenAI-compatible HTTP client. It does not hardcode a
  chat prompt template — `llama-server` applies whatever template is embedded
  in the loaded GGUF's own metadata, so this stays correct for any model.

## Why a subprocess + HTTP, not `llama-cpp-python`

Ternary-Bonsai's ternary GGML tensor types (`PTQ1_0`/`PQ2_0`) are **not in
mainline `ggml-org/llama.cpp`** — see
[ggml-org/llama.cpp#29058](https://github.com/ggml-org/llama.cpp/issues/29058),
a still-open feature request as of this writing. The standard `llama-cpp-python`
PyPI wheels are built against mainline and cannot load these tensors at all.
Driving the fork's own prebuilt `llama-server` binary over HTTP needs zero
compilation and zero source changes on our side, and behaves identically
whether the launched binary is the CPU build or a CUDA/Vulkan/ROCm one.

## What you need to download manually (not automated — see above)

1. A release asset from https://github.com/PrismML-Eng/llama.cpp/releases
   (latest `prism-b*` tag). Pick the asset matching your OS/backend — e.g.
   `win-cpu-x64` for Windows CPU-only, `win-vulkan-x64` if you have a real
   GPU. Extract it, and place `llama-server(.exe)` at:
   ```
   $TERNARY_BONSAI_HOME/bin/<backend>/llama-server[.exe]
   ```
   (`TERNARY_BONSAI_HOME` defaults to `~/.cache/ternary-bonsai` if unset.)
2. The GGUF weights from
   https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf — `PTQ1_0`
   (5.95 GB) is the default quant used by this module, because as of this
   writing it's the only one with a dedicated fast CPU kernel
   ([PR #181](https://github.com/PrismML-Eng/llama.cpp/pull/181), still open
   — re-check its merge status before relying on that number). `PQ2_0`
   (7.21 GB) works too but currently runs the slower generic scalar path on
   CPU. Place it at:
   ```
   $TERNARY_BONSAI_HOME/models/Ternary-Bonsai-2-27B.PTQ1_0.gguf
   ```

Or skip the cache-dir convention entirely and pass `server_binary=` /
`model_path=` explicitly to `LlamaServerConfig` — see below.

## Usage

```python
from config import LlamaServerConfig
from runtime_manager import LlamaServerProcess
from client import LlamaClient

# Every hardware-shaped field below (backend, threads, gpu layers) is
# resolved against THIS machine's real capabilities at construction time --
# nothing here is specific to any one CPU or GPU.
cfg = LlamaServerConfig()
print(cfg.resolved_backend, cfg.n_threads, cfg.n_gpu_layers)

with LlamaServerProcess(cfg) as server:
    client = LlamaClient(server.base_url)
    print(client.chat([{"role": "user", "content": "Hello"}]))
```

Force a specific backend (e.g. to prove the CPU path works on a machine that
also has a GPU) rather than relying on auto-detection:

```python
cfg = LlamaServerConfig(backend="cpu")
```

## Honest performance caveats (do not skip)

Verified against the fork's own PR #181 numbers before writing this module —
not re-derived here:
- **Absolute throughput is low.** ~2.9 tok/s generation on a strong 24-core
  chip (Core Ultra 9 275HX) even with the fast CPU kernel; well under 1 tok/s
  without it. This is a research/prototype-tier model on CPU, not a
  production-latency one.
- **The reported 3.6-4.4x CPU speedup from PR #181 is MSVC-specific.** Under
  Clang, the PR's own numbers show near-parity between the "optimized" and
  generic paths — most of the win compensates for MSVC's weaker
  auto-vectorization, not a universal hardware truth. Report your compiler
  alongside any number you measure.
- **PQ2_0 has no fast CPU kernel yet** — only PTQ1_0 does, and only via a
  still-unmerged PR. Re-verify its merge status before trusting either fact.

## Running the tests

```
cd backend
python -m pytest ../research/cpu_llm_inference/tests/ -q
```

51 tests, all fully mocked (no subprocess spawned, no HTTP call made, no GPU
required) — they pass identically on any machine, which is the same property
the module itself is built to have.

## Integrating into vendor-extractor (not done yet)

If/when this becomes a real backend service:
1. Move this directory's four modules into
   `backend/app/services/llm_inference/`, updating the relative imports to
   package-relative (`from .device_capabilities import ...`).
2. Fold `LlamaServerConfig` into the project's own `app/config/config.py`
   `Settings` class (same `pydantic-settings` pattern already used there) so
   `TERNARY_BONSAI_*` env vars sit alongside the app's existing ones.
3. Decide server lifecycle: a long-lived `LlamaServerProcess` started once at
   FastAPI app startup (`lifespan`) and shared, rather than one per request —
   `runtime_manager.py`'s context-manager shape already supports either.
