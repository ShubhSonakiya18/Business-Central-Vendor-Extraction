"""Launches and manages a llama-server subprocess -- CPU or GPU, whichever
LlamaServerConfig resolved for THIS machine. This is the only place that
shells out to the model runtime; everything else in this package is either
pure detection (device_capabilities) or pure lookup (binary_catalog).

Why a subprocess + HTTP client, not the llama-cpp-python C-extension binding:
Ternary-Bonsai's PTQ1_0/PQ2_0 ternary GGML types are NOT in mainline
ggml-org/llama.cpp yet (see ggml-org/llama.cpp#29058, a still-open feature
request) -- they only exist on the PrismML-Eng fork. The standard PyPI
llama-cpp-python wheels are built against mainline and cannot load this
model's tensors at all. Driving the fork's own prebuilt llama-server binary
over its OpenAI-compatible HTTP API needs zero source changes on our side
(constraint: don't modify llama.cpp itself) and works identically whether
that binary is a CPU build or a CUDA/Vulkan/ROCm one -- the process-
management and HTTP-client code below never needs to know which.

CPU-level SIMD dispatch (does this binary use AVX2, AVX-VNNI, AVX-512, or a
scalar fallback) happens INSIDE the launched process, at ITS OWN load time,
via ggml's GGML_CPU_ALL_VARIANTS runtime dispatcher -- confirmed present in
the fork's release build workflow (release-prism.yml: GGML_CPU_ALL_VARIANTS=ON,
GGML_BACKEND_DL=ON, GGML_NATIVE=OFF). Nothing here needs to re-implement or
second-guess that; it is why this module can be genuinely hardware-agnostic
on the CPU path without containing a single CPUID check of its own.
"""
from __future__ import annotations

import subprocess
import time
from types import TracebackType
from typing import Optional

import requests

from binary_catalog import find_model_file, find_server_binary
from config import LlamaServerConfig

_HEALTH_POLL_INTERVAL_S = 0.5


class LlamaServerStartupError(RuntimeError):
    """Raised when the server process exits, or never becomes healthy,
    within startup_timeout_s. Carries the process's own stderr tail so the
    real reason (missing DLL, wrong ISA, OOM, port in use, ...) is visible
    instead of just "it didn't start"."""


class LlamaServerProcess:
    """Owns exactly one llama-server subprocess. Use as a context manager:

        cfg = LlamaServerConfig()               # backend/threads/etc. all
                                                  # resolved from THIS machine
        with LlamaServerProcess(cfg) as server:
            client = LlamaClient(server.base_url)
            print(client.chat([{"role": "user", "content": "hi"}]))
    """

    def __init__(self, config: LlamaServerConfig):
        self.config = config
        self._process: Optional[subprocess.Popen] = None

    @property
    def base_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}"

    def _build_command(self) -> list[str]:
        backend = self.config.resolved_backend
        server = find_server_binary(
            self.config.capabilities.os_name, backend,
            explicit_path=self.config.server_binary,
        )
        model_path = find_model_file(explicit_path=self.config.model_path, quant=self.config.quant)
        return [
            str(server.server_path),
            "-m", str(model_path),
            "--host", self.config.host,
            "--port", str(self.config.port),
            "-c", str(self.config.context_length),
            "-t", str(self.config.n_threads),
            "-ngl", str(self.config.n_gpu_layers),
        ]

    def start(self) -> "LlamaServerProcess":
        if self._process is not None:
            raise RuntimeError("already started")

        command = self._build_command()
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        deadline = time.monotonic() + self.config.startup_timeout_s
        while time.monotonic() < deadline:
            exit_code = self._process.poll()
            if exit_code is not None:
                raise LlamaServerStartupError(
                    f"llama-server exited with code {exit_code} before becoming "
                    f"healthy.\ncommand: {' '.join(command)}\noutput:\n"
                    f"{self._read_output_tail()}"
                )
            try:
                resp = requests.get(f"{self.base_url}/health", timeout=2.0)
                if resp.status_code == 200:
                    return self
            except requests.RequestException:
                pass
            time.sleep(_HEALTH_POLL_INTERVAL_S)

        self.stop()
        raise LlamaServerStartupError(
            f"llama-server did not become healthy within "
            f"{self.config.startup_timeout_s}s.\ncommand: {' '.join(command)}"
        )

    def _read_output_tail(self, max_lines: int = 40) -> str:
        if self._process is None or self._process.stdout is None:
            return ""
        lines = self._process.stdout.readlines()
        return "".join(lines[-max_lines:])

    def stop(self, *, terminate_timeout_s: float = 10.0) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=terminate_timeout_s)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        self._process = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def __enter__(self) -> "LlamaServerProcess":
        return self.start()

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.stop()
