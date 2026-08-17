"""
V2 Validation Engine
====================
One generic executor for every rule in validation_rules.yaml. V1 carried the
same six regexes in two files that could drift apart; here a rule exists once,
in YAML, and this module runs whatever it finds.

Rule types map to `_RULES` entries. `derived` rules compare a field against
something computed from ANOTHER field -- that is how "the PAN inside the GSTIN
must equal the PAN field" is expressed without either field name appearing in
Python.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from rapidfuzz import fuzz, process as fuzz_process

from .config_loader import ValidationRules, ValidatorSpec
from .dictionaries import load_dictionary

# GST state codes 01-38 are assigned; the rest are unallocated.
_VALID_STATE_CODES = {f"{i:02d}" for i in range(1, 39)}


@dataclass
class Finding:
    validator: str
    severity: str      # error | warning
    message: str
    ok: bool

    def to_dict(self) -> dict:
        return {
            "validator": self.validator,
            "severity": self.severity,
            "message": self.message,
            "ok": self.ok,
        }


# ---------------------------------------------------------------------------
# RULE IMPLEMENTATIONS
# ---------------------------------------------------------------------------

def _rule_regex(spec: ValidatorSpec, value: str, values: dict) -> bool:
    return bool(spec.pattern and spec.pattern.fullmatch(value))


def _rule_length(spec: ValidatorSpec, value: str, values: dict) -> bool:
    if spec.digits_only and not value.isdigit():
        return False
    if spec.min is not None and len(value) < spec.min:
        return False
    if spec.max is not None and len(value) > spec.max:
        return False
    return True


def _rule_enum(spec: ValidatorSpec, value: str, values: dict) -> bool:
    target = value.strip().lower()
    return any(target == allowed.strip().lower() for allowed in spec.values)


def _rule_non_empty(spec: ValidatorSpec, value: str, values: dict) -> bool:
    return bool(value and value.strip())


def _rule_dictionary(spec: ValidatorSpec, value: str, values: dict) -> bool:
    """Fuzzy-check `value` against a curated word list (config/dictionaries/).

    Two modes, chosen per validator in YAML:

    - "membership": the whole value must fuzzy-match ONE dictionary entry.
      For a genuinely closed set (scheduled banks) -- an entry that scores
      below min_similarity against every bank name is either a bank not on
      RBI's list (rare for a vendor onboarding) or, far more often on a
      cheque scan, OCR noise.

    - "contains": the value must fuzzy-contain ANY dictionary entry as a
      substring match. For vendor_name against entity_suffixes: the full
      name isn't enumerable, but Indian company names overwhelmingly end in
      a small set of legal-entity suffixes, so checking for one of those
      catches OCR damage to that specific, usually-smaller-print portion of
      the name without trying to validate the whole string.

    Scorer differs by mode, deliberately. "membership" uses plain `ratio`:
    the whole value should closely resemble the whole entry, so a value that
    merely contains a bank-shaped word ("Xyzabc Fake Bank Corp" contains
    "Bank") must still score low overall. `WRatio`'s partial-match credit is
    exactly wrong here -- measured giving that fake name an 85/100 against
    "ICICI Bank", comfortably over threshold, versus `ratio`'s 45/100.
    "contains" uses `WRatio` instead, because there the length mismatch
    between a short suffix and a long value is expected and wanted: "PVT LTD"
    genuinely is a substring of "M B CONTROL & SYSTEMS PVT LTD", and `ratio`
    would penalize that length difference even though it's a clean match.

    Comparison is case-folded regardless of mode: `ratio` is case-sensitive,
    and a field's own normalization chain may not include case folding (a
    bank name is deliberately title-cased for the final Excel output, not
    upper/lowercased), so folding case only for this comparison avoids that
    choice leaking into what should be a pure format check.
    """
    if not value:
        return False

    entries = load_dictionary(spec.dictionary)
    threshold = spec.min_similarity * 100
    value_cf = value.lower()

    if spec.match == "membership":
        match = fuzz_process.extractOne(value_cf, [e.lower() for e in entries], scorer=fuzz.ratio)
        return bool(match and match[1] >= threshold)

    # "contains"
    return any(fuzz.WRatio(entry.lower(), value_cf) >= threshold for entry in entries)


def _derived_substring_equals(spec: ValidatorSpec, value: str, values: dict) -> Optional[bool]:
    """Compare a slice of `source` against `target`. Returns None ("cannot
    judge") when either side is absent -- a missing PAN is the PAN field's
    problem to report, not this rule's."""
    source_value = values.get(spec.source or "")
    target_value = values.get(spec.target or "")
    if not source_value or not target_value:
        return None
    start = spec.start or 0
    end = spec.end if spec.end is not None else len(source_value)
    return source_value[start:end].upper() == target_value.upper()


def _derived_state_code_valid(spec: ValidatorSpec, value: str, values: dict) -> Optional[bool]:
    source_value = values.get(spec.source or "")
    if not source_value:
        return None
    start = spec.start or 0
    end = spec.end if spec.end is not None else 2
    return source_value[start:end] in _VALID_STATE_CODES


_RULES: dict[str, Callable[[ValidatorSpec, str, dict], bool]] = {
    "regex": _rule_regex,
    "length": _rule_length,
    "enum": _rule_enum,
    "non_empty": _rule_non_empty,
    "dictionary": _rule_dictionary,
}

_DERIVED: dict[str, Callable[[ValidatorSpec, str, dict], Optional[bool]]] = {
    "substring_equals": _derived_substring_equals,
    "state_code_valid": _derived_state_code_valid,
}


# ---------------------------------------------------------------------------
# ENGINE
# ---------------------------------------------------------------------------

class Validator:
    def __init__(self, rules: ValidationRules):
        self.rules = rules

    def check(self, validator_names: list[str], value: str, all_values: dict) -> list[Finding]:
        """Run named validators against `value`. `all_values` gives derived
        rules access to the other extracted fields."""
        findings: list[Finding] = []
        for name in validator_names:
            spec = self.rules.get(name)

            if spec.type == "derived":
                fn = _DERIVED.get(spec.rule or "")
                if fn is None:
                    raise KeyError(f"Derived rule not implemented: {spec.rule!r}")
                outcome = fn(spec, value, all_values)
                if outcome is None:
                    continue  # not enough data to judge
                ok = outcome
            else:
                fn = _RULES.get(spec.type)
                if fn is None:
                    raise KeyError(f"Validator type not implemented: {spec.type!r}")
                ok = fn(spec, value, all_values)

            findings.append(
                Finding(validator=name, severity=spec.severity, message=spec.message, ok=ok)
            )
        return findings

    def status_of(self, findings: list[Finding]) -> str:
        if any(not f.ok and f.severity == "error" for f in findings):
            return "invalid"
        if any(not f.ok and f.severity == "warning" for f in findings):
            return "warning"
        return "valid" if findings else "not_validated"

    # -- cross-document -----------------------------------------------------

    def compare_across_documents(self, values_by_document: dict[str, str]) -> tuple[str, list[str]]:
        """Report whether the same field agrees across the documents it was
        found in. Comparison is fuzzy so that 'M B CONTROL & SYSTEMS PVT LTD'
        and 'M.B.CONTROL & SYSTEM PVT LTD' count as agreement, while a
        genuinely different company does not."""
        distinct = {k: v for k, v in values_by_document.items() if v}
        if len(distinct) <= 1:
            return ("single_source" if distinct else "not_checked"), []

        threshold = self.rules.cross_document.similarity_threshold * 100
        items = list(distinct.items())
        disagreements: list[str] = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (doc_a, val_a), (doc_b, val_b) = items[i], items[j]
                if fuzz.ratio(val_a.lower(), val_b.lower()) < threshold:
                    disagreements.append(f"{doc_a}={val_a!r} vs {doc_b}={val_b!r}")

        return ("inconsistent" if disagreements else "consistent"), disagreements
