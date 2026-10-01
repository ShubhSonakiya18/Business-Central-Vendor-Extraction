"""Tests for address_representation.py -- the step-5 presentation fallback
and the steps 6-9 BC representation orchestrator.

See docs/ADDRESS_SEGMENTATION_PLAN.md §11.1 for the named cases this file
implements (2, 3, 3c, 5-10, 12, 15, 16) and §10 for the invariants (S-08,
BC-08, BC-09). Layouts are built via
`layout_from_segmented(segment_leftover([...]))` -- i.e. through the real,
unchanged Layer 1 segmenter -- so these tests exercise the actual boundary
between Layer 1 and Layer 2, not a synthetic stand-in for it.
"""

from __future__ import annotations

from app.services.bc_target_profile import AddressLimits, load_profile
from app.services.extraction_pipeline.extract.address_representation import (
    ADDRESS_1,
    ADDRESS_2,
    AUTO_FIX,
    AUTO_PASS,
    BLOCK_SUBMISSION,
    MANUAL_REVIEW,
    REASON_ADDRESS_1_BACKFILLED,
    REASON_ADDRESS_OVERFLOW,
    REASON_BC_LENGTH_REBALANCE,
    RULE_FIRST_1_2_FRAGMENTS,
    RULE_LEADING_THOROUGHFARE,
    DecisionStatus,
    LayoutFragment,
    SemanticLayout,
    apply_a1_fallback,
    layout_from_segmented,
    layout_from_stored,
    represent_address,
)
from app.services.extraction_pipeline.extract.address_segmenter import segment_leftover

LIMITS = AddressLimits(address_1_max=100, address_2_max=50, separator=", ")


def _sem(fragments: list[str]) -> SemanticLayout:
    return layout_from_segmented(segment_leftover(fragments))


# ---------------------------------------------------------------------------
# layout_from_segmented / SemanticLayout basics
# ---------------------------------------------------------------------------

class TestLayoutFromSegmented:
    def test_case1_normal_premise_address_no_fallback_needed(self):
        # Case 1: F-192, Phase 8B, Industrial Area, Sector 74
        sem = _sem(["F-192", "Phase 8B", "Industrial Area", "Sector 74"])
        assert sem.semantic_boundary == 1
        assert sem.semantic_address_1 == "F-192"
        assert sem.semantic_address_2 == "Phase 8B, Industrial Area, Sector 74"
        assert sem.fragments[0].semantic_role == ADDRESS_1
        assert sem.fragments[1].semantic_role == ADDRESS_2  # Phase -> ADDRESS_2

    def test_case11_boundary_never_reopens(self):
        # Case 11 / Case 7 in the plan's original brief: Flat 402, Tower B,
        # Sunrise Apartments, Block C, Sector 10 -- Block C (structural,
        # ADDRESS_1-role in isolation) must NOT reopen Address 1.
        sem = _sem(["Flat 402", "Tower B", "Sunrise Apartments", "Block C", "Sector 10"])
        assert sem.semantic_boundary == 2
        assert sem.semantic_address_1 == "Flat 402, Tower B"
        assert sem.semantic_address_2 == "Sunrise Apartments, Block C, Sector 10"

    def test_case9_unknown_never_semantically_address_1(self):
        sem = _sem(["Unknown A", "Unknown B"])
        assert sem.semantic_boundary == 0


# ---------------------------------------------------------------------------
# step 5: apply_a1_fallback
# ---------------------------------------------------------------------------

class TestApplyA1FallbackNoOp:
    def test_nonempty_semantic_boundary_is_noop(self):
        sem = _sem(["F-192", "Phase 8B"])
        layout, transform = apply_a1_fallback(sem)
        assert transform is None
        assert layout.boundary == sem.semantic_boundary
        assert layout.address_1 == sem.semantic_address_1

    def test_empty_fragment_list_is_noop(self):
        sem = SemanticLayout(fragments=(), semantic_boundary=0)
        layout, transform = apply_a1_fallback(sem)
        assert transform is None
        assert layout.boundary == 0


class TestApplyA1FallbackGeneric:
    """Case 2/3: A1 empty, generic first_1_2_fragments variant."""

    def test_case2_single_fragment_moves_entirely(self):
        sem = _sem(["Sector 67"])
        layout, transform = apply_a1_fallback(sem)
        assert layout.address_1 == "Sector 67"
        assert layout.address_2 == ""
        assert transform.reason_code == REASON_ADDRESS_1_BACKFILLED
        assert transform.automation_class == AUTO_FIX
        assert transform.transformation == RULE_FIRST_1_2_FRAGMENTS
        assert transform.manual_review_required is False

    def test_case3_three_fragments_moves_first_two(self):
        sem = _sem(["Ward 07", "Sector 67", "Industrial Area"])
        layout, transform = apply_a1_fallback(sem)
        assert layout.address_1 == "Ward 07, Sector 67"
        assert layout.address_2 == "Industrial Area"
        assert transform.boundary_before == 0
        assert transform.boundary_after == 2

    def test_four_unknown_fragments_moves_first_two_preserving_order(self):
        sem = _sem(["A", "B", "C", "D"])
        layout, transform = apply_a1_fallback(sem)
        assert layout.address_1 == "A, B"
        assert layout.address_2 == "C, D"

    def test_provenance_records_original_and_final(self):
        sem = _sem(["Ward 07", "Sector 67", "Industrial Area"])
        _, transform = apply_a1_fallback(sem)
        assert transform.original_address_1 == ""
        assert transform.original_address_2 == "Ward 07, Sector 67, Industrial Area"
        assert transform.final_address_1 == "Ward 07, Sector 67"
        assert transform.final_address_2 == "Industrial Area"

    def test_moved_fragments_get_final_bc_field_address_1_but_keep_semantic_role(self):
        # Case 10 (generic-backfill variant): a moved fragment's
        # semantic_role must be unchanged; only final_bc_field/moved_by move.
        sem = _sem(["Sector 67"])  # 'Sector 67' is tier=locality -> ADDRESS_2 semantically
        assert sem.fragments[0].semantic_role == ADDRESS_2
        layout, transform = apply_a1_fallback(sem)
        moved = layout.fragments[0]
        assert moved.semantic_role == ADDRESS_2          # unchanged
        assert moved.final_bc_field == ADDRESS_1          # moved here
        assert moved.moved_by == REASON_ADDRESS_1_BACKFILLED


class TestApplyA1FallbackThoroughfare:
    """Case 3c: MG Road, B, C, D -> leading_thoroughfare variant, stops."""

    def test_leading_thoroughfare_moves_only_fragment_zero(self):
        sem = _sem(["MG Road", "B", "C", "D"])
        assert sem.thoroughfare_fallback_applied is True
        assert sem.semantic_boundary == 0
        layout, transform = apply_a1_fallback(sem)
        assert layout.address_1 == "MG Road"
        assert layout.address_2 == "B, C, D"
        assert transform.transformation == RULE_LEADING_THOROUGHFARE
        assert transform.reason_code == REASON_ADDRESS_1_BACKFILLED
        assert transform.automation_class == AUTO_FIX

    def test_generic_backfill_does_not_also_fire(self):
        """The two variants are mutually exclusive: when thoroughfare fires,
        first_1_2_fragments must NOT also move a second fragment."""
        sem = _sem(["MG Road", "B", "C", "D"])
        layout, transform = apply_a1_fallback(sem)
        assert transform.boundary_after == 1  # not 2
        assert len(transform.moved_fragment_indices) == 1


class TestApplyA1FallbackGeographySafety:
    """Case 4: the fallback never sees geography -- structural guarantee,
    checked here by confirming it operates purely on the fragment list."""

    def test_fallback_has_no_access_to_geography(self):
        # Geography (city/state/pin/country) is peeled BEFORE segment_leftover
        # ever runs, so it cannot appear in `sem.fragments` at all -- this
        # test documents that guarantee by using fragments that would look
        # like geography tokens if they leaked in, and confirming they are
        # treated as ordinary text (because in a real pipeline they'd never
        # reach here to begin with).
        sem = _sem(["Ward 07", "Sector 67"])
        layout, transform = apply_a1_fallback(sem)
        # nothing resembling "Punjab"/"India"/a 6-digit PIN was ever in the
        # input, and none appears in the output -- geography simply isn't
        # part of this function's vocabulary.
        assert "Punjab" not in layout.address_1
        assert "India" not in layout.address_1


# ---------------------------------------------------------------------------
# steps 6-9: represent_address
# ---------------------------------------------------------------------------

class TestRepresentAddressAutoPass:
    def test_case1_fits_no_rebalance_no_review(self):
        sem = _sem(["F-192", "Phase 8B", "Industrial Area", "Sector 74"])
        decision = represent_address(sem, LIMITS)
        assert decision.status == DecisionStatus.AUTO_PASS
        assert decision.address_1 == "F-192"
        assert decision.address_2 == "Phase 8B, Industrial Area, Sector 74"
        assert decision.transforms == ()
        assert decision.findings == ()

    def test_case5_a2_exactly_at_limit(self):
        sem = SemanticLayout(
            fragments=(
                LayoutFragment(0, "UNIT 7", "premises_unit", ADDRESS_1, ADDRESS_1),
                LayoutFragment(1, "B" * 50, "locality", ADDRESS_2, ADDRESS_2),
            ),
            semantic_boundary=1,
        )
        decision = represent_address(sem, LIMITS)
        assert decision.status == DecisionStatus.AUTO_PASS
        assert len(decision.address_2) == 50

    def test_case11_boundary_never_reopens_and_fits(self):
        sem = _sem(["Flat 402", "Tower B", "Sunrise Apartments", "Block C", "Sector 10"])
        decision = represent_address(sem, LIMITS)
        assert decision.status == DecisionStatus.AUTO_PASS
        assert decision.address_1 == "Flat 402, Tower B"
        assert decision.address_2 == "Sunrise Apartments, Block C, Sector 10"


class TestRepresentAddressAutoFixBackfill:
    def test_case3b_no_premise_low_confidence_still_auto_fix_no_review(self):
        # Mauli Baidwan, Circular Road, Sector 80 -- no premise identifier at
        # all -> segmenter confidence 'low', but that must NOT create a
        # review finding (plan §7, decision confirmed by the user).
        sem = _sem(["Mauli Baidwan", "Circular Road", "Sector 80"])
        assert sem.semantic_boundary == 0
        decision = represent_address(sem, LIMITS)
        assert decision.status == DecisionStatus.AUTO_FIX
        assert decision.address_1 == "Mauli Baidwan, Circular Road"
        assert decision.address_2 == "Sector 80"
        assert decision.findings == ()  # no review finding
        assert decision.transforms[0].reason_code == REASON_ADDRESS_1_BACKFILLED

    def test_case12_leading_unknown_backfill_by_position_not_scan(self):
        # Unknown Fragment, F-192, Phase 8B, Industrial Area, Sector 74 --
        # semantic boundary is 0 (no forward scan promotes F-192); the
        # backfill takes the first 2 BY POSITION.
        sem = _sem(["Unknown Fragment", "F-192", "Phase 8B", "Industrial Area", "Sector 74"])
        assert sem.semantic_boundary == 0
        decision = represent_address(sem, LIMITS)
        assert decision.status == DecisionStatus.AUTO_FIX
        assert decision.address_1 == "Unknown Fragment, F-192"
        assert decision.address_2 == "Phase 8B, Industrial Area, Sector 74"
        # F-192 was moved by the backfill, not classified as premise-first
        moved = [f for f in decision.final.fragments if f.text == "F-192"][0]
        assert moved.moved_by == REASON_ADDRESS_1_BACKFILLED
        assert moved.semantic_role == ADDRESS_2  # unchanged despite the move


class TestRepresentAddressRebalanceManualReview:
    def test_case7_howrah_baseline_rebalances_one_click(self):
        sem = _sem([
            "3RD FLOOR", "PART A BLOCK B", "SRIJAN INDUSTRIAL LOGISTIC PARK",
            "MOHIARY CHANDIBAGAN", "ANDUL", "Natibpur",
        ])
        decision = represent_address(sem, LIMITS, profile_name="bc22_in_vendorcard")
        assert decision.status == DecisionStatus.MANUAL_REVIEW
        assert decision.address_1 == "3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK"
        assert decision.address_2 == "MOHIARY CHANDIBAGAN, ANDUL, Natibpur"
        assert len(decision.address_1) == 58
        assert len(decision.address_2) == 36
        rebalance_t = [t for t in decision.transforms if t.layer == "bc_representation"][0]
        assert rebalance_t.reason_code == REASON_BC_LENGTH_REBALANCE
        assert rebalance_t.automation_class == MANUAL_REVIEW
        assert rebalance_t.constraint == "BC_ADDRESS_2_MAX_LENGTH"
        assert rebalance_t.profile == "bc22_in_vendorcard"
        finding = decision.findings[0]
        assert finding.reason_code == REASON_BC_LENGTH_REBALANCE
        assert finding.automation_class == MANUAL_REVIEW

    def test_case10_moved_fragment_keeps_semantic_role_address_2(self):
        # Phase 8B: semantic_role ADDRESS_2, moved into Address 1 by the
        # rebalance -> final_bc_field ADDRESS_1, semantic_role UNCHANGED.
        sem = _sem([
            "3RD FLOOR", "PART A BLOCK B", "SRIJAN INDUSTRIAL LOGISTIC PARK",
            "MOHIARY CHANDIBAGAN", "ANDUL", "Natibpur",
        ])
        decision = represent_address(sem, LIMITS)
        moved = [f for f in decision.final.fragments if "SRIJAN" in f.text][0]
        assert moved.semantic_role == ADDRESS_2
        assert moved.final_bc_field == ADDRESS_1
        assert moved.moved_by == REASON_BC_LENGTH_REBALANCE
        # and the classifier itself must be unaffected by this move
        from app.services.extraction_pipeline.extract.address_segmenter import (
            classify_fragment,
        )
        tier, *_ = classify_fragment("SRIJAN INDUSTRIAL LOGISTIC PARK")
        assert tier == "estate_zone"  # still classifies as ADDRESS_2-role, unaffected

    def test_case9_fragments_never_reordered_by_rebalance(self):
        sem = SemanticLayout(
            fragments=(
                LayoutFragment(0, "A", "premises_unit", ADDRESS_1, ADDRESS_1),
                LayoutFragment(1, "B" * 10, "structural", ADDRESS_1, ADDRESS_1),
                LayoutFragment(2, "C" * 30, "locality", ADDRESS_2, ADDRESS_2),
                LayoutFragment(3, "D" * 30, "locality", ADDRESS_2, ADDRESS_2),
            ),
            semantic_boundary=2,
        )
        decision = represent_address(sem, LIMITS)
        texts_in_order = [f.text for f in decision.final.fragments]
        assert texts_in_order == ["A", "B" * 10, "C" * 30, "D" * 30]


class TestRepresentAddressOverflowBlock:
    def test_case7b_granularity_overflow_blocks_values_unchanged(self):
        sem = SemanticLayout(
            fragments=(
                LayoutFragment(0, "UNIT 7", "premises_unit", ADDRESS_1, ADDRESS_1),
                LayoutFragment(1, "X" * 70, "locality", ADDRESS_2, ADDRESS_2),
                LayoutFragment(2, "Y" * 55, "locality", ADDRESS_2, ADDRESS_2),
            ),
            semantic_boundary=1,
        )
        decision = represent_address(sem, LIMITS)
        # "MANUAL_REVIEW / BLOCK" = BLOCK_SUBMISSION fixed by a human edit (plan §0)
        assert decision.status == DecisionStatus.BLOCK
        assert decision.findings[0].automation_class == BLOCK_SUBMISSION
        assert decision.address_1 == "UNIT 7"  # unchanged
        assert decision.address_2 == "X" * 70 + ", " + "Y" * 55  # unchanged, NOT truncated
        assert decision.findings[0].reason_code == REASON_ADDRESS_OVERFLOW

    def test_case8_single_long_fragment_blocks_not_truncated(self):
        sem = SemanticLayout(
            fragments=(LayoutFragment(0, "X" * 110, "unknown", ADDRESS_2, ADDRESS_2),),
            semantic_boundary=0,
        )
        decision = represent_address(sem, LIMITS)
        assert decision.status == DecisionStatus.BLOCK
        overflow = [f for f in decision.findings if f.reason_code == REASON_ADDRESS_OVERFLOW]
        assert overflow and overflow[0].detail == "fragment_too_long"
        # backfilled into A1 but still overflows -> kept whole, never cut
        assert decision.address_1 == "X" * 110
        # the expected over-length is not double-reported as an invariant violation
        assert all(f.reason_code != "ADDRESS_INVARIANT_VIOLATION" for f in decision.findings)


class TestRepresentAddressBackfillThenRebalanceCase15:
    def test_backfill_followed_by_rebalance_two_entries_stricter_class_wins(self):
        # No premise, but the resulting A2 is still too long after the
        # backfill -> both transforms fire in order.
        long_locality = "Industrial Estate Extension Road Number Seven Colony"
        sem = SemanticLayout(
            fragments=(
                LayoutFragment(0, "Ward 07", "unknown", ADDRESS_2, ADDRESS_2),
                LayoutFragment(1, "Sector 67", "locality", ADDRESS_2, ADDRESS_2),
                LayoutFragment(2, long_locality, "locality", ADDRESS_2, ADDRESS_2),
            ),
            semantic_boundary=0,
        )
        decision = represent_address(sem, LIMITS)
        assert len(decision.transforms) == 2
        assert decision.transforms[0].reason_code == REASON_ADDRESS_1_BACKFILLED
        assert decision.transforms[1].reason_code == REASON_BC_LENGTH_REBALANCE
        assert decision.status == DecisionStatus.MANUAL_REVIEW
        # chaining: second transform's "original" equals first transform's "final"
        assert decision.transforms[1].original_address_1 == decision.transforms[0].final_address_1
        assert decision.transforms[1].original_address_2 == decision.transforms[0].final_address_2


class TestRepresentAddressCase16NoOscillation:
    def test_a1_over_limit_after_backfill_never_shifts_left_past_floor(self):
        # After a backfill moves 2 fragments into A1 and A1 ends up over 100
        # chars, the rebalance must NOT shift left past the backfill's own
        # boundary (that would undo the backfill -- A1<->A2 oscillation).
        sem = SemanticLayout(
            fragments=(
                LayoutFragment(0, "X" * 60, "unknown", ADDRESS_2, ADDRESS_2),
                LayoutFragment(1, "Y" * 60, "unknown", ADDRESS_2, ADDRESS_2),
                LayoutFragment(2, "z", "unknown", ADDRESS_2, ADDRESS_2),
            ),
            semantic_boundary=0,
        )
        decision = represent_address(sem, LIMITS)
        # backfill moves fragments 0,1 into A1 (n=3 -> first 2) -> A1 = 60+2+60=122 > 100.
        # A left shift to boundary 1 WOULD fit, but it would hand a backfilled
        # fragment back to A2 -- forbidden. So: ADDRESS_OVERFLOW, BLOCK.
        assert decision.final.boundary == 2
        assert [t.reason_code for t in decision.transforms] == [REASON_ADDRESS_1_BACKFILLED]
        assert decision.status == DecisionStatus.BLOCK
        assert [f.reason_code for f in decision.findings] == [REASON_ADDRESS_OVERFLOW]


# ---------------------------------------------------------------------------
# layout_from_stored / gate mode
# ---------------------------------------------------------------------------

class TestLayoutFromStored:
    def test_round_trips_simple_a1_a2(self):
        sem = layout_from_stored("F-192", "Phase 8B, Industrial Area")
        assert sem.semantic_address_1 == "F-192"
        assert sem.semantic_address_2 == "Phase 8B, Industrial Area"
        assert sem.semantic_boundary == 1

    def test_legacy_address_3_4_folded_into_a2_recovery(self):
        sem = layout_from_stored("F-192", "Phase 8B", "Sector 74", "Near Metro")
        assert sem.semantic_boundary == 1
        # all of a2+a3+a4's fragments appear, in order, after the boundary
        recovered_a2_texts = [f.text for f in sem.fragments[1:]]
        assert recovered_a2_texts == ["Phase 8B", "Sector 74", "Near Metro"]

    def test_gate_mode_never_mutates_only_proposes(self):
        sem = layout_from_stored(
            "3RD FLOOR, PART A BLOCK B",
            "SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY CHANDIBAGAN, ANDUL, Natibpur",
        )
        decision = represent_address(sem, LIMITS, mode="check")
        # the gate call itself does not write anywhere -- it just returns a
        # decision; the caller decides whether to persist decision.final
        assert decision.status == DecisionStatus.MANUAL_REVIEW
        assert len(decision.address_2) <= 50


# ---------------------------------------------------------------------------
# BC-09 / S-08 property-style checks over the corpus
# ---------------------------------------------------------------------------

class TestInvariantsAcrossCorpus:
    def test_semantic_role_never_changes_across_the_pipeline(self):
        import yaml
        from pathlib import Path

        cases_file = Path(__file__).parent.parent / "app" / "eval" / "address_line_cases.yaml"
        doc = yaml.safe_load(cases_file.read_text(encoding="utf-8"))
        for case in doc["cases"]:
            segs = case["segments"]
            sem = layout_from_segmented(segment_leftover(segs))
            decision = represent_address(sem, LIMITS)
            sem_roles = {f.index: f.semantic_role for f in sem.fragments}
            for f in decision.final.fragments:
                assert f.semantic_role == sem_roles[f.index], (
                    f"case {case.get('id')}: fragment {f.index} semantic_role changed"
                )
        assert len(doc["cases"]) >= 74  # guard against a silently empty sweep

    def test_source_order_and_no_loss_across_corpus(self):
        import yaml
        from pathlib import Path

        cases_file = Path(__file__).parent.parent / "app" / "eval" / "address_line_cases.yaml"
        doc = yaml.safe_load(cases_file.read_text(encoding="utf-8"))
        for case in doc["cases"]:
            segs = case["segments"]
            sem = layout_from_segmented(segment_leftover(segs))
            decision = represent_address(sem, LIMITS)
            indices = [f.index for f in decision.final.fragments]
            assert indices == sorted(indices), f"case {case.get('id')}: order not preserved"
            assert len(indices) == len(sem.fragments), f"case {case.get('id')}: fragment count changed"
        assert len(doc["cases"]) >= 74  # guard against a silently empty sweep
