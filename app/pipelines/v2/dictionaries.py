"""
V2 Dictionary Loader
=====================
Loads the word lists a `dictionary` validator checks against (see
validator.py). Each dictionary is a plain UTF-8 text file under
app/config/dictionaries/, one entry per line, '#'-prefixed lines and blank
lines ignored -- same shape as the rest of V2's config, editable without
touching Python.

Loaded once per process and cached; these lists are small (tens to low
hundreds of entries) and read-only for the life of the pipeline.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .config_loader import CONFIG_DIR

DICTIONARIES_DIR = CONFIG_DIR / "dictionaries"


@lru_cache(maxsize=None)
def load_dictionary(name: str) -> tuple[str, ...]:
    path = DICTIONARIES_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Dictionary file not found: {path}")

    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(line)
    return tuple(entries)
