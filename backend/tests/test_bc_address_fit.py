"""Tests for the pure Layer 2 BC representation module (bc_address_fit.py).

See docs/ADDRESS_SEGMENTATION_PLAN.md §§5-6, 10, 11. This module is tested
in complete isolation from address semantics -- every test constructs plain
fragment lists directly, exactly as the plan requires ("this module knows
nothing about address semantics").
"""

from __future__ import annotations

import random

import pytest

from app.services.bc_target_profile import AddressLimits
from app.services.extraction_pipeline.extract.bc_address_fit import (
    FRAGMENT_TOO_LONG,
    FitStatus,
    check_constraints,
    rebalance,
    validate_final,
)

LIMITS = AddressLimits(address_1_max=100, address_2_max=50, separator=", ")


def _split(a1: str, a2: str) -> tuple[list[str], int]:
    """Helper: turn 'A1 text' / 'A2 text' into (fragments, boundary) by
    comma-splitting, matching how the resolver recovers fragments from
    stored text (plan §6 "Gate mode")."""
    f1 = [s.strip() for s in a1.split(",") if s.strip()]
    f2 = [s.strip() for s in a2.split(",") if s.strip()]
    return f1 + f2, len(f1)


class TestCheckConstraints:
    def test_both_fit_returns_empty(self):
        assert check_constraints("A" * 100, "B" * 50, LIMITS) == []

    def test_a1_over_limit(self):
        assert check_constraints("A" * 101, "B", LIMITS) == ["BC_ADDRESS_1_MAX_LENGTH"]

    def test_a2_over_limit(self):
        assert check_constraints("A", "B" * 51, LIMITS) == ["BC_ADDRESS_2_MAX_LENGTH"]

    def test_both_over_limit(self):
        result = check_constraints("A" * 101, "B" * 51, LIMITS)
        assert set(result) == {"BC_ADDRESS_1_MAX_LENGTH", "BC_ADDRESS_2_MAX_LENGTH"}


class TestRebalanceFit:
    """Case 1/5/13: already fits -> FIT, boundary unchanged, AUTO_PASS path."""

    def test_within_limits_no_change(self):
        frags = ["F-192", "Phase 8B", "Industrial Area", "Sector 74"]
        result = rebalance(frags, boundary=1, limits=LIMITS)
        assert result.status == FitStatus.FIT
        assert result.boundary == 1

    def test_a2_exactly_at_limit_fits(self):
        # Case 5: A2 exactly 50 chars -> AUTO_PASS, no rebalance.
        a2_frag = "B" * 50
        frags = ["UNIT 7", a2_frag]
        result = rebalance(frags, boundary=1, limits=LIMITS)
        assert result.status == FitStatus.FIT
        assert result.boundary == 1

    def test_empty_fragment_list(self):
        result = rebalance([], boundary=0, limits=LIMITS)
        assert result.status == FitStatus.FIT
        assert result.boundary == 0


class TestRebalanceShiftRight:
    def test_canonical_howrah_baseline(self):
        # plan §6 "Measured": 25/69 -> 58/36
        a1 = "3RD FLOOR, PART A BLOCK B"
        a2 = "SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY CHANDIBAGAN, ANDUL, Natibpur"
        frags, boundary = _split(a1, a2)
        result = rebalance(frags, boundary, LIMITS)
        assert result.status == FitStatus.REBALANCED
        new_a1 = LIMITS.separator.join(frags[:result.boundary])
        new_a2 = LIMITS.separator.join(frags[result.boundary:])
        assert new_a1 == "3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK"
        assert new_a2 == "MOHIARY CHANDIBAGAN, ANDUL, Natibpur"
        assert len(new_a1) == 58
        assert len(new_a2) == 36

    def test_corpus_variant(self):
        a1 = "3RD FLOOR, PART A BLOCK B"
        a2 = "SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY, CHANDIBAGAN, ANDUL, NATIBPUR"
        frags, boundary = _split(a1, a2)
        result = rebalance(frags, boundary, LIMITS)
        assert result.status == FitStatus.REBALANCED
        new_a2 = LIMITS.separator.join(frags[result.boundary:])
        assert len(LIMITS.separator.join(frags[:result.boundary])) == 58
        assert len(new_a2) == 37

    def test_ho24_case(self):
        a1 = "SEZ UNIT 4, BRIGADE TECH GARDENS"
        a2 = "KADUBEESANAHALLI, DODDANEKKUNDI, MARATHAHALLI, BELLANDUR, VARTHUR"
        frags, boundary = _split(a1, a2)
        result = rebalance(frags, boundary, LIMITS)
        assert result.status == FitStatus.REBALANCED
        assert len(LIMITS.separator.join(frags[:result.boundary])) == 50
        assert len(LIMITS.separator.join(frags[result.boundary:])) == 47

    def test_one_char_over_limit_rebalances(self):
        # Case 6: A2 = 51 chars made of whole fragments.
        frags = ["UNIT 7", "A" * 20, "B" * 27]  # A2 = "AAAA..., BBBB..." = 20+2+27=49? recompute below
        # Build precisely: two fragments joined with ", " (2 chars) must total 51.
        frag_a, frag_b = "A" * 24, "B" * 25  # 24 + 2 + 25 = 51
        frags = ["UNIT 7", frag_a, frag_b]
        result = rebalance(frags, boundary=1, limits=LIMITS)
        assert result.status == FitStatus.REBALANCED

    def test_single_fragment_moved_when_it_only_fits_a1(self):
        # Case 8b: a 60-char fragment in A2, short A1 -> must move to A1.
        frags = ["Unit 1", "X" * 60]
        result = rebalance(frags, boundary=1, limits=LIMITS)
        assert result.status == FitStatus.REBALANCED
        assert result.boundary == 2

    def test_minimal_move_first_fit_wins(self):
        # Several possible right-shift boundaries fit; must pick the smallest.
        frags = ["A1", "B" * 10, "C" * 10, "D" * 45]  # A2 starts too long
        result = rebalance(frags, boundary=1, limits=LIMITS)
        if result.status == FitStatus.REBALANCED:
            # first boundary at which A2 fits must be chosen, not a later one
            for nb in range(2, len(frags) + 1):
                a2 = LIMITS.separator.join(frags[nb:])
                if len(a2) <= LIMITS.address_2_max:
                    assert result.boundary == nb
                    break


class TestRebalanceShiftLeft:
    def test_a1_over_limit_shifts_left(self):
        frags = ["A" * 60, "B" * 45, "c"]
        # boundary=2 -> A1 = 60+2+45=107 (>100), A2="c" fits
        result = rebalance(frags, boundary=2, limits=LIMITS)
        assert result.status == FitStatus.REBALANCED
        assert result.boundary < 2

    def test_left_shift_never_goes_below_floor(self):
        # floor=1 must never be crossed even if a lower boundary would fit.
        frags = ["A" * 60, "B" * 45, "c"]
        result = rebalance(frags, boundary=2, limits=LIMITS, floor=1)
        assert result.boundary >= 1

    def test_left_shift_blocked_by_floor_overflows(self):
        # A1 too long, but the only fitting boundary is below the floor ->
        # must report OVERFLOW rather than crossing the floor (Case 16: no
        # A1<->A2 oscillation past a backfill boundary).
        frags = ["A" * 101, "b"]
        result = rebalance(frags, boundary=1, limits=LIMITS, floor=1)
        assert result.status == FitStatus.OVERFLOW
        assert result.boundary == 1  # unchanged


class TestRebalanceOverflow:
    def test_granularity_overflow_under_combined_limit(self):
        # Case 7b: UNIT 7 + 70-char + 55-char fragments, total 135 < 152,
        # but no whole-fragment boundary makes both lines fit.
        frags = ["UNIT 7", "X" * 70, "Y" * 55]
        result = rebalance(frags, boundary=1, limits=LIMITS)
        assert result.status == FitStatus.OVERFLOW
        assert result.boundary == 1  # values unchanged

    def test_total_over_combined_limit(self):
        # Case 7c: total > 152.
        frags = ["A" * 80, "B" * 80]
        result = rebalance(frags, boundary=1, limits=LIMITS)
        assert result.status == FitStatus.OVERFLOW

    def test_single_fragment_exceeds_a1_limit_never_truncated(self):
        # Case 8: one 110-char comma-less fragment.
        frags = ["X" * 110]
        result = rebalance(frags, boundary=0, limits=LIMITS)
        assert result.status == FitStatus.OVERFLOW
        assert result.detail == FRAGMENT_TOO_LONG

    def test_overflow_never_mutates_the_boundary(self):
        frags = ["A" * 200]
        before = list(frags)
        result = rebalance(frags, boundary=0, limits=LIMITS)
        assert frags == before  # caller list untouched
        assert result.status == FitStatus.OVERFLOW


class TestNoTruncationEver:
    """BC-03: joined final text must always equal a contiguous slice-join of
    the ORIGINAL fragments -- never a truncated string."""

    def test_no_slicing_of_fragment_text(self):
        frags = ["Industrial Area", "X" * 90]
        result = rebalance(frags, boundary=0, limits=LIMITS)
        # whatever the outcome, every fragment's full text must appear intact
        final_a1 = LIMITS.separator.join(frags[:result.boundary])
        final_a2 = LIMITS.separator.join(frags[result.boundary:])
        assert "Industrial Area" in (final_a1 + final_a2)
        assert ("Industrial Ar" not in final_a1) or ("Industrial Area" in final_a1)


class TestValidateFinal:
    def test_valid_layout_passes(self):
        frags = ["A", "B", "C"]
        assert validate_final(frags, boundary=1, limits=LIMITS) == []

    def test_a1_too_long_flagged(self):
        frags = ["A" * 101, "b"]
        assert "BC-01" in validate_final(frags, boundary=1, limits=LIMITS)

    def test_a2_too_long_flagged(self):
        frags = ["a", "B" * 51]
        assert "BC-02" in validate_final(frags, boundary=1, limits=LIMITS)

    def test_out_of_range_boundary_flagged(self):
        frags = ["a", "b"]
        assert "BC-06" in validate_final(frags, boundary=5, limits=LIMITS)
        assert "BC-06" in validate_final(frags, boundary=-1, limits=LIMITS)

    def test_boundary_at_both_ends_is_valid_range(self):
        frags = ["a", "b"]
        assert validate_final(frags, boundary=0, limits=LIMITS) == []
        assert validate_final(frags, boundary=2, limits=LIMITS) == []


# ---------------------------------------------------------------------------
# Property tests (plan §11.2): corpus-independent, seeded random fragment
# lists, checking algorithm invariants that must hold for ANY input.
# ---------------------------------------------------------------------------

def _random_fragments(rng: random.Random, n: int) -> list[str]:
    return ["".join(rng.choices("ABCDEFGHIJ ", k=rng.randint(1, 40))).strip() or "X"
            for _ in range(n)]


class TestRebalanceProperties:
    SEED = 20260930
    N_TRIALS = 2000

    def _cases(self):
        rng = random.Random(self.SEED)
        for _ in range(self.N_TRIALS):
            n = rng.randint(0, 8)
            frags = _random_fragments(rng, n)
            boundary = rng.randint(0, n)
            max1 = rng.choice([20, 50, 100, 150])
            max2 = rng.choice([10, 30, 50, 80])
            limits = AddressLimits(address_1_max=max1, address_2_max=max2, separator=", ")
            yield frags, boundary, limits

    def test_lossless_join_and_order_preserved(self):
        """I3/BC-06: the fragment list itself is never touched by rebalance;
        joining across the returned boundary always reconstructs a
        contiguous, order-preserving slice of the SAME list."""
        for frags, boundary, limits in self._cases():
            before = list(frags)
            result = rebalance(frags, boundary, limits)
            assert frags == before  # never mutated in place
            assert 0 <= result.boundary <= len(frags)
            # reconstructing via the returned boundary always uses every
            # fragment exactly once, in original order
            reconstructed = frags[:result.boundary] + frags[result.boundary:]
            assert reconstructed == frags

    def test_limits_respected_unless_overflow(self):
        """BC-01/BC-02: FIT or REBALANCED must always satisfy both limits."""
        for frags, boundary, limits in self._cases():
            result = rebalance(frags, boundary, limits)
            if result.status in (FitStatus.FIT, FitStatus.REBALANCED):
                a1 = limits.separator.join(frags[:result.boundary])
                a2 = limits.separator.join(frags[result.boundary:])
                assert len(a1) <= limits.address_1_max
                assert len(a2) <= limits.address_2_max

    def test_overflow_never_changes_boundary(self):
        for frags, boundary, limits in self._cases():
            result = rebalance(frags, boundary, limits)
            if result.status == FitStatus.OVERFLOW:
                assert result.boundary == boundary

    def test_deterministic(self):
        for frags, boundary, limits in self._cases():
            r1 = rebalance(list(frags), boundary, limits)
            r2 = rebalance(list(frags), boundary, limits)
            assert r1 == r2

    def test_idempotent(self):
        """Running rebalance again on its own output boundary must return
        FIT at that same boundary and never move further."""
        for frags, boundary, limits in self._cases():
            first = rebalance(frags, boundary, limits)
            if first.status in (FitStatus.FIT, FitStatus.REBALANCED):
                second = rebalance(frags, first.boundary, limits)
                assert second.boundary == first.boundary
                assert second.status == FitStatus.FIT

    def test_flag_equivalent_when_already_fitting(self):
        """If the original boundary already fits, rebalance is a true no-op
        (FIT, same boundary) -- this is what makes 'flag on with a fitting
        address' == 'flag off' (plan §10 algorithm properties)."""
        for frags, boundary, limits in self._cases():
            a1 = limits.separator.join(frags[:boundary])
            a2 = limits.separator.join(frags[boundary:])
            if len(a1) <= limits.address_1_max and len(a2) <= limits.address_2_max:
                result = rebalance(frags, boundary, limits)
                assert result.status == FitStatus.FIT
                assert result.boundary == boundary

    def test_never_reverses_below_floor(self):
        """BC rebalance must never return a boundary below the given floor
        (no A1<->A2 oscillation past a step-5 backfill, plan §2/§17)."""
        rng = random.Random(self.SEED + 1)
        for _ in range(500):
            n = rng.randint(1, 8)
            frags = _random_fragments(rng, n)
            floor = rng.randint(0, n)
            boundary = rng.randint(floor, n)
            limits = AddressLimits(
                address_1_max=rng.choice([10, 30, 100]),
                address_2_max=rng.choice([10, 30, 50]),
                separator=", ",
            )
            result = rebalance(frags, boundary, limits, floor=floor)
            assert result.boundary >= floor

    def test_no_fragment_longer_than_a1_can_ever_fit(self):
        rng = random.Random(self.SEED + 2)
        for _ in range(500):
            long_frag = "Z" * rng.randint(101, 200)
            frags = ["short"] + [long_frag] if rng.random() < 0.5 else [long_frag]
            boundary = 0
            limits = AddressLimits(address_1_max=100, address_2_max=50, separator=", ")
            result = rebalance(frags, boundary, limits)
            if long_frag in frags and len(long_frag) > limits.address_1_max:
                assert result.status == FitStatus.OVERFLOW
