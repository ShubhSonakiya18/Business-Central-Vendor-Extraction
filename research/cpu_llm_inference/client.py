"""Thin HTTP client for a running llama-server, using its OpenAI-compatible
endpoints. Deliberately does NOT hardcode a Qwen-style chat prompt template
-- llama-server applies the chat template embedded in the GGUF's own
metadata automatically, so this stays correct regardless of which model or
quant is actually loaded behind it.
"""
from __future__ import annotations

from typing import Optional

import requests


class LlamaClient:
    def __init__(self, base_url: str, *, timeout_s: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        resp = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json={
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
        stop: Optional[list[str]] = None,
    ) -> str:
        resp = requests.post(
            f"{self.base_url}/completion",
            json={
                "prompt": prompt,
                "n_predict": max_tokens,
                "temperature": temperature,
                "stop": stop or [],
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return resp.json()["content"]

    def health(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=5.0)
            return resp.status_code == 200
        except requests.RequestException:
            return False
