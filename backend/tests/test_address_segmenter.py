"""address_segmenter.py -- classification, boundary injection, grouping,
and the corpus/invariant sweep.

The corpus (app/eval/address_line_cases.yaml, 74 synthetic cases) is scored
here as exact-match PLUS a set of invariants that must hold on EVERY case,
not just the ones that happen to be exact-match-correct -- see TestInvariants.
Exact-match failures point at a specific wrong classification/threshold;
invariant failures point at a structural bug (lost/duplicated/reordered
content), which is the more serious class and is checked independently.
"""

from __future__ import annotations

import statistics
import time
from collections import Counter
from pathlib import Path

import pytest
import yaml

from app.services.extraction_pipeline.extract.address_segmenter import (
    Fragment,
    classify_fragment,
    inject_boundaries,
    segment_leftover,
    segmentation_keywords,
)
from app.services.extraction_pipeline.extract.address_segmenter import (
    _desegment_run,
    _desegment_segments,
    _desegment_vocab,
)

_CASES_FILE = Path(__file__).parent.parent / "app" / "eval" / "address_line_cases.yaml"


def _load_cases() -> list[dict]:
    doc = yaml.safe_load(_CASES_FILE.read_text(encoding="utf-8"))
    return doc["cases"]


_CASES = _load_cases()


def _tokens(s: str) -> list[str]:
    return [t.strip(",") for t in s.split()]


def _in_tokens(segments: list[str]) -> Counter:
    return Counter(t for s in segments for t in _tokens(s))


def _out_tokens(lines: list[str]) -> Counter:
    return Counter(t for line in lines for t in _tokens(line))


# ---------------------------------------------------------------------------
# sanity: the data file itself
# ---------------------------------------------------------------------------

def test_corpus_file_exists_and_has_at_least_60_cases():
    assert _CASES_FILE.is_file()
    assert len(_CASES) >= 60


def test_corpus_ids_are_unique():
    ids = [c["id"] for c in _CASES]
    assert len(ids) == len(set(ids))


def test_keywords_file_loads():
    kw = segmentation_keywords()
    assert kw, "segmentation_keywords.yaml failed to load -- check YAML syntax"
    assert "tiers" in kw


# ---------------------------------------------------------------------------
# TestClassification -- classify_fragment is a pure function of its text
# ---------------------------------------------------------------------------

class TestClassification:
    @pytest.mark.parametrize("text,expected_tier", [
        ("3RD FLOOR", "premises_unit"),
        ("PLOT 45", "premises_unit"),
        ("FLAT 302", "premises_unit"),
        ("GALA NO 12", "premises_unit"),
        ("PART A", "structural"),
        ("BLOCK B", "structural"),
        ("PHASE 2", "structural"),
        ("SILVER OAK COMPLEX", "building_name"),
        ("PALM RESIDENCY", "building_name"),
        ("MIDC INDUSTRIAL AREA", "estate_zone"),
        ("SIPCOT INDUSTRIAL COMPLEX", "estate_zone"),
        ("MG ROAD", "thoroughfare"),
        ("PARK STREET", "thoroughfare"),
        ("NEAR CITY HOSPITAL", "landmark"),
        ("SALT LAKE", "locality"),
        ("SECTOR 21", "locality"),
        ("VILL- RAMPUR", "village_po"),
        ("P.O. SITAPUR", "village_po"),
        ("TAL SHIRUR", "village_po"),
    ])
    def test_known_tiers(self, text, expected_tier):
        tier, level, conf, evidence = classify_fragment(text)
        assert tier == expected_tier, f"{text!r} classified {tier!r} not {expected_tier!r} ({evidence})"
        # >= not >: a fragment matching more than one tier's keywords (e.g.
        # "SIPCOT INDUSTRIAL COMPLEX" matches both estate_zone via an
        # any-phrase and building_name via tail:complex) is legitimately
        # capped at exactly _CONFLICT_CONFIDENCE_CAP (0.5) -- see
        # test_conflict_resolution_caps_confidence below for that mechanism
        # tested directly.
        assert conf >= 0.5

    def test_unknown_fragment_defaults_to_locality_tier_not_zero_confidence(self):
        """A keyword-less fragment is the NORMAL case for a locality name,
        not a failure -- see address_segmenter.py's module docstring."""
        tier, level, conf, evidence = classify_fragment("MOHIARY")
        assert tier == "unknown"
        # Asserted against the data, not a literal: `unknown` must sit at
        # whatever level segmentation_keywords.yaml gives `locality`, so a
        # renumbering of the tier levels stays a data-only change. (Hardcoding
        # 3 here made this test fail for the right answer when the taxonomy
        # gained a level to separate premises from the building they name.)
        kw = segmentation_keywords()
        assert level == kw["tiers"]["locality"]["level"]
        assert conf == pytest.approx(0.55)

    def test_bare_designator_is_premises_via_shape_rule(self):
        tier, level, conf, evidence = classify_fragment("31/1")
        assert tier == "premises_unit"
        assert level == 1

    def test_classification_is_pure_no_positional_dependence(self):
        """Classifying the same text twice, or classifying it as if it were
        at a different index, must give the identical result -- this is what
        makes grouping order-independent (see TestInvariants.test_ordering)."""
        a = classify_fragment("3RD FLOOR")
        b = classify_fragment("3RD FLOOR")
        assert a == b

    def test_conflict_resolution_caps_confidence(self):
        """A fragment matching more than one tier's keywords is resolved via
        priority and its confidence is capped -- never presented as fully
        confident when genuinely ambiguous."""
        tier, level, conf, evidence = classify_fragment("NEAR GIDC ROAD")
        assert conf <= 0.5
        assert evidence.startswith("ambiguous:")


# ---------------------------------------------------------------------------
# TestBoundaryInjection -- comma-less repair, guarded
# ---------------------------------------------------------------------------

class TestBoundaryInjection:
    def test_short_segment_untouched_via_segment_leftover(self):
        """The minimum-token-count gate (default 4) is enforced by the
        CALLER (segment_leftover), not by inject_boundaries() itself --
        inject_boundaries is a lower-level utility that will happily split a
        2-3 token string if a keyword is present (see
        test_inject_boundaries_itself_has_no_length_floor below). The real,
        guaranteed contract -- "short comma-less segments are left alone" --
        is only true end-to-end through segment_leftover(). The untouched
        fragment classifies `unknown` (whole-fragment classification looks at
        the first/last TOKEN, not an embedded word like "FLOOR"), which is
        ALWAYS ADDRESS_2 -- Address 1 is empty."""
        r = segment_leftover(["3RD FLOOR ABC"])
        assert r.lines == ["", "3RD FLOOR ABC"]

    def test_inject_boundaries_itself_has_no_length_floor(self):
        """Documents the actual (correct) contract of the low-level utility:
        it refuses only genuinely un-splittable input (<2 tokens), not
        anything below segment_leftover's 4-token policy threshold."""
        parts = inject_boundaries("3RD FLOOR ABC")
        assert len(parts) == 2
        assert " ".join(p[0] for p in parts).split() == "3RD FLOOR ABC".split()

    def test_no_keywords_stays_whole(self):
        """A comma-less run with zero role keywords must never be split on
        token count or capitalisation alone."""
        parts = inject_boundaries("MOHIARY CHANDIBAGAN ANDUL NATIBPUR")
        assert parts == [("MOHIARY CHANDIBAGAN ANDUL NATIBPUR", False)]

    def test_park_street_not_shredded(self):
        """PARK (estate_zone tail) followed immediately by STREET
        (thoroughfare tail) is a tail-tail compound -- the adjacency guard
        must keep it as one fragment, not split a proper name apart."""
        parts = inject_boundaries("SHOP NO 5 GREEN PARK EXTENSION NEW DELHI")
        texts = [p[0] for p in parts]
        assert not any(t.strip() == "GREEN PARK" for t in texts), texts
        joined = " ".join(texts)
        assert "GREEN PARK EXTENSION" in joined

    def test_plot_no_not_split_at_connector(self):
        parts = inject_boundaries("PLOT NO 4 SILVER OAK COMPLEX ANDHERI")
        texts = [p[0] for p in parts]
        assert texts[0].strip() in ("PLOT NO 4",)

    def test_injection_purity_ordered_tokens_preserved(self):
        """I9: injection may only insert boundaries, never edit, drop,
        reorder, or normalise text."""
        original = "UNIT 7 MIDC INDUSTRIAL AREA TALOJA PANVEL"
        parts = inject_boundaries(original)
        reassembled = " ".join(p[0] for p in parts)
        assert reassembled.split() == original.split()

    @pytest.mark.parametrize("text", [
        "3RD FLOOR PART A BLOCK B SRIJAN INDUSTRIAL PARK ANDUL",
        "FLAT 4 LAKE GARDENS KOLKATA SOUTH",
        "PLOT 45 GIDC PHASE 2 VATVA",
    ])
    def test_injection_purity_sweep(self, text):
        parts = inject_boundaries(text)
        reassembled = " ".join(p[0] for p in parts)
        assert reassembled.split() == text.split()


# ---------------------------------------------------------------------------
# TestGrouping -- 1/2/3/4-line outcomes and the conservative fallback
# ---------------------------------------------------------------------------

class TestGrouping:
    def test_single_group_all_premises(self):
        r = segment_leftover(["UNIT 302", "BLOCK B", "3RD FLOOR"])
        assert len(r.lines) == 1
        assert r.lines[0] == "UNIT 302, BLOCK B, 3RD FLOOR"

    def test_two_lines_road_then_locality(self):
        r = segment_leftover(["14 EXAMPLE ROAD", "KORAMANGALA"])
        assert r.lines == ["14 EXAMPLE ROAD", "KORAMANGALA"]

    def test_does_not_manufacture_a_second_line(self):
        r = segment_leftover(["UNIT 302"])
        assert r.lines == ["UNIT 302"]
        assert len(r.lines) == 1

    def test_worked_example_exact(self):
        """Address 1 = the initial contiguous premises run (floor + block);
        the boundary is FINAL the moment the estate name (non-premises) is
        reached -- everything after it, including the trailing locality run,
        joins Address 2 as one string."""
        segs = ["3RD FLOOR", "PART A BLOCK B", "SRIJAN INDUSTRIAL LOGISTIC PARK",
                "MOHIARY", "CHANDIBAGAN", "ANDUL", "NATIBPUR"]
        r = segment_leftover(segs)
        assert r.lines == [
            "3RD FLOOR, PART A BLOCK B",
            "SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY, CHANDIBAGAN, ANDUL, NATIBPUR",
        ]
        assert r.confidence == "high"

    def test_village_po_keyword_bypasses_tail_split_threshold(self):
        """Neither fragment is premises_unit/structural-tier (SILVER OAK is
        building_name; VILL- SAKINAKA is village_po), so Address 1 is empty
        and both join Address 2 as one string."""
        r = segment_leftover(["SILVER OAK", "VILL- SAKINAKA"])
        assert r.lines == ["", "SILVER OAK, VILL- SAKINAKA"]

    def test_empty_leftover(self):
        r = segment_leftover([])
        assert r.lines == []
        assert r.confidence == "low"


class TestSemanticBoundaryField:
    """SegmentedAddress.semantic_boundary / .fallback_applied (additive
    fields for the BC address representation layer -- see
    docs/ADDRESS_SEGMENTATION_PLAN.md §2/§4/§12). Purely observational: they
    must reflect what _split_by_role already decided, without changing any
    existing output (lines/groups/confidence/notes)."""

    def test_normal_premise_run_reports_its_length(self):
        r = segment_leftover(["UNIT 302", "BLOCK B", "SRIJAN PARK"])
        assert r.semantic_boundary == 2
        assert r.fallback_applied is False

    def test_no_premise_at_all_boundary_is_zero_no_fallback(self):
        r = segment_leftover(["SILVER OAK", "VILL- SAKINAKA"])
        assert r.semantic_boundary == 0
        assert r.fallback_applied is False
        assert r.lines[0] == ""  # Address 1 stayed empty -- no fallback fired

    def test_leading_thoroughfare_fallback_boundary_is_zero_not_one(self):
        """When the thoroughfare fallback fires, semantic_boundary is 0 (no
        ADDRESS_1-role run existed) even though the FINAL group boundary
        (len(groups[0])) is 1. These two numbers are deliberately different
        -- semantic_boundary is the pre-fallback truth."""
        r = segment_leftover(["MG ROAD", "SECTOR 12", "PHASE 3"])
        assert r.fallback_applied is True
        assert r.semantic_boundary == 0
        assert len(r.groups[0]) == 1  # the fallback's own result

    def test_empty_leftover_boundary_is_zero(self):
        r = segment_leftover([])
        assert r.semantic_boundary == 0
        assert r.fallback_applied is False


class TestTailSplitConservatism:
    """The old locality-tail-split heuristic is REMOVED under the Address
    1/Address 2 role model -- there is no third line to peel a fragment onto.
    These tests now confirm Address 2 joining has no length limit: any number
    of non-premises fragments join ONE Address 2 string, regardless of count
    or whether premises content precedes them."""

    def test_two_localities_join_address_2(self):
        r = segment_leftover(["KORAMANGALA", "INDIRANAGAR"])
        assert r.lines == ["", "KORAMANGALA, INDIRANAGAR"]

    def test_three_localities_join_address_2(self):
        r = segment_leftover(["MOHIARY", "CHANDIBAGAN", "ANDUL"])
        assert r.lines == ["", "MOHIARY, CHANDIBAGAN, ANDUL"]

    def test_four_localities_with_no_other_content_join_address_2(self):
        """Four co-equal locality names and NOTHING else all join ONE
        Address 2 string -- no per-count heuristic exists to peel one off."""
        r = segment_leftover(["ANDHERI", "VILE PARLE", "SANTACRUZ", "BANDRA"])
        assert r.lines == ["", "ANDHERI, VILE PARLE, SANTACRUZ, BANDRA"]

    def test_five_localities_with_no_other_content_join_address_2(self):
        r = segment_leftover(["A", "B", "C", "D", "E"])
        assert r.lines == ["", "A, B, C, D, E"]

    def test_four_localities_join_address_2_even_when_preceded_by_premises(self):
        """The same 4-locality run joins Address 2 together with the estate
        name that precedes it, regardless of how much non-premises content
        exists -- there is no length-based trigger to split it further."""
        r = segment_leftover([
            "3RD FLOOR", "PART A BLOCK B", "SRIJAN INDUSTRIAL LOGISTIC PARK",
            "MOHIARY", "CHANDIBAGAN", "ANDUL", "NATIBPUR",
        ])
        assert len(r.lines) == 2
        assert r.lines[1] == "SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY, CHANDIBAGAN, ANDUL, NATIBPUR"


# ---------------------------------------------------------------------------
# TestConfidence
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_premises_then_locality_run_is_high_confidence(self):
        """A clean premises run followed by a clean, fully-classified
        non-premises run is high confidence -- there is no tail-split
        mechanism left to cap it at medium."""
        r = segment_leftover([
            "3RD FLOOR", "PART A BLOCK B", "SRIJAN INDUSTRIAL LOGISTIC PARK",
            "MOHIARY", "CHANDIBAGAN", "ANDUL", "NATIBPUR",
        ])
        assert r.confidence == "high"

    def test_injected_boundary_caps_confidence_at_medium(self):
        r = segment_leftover(["3RD FLOOR PART A BLOCK B SRIJAN INDUSTRIAL PARK ANDUL"])
        assert "boundaries_inferred" in r.notes
        assert r.confidence in ("medium", "low")

    def test_low_confidence_caps_to_two_lines(self):
        """I6: whatever produced a `low` confidence result, the line count
        must not exceed 2."""
        for c in _CASES:
            r = segment_leftover(c["segments"])
            if r.confidence == "low":
                assert len(r.lines) <= 2, c["id"]


# ---------------------------------------------------------------------------
# TestDesegment -- OCR word re-segmentation (_desegment_run)
# ---------------------------------------------------------------------------
# The de-glue layer replaced ~340 lines of hand-ordered splitters + hardcoded
# frozensets with one scored DP word-break (address_segmenter.py section
# comment). These tests are written from GENERAL principles of Indian address
# structure, not from the 20 gu_* evaluation fixtures:
#   * a run splits only when a properly-positioned STRONG anchor (a >=4-char
#     head/tail keyword, or a designator shape) pays for the cut against the
#     Occam penalty;
#   * a proper noun with no such anchor -- including one that merely CONTAINS
#     a keyword substring ("mahal" in MAHALAXMI, "gram" in GURUGRAM, "hall" in
#     BOMMANAHALLI) -- is returned whole;
#   * two same-role keywords are never cut apart ("PARK STREET", "NAGAR
#     ROAD"), mirroring inject_boundaries();
#   * output is a pure re-spacing: same characters, same order (I1/I3).

class TestDesegment:
    V = None

    @classmethod
    def setup_class(cls):
        cls.V = _desegment_vocab()

    def run(self, s):
        return _desegment_run(s, self.V)

    # -- proper nouns that embed a keyword substring stay WHOLE ---------------
    @pytest.mark.parametrize("name", [
        "MAHALAXMI",        # contains tail kw "mahal"
        "GURUGRAM",         # contains locality tail "gram"
        "KANPUR",           # contains locality tail "pur"
        "SRILAKSHMI",       # no keyword, no clean split
        "NEWBARRACKPORE",   # contains "pore"~"pur"? still no confident split
        "KORAMANGALA",      # contains premises head "gala"
        "SIKANDERPUR",
        "BOMMANAHALLI",     # contains building tail "hall", locality tail "halli"
        "SINGASANDRA",
        "GARVEBHAVIPALYA",
        "CHANDIBAGAN",
        "NATIBPUR",
        "UDYOGVIHAR",       # "udyog vihar" is one estate/locality name
    ])
    def test_embedded_keyword_name_stays_whole(self, name):
        assert self.run(name) == [name]

    # -- adversarial keyword traps: the OBVIOUS split is WRONG ---------------
    @pytest.mark.parametrize("glued", [
        "PARKSTREET",          # PARK|STREET -> two tail kws, guarded
        "NAGARROAD",           # NAGAR|ROAD  -> two tail kws, guarded
        "LAKEGARDENS",         # LAKE|GARDENS
        "TOWERROAD",           # tower is head&tail, road tail -> share tail role
        "GREENPARKEXTENSION",  # PARK & EXTENSION both tail
        "MAINROAD",
        "CROSSROAD",
        "INDUSTRIALAREAROAD",   # 'industrial area' + 'road' -- proper-noun-ish
    ])
    def test_adversarial_keyword_trap_stays_whole(self, glued):
        assert self.run(glued) == [glued]

    # -- runs that SHOULD split: real component boundary --------------------
    @pytest.mark.parametrize("glued,n_pieces", [
        ("2NDFLOOR", 2),
        ("3RDFLOOR", 2),
        ("BLOCKB", 2),
        ("TOWERC", 2),
        ("SECTOR18", 2),
        ("BUILDING4", 2),
        ("FLATNO302", 3),          # FLAT | NO (connector) | 302
        ("PLOTNO47", 3),
        ("TALOJAROAD", 2),
        ("HOSURROAD", 2),
        ("SERVICEROAD", 2),
        ("PARTABLOCKB", 4),
        ("2NDFLOORPARTA", 4),
        ("ELECTRONICCITYROAD", 3),
        ("TALOJAINDUSTRIALAREA", 3),
        ("BOMMANAHALLIINDUSTRIALZONE", 3),
        ("SRIJANINDUSTRIALLOGISTICPARK", 4),
        ("GREENFIELDBUSINESSPARK", 2),
    ])
    def test_real_boundary_splits(self, glued, n_pieces):
        assert len(self.run(glued)) == n_pieces

    def test_split_is_pure_respacing(self):
        """I1/I3: the only change a split makes is inserting spaces -- same
        characters, same order."""
        for glued in ["2NDFLOORPARTA", "SRIJANINDUSTRIALLOGISTICPARK",
                      "TALOJAINDUSTRIALAREA", "SECTOR18", "PARTABLOCKB"]:
            pieces = self.run(glued)
            assert "".join(pieces).casefold() == glued.casefold(), glued

    def test_word_is_never_corrupted(self):
        """A plural/suffix must not be peeled off a real word (TOWERS is not
        TOWER + S)."""
        for w in ["TOWERS", "GARDENS", "WORKS", "MANSIONS", "MILLS", "HEIGHTS"]:
            assert self.run(w) == [w]

    def test_already_spaced_input_untouched(self):
        assert _desegment_segments(["2ND FLOOR", "PART A BLOCK B", "MOHIARY"]) == \
            ["2ND FLOOR", "PART A BLOCK B", "MOHIARY"]

    def test_short_run_untouched(self):
        # below _DESEG_MIN_RUN (6): a 5-char glued token is rare and usually
        # survives OCR as two tokens anyway -- not worth the false-split risk.
        for w in ["WINGC", "WINGD", "NO5", "A1"]:
            assert self.run(w) == [w]

    def test_very_long_run_left_whole(self):
        blob = "SRIJANINDUSTRIALLOGISTICPARKGREENFIELDBUSINESSTOWERCOMPLEX"
        assert self.run(blob) == [blob]

    def test_end_to_end_glued_address_segments(self):
        """A fully space-stripped combined address still produces the worked
        example's Address 1/Address 2 split once re-spaced."""
        segs = ["3RDFLOOR", "PARTABLOCKB", "SRIJANINDUSTRIALLOGISTICPARK",
                "MOHIARY", "CHANDIBAGAN", "ANDUL", "NATIBPUR"]
        r = segment_leftover(segs)
        assert "ocr_deglue_applied" in r.notes
        assert r.lines == [
            "3RD FLOOR, PART A BLOCK B",
            "SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY, CHANDIBAGAN, ANDUL, NATIBPUR",
        ]

    def test_deterministic(self):
        for w in ["TALOJAINDUSTRIALAREA", "MAHALAXMI", "2NDFLOORPARTA"]:
            assert self.run(w) == self.run(w) == self.run(w)


# ---------------------------------------------------------------------------
# TestInvariants -- asserted over EVERY corpus case (the real payoff)
# ---------------------------------------------------------------------------

class TestInvariants:
    @pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
    def test_exact_match(self, case):
        r = segment_leftover(case["segments"])
        got = {
            "address_1": r.get(1), "address_2": r.get(2),
            "address_3": r.get(3), "address_4": r.get(4),
        }
        assert got == case["expect"], case.get("note", "")

    @pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
    def test_i1_no_loss_no_duplication(self, case):
        r = segment_leftover(case["segments"])
        assert _out_tokens(r.lines) == _in_tokens(case["segments"])

    @pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
    def test_i2_exact_partition(self, case):
        r = segment_leftover(case["segments"])
        all_indices = sorted(f.index for g in r.groups for f in g)
        assert all_indices == list(range(len(r.fragments)))

    @pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
    def test_i3_source_order_preserved(self, case):
        """Concatenating the groups in order reproduces the input fragment
        sequence exactly -- fragments are never reordered relative to the
        source, only grouped."""
        r = segment_leftover(case["segments"])
        in_all = [t for s in case["segments"] for t in _tokens(s)]
        out_all = [t for line in r.lines for t in _tokens(line)]
        assert out_all == in_all, case["id"]

    @pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
    def test_i6_confidence_caps_line_count(self, case):
        r = segment_leftover(case["segments"])
        cap = {"high": 4, "medium": 3, "low": 2}[r.confidence]
        assert len(r.lines) <= cap, case["id"]

    @pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
    def test_i7_no_holes(self, case):
        r = segment_leftover(case["segments"])
        lines = (r.lines + ["", "", "", ""])[:4]
        if lines[2]:
            assert lines[1], f"{case['id']}: address_3 set but address_2 empty"
        if lines[3]:
            assert lines[2], f"{case['id']}: address_4 set but address_3 empty"

    @pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
    def test_i8_determinism(self, case):
        r1 = segment_leftover(case["segments"])
        r2 = segment_leftover(case["segments"])
        assert r1.lines == r2.lines
        assert r1.confidence == r2.confidence

    def test_i5_semantic_equivalence_under_reordering(self):
        """Two orderings of the same premises components must group
        identically (same per-line multiset), each rendered in its OWN
        source order -- NOT forced to character-identical output."""
        forward = segment_leftover(["3RD FLOOR", "BLOCK B", "UNIT 302"])
        reversed_ = segment_leftover(["UNIT 302", "BLOCK B", "3RD FLOOR"])

        def line_sets(r):
            return [frozenset(_tokens(l)) for l in r.lines]

        # collapse multi-word tokens for a fair set comparison
        def token_sets(r):
            return [frozenset(t for line in [l] for t in line.split(", ")) for l in r.lines]

        assert len(forward.lines) == len(reversed_.lines) == 1
        assert set(_tokens(forward.lines[0])) == set(_tokens(reversed_.lines[0]))

    def test_i9_no_out_of_order_reassembly_across_all_cases(self):
        """Address components are never silently reordered to a 'canonical'
        sequence -- explicitly covers the out-of-order reorder_pair_*_reversed
        cases in the corpus."""
        reversed_cases = [c for c in _CASES if c["id"].endswith("_reversed")]
        assert len(reversed_cases) >= 3
        for c in reversed_cases:
            r = segment_leftover(c["segments"])
            in_all = [t for s in c["segments"] for t in _tokens(s)]
            out_all = [t for line in r.lines for t in _tokens(line)]
            assert out_all == in_all


# ---------------------------------------------------------------------------
# TestBackCompat -- the multiline flag must not change legacy behaviour
# ---------------------------------------------------------------------------

class TestBackCompat:
    def test_resolve_address_blob_default_is_multiline_false(self):
        from app.services.extraction_pipeline.extract.address_resolver import (
            ResolvedAddress,
            resolve_address_blob,
        )

        addr = "3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY, CHANDIBAGAN, ANDUL, NATIBPUR, HOWRAH, West Bengal, 711302"
        r = resolve_address_blob(addr)
        assert r.address_2 == ""
        assert r.address_3 == ""
        assert r.address_4 == ""
        assert "MOHIARY" in r.address_1

    def test_as_dict_still_has_exactly_five_keys(self):
        from app.services.extraction_pipeline.extract.address_resolver import (
            resolve_address_blob,
        )

        r = resolve_address_blob("14 EXAMPLE ROAD, KORAMANGALA, BENGALURU, Karnataka, 560095")
        d = r.as_dict()
        assert set(d.keys()) == {"address_1", "address_2", "city", "state", "pin_code"}

    def test_as_dict_full_adds_address_3_and_4(self):
        """address_3/address_4 remain on the dict for interface-shape
        back-compat, always empty in this workflow -- never populated."""
        from app.services.extraction_pipeline.extract.address_resolver import (
            resolve_address_blob,
        )

        r = resolve_address_blob(
            "3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY, CHANDIBAGAN, ANDUL, NATIBPUR, HOWRAH, West Bengal, 711302",
            multiline=True,
        )
        d = r.as_dict_full()
        assert set(d.keys()) == {"address_1", "address_2", "address_3", "address_4", "city", "state", "pin_code", "country"}
        assert d["address_3"] == ""
        assert d["address_4"] == ""

    def test_multiline_true_reproduces_worked_example_end_to_end(self):
        """The task brief's own worked example (docs/ADDRESS_SEGMENTATION_
        RESEARCH.md-adjacent redesign): Address 1 is the initial contiguous
        premises run; the boundary is final the moment the estate name is
        reached, so the trailing locality run joins Address 2 as one string.
        address_3/address_4 are always empty in this workflow."""
        from app.services.extraction_pipeline.extract.address_resolver import (
            resolve_address_blob,
        )

        r = resolve_address_blob(
            "3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY, CHANDIBAGAN, ANDUL, NATIBPUR, HOWRAH, West Bengal, 711302",
            multiline=True,
        )
        assert r.address_1 == "3RD FLOOR, PART A BLOCK B"
        assert r.address_2 == "SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY, CHANDIBAGAN, ANDUL, NATIBPUR"
        assert r.address_3 == ""
        assert r.address_4 == ""
        assert r.city == "Howrah"
        assert r.state == "West Bengal"
        assert r.pin_code == "711302"

    def test_multiline_customer_billing_join_is_byte_identical_to_legacy(self):
        """The customer path's own join (address_1..4 with ', ') must
        reproduce the LEGACY single-address_1 string exactly, regardless of
        how many lines the segmenter produced -- this is what makes the
        multiline switch safe for the customer path without touching it."""
        from app.services.extraction_pipeline.extract.address_resolver import (
            resolve_address_blob,
        )

        addr = "3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY, CHANDIBAGAN, ANDUL, NATIBPUR, HOWRAH, West Bengal, 711302"
        legacy = resolve_address_blob(addr)
        multi = resolve_address_blob(addr, multiline=True)

        joined = ", ".join(
            p for p in (multi.address_1, multi.address_2, multi.address_3, multi.address_4) if p
        )
        assert joined == legacy.address_1


# ---------------------------------------------------------------------------
# TestAddress1FallbackPopulation -- presentation/business fallback
# ---------------------------------------------------------------------------
# _fallback_populate_address_1() is NOT semantic re-segmentation. The primary
# segmentation (segment_leftover) has already decided Address 1 vs Address 2
# on semantic grounds by the time this runs; this fallback only fires when
# that decision left Address 1 completely empty while Address 2 has content
# -- an empty Address 1 looks incomplete in vendor output, while an empty
# Address 2 is fully acceptable. See address_resolver.py's docstring on the
# function itself for the full rule.

class TestAddress1FallbackPopulation:
    @staticmethod
    def _fb():
        from app.services.extraction_pipeline.extract.address_resolver import (
            _fallback_populate_address_1,
        )
        return _fallback_populate_address_1

    def test_business_requirement_address_1_never_empty_when_address_2_has_content(self):
        """The requirement this whole fallback exists for, stated directly as
        one test: Address 1 must never remain empty when Address 2 contains
        remaining content."""
        fb = self._fb()
        assert fb("", "Sector 67") == ("Sector 67", "")
        assert fb("", "Ward 07, Sector 67") == ("Ward 07", "Sector 67")
        assert fb("", "Ward 07, Sector 67, Industrial Area") == ("Ward 07, Sector 67", "Industrial Area")

    def test_case1_single_fragment_moves_entirely_address_2_becomes_empty(self):
        fb = self._fb()
        assert fb("", "Sector 67") == ("Sector 67", "")

    def test_case2_two_fragments_moves_only_the_first(self):
        fb = self._fb()
        assert fb("", "Ward 07, Sector 67") == ("Ward 07", "Sector 67")

    def test_case3_three_fragments_moves_first_two(self):
        fb = self._fb()
        assert fb("", "Ward 07, Sector 67, Industrial Area") == ("Ward 07, Sector 67", "Industrial Area")

    def test_case4_four_fragments_moves_first_two_preserving_order(self):
        fb = self._fb()
        assert fb("", "A, B, C, D") == ("A, B", "C, D")

    def test_case5_real_gst_registry_example(self):
        fb = self._fb()
        got = fb(
            "",
            "WARD NO 07, JHANSI SERVICE ROAD NIWARI TIGELA, "
            "JHANSI SERVICE ROAD NIWARI TIGELA, Niwari JHANSI SERVICE ROAD NIWARI TIGELA",
        )
        assert got == (
            "WARD NO 07, JHANSI SERVICE ROAD NIWARI TIGELA",
            "JHANSI SERVICE ROAD NIWARI TIGELA, Niwari JHANSI SERVICE ROAD NIWARI TIGELA",
        )

    def test_case6_existing_address_1_is_never_touched(self):
        fb = self._fb()
        assert fb("F-192", "Phase 8B, Industrial Area, Sector 74") == (
            "F-192", "Phase 8B, Industrial Area, Sector 74",
        )

    def test_case7_existing_multi_fragment_address_1_is_never_touched(self):
        fb = self._fb()
        assert fb("Flat 402, Tower B", "Sunrise Apartments, Block C, Sector 10") == (
            "Flat 402, Tower B", "Sunrise Apartments, Block C, Sector 10",
        )

    def test_empty_address_2_is_a_noop_not_an_invented_value(self):
        fb = self._fb()
        assert fb("", "") == ("", "")
        assert fb("", "   ") == ("", "   ")

    def test_no_fragment_is_dropped_or_duplicated(self):
        """Every original comma-delimited fragment appears exactly once
        across the two outputs, regardless of how many fragments there are."""
        fb = self._fb()
        for a2 in ("Sector 67", "Ward 07, Sector 67", "Ward 07, Sector 67, Industrial Area",
                   "A, B, C, D", "A, B, C, D, E, F"):
            a1_out, a2_out = fb("", a2)
            before = [f.strip() for f in a2.split(",") if f.strip()]
            after = [f.strip() for f in a1_out.split(",") if f.strip()] + \
                    [f.strip() for f in a2_out.split(",") if f.strip()]
            assert before == after, f"fragment set/order changed for {a2!r}: {before} != {after}"

    def test_source_order_never_changes(self):
        """Only a contiguous PREFIX may move -- never a reordering."""
        fb = self._fb()
        a1_out, a2_out = fb("", "A, B, C, D")
        assert a1_out == "A, B"
        assert a2_out == "C, D"
        # explicitly NOT "B" / "A, C, D" or "C" / "A, B, D"
        assert a1_out != "B"
        assert a1_out != "C"

    def test_end_to_end_through_resolve_address_blob(self):
        """The fallback is wired into the real entry point, not just tested
        in isolation -- and City/State/Country/PIN/address_3/address_4 are
        untouched by it."""
        from app.services.extraction_pipeline.extract.address_resolver import (
            resolve_address_blob,
        )

        addr = (
            "WARD NO 07, JHANSI SERVICE ROAD NIWARI TIGELA, "
            "JHANSI SERVICE ROAD NIWARI TIGELA, Niwari JHANSI SERVICE ROAD NIWARI TIGELA, 472442"
        )
        r = resolve_address_blob(addr, multiline=True)
        assert r.address_1 == "WARD NO 07, JHANSI SERVICE ROAD NIWARI TIGELA"
        assert r.address_2 == "JHANSI SERVICE ROAD NIWARI TIGELA, Niwari JHANSI SERVICE ROAD NIWARI TIGELA"
        assert r.address_3 == ""
        assert r.address_4 == ""
        assert r.city == "Niwari"
        assert r.state == "Madhya Pradesh"
        assert r.pin_code == "472442"

    def test_end_to_end_does_not_fire_when_address_1_already_populated(self):
        from app.services.extraction_pipeline.extract.address_resolver import (
            resolve_address_blob,
        )

        r = resolve_address_blob(
            "F-192, Phase 8B, Industrial Area, Sector 74, SAS Nagar, Punjab 160055",
            multiline=True,
        )
        assert r.address_1 == "F-192"
        assert r.address_2 == "Phase 8B, Industrial Area, Sector 74"


# ---------------------------------------------------------------------------
# TestPerformance
# ---------------------------------------------------------------------------

class TestPerformance:
    def test_sub_millisecond_median(self):
        segment_leftover(["WARMUP"])  # populate the lru_cache before timing
        samples = []
        for _ in range(20):
            for case in _CASES:
                t0 = time.perf_counter()
                segment_leftover(case["segments"])
                samples.append(time.perf_counter() - t0)
        median = statistics.median(samples)
        samples.sort()
        p95 = samples[int(len(samples) * 0.95)]
        assert median < 0.001, f"median {median * 1000:.3f}ms exceeds 1ms budget"
        assert p95 < 0.003, f"p95 {p95 * 1000:.3f}ms exceeds 3ms budget"

    def test_keyword_file_parsed_once(self):
        segment_leftover(["12 MG ROAD"])
        info_before = segmentation_keywords.cache_info()
        for _ in range(50):
            segment_leftover(["12 MG ROAD", "KORAMANGALA"])
        info_after = segmentation_keywords.cache_info()
        assert info_after.misses == info_before.misses, "keyword YAML re-parsed on a call it should have cached"
