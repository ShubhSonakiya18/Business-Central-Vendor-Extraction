"""device_capabilities must report the SAME answer regardless of which
machine runs the test -- so every test here mocks subprocess/shutil rather
than depending on what tools actually happen to be installed. A test that
only passes on the author's laptop would be exactly the "hardcoded to one
machine" bug this whole module exists to avoid.
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

import device_capabilities as dc


# ---------------------------------------------------------------------------
# detect_os / detect_arch
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [("Windows", "windows"), ("Linux", "linux"), ("Darwin", "macos")])
def test_detect_os_normalizes(monkeypatch, raw, expected):
    monkeypatch.setattr(dc.platform, "system", lambda: raw)
    assert dc.detect_os() == expected


def test_detect_os_rejects_unknown(monkeypatch):
    monkeypatch.setattr(dc.platform, "system", lambda: "FreeBSD")
    with pytest.raises(RuntimeError, match="Unsupported OS"):
        dc.detect_os()


@pytest.mark.parametrize("raw,expected", [("x86_64", "x64"), ("AMD64", "x64"), ("arm64", "arm64"), ("aarch64", "arm64")])
def test_detect_arch_normalizes(monkeypatch, raw, expected):
    monkeypatch.setattr(dc.platform, "machine", lambda: raw)
    assert dc.detect_arch() == expected


# ---------------------------------------------------------------------------
# _probe -- the shared "tool may or may not exist" primitive
# ---------------------------------------------------------------------------
def test_probe_returns_none_when_tool_absent(monkeypatch):
    monkeypatch.setattr(dc.shutil, "which", lambda name: None)
    assert dc._probe(["nonexistent-tool"]) is None


def test_probe_returns_none_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(dc.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(dc.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
    assert dc._probe(["some-tool"]) is None


def test_probe_returns_none_on_timeout(monkeypatch):
    monkeypatch.setattr(dc.shutil, "which", lambda name: "/usr/bin/" + name)

    def raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=5)

    monkeypatch.setattr(dc.subprocess, "run", raise_timeout)
    assert dc._probe(["some-tool"]) is None


def test_probe_returns_stdout_on_success(monkeypatch):
    monkeypatch.setattr(dc.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(dc.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="ok"))
    assert dc._probe(["some-tool"]) == "ok"


# ---------------------------------------------------------------------------
# has_cuda / has_rocm
# ---------------------------------------------------------------------------
def test_has_cuda_false_when_nvidia_smi_absent(monkeypatch):
    monkeypatch.setattr(dc, "_probe", lambda cmd: None)
    assert dc.has_cuda() is False


def test_has_cuda_true_when_nvidia_smi_succeeds(monkeypatch):
    monkeypatch.setattr(dc, "_probe", lambda cmd: "GPU 0: NVIDIA GeForce RTX 4070")
    assert dc.has_cuda() is True


def test_has_rocm_requires_gpu_in_output(monkeypatch):
    monkeypatch.setattr(dc, "_probe", lambda cmd: "no devices found")
    assert dc.has_rocm() is False
    monkeypatch.setattr(dc, "_probe", lambda cmd: "GPU[0]")
    assert dc.has_rocm() is True


# ---------------------------------------------------------------------------
# has_vulkan -- the one with real logic (reject CPU-type + software renderers)
# ---------------------------------------------------------------------------
_REAL_GPU_OUTPUT = """
Devices:
========
GPU0:
\tdeviceType         = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU
\tdeviceName         = Intel(R) Iris(R) Xe Graphics
"""

_SOFTWARE_RENDERER_OUTPUT = """
Devices:
========
GPU0:
\tdeviceType         = PHYSICAL_DEVICE_TYPE_CPU
\tdeviceName         = llvmpipe (LLVM 15.0.0, 256 bits)
"""

_LAVAPIPE_NAMED_BUT_WRONG_TYPE_OUTPUT = """
Devices:
========
GPU0:
\tdeviceType         = PHYSICAL_DEVICE_TYPE_OTHER
\tdeviceName         = SwiftShader Device (LLVM 10.0.0)
"""

_NO_DEVICES_OUTPUT = "Devices:\n========\n"


def test_has_vulkan_true_for_real_integrated_gpu(monkeypatch):
    monkeypatch.setattr(dc, "_probe", lambda cmd: _REAL_GPU_OUTPUT)
    assert dc.has_vulkan() is True


def test_has_vulkan_false_for_cpu_type_software_renderer(monkeypatch):
    monkeypatch.setattr(dc, "_probe", lambda cmd: _SOFTWARE_RENDERER_OUTPUT)
    assert dc.has_vulkan() is False


def test_has_vulkan_false_for_named_software_renderer_regardless_of_type(monkeypatch):
    monkeypatch.setattr(dc, "_probe", lambda cmd: _LAVAPIPE_NAMED_BUT_WRONG_TYPE_OUTPUT)
    assert dc.has_vulkan() is False


def test_has_vulkan_false_when_no_devices(monkeypatch):
    monkeypatch.setattr(dc, "_probe", lambda cmd: _NO_DEVICES_OUTPUT)
    assert dc.has_vulkan() is False


def test_has_vulkan_false_when_tool_absent(monkeypatch):
    monkeypatch.setattr(dc, "_probe", lambda cmd: None)
    assert dc.has_vulkan() is False


# ---------------------------------------------------------------------------
# detect_gpu_backends / pick_backend / MachineCapabilities
# ---------------------------------------------------------------------------
def test_detect_gpu_backends_empty_on_cpu_only_machine(monkeypatch):
    monkeypatch.setattr(dc, "detect_os", lambda: "linux")
    monkeypatch.setattr(dc, "has_cuda", lambda: False)
    monkeypatch.setattr(dc, "has_rocm", lambda: False)
    monkeypatch.setattr(dc, "has_vulkan", lambda: False)
    assert dc.detect_gpu_backends() == []


def test_detect_gpu_backends_prefers_cuda_over_vulkan(monkeypatch):
    monkeypatch.setattr(dc, "detect_os", lambda: "linux")
    monkeypatch.setattr(dc, "has_cuda", lambda: True)
    monkeypatch.setattr(dc, "has_rocm", lambda: False)
    monkeypatch.setattr(dc, "has_vulkan", lambda: True)
    assert dc.detect_gpu_backends() == ["cuda", "vulkan"]


def test_detect_gpu_backends_macos_uses_metal_only(monkeypatch):
    monkeypatch.setattr(dc, "detect_os", lambda: "macos")
    assert dc.detect_gpu_backends() == ["metal"]


def test_pick_backend_auto_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(dc, "detect_gpu_backends", lambda: [])
    assert dc.pick_backend("auto") == "cpu"


def test_pick_backend_auto_picks_first_available_gpu(monkeypatch):
    monkeypatch.setattr(dc, "detect_gpu_backends", lambda: ["cuda", "vulkan"])
    assert dc.pick_backend("auto") == "cuda"


def test_pick_backend_explicit_cpu_always_allowed(monkeypatch):
    monkeypatch.setattr(dc, "detect_gpu_backends", lambda: [])
    assert dc.pick_backend("cpu") == "cpu"


def test_pick_backend_explicit_unavailable_raises(monkeypatch):
    monkeypatch.setattr(dc, "detect_gpu_backends", lambda: [])
    with pytest.raises(RuntimeError, match="does not have it available"):
        dc.pick_backend("cuda")


def test_pick_backend_explicit_available_is_honored(monkeypatch):
    monkeypatch.setattr(dc, "detect_gpu_backends", lambda: ["vulkan"])
    assert dc.pick_backend("vulkan") == "vulkan"


def test_default_thread_count_leaves_one_core_free(monkeypatch):
    monkeypatch.setattr(dc.os, "cpu_count", lambda: 8)
    assert dc.default_thread_count() == 7


def test_default_thread_count_never_below_one(monkeypatch):
    monkeypatch.setattr(dc.os, "cpu_count", lambda: 1)
    assert dc.default_thread_count() == 1


def test_default_thread_count_handles_unknown_cpu_count(monkeypatch):
    monkeypatch.setattr(dc.os, "cpu_count", lambda: None)
    assert dc.default_thread_count() == 3  # falls back to 4 cores, minus 1


def test_machine_capabilities_probe_is_a_real_snapshot(monkeypatch):
    monkeypatch.setattr(dc, "detect_os", lambda: "linux")
    monkeypatch.setattr(dc, "detect_arch", lambda: "x64")
    monkeypatch.setattr(dc, "detect_gpu_backends", lambda: [])
    monkeypatch.setattr(dc, "default_thread_count", lambda: 7)
    caps = dc.MachineCapabilities.probe()
    assert caps == dc.MachineCapabilities(os_name="linux", arch="x64", gpu_backends=[], cpu_threads=7)
    assert caps.resolve_backend("auto") == "cpu"


def test_machine_capabilities_resolve_backend_explicit_unavailable_raises():
    caps = dc.MachineCapabilities(os_name="linux", arch="x64", gpu_backends=[], cpu_threads=4)
    with pytest.raises(RuntimeError):
        caps.resolve_backend("cuda")
