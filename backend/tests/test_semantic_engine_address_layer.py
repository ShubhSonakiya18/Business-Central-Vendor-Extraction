"""The BC address representation layer inside the extraction engine
(SemanticEngine._resolve_combined_address) -- plan step 7.

docs/ADDRESS_SEGMENTATION_PLAN.md §8 (provenance), §11.1 cases 13, 14, 17,
and the write-back defects in §0.1. Results are built by hand (no OCR) and
run through the real engine method with the shipped config.
"""

from __future__ import annotations

import pytest

from app.config.config import settings
from app.services.extraction_pipeline.config_loader import load_config
from app.services.extraction_pipeline.extract.semantic_engine import (
    DocumentClassifier,
    SemanticEngine,
)
from app.services.extraction_pipeline.models import ExtractionResult, FieldResult
from app.services.onboarding_mapper import _fields_needing_review

HOWRAH = ("3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY CHANDIBAGAN, "
          "ANDUL, Natibpur, Howrah, West Bengal, 711302")


@pytest.fixture(scope="module")
def engine():
    dictionary, rules = load_config()
    return SemanticEngine(dictionary, rules, DocumentClassifier())


@pytest.fixture
def layer_on(monkeypatch):
    monkeypatch.setattr(settings, "BC_ADDRESS_LAYER_ENABLED", True)


@pytest.fixture
def layer_off(monkeypatch):
    monkeypatch.setattr(settings, "BC_ADDRESS_LAYER_ENABLED", False)


def _result(**values) -> ExtractionResult:
    """An ExtractionResult with the given field values; country defaults to
    the config default the engine itself would have filled in step 1."""
    r = ExtractionResult()
    for key, val in values.items():
        r.fields[key] = FieldResult(key=key, value=val, confidence=0.9, source_document="gst_certificate")
    if "country" not in values:
        r.fields["country"] = FieldResult(key="country", value="India", confidence=1.0,
                                          source_document="config_default",
                                          notes=["filled_from_config_default"])
    return r


def _v(result, key):
    fr = result.fields.get(key)
    return (fr.value or "") if fr else ""


class TestFlagOffUnchanged:
    def test_no_provenance_no_new_keys(self, engine, layer_off):
        r = _result(address_1=HOWRAH)
        engine._resolve_combined_address(r)
        assert r.fields["address_1"].provenance == []
        assert all("automation_class" not in e for e in r.needs_review)
        # today's behaviour: the 69-char Address 2 is left as is
        assert _v(r, "address_2") == "SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY CHANDIBAGAN, ANDUL, Natibpur"

    def test_stale_address_3_survives_with_layer_off(self, engine, layer_off):
        """Documents the defect the layer fixes: without it, a stale matcher
        address_3 is left in place (plan §0.1 'Write-back')."""
        r = _result(address_1="F-192, Phase 8B, Industrial Area, Sector 74, SAS Nagar, Punjab 160055",
                    address_3="stale noise")
        engine._resolve_combined_address(r)
        assert _v(r, "address_3") == "stale noise"


class TestResolverPathLayerOn:
    def test_rebalance_written_back_with_provenance_and_one_finding(self, engine, layer_on):
        r = _result(address_1=HOWRAH)
        engine._resolve_combined_address(r)
        assert _v(r, "address_1") == "3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK"
        assert _v(r, "address_2") == "MOHIARY CHANDIBAGAN, ANDUL, Natibpur"
        assert (_v(r, "city"), _v(r, "state"), _v(r, "pin_code")) == ("Howrah", "West Bengal", "711302")

        prov = r.fields["address_1"].provenance
        assert prov[0]["layer"] == "semantic"
        assert prov[1]["reason_code"] == "ADDRESS_BC_LENGTH_REBALANCE"
        assert prov[-1]["layer"] == "final"

        flagged = [e for e in r.needs_review if e.get("automation_class")]
        assert len(flagged) == 1
        e = flagged[0]
        assert e["field"] == "address_1"
        assert e["reason_code"] == "ADDRESS_BC_LENGTH_REBALANCE"
        assert e["automation_class"] == "MANUAL_REVIEW"
        assert e["provenance_index"] == 1
        assert r.fields["address_1"].to_dict()["provenance"] == prov

    def test_backfill_is_logged_but_never_flagged(self, engine, layer_on):
        r = _result(address_1="Mauli Baidwan, Circular Road, Sector 80, SAS Nagar, Punjab 140308")
        engine._resolve_combined_address(r)
        assert (_v(r, "address_1"), _v(r, "address_2")) == ("Mauli Baidwan, Circular Road", "Sector 80")
        prov = r.fields["address_1"].provenance
        assert prov[1]["reason_code"] == "ADDRESS_1_BACKFILLED"
        assert prov[1]["automation_class"] == "AUTO_FIX"
        assert not [e for e in r.needs_review if e.get("automation_class")]
        assert any("bc_address_layer: AUTO_FIX" in n for n in r.fields["address_1"].notes)

    def test_case13_stale_address_2_3_4_cleared(self, engine, layer_on):
        r = _result(address_1="F-192, SAS Nagar, Punjab 160055",
                    address_2="stale a2", address_3="stale a3", address_4="stale a4")
        engine._resolve_combined_address(r)
        assert _v(r, "address_1") == "F-192"
        assert _v(r, "address_2") == ""
        assert _v(r, "address_3") == "" and _v(r, "address_4") == ""
        assert any("cleared: stale value" in n for n in r.fields["address_3"].notes)

    def test_fully_peeled_blob_not_left_in_address_1(self, engine, layer_on):
        r = _result(address_1="SAS Nagar, Punjab, 160055")
        engine._resolve_combined_address(r)
        assert _v(r, "address_1") == ""
        assert (_v(r, "city"), _v(r, "state"), _v(r, "pin_code")) == ("SAS Nagar", "Punjab", "160055")
        codes = [e.get("reason_code") for e in r.needs_review]
        assert "FIELD_NOT_FOUND" in codes

    def test_case14_extracted_country_replaces_default_only(self, engine, layer_on):
        r = _result(address_1="9 LODHI ROAD, NEW DELHI, Delhi, 110003, INDIA")
        engine._resolve_combined_address(r)
        c = r.fields["country"]
        assert c.value == "India"
        assert c.source_document == "address_resolver"
        assert "country_extracted_from_combined_address" in c.notes

    def test_case14_captioned_country_never_overwritten(self, engine, layer_on):
        r = _result(address_1="9 LODHI ROAD, NEW DELHI, Delhi, 110003, INDIA", country="Bharat")
        engine._resolve_combined_address(r)
        assert r.fields["country"].value == "Bharat"
        assert r.fields["country"].source_document == "gst_certificate"

    def test_default_country_kept_when_none_extracted(self, engine, layer_on):
        r = _result(address_1="9 LODHI ROAD, NEW DELHI, Delhi, 110003")
        engine._resolve_combined_address(r)
        assert r.fields["country"].source_document == "config_default"


class TestCaptionedPathLayerOn:
    """Case 17: the bail path (city, state and a solid PIN captioned
    separately) no longer skips the BC layer."""

    def _captioned(self, a1, a2="", a3="", a4=""):
        r = _result(address_1=a1, city="Howrah", state="West Bengal", pin_code="711302")
        for k, v in (("address_2", a2), ("address_3", a3), ("address_4", a4)):
            if v:
                r.fields[k] = FieldResult(key=k, value=v, confidence=0.9, source_document="udyam_certificate")
        return r

    def test_captioned_overlong_a2_is_rebalanced(self, engine, layer_on):
        r = self._captioned("UNIT 7, SRIJAN INDUSTRIAL LOGISTIC PARK",
                            "MOHIARY CHANDIBAGAN, ANDUL, NATIBPUR, NEAR RAILWAY STATION ROAD")
        assert len(_v(r, "address_2")) > 50
        engine._resolve_combined_address(r)
        assert len(_v(r, "address_2")) <= 50
        joined = f"{_v(r, 'address_1')}, {_v(r, 'address_2')}"
        assert joined == ("UNIT 7, SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY CHANDIBAGAN, "
                          "ANDUL, NATIBPUR, NEAR RAILWAY STATION ROAD")
        codes = [e.get("reason_code") for e in r.needs_review]
        assert "ADDRESS_BC_LENGTH_REBALANCE" in codes

    def test_captioned_legacy_a3_a4_folded_into_a2_never_dropped(self, engine, layer_on):
        r = self._captioned("F-192", "Phase 8B", "Sector 74", "Industrial Area")
        engine._resolve_combined_address(r)
        assert _v(r, "address_1") == "F-192"
        assert _v(r, "address_2") == "Phase 8B, Sector 74, Industrial Area"
        assert _v(r, "address_3") == "" and _v(r, "address_4") == ""

    def test_captioned_fitting_address_unchanged(self, engine, layer_on):
        r = self._captioned("F-192", "Phase 8B, Industrial Area")
        engine._resolve_combined_address(r)
        assert (_v(r, "address_1"), _v(r, "address_2")) == ("F-192", "Phase 8B, Industrial Area")
        assert r.fields["address_1"].provenance[-1]["status"] == "AUTO_PASS"
        assert not [e for e in r.needs_review if e.get("automation_class")]

    def test_captioned_path_skipped_with_layer_off(self, engine, layer_off):
        r = self._captioned("UNIT 7, SRIJAN INDUSTRIAL LOGISTIC PARK",
                            "MOHIARY CHANDIBAGAN, ANDUL, NATIBPUR, NEAR RAILWAY STATION ROAD")
        before = (_v(r, "address_1"), _v(r, "address_2"))
        engine._resolve_combined_address(r)
        assert (_v(r, "address_1"), _v(r, "address_2")) == before


class TestCustomerReviewListUnaffected:
    """The customer form joins address_1..4 into one billing_address, so the
    vendor layer's line-width findings must not put it up for review -- but
    findings that still matter for a joined address (empty address,
    geography leak) must."""

    @staticmethod
    def _with(*entries):
        r = ExtractionResult()
        r.needs_review = [dict(e) for e in entries]
        return r

    def test_line_width_codes_are_skipped(self):
        for code in ("ADDRESS_BC_LENGTH_REBALANCE", "ADDRESS_OVERFLOW"):
            r = self._with({"field": "address_1", "reason": code, "reason_code": code,
                            "automation_class": "MANUAL_REVIEW"})
            assert "billing_address" not in _fields_needing_review(r), code

    def test_other_address_findings_still_reported(self):
        for code in ("FIELD_NOT_FOUND", "ADDRESS_INVARIANT_VIOLATION"):
            r = self._with({"field": "address_1", "reason": code, "reason_code": code,
                            "automation_class": "MANUAL_REVIEW"})
            assert _fields_needing_review(r) == ["billing_address"], code

    def test_legacy_entries_without_reason_code_unchanged(self):
        r = self._with({"field": "address_2", "reason": "value_resolved_from_combined_address"})
        assert _fields_needing_review(r) == ["billing_address"]
