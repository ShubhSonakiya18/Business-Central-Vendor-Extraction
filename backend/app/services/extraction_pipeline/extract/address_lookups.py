"""In-memory address reference data, loaded once from backend/data/address/.

Three tables, all built by app.cli.build_address_lookups:

    pin_state_district(pin)  -> (state, district) | None
    canonical_state(token)   -> "West Bengal" | None   (exact, alias, or
                                whitespace/punctuation-insensitive match)
    is_known_city(token)     -> bool                    (normalised match
                                against ~140k district / town names)

Everything is deterministic and local -- no network, no model. Loading is
lazy + cached so importing this module (e.g. for a unit test) is free until a
lookup actually runs.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "address"
_PIN_CSV = _DATA_DIR / "pin_directory.csv"
_STATES_TXT = _DATA_DIR / "states.txt"
_CITIES_TXT = _DATA_DIR / "cities.txt"

# Normalise a token for fuzzy-but-cheap matching: casefold, drop all
# non-alphanumerics (so "S.A.S Nagar" == "sas nagar" == "SAS  Nagar").
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm(s: str) -> str:
    return _NON_ALNUM.sub("", (s or "").casefold())


@lru_cache(maxsize=1)
def _pin_table() -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    if not _PIN_CSV.is_file():
        return out
    with _PIN_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            pin = (row.get("pincode") or "").strip()
            if len(pin) == 6 and pin.isdigit():
                out[pin] = ((row.get("state") or "").strip(), (row.get("district") or "").strip())
    return out


@lru_cache(maxsize=1)
def _all_district_names() -> frozenset[str]:
    """Every DISTRICT value that appears anywhere in the PIN directory,
    normalised. Used to tell a "pure" city/town name (never itself a
    district -- e.g. Mohali) apart from a name that IS a district in its own
    right (e.g. Tikamgarh, S.A.S Nagar) -- see is_district_name()."""
    return frozenset(_norm(d) for _, d in _pin_table().values() if d)


def is_district_name(token: str) -> bool:
    """True if `token` is itself a district value somewhere in the PIN
    directory (regardless of which PIN/state). A city/town that is NEVER a
    district (e.g. "Mohali") returns False even though it is a perfectly
    valid, known city -- see is_known_city()."""
    n = _norm(token)
    return bool(n) and n in _all_district_names()


@lru_cache(maxsize=1)
def _state_tables() -> tuple[dict[str, str], dict[str, str]]:
    """(normalised-canonical -> canonical, normalised-alias -> canonical)."""
    canonical: dict[str, str] = {}
    aliases: dict[str, str] = {}
    if not _STATES_TXT.is_file():
        return canonical, aliases
    for line in _STATES_TXT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            alias, target = line.split("\t", 1)
            aliases[_norm(alias)] = target.strip()
        else:
            canonical[_norm(line)] = line
    return canonical, aliases


@lru_cache(maxsize=1)
def _city_tables() -> tuple[frozenset[str], dict[str, str]]:
    """(normalised city/district names, normalised-alias -> canonical).

    Same tab-separated format as _state_tables(): a plain line is a known
    city/district name as-is; an "alias\\tcanonical" line maps a full/expanded
    name to the abbreviated or PIN-directory form it's an alias of (e.g.
    "Sahibzada Ajit Singh Nagar" -> "S.A.S Nagar"). Without this, a document
    that spells the district out in full is never recognised as naming the
    same place the PIN directory already resolved, and the full name is left
    behind as ordinary locality text -- duplicating the city instead of being
    recognised and dropped."""
    names: set[str] = set()
    aliases: dict[str, str] = {}
    if not _CITIES_TXT.is_file():
        return frozenset(), {}
    for line in _CITIES_TXT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            alias, target = line.split("\t", 1)
            aliases[_norm(alias)] = target.strip()
        else:
            names.add(_norm(line))
    return frozenset(names), aliases


# --- public ----------------------------------------------------------------

def pin_state_district(pin: str) -> tuple[str, str] | None:
    """(state, district) for a 6-digit PIN, or None if unknown."""
    return _pin_table().get((pin or "").strip()) or None


def canonical_state(token: str) -> str | None:
    """Map a token to its canonical state/UT name. Tries exact canonical, then
    known aliases / abbreviations / OCR misreads. Returns None if not a state."""
    n = _norm(token)
    if not n:
        return None
    canonical, aliases = _state_tables()
    return canonical.get(n) or aliases.get(n)


def is_known_city(token: str) -> bool:
    """True if the token normalises to a known city / district / town name,
    OR to a known alias of one (e.g. "Sahibzada Ajit Singh Nagar" for
    "S.A.S Nagar") -- see canonical_city()."""
    n = _norm(token)
    if not n:
        return False
    names, aliases = _city_tables()
    return n in names or n in aliases


def canonical_city(token: str) -> str | None:
    """Map a token to its canonical city/district name when it IS one, via an
    exact or aliased match; None otherwise. Mirrors canonical_state(). Unlike
    is_known_city() (a plain membership check, used to detect city-shaped
    tokens generically), this resolves an alias to the SAME canonical string
    the PIN directory would return for it, which is what lets a duplicate
    mention (full name in the text + PIN-derived abbreviation) collapse to
    one value instead of leaving the alias behind as ordinary text."""
    n = _norm(token)
    if not n:
        return None
    names, aliases = _city_tables()
    if n in aliases:
        return aliases[n]
    if n in names:
        return token.strip()
    return None


def data_files_present() -> bool:
    """True when all three lookup files exist -- callers can degrade gracefully
    (skip the PIN-directory path) rather than crash if they were never built."""
    return _PIN_CSV.is_file() and _STATES_TXT.is_file() and _CITIES_TXT.is_file()


# ---------------------------------------------------------------------------
# Address-line segmentation keywords (extract/address_segmenter.py)
# ---------------------------------------------------------------------------
_SEGMENTATION_YAML = _DATA_DIR / "segmentation_keywords.yaml"


@lru_cache(maxsize=1)
def segmentation_keywords() -> dict:
    """Parsed segmentation_keywords.yaml, or {} if missing/malformed.

    A malformed or absent file is NOT an error -- address_segmenter.py degrades
    to a single-fragment, low-confidence result (identical to the pre-segmenter
    behaviour) exactly the way the rest of this module degrades when the PIN/
    state/city files are absent. Cached so the file is parsed once per process.
    """
    if not _SEGMENTATION_YAML.is_file():
        return {}
    import yaml

    try:
        with _SEGMENTATION_YAML.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def segmentation_data_present() -> bool:
    """True when the segmentation keyword file exists and parsed to a non-empty
    dict -- mirrors data_files_present()'s degrade-gracefully contract."""
    return bool(segmentation_keywords())
