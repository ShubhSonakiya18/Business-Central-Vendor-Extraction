"""Static list of Indian states + union territories, and a best-effort
State -> REGION suggestion used to pre-fill (but not lock) the REGION field."""
from __future__ import annotations

STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal",
]

UNION_TERRITORIES = [
    "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry",
]

ALL_STATES_AND_UTS = STATES + UNION_TERRITORIES

_NORMALIZED = {s.upper().replace(" ", ""): s for s in ALL_STATES_AND_UTS}

# Common OCR/abbreviation aliases -> canonical name.
_ALIASES = {
    "ORISSA": "Odisha",
    "PONDICHERRY": "Puducherry",
    "NCTOFDELHI": "Delhi",
    "NCT OF DELHI": "Delhi",
}


def normalize_state(raw: str | None) -> str | None:
    """Validate/normalize free text against the known state/UT list. Returns
    the canonical name, or None if it doesn't match anything known."""
    if not raw:
        return None
    cleaned = raw.strip()
    key = cleaned.upper().replace(" ", "")
    if key in _NORMALIZED:
        return _NORMALIZED[key]
    if cleaned.upper() in _ALIASES:
        return _ALIASES[cleaned.upper()]
    # Loose contains-match as a last resort (OCR often trails junk).
    for norm_key, canonical in _NORMALIZED.items():
        if norm_key and norm_key in key:
            return canonical
    return None


# Coarse regional grouping -- a *suggestion* only, always editable in the review UI.
_REGION_MAP = {
    "East": [
        "West Bengal", "Bihar", "Jharkhand", "Odisha", "Sikkim", "Assam",
        "Arunachal Pradesh", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
        "Tripura",
    ],
    "North": [
        "Delhi", "Haryana", "Punjab", "Himachal Pradesh", "Uttarakhand",
        "Uttar Pradesh", "Jammu and Kashmir", "Ladakh", "Chandigarh",
    ],
    "West": [
        "Maharashtra", "Gujarat", "Rajasthan", "Goa",
        "Dadra and Nagar Haveli and Daman and Diu",
    ],
    "South": [
        "Karnataka", "Kerala", "Tamil Nadu", "Andhra Pradesh", "Telangana",
        "Puducherry", "Andaman and Nicobar Islands", "Lakshadweep",
    ],
    "Central": ["Madhya Pradesh", "Chhattisgarh"],
}

_STATE_TO_REGION = {
    state: region for region, states in _REGION_MAP.items() for state in states
}


def suggest_region(state: str | None) -> str | None:
    canonical = normalize_state(state) if state else None
    if not canonical:
        return None
    return _STATE_TO_REGION.get(canonical)
