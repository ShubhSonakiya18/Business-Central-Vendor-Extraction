"""Experimental implementation of the §24 IMPLEMENTATION-READY BUSINESS LOGIC
from docs/ADDRESS_SEGMENTATION_RESEARCH.md.

ISOLATED, READ-ONLY with respect to production: imports classify_fragment,
_gap_strength, Fragment, and the tier/level constants from the EXISTING
backend/app/services/extraction_pipeline/extract/address_segmenter.py --
nothing there is modified, and nothing in this file is imported back into
production. This module is not wired into any pipeline; it is a standalone
research artifact for testing the proposed algorithm against real data.

Pipeline (mirrors the report's §24 pseudocode step-for-step):
  1. normalize
  2. hard-fail structural checks (reconstruction, order, empty address_1)
  3. locate boundary (token index into the tokenized full address)
  4. structural/semantic plausibility (reuses the production tier/gap system)
  5. cross-check against a second candidate, when supplied (soft)
  6. combine into ACCEPT / REVIEW / REJECT
  7. return a structured, loggable result
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, r"C:\Users\shubh\Downloads\vendor-extractor\backend")
from app.services.extraction_pipeline.extract.address_segmenter import (  # noqa: E402
    Fragment,
    _gap_strength,
    classify_fragment,
    segmentation_keywords,
)

import metrics as M  # noqa: E402

_COMMA_SPACE_FIX = re.compile(r"\s+([,;])")
_WS = re.compile(r"\s+")


def normalize(s: str) -> str:
    """§24 Step 1 -- whitespace collapse + explicit comma/semicolon-spacing
    fix (the §10 finding: plain whitespace-run collapsing is not sufficient)."""
    if s is None:
        return ""
    s = _WS.sub(" ", str(s)).strip()
    s = _COMMA_SPACE_FIX.sub(r"\1", s)
    return s


_PIN_RE = re.compile(r"\b\d{6}\b")


def _is_order_preserving_subsequence(needle: list[str], haystack: list[str]) -> bool:
    """True if `needle` appears in `haystack`, in the same relative order,
    with other (haystack-only) tokens allowed between/around them -- this is
    the right check once city/state/pin/country are legitimately extracted
    OUT of their original position into separate fields: the address LINES
    must still be internally un-reordered relative to the source, but they
    need not sit contiguously at the exact same offset once other fields are
    removed from around them."""
    it = iter(haystack)
    return all(tok in it for tok in needle)


@dataclass
class ValidationResult:
    verdict: str  # ACCEPT | REVIEW | REJECT
    deciding_stage: int  # 2, 4, or 5
    hard_fail_reason: str | None = None
    boundary_index: int | None = None
    gap_strength: float | None = None
    adjacency_violation: bool | None = None
    structural_plausibility: str | None = None  # HIGH | LOW | None
    ref_token_sequence_ratio: float | None = None
    ref_char_sequence_ratio: float | None = None
    ref_boundary_token_distance: int | None = None
    review_reason: str | None = None
    reconstruction_detail: dict = field(default_factory=dict)


def _flat_tail_set(kw: dict) -> set[str]:
    tails: set[str] = set()
    for spec in (kw.get("tiers") or {}).values():
        tails |= {w.casefold() for w in (spec.get("tail") or [])}
    return tails


def _edge_role_guard(kw: dict, text_a: str, text_b: str) -> bool:
    """§24 Step 4d -- same-role tail-keyword adjacency violation. Mirrors
    production's REAL guard (address_segmenter._flat_role_set / the same-role
    check in inject_boundaries()): tail words are flattened ACROSS ALL TIERS,
    not matched per-tier -- e.g. 'PARK' (estate_zone tail) and 'STREET'
    (thoroughfare tail) are DIFFERENT tiers but BOTH tail-role, so the cut
    between them is still blocked. An earlier version of this guard required
    tier_a == tier_b, which is wrong and does not match production."""
    last_word_a = M.tokens(text_a)[-1] if M.tokens(text_a) else ""
    first_word_b = M.tokens(text_b)[0] if M.tokens(text_b) else ""
    tail_set = _flat_tail_set(kw)
    return last_word_a in tail_set and first_word_b in tail_set


def validate(
    full_address: str,
    candidate_address_1: str,
    candidate_address_2: str,
    candidate_address_3: str = "",
    candidate_address_4: str = "",
    candidate_source: str = "unknown",
    reference_address_1: str | None = None,
    candidate_city: str = "",
    candidate_state: str = "",
    candidate_pin: str = "",
    candidate_country: str = "",
) -> ValidationResult:
    """`candidate_city/state/pin/country` -- §9.2 of the research report found
    that a real Indian-address resolver correctly peels city/state/pin/
    country into SEPARATE typed fields before ever building address_1..4, so
    those lines are NOT expected to reconstruct the full original string on
    their own. Pass the resolver's other output fields here so reconstruction
    is checked against the COMPLETE fielded decomposition, not just the
    address lines -- otherwise every correct extraction is wrongly flagged as
    "missing tokens" (city/state/pin were not lost, they were moved to their
    own fields). If a caller has no such fields (e.g. testing a bare 2-line
    candidate with no city/state resolution), leave these blank; the check
    then requires the lines alone to reconstruct the full address, as before.
    """
    # --- Step 1: normalize -------------------------------------------------
    full_n = normalize(full_address)
    a1_n = normalize(candidate_address_1)
    a2_n = normalize(candidate_address_2)
    a3_n = normalize(candidate_address_3)
    a4_n = normalize(candidate_address_4)
    city_n, state_n, pin_n, country_n = (normalize(candidate_city), normalize(candidate_state),
                                          normalize(candidate_pin), normalize(candidate_country))
    # Union territories (Delhi, Chandigarh, Puducherry, ...) legitimately have
    # city == state -- one source token correctly resolved into BOTH fields.
    # Counting it twice in the reconstruction multiset would flag a correct
    # extraction as a hallucinated extra token, so when the two are identical,
    # include the shared value only once.
    admin_fields = [city_n, state_n] if city_n.casefold() != state_n.casefold() else [city_n]
    candidate_lines = [x for x in (a1_n, a2_n, a3_n, a4_n, *admin_fields, pin_n, country_n) if x]

    # --- Step 2: hard-fail structural checks --------------------------------
    if not a1_n:
        return ValidationResult(verdict="REJECT", deciding_stage=2, hard_fail_reason="empty_address_1")

    # MULTISET check over the COMPLETE fielded decomposition (address lines
    # + city/state/pin/country) -- nothing may be lost or hallucinated across
    # ANY of the resolver's output fields, not just the address lines.
    joined = ", ".join(candidate_lines)
    diff = M.reconstruction_diff(full_n, joined, "")
    if diff["missing_tokens"]:
        return ValidationResult(verdict="REJECT", deciding_stage=2, hard_fail_reason="missing_token",
                                 reconstruction_detail=diff)
    if diff["extra_tokens"]:
        return ValidationResult(verdict="REJECT", deciding_stage=2, hard_fail_reason="extra_token",
                                 reconstruction_detail=diff)

    # ORDER check -- ONLY across the address LINES (a1..a4), as a subsequence
    # of the full address's tokens. city/state/pin/country are legitimately
    # extracted OUT of their original position by design (§9.2 finding), so
    # they are correctly excluded from THIS check -- their presence was
    # already confirmed by the multiset check above; what must never happen
    # is the address_1..4 CONTENT itself being reordered relative to the
    # source (mirrors production's own I3 invariant).
    line_tokens = M.tokens(a1_n) + M.tokens(a2_n) + M.tokens(a3_n) + M.tokens(a4_n)
    full_tokens = M.tokens(full_n)
    if not _is_order_preserving_subsequence(line_tokens, full_tokens):
        return ValidationResult(verdict="REJECT", deciding_stage=2, hard_fail_reason="reordered",
                                 reconstruction_detail=diff)

    input_pins = set(_PIN_RE.findall(full_n))
    output_pins = set(_PIN_RE.findall(joined))
    if not input_pins.issubset(output_pins):
        return ValidationResult(verdict="REJECT", deciding_stage=2, hard_fail_reason="critical_field_changed",
                                 reconstruction_detail={"missing_pins": list(input_pins - output_pins)})

    # --- Step 3: locate the boundary ----------------------------------------
    boundary_index = M.boundary_token_index(full_n, a1_n)

    # --- Step 4: structural/semantic plausibility (reuses production tiers) -
    kw = segmentation_keywords()
    last_frag_text = a1_n.split(",")[-1].strip() if "," in a1_n else a1_n
    first_frag_text = a2_n.split(",")[0].strip() if a2_n and "," in a2_n else a2_n

    plausibility = None
    gap = None
    adjacency_violation = None
    if first_frag_text:
        tier_a, level_a, conf_a, ev_a = classify_fragment(last_frag_text)
        tier_b, level_b, conf_b, ev_b = classify_fragment(first_frag_text)
        frag_a = Fragment(text=last_frag_text, index=0, tier=tier_a, level=level_a, confidence=conf_a, evidence=ev_a)
        frag_b = Fragment(text=first_frag_text, index=1, tier=tier_b, level=level_b, confidence=conf_b, evidence=ev_b)
        gap = _gap_strength(frag_a, frag_b)
        adjacency_violation = _edge_role_guard(kw, last_frag_text, first_frag_text)
        threshold = (kw.get("thresholds") or {}).get("boundary_strength", 0.5)
        plausibility = "HIGH" if (gap >= threshold and not adjacency_violation) else "LOW"
    else:
        # address_2 empty: nothing to score a gap against. Treat as
        # plausible only if address_1 alone already reconstructs the address
        # (single-line address, not a segmentation at all).
        plausibility = "HIGH" if a1_n == full_n else "LOW"

    # --- Step 5: cross-check against a second candidate (soft) -------------
    ref_tsr = ref_csr = ref_btd = None
    if reference_address_1:
        ref_n = normalize(reference_address_1)
        ref_tsr = M.token_sequence_ratio(a1_n, ref_n)
        ref_csr = M.char_sequence_ratio(a1_n, ref_n)
        ref_btd = M.boundary_token_distance(full_n, ref_n, a1_n)

    # --- Step 6: combine into a verdict -------------------------------------
    if plausibility == "HIGH":
        return ValidationResult(
            verdict="ACCEPT", deciding_stage=4, boundary_index=boundary_index,
            gap_strength=gap, adjacency_violation=adjacency_violation,
            structural_plausibility=plausibility,
            ref_token_sequence_ratio=ref_tsr, ref_char_sequence_ratio=ref_csr,
            ref_boundary_token_distance=ref_btd,
        )

    # plausibility == LOW
    if reference_address_1 is None or (ref_tsr is not None and ref_tsr >= 0.96):
        return ValidationResult(
            verdict="REVIEW", deciding_stage=4, boundary_index=boundary_index,
            gap_strength=gap, adjacency_violation=adjacency_violation,
            structural_plausibility=plausibility,
            ref_token_sequence_ratio=ref_tsr, ref_char_sequence_ratio=ref_csr,
            ref_boundary_token_distance=ref_btd,
            review_reason="low_structural_plausibility",
        )

    return ValidationResult(
        verdict="REVIEW", deciding_stage=5, boundary_index=boundary_index,
        gap_strength=gap, adjacency_violation=adjacency_violation,
        structural_plausibility=plausibility,
        ref_token_sequence_ratio=ref_tsr, ref_char_sequence_ratio=ref_csr,
        ref_boundary_token_distance=ref_btd,
        review_reason="low_plausibility_and_reference_disagrees",
    )
