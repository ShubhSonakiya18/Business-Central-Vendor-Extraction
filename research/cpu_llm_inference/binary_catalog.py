"""Maps (os, arch, backend) -> the release asset PATTERN to look for on
PrismML-Eng/llama.cpp's releases page, and resolves a LOCAL path to an
already-downloaded binary.

Deliberately does NOT download anything. Fetching a multi-hundred-MB binary
(and separately, a multi-GB GGUF model file) is a consequential, bandwidth-
and disk-costly action -- this module's job is to tell the caller EXACTLY
what to get and from where, and to find it once it's been placed locally, not
to reach out to the network on its own. See README.md for the manual
download step.

Patterns below were confirmed against the actual releases page (see
docs/ADDRESS_SEGMENTATION_RESEARCH.md-style provenance: verified via
PrismML-Eng/llama.cpp/releases on 2026-09-19 -- reconfirm if a long time has
passed, release asset naming can change between the fork's own release
workflow revisions).
"""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

from device_capabilities import Backend

RELEASES_URL = "https://github.com/PrismML-Eng/llama.cpp/releases"

# (os, backend) -> asset name FRAGMENT that appears in the release zip/tar
# filename. arch ("x64"/"arm64") is appended separately since it varies
# independently of backend for a couple of these.
_ASSET_FRAGMENTS: dict[tuple[str, Backend], str] = {
    ("windows", "cpu"): "win-cpu",
    ("windows", "cuda"): "win-cuda",
    ("windows", "vulkan"): "win-vulkan",
    ("windows", "rocm"): "win-hip",
    ("linux", "cpu"): "ubuntu-cpu",
    ("linux", "cuda"): "ubuntu-cuda",
    ("linux", "vulkan"): "ubuntu-vulkan",
    ("linux", "rocm"): "ubuntu-rocm",
    ("macos", "metal"): "macos-arm64",
    ("macos", "cpu"): "macos-x64",  # Intel Mac, no discrete Metal-relevant GPU path taken
}

_SERVER_EXE_NAME = {
    "windows": "llama-server.exe",
    "linux": "llama-server",
    "macos": "llama-server",
}


def expected_asset_fragment(os_name: str, backend: Backend) -> str:
    key = (os_name, backend)
    if key not in _ASSET_FRAGMENTS:
        raise RuntimeError(
            f"No known PrismML-Eng/llama.cpp release asset for os={os_name!r} "
            f"backend={backend!r}. Known combinations: {sorted(_ASSET_FRAGMENTS)}. "
            f"Check {RELEASES_URL} for the current asset naming -- the fork's "
            f"release workflow may have changed since this catalog was written."
        )
    return _ASSET_FRAGMENTS[key]


@dataclass(frozen=True)
class ResolvedBinary:
    server_path: pathlib.Path
    backend: Backend


def _default_cache_dir() -> pathlib.Path:
    """Where this module looks for an already-extracted release, if the
    caller didn't point at one explicitly. XDG-ish on every OS via a single
    env var so there's one obvious override, not three OS-specific ones."""
    override = os.environ.get("TERNARY_BONSAI_HOME")
    if override:
        return pathlib.Path(override)
    return pathlib.Path.home() / ".cache" / "ternary-bonsai"


def find_server_binary(
    os_name: str,
    backend: Backend,
    *,
    explicit_path: str | pathlib.Path | None = None,
) -> ResolvedBinary:
    """Locate a llama-server executable for the given backend.

    Resolution order:
      1. `explicit_path`, if given -- must exist, no guessing.
      2. `$TERNARY_BONSAI_HOME/bin/<backend>/<exe name>` (or
         `~/.cache/ternary-bonsai/...` if that env var is unset).
    Raises a RuntimeError naming the EXACT release asset to download and
    where to put it, rather than attempting any network fetch itself.
    """
    if explicit_path is not None:
        path = pathlib.Path(explicit_path)
        if not path.is_file():
            raise RuntimeError(f"server binary not found at explicit path: {path}")
        return ResolvedBinary(server_path=path, backend=backend)

    exe_name = _SERVER_EXE_NAME[os_name]
    cache_dir = _default_cache_dir()
    candidate = cache_dir / "bin" / backend / exe_name
    if candidate.is_file():
        return ResolvedBinary(server_path=candidate, backend=backend)

    fragment = expected_asset_fragment(os_name, backend)
    raise RuntimeError(
        f"No llama-server binary found for backend={backend!r}.\n"
        f"  Looked at: {candidate}\n"
        f"  Fix: download the release asset containing '{fragment}' in its name "
        f"from {RELEASES_URL} (latest 'prism-b*' release), extract it, and "
        f"place '{exe_name}' at the path above -- or pass server_binary= "
        f"explicitly pointing at wherever you extracted it."
    )


def find_model_file(
    *, explicit_path: str | pathlib.Path | None = None, quant: str = "PTQ1_0"
) -> pathlib.Path:
    """Locate the GGUF weights file. Same non-downloading policy as
    find_server_binary -- a multi-GB model file is never fetched implicitly.

    `quant` matters beyond just which file to look for: only PTQ1_0 has a
    dedicated fast CPU kernel as of this module's writing (PR #181 on the
    fork, not yet merged) -- PQ2_0 runs the slower generic scalar path on
    CPU. Default to PTQ1_0 for that reason; pass quant="PQ2_0" deliberately,
    not as an unexamined default.
    """
    if explicit_path is not None:
        path = pathlib.Path(explicit_path)
        if not path.is_file():
            raise RuntimeError(f"model file not found at explicit path: {path}")
        return path

    cache_dir = _default_cache_dir()
    candidate = cache_dir / "models" / f"Ternary-Bonsai-2-27B.{quant}.gguf"
    if candidate.is_file():
        return candidate

    raise RuntimeError(
        f"No GGUF weights file found for quant={quant!r}.\n"
        f"  Looked at: {candidate}\n"
        f"  Fix: download 'Ternary-Bonsai-2-27B.{quant}.gguf' from "
        f"https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf and place "
        f"it at the path above -- or pass model_path= explicitly."
    )
