"""The 29-case validation audit of docs/ADDRESS_SEGMENTATION_PLAN.md, as a
permanent regression suite (cases in app/eval/address_audit29_cases.yaml).

Every case runs through the real entry point with the BC layer on and is
checked for its own expectations plus the plan's universal invariants:
fragments preserved in order (no truncation), semantic_role never rewritten,
every moved fragment explained by a provenance entry, Address 3/4 empty, and
the payload carrying exactly the lines the layer produced.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config.config import settings
from app.models.model import Vendor
from app.services.bc_mapper import BcPayloadError, vendor_to_bc_payload
from app.services.bc_payload_gate import gate_vendor
from app.services.bc_target_profile import load_profile
from app.services.extraction_pipeline.extract.address_resolver import resolve_address_blob

_CASES_FILE = Path(__file__).resolve().parents[1] / "app" / "eval" / "address_audit29_cases.yaml"
CASES = yaml.safe_load(_CASES_FILE.read_text(encoding="utf-8"))["cases"]
PROFILE = load_profile("bc22_in_vendorcard")


def _run(case):
    r = resolve_address_blob(case["address"], multiline=True, bc_layer=True)
    assert r.representation is not None
    return r, r.representation


def _ids(cases):
    return [c["id"] for c in cases]


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_expectations(case):
    r, rep = _run(case)
    sem = rep["semantic"]

    if "semantic" in case:
        exp = case["semantic"]
        if "a1" in exp:
            assert sem["semantic_address_1"] == exp["a1"]
        if "a2" in exp:
            assert sem["semantic_address_2"] == exp["a2"]
        if "boundary" in exp:
            assert sem["semantic_boundary"] == exp["boundary"]
    if "final" in case:
        assert (r.address_1, r.address_2) == (case["final"]["a1"], case["final"]["a2"])
    for key, attr in (("city", "city"), ("state", "state"), ("pin", "pin_code"),
                      ("country", "country"), ("country_source", "country_source")):
        if key in case.get("geo", {}):
            assert (getattr(r, attr) or "") == case["geo"][key], key
    if "status" in case:
        assert rep["status"] == case["status"]
    if "transforms" in case:
        got = [[t["reason_code"], t["transformation"]] for t in rep["transforms"]]
        assert got == case["transforms"]
    if "findings" in case:
        assert sorted(f["reason_code"] for f in r.findings) == sorted(case["findings"])
    if "finding_detail" in case:
        assert any(case["finding_detail"] in f["detail"] for f in r.findings
                   if f["reason_code"] == "ADDRESS_OVERFLOW")
    if "moved" in case:
        moved = {f["index"]: f["moved_by"] for f in rep["final_fragments"] if f["moved_by"]}
        assert moved == {int(k): v for k, v in case["moved"].items()}


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_universal_invariants(case):
    r, rep = _run(case)
    sem_frags = rep["semantic"]["fragments"]
    texts = [f["text"] for f in sem_frags]

    # A3/A4 never populated (BC-12)
    assert r.address_3 == "" and r.address_4 == ""
    # no truncation, loss, duplication or reordering (BC-03..BC-06)
    final_texts = [p for line in (r.address_1, r.address_2) for p in line.split(", ") if p]
    assert final_texts == texts
    # semantic_role never rewritten (BC-09)
    roles = {f["index"]: f["semantic_role"] for f in sem_frags}
    assert all(f["semantic_role"] == roles[f["index"]] for f in rep["final_fragments"])
    # every moved fragment is named by a provenance entry (BC-08)
    named = {i for t in rep["transforms"] for i in t["moved_fragment_indices"]}
    assert {f["index"] for f in rep["final_fragments"] if f["moved_by"]} == named


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_payload_carries_exactly_the_layer_output(case, monkeypatch):
    monkeypatch.setattr(settings, "BC_PAYLOAD_GATE_ENABLED", True)
    r, _ = _run(case)
    vendor = Vendor(vendor_name="Audit Vendor Pvt Ltd", address_1=r.address_1,
                    address_2=r.address_2, city=r.city, state=r.state,
                    pin_code=r.pin_code, country=r.country)
    payload = vendor_to_bc_payload(vendor)
    assert payload["Address"] == r.address_1
    assert (payload.get("Address_2") or "") == r.address_2
    assert (payload.get("City") or "") == (r.city or "")
    assert (payload.get("County") or "") == (r.state or "")
    assert payload["Name"] == vendor.vendor_name


def test_c23_legacy_address_3_4_never_joined(monkeypatch):
    monkeypatch.setattr(settings, "BC_PAYLOAD_GATE_ENABLED", True)
    vendor = Vendor(vendor_name="Audit Vendor Pvt Ltd", address_1="F-192", address_2="Phase 8B",
                    address_3="Industrial Area", address_4="Sector 74", city="SAS Nagar",
                    state="Punjab", pin_code="160055", country="India")
    gate = gate_vendor(vendor, PROFILE)
    assert gate.blocked
    [f] = [f for f in gate.findings if f.field == "address_1"]
    assert (f.reason_code, f.automation_class, f.constraint) == (
        "ADDRESS_BC_LENGTH_REBALANCE", "MANUAL_REVIEW", "BC_NO_ADDRESS_3_4")
    assert f.proposal == {"address_1": "F-192", "address_2": "Phase 8B, Industrial Area, Sector 74"}
    with pytest.raises(BcPayloadError):
        vendor_to_bc_payload(vendor)
    # the stored record is untouched by the gate
    assert (vendor.address_2, vendor.address_3, vendor.address_4) == (
        "Phase 8B", "Industrial Area", "Sector 74")
