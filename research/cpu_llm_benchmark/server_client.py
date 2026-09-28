"""Minimal streaming client for llama-server's /completion endpoint.

API shape below was confirmed against a REAL request to a running server
before this was written (see CPU_BENCHMARK_REPORT.md methodology) -- not
assumed from documentation. Notably, the runtime itself returns a first-
party `timings` object on the final SSE chunk with `prompt_per_second` and
`predicted_per_second` -- these are used as the authoritative throughput
numbers wherever available, per the requirement to prefer runtime-exposed
metrics over ones this script would otherwise have to derive.

TTFT is measured independently via wall-clock (time from request-send to
first SSE chunk arrival), which the runtime does NOT expose directly -- this
also captures real HTTP/local-loopback overhead, not just server-side timing.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import requests


@dataclass
class CompletionResult:
    prompt_text: str
    output_text: str
    requested_max_tokens: int
    ttft_s: float | None                 # wall-clock: request sent -> first token chunk received
    total_wall_s: float                  # wall-clock: request sent -> stream fully closed
    prompt_tokens: int | None            # from runtime `timings.prompt_n`
    predicted_tokens: int | None         # from runtime `timings.predicted_n`
    prompt_ms: float | None              # from runtime `timings.prompt_ms`
    predicted_ms: float | None           # from runtime `timings.predicted_ms`
    prompt_tok_per_s: float | None       # from runtime `timings.prompt_per_second`
    generation_tok_per_s: float | None   # from runtime `timings.predicted_per_second`
    raw_final_chunk: dict = field(default_factory=dict)


def run_completion(
    base_url: str,
    prompt: str,
    max_tokens: int,
    *,
    timeout_s: float = 900.0,
) -> CompletionResult:
    """Send one streaming completion request, measuring wall-clock TTFT and
    total time directly, while also capturing the runtime's own first-party
    `timings` block from the final chunk."""
    payload = {
        "prompt": prompt,
        "n_predict": max_tokens,
        "stream": True,
        "timings_per_token": True,
    }

    t_start = time.monotonic()
    ttft_s: float | None = None
    output_parts: list[str] = []
    final_chunk: dict = {}

    with requests.post(
        f"{base_url.rstrip('/')}/completion", json=payload, stream=True, timeout=timeout_s,
    ) as resp:
        resp.raise_for_status()
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data: "):
                continue
            if ttft_s is None:
                ttft_s = time.monotonic() - t_start
            chunk = json.loads(raw_line[len("data: "):])
            output_parts.append(chunk.get("content", ""))
            if chunk.get("stop"):
                final_chunk = chunk

    total_wall_s = time.monotonic() - t_start
    timings = final_chunk.get("timings", {})

    return CompletionResult(
        prompt_text=prompt,
        output_text="".join(output_parts),
        requested_max_tokens=max_tokens,
        ttft_s=ttft_s,
        total_wall_s=total_wall_s,
        prompt_tokens=timings.get("prompt_n"),
        predicted_tokens=timings.get("predicted_n"),
        prompt_ms=timings.get("prompt_ms"),
        predicted_ms=timings.get("predicted_ms"),
        prompt_tok_per_s=timings.get("prompt_per_second"),
        generation_tok_per_s=timings.get("predicted_per_second"),
        raw_final_chunk=final_chunk,
    )
