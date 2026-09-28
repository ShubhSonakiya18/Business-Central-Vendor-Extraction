"""Starts/stops llama-server and measures model load time directly via
wall-clock (process start -> /health returns 200). This is Section 4A's
"time required to load the GGUF model into memory" measurement.

Self-contained -- does not import from research/cpu_llm_inference (that
module was built for a different purpose, app-integration scaffolding; this
benchmark is explicitly required to stand alone, independent of it).
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import requests

_HEALTH_POLL_S = 0.5


@dataclass
class LoadResult:
    load_time_s: float
    process: subprocess.Popen
    command: list[str]
    stdout_path: Path


def start_server_and_measure_load(
    server_exe: Path,
    model_path: Path,
    *,
    host: str,
    port: int,
    n_threads: int,
    n_ctx: int,
    n_gpu_layers: int,
    log_path: Path,
    timeout_s: float = 300.0,
) -> LoadResult:
    """Launches llama-server, polls /health, returns wall-clock load time.
    `n_gpu_layers` is passed through explicitly and unconditionally (-ngl) --
    this benchmark never launches the server without stating it, per the
    requirement to verify, not assume, CPU-only execution."""
    command = [
        str(server_exe),
        "-m", str(model_path),
        "--host", host,
        "--port", str(port),
        "-t", str(n_threads),
        "-c", str(n_ctx),
        "-ngl", str(n_gpu_layers),
    ]
    log_file = open(log_path, "w", encoding="utf-8")
    t_start = time.monotonic()
    process = subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)

    deadline = t_start + timeout_s
    base_url = f"http://{host}:{port}"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_file.close()
            raise RuntimeError(
                f"llama-server exited with code {process.returncode} before becoming healthy. "
                f"See log: {log_path}"
            )
        try:
            resp = requests.get(f"{base_url}/health", timeout=2.0)
            if resp.status_code == 200:
                load_time_s = time.monotonic() - t_start
                return LoadResult(load_time_s=load_time_s, process=process, command=command, stdout_path=log_path)
        except requests.RequestException:
            pass
        time.sleep(_HEALTH_POLL_S)

    process.terminate()
    log_file.close()
    raise RuntimeError(f"llama-server did not become healthy within {timeout_s}s. See log: {log_path}")


def stop_server(process: subprocess.Popen, *, timeout_s: float = 15.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
