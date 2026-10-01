"""Hardware/backend detection -- the ONE place that is allowed to know
anything about "what machine is this." Everything downstream (binary_catalog,
runtime_manager) takes a `backend` string and never inspects hardware itself.

Deliberately dependency-free (stdlib only): detecting "is there a GPU" must
not itself require installing CUDA/ROCm/Vulkan Python packages, which would
contradict the point of a CPU-first, hardware-agnostic module. Every probe
below shells out to a tool that's part of the vendor's own driver install
(nvidia-smi, rocm-smi, vulkaninfo) and is wrapped so its ABSENCE is just a
negative result, never a crash -- a machine with no GPU simply doesn't have
these binaries on PATH, which is the normal, expected case this module must
handle cleanly.

Nothing here is specific to any one CPU model, instruction set, or vendor.
CPU-level SIMD dispatch (AVX2/AVX-VNNI/AVX-512/...) is intentionally NOT
handled here -- see the module docstring in runtime_manager.py for why: the
llama.cpp binary itself already does that, at load time, via its own
GGML_CPU_ALL_VARIANTS runtime dispatcher. Re-implementing that here would be
exactly the "hardcode it to my machine" mistake this module exists to avoid.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Literal

Backend = Literal["cpu", "cuda", "vulkan", "rocm", "metal"]

_PROBE_TIMEOUT_S = 5.0


def detect_os() -> str:
    """One of "windows" / "linux" / "macos" -- matches the OS component of
    PrismML-Eng/llama.cpp's release asset names."""
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system in ("windows", "linux"):
        return system
    raise RuntimeError(
        f"Unsupported OS {platform.system()!r} -- this module only knows the "
        f"asset-naming convention for windows/linux/macos release binaries."
    )


def detect_arch() -> str:
    """"x64" or "arm64" -- matches the arch component of release asset names."""
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    raise RuntimeError(
        f"Unsupported CPU architecture {platform.machine()!r} -- expected "
        f"x86_64/amd64 or arm64/aarch64."
    )


def _probe(cmd: list[str]) -> str | None:
    """Run `cmd`, return stdout on success, None on ANY failure (tool
    missing, times out, non-zero exit, no permission, ...). The specific
    failure reason is never the caller's concern -- "not available" is a
    single, uniform outcome across every possible way a GPU tool can be
    absent on a given machine."""
    if shutil.which(cmd[0]) is None:
        return None
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def has_cuda() -> bool:
    """NVIDIA GPU + driver present. Checks for the driver's own nvidia-smi,
    never a CUDA toolkit/Python package -- those are build-time concerns for
    whoever compiled the CUDA release binary, not a runtime requirement for
    using it."""
    return _probe(["nvidia-smi", "-L"]) is not None


def has_rocm() -> bool:
    """AMD GPU + ROCm driver present."""
    out = _probe(["rocm-smi", "--showid"])
    return out is not None and "GPU" in out


_SOFTWARE_RENDERER_NAMES = ("llvmpipe", "lavapipe", "swiftshader", "microsoft basic render")


def has_vulkan() -> bool:
    """A REAL Vulkan-capable GPU (discrete or integrated) + loader present --
    works across NVIDIA/AMD/Intel alike, the most hardware-agnostic GPU
    backend llama.cpp offers, useful when neither CUDA nor ROCm apply.

    Explicitly rejects software rasterizers (Mesa llvmpipe/lavapipe, Google
    SwiftShader, Windows' own "Microsoft Basic Render Driver" fallback) --
    these register as valid Vulkan devices so a naive "did vulkaninfo find
    ANY deviceName" check would report a GPU on a machine that has none,
    routing inference through a software emulation path that is typically
    SLOWER than ggml's own CPU kernels. A capability probe that reports a
    real capability's absence as present is worse than reporting nothing.
    """
    out = _probe(["vulkaninfo", "--summary"])
    if out is None:
        return False
    # Each device block looks like:
    #   deviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
    #   deviceName         = NVIDIA GeForce RTX 4070
    # Parse type+name pairs and require at least one real (non-CPU,
    # non-software-named) device -- order within a block isn't guaranteed
    # across vulkaninfo versions, so track the most recent type/name seen
    # rather than assuming a fixed line order.
    current_type = current_name = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("deviceType"):
            current_type = line.split("=", 1)[-1].strip()
        elif line.startswith("deviceName"):
            current_name = line.split("=", 1)[-1].strip()
            if current_type and current_type != "PHYSICAL_DEVICE_TYPE_CPU":
                name_lower = current_name.lower()
                if not any(sw in name_lower for sw in _SOFTWARE_RENDERER_NAMES):
                    return True
            current_type = current_name = None
    return False


def has_metal() -> bool:
    """Apple GPU via Metal -- available on every Apple Silicon Mac, and on
    Intel Macs with a supported discrete/integrated GPU. Not probed via a
    subprocess (no equivalent driver CLI); Metal is part of the OS on any
    Mac capable of running it, so this is an OS check, not a hardware probe."""
    return detect_os() == "macos"


def detect_gpu_backends() -> list[Backend]:
    """Every GPU backend this machine can plausibly run, in the order this
    module prefers them (fastest/most mature first). Empty list = CPU-only
    machine, which is a normal, fully-supported outcome, not an error."""
    if detect_os() == "macos":
        return ["metal"] if has_metal() else []
    backends: list[Backend] = []
    if has_cuda():
        backends.append("cuda")
    if has_rocm():
        backends.append("rocm")
    if has_vulkan():
        backends.append("vulkan")
    return backends


def pick_backend(preferred: Backend | Literal["auto"] = "auto") -> Backend:
    """Resolve "auto" (or validate an explicit choice) against what this
    machine ACTUALLY has, right now. Never assumes; always probes.

    "auto" -> the first available GPU backend, or "cpu" if none.
    An explicit backend is validated (raises if this machine can't run it)
    rather than silently substituted -- a caller who asked for "cuda" wants
    to know their machine has no NVIDIA GPU, not to silently get CPU.
    """
    available_gpu = detect_gpu_backends()
    if preferred == "auto":
        return available_gpu[0] if available_gpu else "cpu"
    if preferred == "cpu":
        return "cpu"
    if preferred in available_gpu:
        return preferred
    raise RuntimeError(
        f"Requested backend {preferred!r} but this machine does not have it "
        f"available (detected GPU backends: {available_gpu or 'none'}). "
        f"Pass backend='auto' to fall back to the best available backend, "
        f"or 'cpu' to force CPU-only inference."
    )


def default_thread_count() -> int:
    """A safe default thread count for the CPU backend -- capability-based
    (however many logical cores THIS machine reports), never a number picked
    for one specific CPU. Leaves one core free by default so the OS/other
    processes (this FastAPI app included, if colocated) stay responsive;
    override via LlamaServerConfig.n_threads for a dedicated inference box."""
    cores = os.cpu_count() or 4
    return max(1, cores - 1)


@dataclass(frozen=True)
class MachineCapabilities:
    """A snapshot of what THIS machine can do, gathered once. Pass this
    around instead of re-probing repeatedly -- probing is cheap but not free
    (subprocess spawns), and a snapshot makes behavior deterministic within
    one run even if, say, a GPU driver flakes mid-session."""

    os_name: str
    arch: str
    gpu_backends: list[Backend] = field(default_factory=list)
    cpu_threads: int = 4

    @classmethod
    def probe(cls) -> "MachineCapabilities":
        return cls(
            os_name=detect_os(),
            arch=detect_arch(),
            gpu_backends=detect_gpu_backends(),
            cpu_threads=default_thread_count(),
        )

    def resolve_backend(self, preferred: Backend | Literal["auto"] = "auto") -> Backend:
        if preferred == "auto":
            return self.gpu_backends[0] if self.gpu_backends else "cpu"
        if preferred == "cpu":
            return "cpu"
        if preferred in self.gpu_backends:
            return preferred
        raise RuntimeError(
            f"Requested backend {preferred!r} but this machine does not have it "
            f"available (detected GPU backends: {self.gpu_backends or 'none'})."
        )
