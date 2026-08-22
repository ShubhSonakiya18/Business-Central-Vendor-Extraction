"""
V2 Normalizer
=============
Applies the `normalization:` op chain from field_dictionary.yaml to a raw
extracted string. Ops are looked up in a registry, so the set of available ops
is data to the rest of the system -- config_loader.KNOWN_NORMALIZERS is the
declared contract and this module is the implementation of it.

No field names appear here. `fix_ifsc_confusions` is named for the shape it
repairs, not for the field that happens to use it.
"""

from __future__ import annotations

import re
from typing import Callable

_MULTISPACE = re.compile(r"\s+")
_NON_DIGIT = re.compile(r"\D")
_LEADING_91 = re.compile(r"^(?:\+?91)[\s\-]?(?=[6-9]\d{9}$)")

# OCR confuses these glyph pairs constantly on scanned documents. The mapping
# is only ever applied at positions where the field's format guarantees a
# letter or a digit, never blindly across the whole string.
_DIGIT_TO_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"}


def _titlecase(value: str) -> str:
    # str.title() mangles "PVT LTD" -> "Pvt Ltd" acceptably but also turns
    # "M.B.CONTROL" into "M.B.Control"; capitalize per whitespace token only.
    return " ".join(w[:1].upper() + w[1:].lower() if w else w for w in value.split(" "))


def _fix_ifsc_confusions(value: str) -> str:
    """Repair an 11-character IFSC-shaped token.

    IFSC is 4 letters, then a literal '0', then 6 alphanumerics. That fixed
    shape means a digit appearing in the first four positions is certainly an
    OCR error and can be mapped back to its letter, and position 4 can be
    forced to '0'. Anything that is not 11 characters is left alone -- guessing
    at a token of the wrong length would invent data.
    """
    if len(value) != 11:
        return value
    chars = list(value.upper())
    for i in range(4):
        chars[i] = _DIGIT_TO_LETTER.get(chars[i], chars[i])
    chars[4] = "0"
    return "".join(chars)


NORMALIZERS: dict[str, Callable[[str], str]] = {
    "strip": lambda v: v.strip(),
    "collapse_spaces": lambda v: _MULTISPACE.sub(" ", v).strip(),
    "remove_spaces": lambda v: _MULTISPACE.sub("", v),
    "uppercase": lambda v: v.upper(),
    "lowercase": lambda v: v.lower(),
    "titlecase": _titlecase,
    "digits_only": lambda v: _NON_DIGIT.sub("", v),
    "strip_country_code": lambda v: _LEADING_91.sub("", v),
    "fix_ifsc_confusions": _fix_ifsc_confusions,
}


def normalize(value: str | None, ops: list[str]) -> str:
    """Run `value` through the named ops in order."""
    if value is None:
        return ""
    out = str(value)
    for op in ops:
        fn = NORMALIZERS.get(op)
        if fn is None:
            # config_loader rejects unknown ops at load time, so reaching here
            # means the registry and KNOWN_NORMALIZERS have drifted apart.
            raise KeyError(f"Normalizer op not implemented: {op!r}")
        out = fn(out)
    return out


def clean_label(text: str) -> str:
    """Reduce a caption to a comparable form: no trailing punctuation, no
    separators, collapsed whitespace, lowercased."""
    text = text.strip()
    text = re.sub(r"^[\s\-:.|*]+", "", text)
    text = re.sub(r"[\s\-:.|*]+$", "", text)
    text = _MULTISPACE.sub(" ", text)
    return text.lower()


def strip_value_prefix(text: str) -> str:
    """Remove the separator sitting between a caption and its value when both
    share one span, e.g. 'PIN Code: 700019' -> '700019' once the caption part
    has been sliced off."""
    return re.sub(r"^[\s:\-–—=|.,)#]+", "", text).strip()
