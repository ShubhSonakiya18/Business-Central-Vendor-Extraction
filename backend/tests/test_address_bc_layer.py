"""End-to-end tests of the BC address representation layer through the real
entry point, `resolve_address_blob(..., multiline=True, bc_layer=...)`.

See docs/ADDRESS_SEGMENTATION_PLAN.md §11.1 (named cases 1, 3b, 4, 7, 10-14)
and §14 R1 (flag-off guard). Unit-level cases for the fallback and the
rebalance algorithm live in test_address_representation.py and
test_bc_address_fit.py; this file checks that the layer is wired in
correctly and that geography, Address 3/4 and the flag-off path are safe.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config.config import settings
from app.services.bc_target_profile import AddressLimits
from app.services.extraction_pipeline.extract.address_representation import (
    ADDRESS_1,
    ADDRESS_2,
    REASON_ADDRESS_INVARIANT_VIOLATION,
    SemanticLayout,
    LayoutFragment,
    represent_address,
)
from app.services.extraction_pipeline.extract.address_resolver import resolve_address_blob

_EVAL_DIR = Path(__file__).resolve().parents[1] / "app" / "eval"
_RAW_CORPORA = ["address_cases.yaml", "address_vendor_lines.yaml", "address_holdout_cases.yaml"]


def _raw_cases():
    for name in _RAW_CORPORA:
        doc = yaml.safe_load((_EVAL_DIR / name).read_text(encoding="utf-8"))
        for case in doc["cases"]:
            if case.get("address"):
                yield name, case


_ALL_RAW = list(_raw_cases())


def _on(addr: str):
    return resolve_address_blob(addr, multiline=True, bc_layer=True)


def _off(addr: str):
    return resolve_address_blob(addr, multiline=True, bc_layer=False)


# ---------------------------------------------------------------------------
# flag wiring
# ---------------------------------------------------------------------------

class TestFlagWiring:
    def test_default_setting_is_off(self):
        assert settings.BC_ADDRESS_LAYER_ENABLED is False

    def test_bc_layer_none_follows_setting(self, monkeypatch):
        addr = "F-192, Phase 8B, Industrial Area, Sector 74, SAS Nagar, Punjab 160055"
        monkeypatch.setattr(settings, "BC_ADDRESS_LAYER_ENABLED", False)
        assert resolve_address_blob(addr, multiline=True).representation is None
        monkeypatch.setattr(settings, "BC_ADDRESS_LAYER_ENABLED", True)
        assert resolve_address_blob(addr, multiline=True).representation is not None

    def test_non_multiline_path_never_uses_the_layer(self):
        r = resolve_address_blob("F-192, Phase 8B, SAS Nagar, Punjab 160055", bc_layer=True)
        assert r.representation is None
        assert r.findings == []


class TestFlagOffGuardR1:
    """R1: with the layer off, output is exactly today's behaviour. The
    existing segmenter/resolver suites already pin today's values; this adds
    the whole-corpus guard that flag-off never carries layer output."""

    @pytest.mark.parametrize("corpus,case", _ALL_RAW, ids=[c["id"] for _, c in _ALL_RAW])
    def test_flag_off_has_no_layer_output(self, corpus, case):
        r = _off(case["address"])
        assert r.representation is None
        assert r.findings == []


class TestCorpusSafetyWithLayerOn:
    @pytest.mark.parametrize("corpus,case", _ALL_RAW, ids=[c["id"] for _, c in _ALL_RAW])
    def test_geography_and_a3_a4_untouched(self, corpus, case):
        """Cases 4, 13, 14: the layer never changes City/State/PIN/Country and
        never populates Address 3/4, on any corpus address."""
        off, on = _off(case["address"]), _on(case["address"])
        assert (on.city, on.state, on.pin_code, on.country) == (off.city, off.state, off.pin_code, off.country)
        assert on.address_3 == "" and on.address_4 == ""

    @pytest.mark.parametrize("corpus,case", _ALL_RAW, ids=[c["id"] for _, c in _ALL_RAW])
    def test_fitting_addresses_identical_to_flag_off(self, corpus, case):
        """Flag on with an address that needs no BC rebalance produces the same
        A1/A2 as flag off -- including every backfilled case (the fragment-level
        backfill must match the old string-level one exactly)."""
        on = _on(case["address"])
        codes = [t["reason_code"] for t in on.representation["transforms"]]
        if "ADDRESS_BC_LENGTH_REBALANCE" in codes:
            pytest.skip("rebalanced by design; covered by TestRebalancedCorpusCases")
        off = _off(case["address"])
        assert (on.address_1, on.address_2) == (off.address_1, off.address_2)

    @pytest.mark.parametrize("corpus,case", _ALL_RAW, ids=[c["id"] for _, c in _ALL_RAW])
    def test_no_invariant_violation_and_limits_hold(self, corpus, case):
        on = _on(case["address"])
        assert all(f["reason_code"] != REASON_ADDRESS_INVARIANT_VIOLATION for f in on.findings)
        if on.representation["status"] != "BLOCK_SUBMISSION":
            assert len(on.address_1) <= 100
            assert len(on.address_2) <= 50


class TestRebalancedCorpusCases:
    """The three corpus addresses whose semantic Address 2 exceeds 50 chars
    (plan §11.3). Their SEMANTIC expectations in the eval YAMLs stay as they
    are; these are their BC representations."""

    def test_howrah_extra_localities(self):
        r = _on("3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY, "
                "CHANDIBAGAN, ANDUL, NATIBPUR, HOWRAH, West Bengal, 711302")
        assert r.address_1 == "3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK"
        assert r.address_2 == "MOHIARY, CHANDIBAGAN, ANDUL, NATIBPUR"
        assert (len(r.address_1), len(r.address_2)) == (58, 37)
        assert r.city == "Howrah" and r.state == "West Bengal" and r.pin_code == "711302"
        assert [f["reason_code"] for f in r.findings] == ["ADDRESS_BC_LENGTH_REBALANCE"]
        assert r.findings[0]["automation_class"] == "MANUAL_REVIEW"

    def test_rebalance_provenance_shape(self):
        """Plan §8: constraint, before/after, and the moved fragment keeps its
        semantic_role while its final_bc_field changes (case 10)."""
        r = _on("3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY CHANDIBAGAN, "
                "ANDUL, Natibpur, Howrah, West Bengal, 711302")
        t = r.representation["transforms"][0]
        assert t["reason_code"] == "ADDRESS_BC_LENGTH_REBALANCE"
        assert t["constraint"] == "BC_ADDRESS_2_MAX_LENGTH"
        assert t["constraint_value"] == 50
        assert t["profile"] == "bc22_in_vendorcard"
        assert t["original_address_1"] == "3RD FLOOR, PART A BLOCK B"
        assert t["original_address_2"] == ("SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY CHANDIBAGAN, "
                                           "ANDUL, Natibpur")
        assert t["final_address_1"] == "3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK"
        assert t["final_address_2"] == "MOHIARY CHANDIBAGAN, ANDUL, Natibpur"
        assert t["manual_review_required"] is True
        moved = [f for f in r.representation["final_fragments"] if f["index"] == 2][0]
        assert moved == {"index": 2, "semantic_role": ADDRESS_2,
                         "final_bc_field": ADDRESS_1, "moved_by": "ADDRESS_BC_LENGTH_REBALANCE"}


# ---------------------------------------------------------------------------
# named cases, end to end
# ---------------------------------------------------------------------------

class TestNamedCasesEndToEnd:
    def test_case1_normal_premise(self):
        r = _on("F-192, Phase 8B, Industrial Area, Sector 74, SAS Nagar, Punjab 160055")
        assert (r.address_1, r.address_2) == ("F-192", "Phase 8B, Industrial Area, Sector 74")
        assert r.representation["status"] == "AUTO_PASS"
        assert r.representation["transforms"] == []
        assert r.findings == []

    def test_case3b_mauli_baidwan_backfill_no_review(self):
        r = _on("Mauli Baidwan, Circular Road, Sector 80, SAS Nagar, Punjab 140308")
        assert (r.address_1, r.address_2) == ("Mauli Baidwan, Circular Road", "Sector 80")
        assert r.representation["status"] == "AUTO_FIX"
        t = r.representation["transforms"][0]
        assert t["reason_code"] == "ADDRESS_1_BACKFILLED"
        assert t["automation_class"] == "AUTO_FIX"
        assert t["original_address_1"] == ""
        assert t["original_address_2"] == "Mauli Baidwan, Circular Road, Sector 80"
        assert t["manual_review_required"] is False
        assert r.findings == []  # low segmenter confidence alone is not a review reason

    def test_case2_single_fragment_backfill(self):
        r = _on("Sector 67, SAS Nagar, Punjab 160062")
        assert (r.address_1, r.address_2) == ("Sector 67", "")
        assert r.representation["transforms"][0]["reason_code"] == "ADDRESS_1_BACKFILLED"

    def test_case4_geography_never_enters_a1_during_backfill(self):
        r = _on("Ward 07, Sector 67, SAS Nagar, Punjab, 160062, India")
        assert (r.address_1, r.address_2) == ("Ward 07", "Sector 67")
        combined = f"{r.address_1}, {r.address_2}"
        for geo in ("SAS Nagar", "Punjab", "160062", "India"):
            assert geo not in combined
        assert (r.city, r.state, r.pin_code, r.country) == ("SAS Nagar", "Punjab", "160062", "India")

    def test_case11_boundary_never_reopens(self):
        r = _on("Flat 402, Tower B, Sunrise Apartments, Block C, Sector 10")
        assert (r.address_1, r.address_2) == ("Flat 402, Tower B", "Sunrise Apartments, Block C, Sector 10")
        block_c = [f for f in r.representation["semantic"]["fragments"] if f["text"] == "Block C"][0]
        # the tier maps to Address 1 in isolation, but the boundary is final
        assert block_c["tier_role"] == ADDRESS_1
        assert block_c["semantic_role"] == ADDRESS_2

    def test_case12_leading_unknown_no_forward_scan(self):
        r = _on("Unknown Fragment, F-192, Phase 8B, Industrial Area, Sector 74, SAS Nagar, Punjab 160055")
        assert r.representation["semantic"]["semantic_boundary"] == 0
        assert (r.address_1, r.address_2) == ("Unknown Fragment, F-192", "Phase 8B, Industrial Area, Sector 74")
        f192 = [f for f in r.representation["final_fragments"] if f["index"] == 1][0]
        assert f192["moved_by"] == "ADDRESS_1_BACKFILLED"
        assert f192["semantic_role"] == ADDRESS_2

    def test_case13_a3_a4_always_empty(self):
        r = _on("3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY, "
                "CHANDIBAGAN, ANDUL, NATIBPUR, HOWRAH, West Bengal, 711302")
        assert r.address_3 == "" and r.address_4 == ""
        assert r.as_dict_full()["address_3"] == "" and r.as_dict_full()["address_4"] == ""

    def test_case14_explicit_country_extracted_default_only_when_absent(self):
        with_country = _on("9 LODHI ROAD, NEW DELHI, Delhi, 110003, INDIA")
        without = _on("9 LODHI ROAD, NEW DELHI, Delhi, 110003")
        assert with_country.country == "India"
        assert without.country == "India"  # default only because none was present
        assert "INDIA" not in with_country.address_1 + with_country.address_2
        # the layer never alters geography
        off = _off("9 LODHI ROAD, NEW DELHI, Delhi, 110003, INDIA")
        assert with_country.country == off.country


# ---------------------------------------------------------------------------
# BC-07 geography guard (defence in depth)
# ---------------------------------------------------------------------------

LIMITS = AddressLimits(address_1_max=100, address_2_max=50, separator=", ")


def _layout(*texts: str, boundary: int) -> SemanticLayout:
    return SemanticLayout(
        fragments=tuple(
            LayoutFragment(i, t, "unknown",
                           ADDRESS_1 if i < boundary else ADDRESS_2,
                           ADDRESS_1 if i < boundary else ADDRESS_2)
            for i, t in enumerate(texts)
        ),
        semantic_boundary=boundary,
    )


class TestGeographyGuard:
    def test_exact_city_in_address_line_blocks(self):
        d = represent_address(_layout("Plot 5", "Howrah", boundary=1), LIMITS,
                              geography={"city": "Howrah", "state": "West Bengal",
                                         "pin_code": "711302", "country": "India"})
        assert d.status.value == "BLOCK_SUBMISSION"
        assert d.findings[-1].reason_code == REASON_ADDRESS_INVARIANT_VIOLATION
        assert "BC-07" in d.findings[-1].detail

    def test_city_alias_in_address_line_blocks(self):
        d = represent_address(_layout("Plot 5", "Sahibzada Ajit Singh Nagar", boundary=1), LIMITS,
                              geography={"city": "S.A.S Nagar", "state": "Punjab",
                                         "pin_code": "160055", "country": "India"})
        assert "BC-07" in d.findings[-1].detail

    def test_pin_or_state_in_address_line_blocks(self):
        for leaked in ("160055", "punjab"):
            d = represent_address(_layout("Plot 5", leaked, boundary=1), LIMITS,
                                  geography={"city": "S.A.S Nagar", "state": "Punjab",
                                             "pin_code": "160055", "country": "India"})
            assert "BC-07" in d.findings[-1].detail, leaked

    def test_district_not_chosen_as_city_is_legitimate(self):
        """Tikamgarh is a real district but the city is Niwari -- a legitimate
        address fragment, not a leak (plan §4)."""
        d = represent_address(_layout("Ward No. 7", "Tikamgarh", boundary=1), LIMITS,
                              geography={"city": "Niwari", "state": "Madhya Pradesh",
                                         "pin_code": "472442", "country": "India"})
        assert d.findings == ()

    def test_no_geography_given_means_no_check(self):
        d = represent_address(_layout("Plot 5", "Howrah", boundary=1), LIMITS)
        assert d.findings == ()


# ---------------------------------------------------------------------------
# bc_expect corpus blocks (plan section 11.3)
# ---------------------------------------------------------------------------

def _line_cases():
    doc = yaml.safe_load((_EVAL_DIR / "address_line_cases.yaml").read_text(encoding="utf-8"))
    return doc["cases"]


class TestLineCasesBcExpect:
    """address_line_cases.yaml is segmenter-level input (`segments`). Its
    `expect` blocks stay semantic and are still asserted by
    test_address_segmenter.py; the three cases whose semantic Address 2
    exceeds BC's limit also carry a `bc_expect` block, checked here."""

    def test_exactly_the_three_over_limit_cases_have_bc_expect(self):
        with_bc = [c["id"] for c in _line_cases() if "bc_expect" in c]
        assert sorted(with_bc) == sorted([
            "degenerate_long_address_many_fragments",
            "localities_worked_example",
            "bc_floor_block_park_localities",
        ])

    @pytest.mark.parametrize("case", _line_cases(), ids=[c["id"] for c in _line_cases()])
    def test_bc_representation(self, case):
        from app.services.bc_target_profile import load_profile
        from app.services.extraction_pipeline.extract.address_representation import (
            layout_from_segmented,
        )
        from app.services.extraction_pipeline.extract.address_segmenter import segment_leftover

        limits = load_profile("bc22_in_vendorcard").address_limits()
        decision = represent_address(layout_from_segmented(segment_leftover(case["segments"])), limits)
        want = case.get("bc_expect")
        if want is None:
            # no BC change: the final lines equal the semantic expectation
            # after the step-5 backfill, and nothing needs review
            assert decision.status.value in ("AUTO_PASS", "AUTO_FIX"), case["id"]
            assert not decision.findings
        else:
            assert decision.address_1 == want["address_1"]
            assert decision.address_2 == want["address_2"]
            assert decision.status.value == want["status"]
            assert sorted(f.reason_code for f in decision.findings) == sorted(want["reason_codes"])


class TestEvalScorerCatchesBcMismatch:
    """The eval tool's bc scoring must actually fail on a wrong result."""

    def test_wrong_bc_lines_reported(self):
        from app.eval.eval_address import _score_bc

        case = {"expect": {"address_1": "A", "address_2": "B"},
                "bc_expect": {"address_1": "A, B", "address_2": "",
                              "status": "MANUAL_REVIEW",
                              "reason_codes": ["ADDRESS_BC_LENGTH_REBALANCE"]}}
        got = {"address_1": "A", "address_2": "B", "status": "AUTO_PASS", "reason_codes": []}
        problems = _score_bc(got, case)
        assert any("address_1" in p for p in problems)
        assert any("status" in p for p in problems)
        assert any("reason_codes" in p for p in problems)

    def test_unexpected_bc_change_reported_when_no_bc_expect(self):
        from app.eval.eval_address import _score_bc

        case = {"expect": {"address_1": "A", "address_2": "B"}}
        got = {"address_1": "A, B", "address_2": "", "status": "MANUAL_REVIEW",
               "reason_codes": ["ADDRESS_BC_LENGTH_REBALANCE"]}
        problems = _score_bc(got, case)
        assert any("must be unchanged" in p for p in problems)
        assert any("no bc_expect" in p for p in problems)

    def test_matching_result_has_no_problems(self):
        from app.eval.eval_address import _score_bc

        case = {"expect": {"address_1": "A", "address_2": "B"}}
        got = {"address_1": "A", "address_2": "B", "status": "AUTO_PASS", "reason_codes": []}
        assert _score_bc(got, case) == []
