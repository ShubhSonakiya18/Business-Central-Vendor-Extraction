"""Stage-11 BC payload gate and the one-click address confirmation
(docs/ADDRESS_SEGMENTATION_PLAN.md steps 10-12; invariants BC-10, BC-11,
BC-12; case 18; T-GATE-01, T-ADR-07, T-MD-01).

Exercised through the real HTTP API with the test database.
"""

from __future__ import annotations

import pytest

from app.config.config import settings

BASE = {
    "vendor_name": "Example Industries Pvt Ltd",
    "address_1": "UNIT 7",
    "address_2": "SRIJAN INDUSTRIAL LOGISTIC PARK",
    "city": "Howrah",
    "state": "West Bengal",
    "country": "India",
    "pin_code": "711302",
}

LONG_A2 = "SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY CHANDIBAGAN, ANDUL, Natibpur"  # 69 chars


@pytest.fixture
def bc_on(monkeypatch):
    monkeypatch.setattr(settings, "BC_ENABLED", True)
    monkeypatch.setattr(settings, "BC_PAYLOAD_GATE_ENABLED", True)


@pytest.fixture
def gate_off(monkeypatch):
    monkeypatch.setattr(settings, "BC_ENABLED", True)
    monkeypatch.setattr(settings, "BC_PAYLOAD_GATE_ENABLED", False)


def _create(auth_client, **overrides) -> int:
    body = {**BASE, **overrides}
    r = auth_client.post("/vendors", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _payload(auth_client, vid):
    return auth_client.get(f"/business-central/vendors/{vid}/payload")


def _confirm(auth_client, vid, a1, a2):
    return auth_client.post(f"/business-central/vendors/{vid}/address-review/confirm",
                            json={"address_1": a1, "address_2": a2})


def _codes(resp):
    return [f["reason_code"] for f in resp.json()["detail"]["findings"]]


# ---------------------------------------------------------------------------
# gate off: today's behaviour
# ---------------------------------------------------------------------------

class TestGateOff:
    def test_country_name_unchanged(self, auth_client, gate_off):
        """Gate off keeps the stored country value (tenant code IN vs INDIA is
        still unverified, plan Q4)."""
        vid = _create(auth_client)
        r = _payload(auth_client, vid)
        assert r.status_code == 200
        p = r.json()["payload"]
        assert p["Address_2"] == BASE["address_2"]
        assert p["Country_Region_Code"] == "India"
        assert "findings" not in r.json()

    def test_address_3_4_never_joined_or_dropped(self, auth_client, gate_off):
        """The old gate-off path joined Address 2+3+4 into Address_2 (the join
        behind BC's Application_StringExceededLength). Now the mapper refuses
        rather than join or silently drop the extra lines."""
        vid = _create(auth_client, address_3="Sector 74", address_4="Near Metro")
        r = _payload(auth_client, vid)
        assert r.status_code == 409
        assert sorted(f["field"] for f in r.json()["detail"]["findings"]) == ["address_3", "address_4"]
        stored = auth_client.get(f"/vendors/{vid}").json()
        assert (stored["address_3"], stored["address_4"]) == ("Sector 74", "Near Metro")

    def test_gate_endpoints_unavailable(self, auth_client, gate_off):
        vid = _create(auth_client)
        assert auth_client.get(f"/business-central/vendors/{vid}/gate").status_code == 503
        assert _confirm(auth_client, vid, "UNIT 7", BASE["address_2"]).status_code == 503


# ---------------------------------------------------------------------------
# gate on
# ---------------------------------------------------------------------------

class TestGatePasses:
    def test_fitting_vendor_gets_payload_with_country_code(self, auth_client, bc_on):
        vid = _create(auth_client)
        r = _payload(auth_client, vid)
        assert r.status_code == 200, r.text
        p = r.json()["payload"]
        assert p["Country_Region_Code"] == "IN"          # T-MD-01: a code, never the name
        assert p["Address"] == "UNIT 7"
        assert p["Address_2"] == "SRIJAN INDUSTRIAL LOGISTIC PARK"
        assert r.json()["findings"] == []

    def test_payload_never_truncates(self, auth_client, bc_on):
        """T-GATE-01: an over-length value is blocked, never shortened."""
        vid = _create(auth_client, address_2=LONG_A2)
        r = _payload(auth_client, vid)
        assert r.status_code == 409
        assert "payload" not in r.json()["detail"]


class TestOverLengthAddress:
    def test_a2_over_limit_safe_layout_needs_one_click(self, auth_client, bc_on):
        """A stored Address 2 over 50 with a safe whole-fragment layout is a
        one-click ADDRESS_BC_LENGTH_REBALANCE (plan section 6-7) -- still
        not pushable until confirmed, and never shortened."""
        vid = _create(auth_client, address_1="3RD FLOOR, PART A BLOCK B", address_2=LONG_A2)
        r = _payload(auth_client, vid)
        assert r.status_code == 409
        f = r.json()["detail"]["findings"][0]
        assert f["reason_code"] == "ADDRESS_BC_LENGTH_REBALANCE"
        assert f["automation_class"] == "MANUAL_REVIEW"
        assert f["confirmed"] is False
        assert f["constraint"] == "BC_ADDRESS_2_MAX_LENGTH"
        assert f["proposal"] == {
            "address_1": "3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK",
            "address_2": "MOHIARY CHANDIBAGAN, ANDUL, Natibpur",
        }

    def test_confirming_the_proposal_unblocks(self, auth_client, bc_on):
        vid = _create(auth_client, address_1="3RD FLOOR, PART A BLOCK B", address_2=LONG_A2)
        proposal = _payload(auth_client, vid).json()["detail"]["findings"][0]["proposal"]
        r = _confirm(auth_client, vid, proposal["address_1"], proposal["address_2"])
        assert r.status_code == 200, r.text
        review = r.json()["address_review"]
        assert review["reason_code"] == "ADDRESS_BC_LENGTH_REBALANCE"
        assert review["final_address_1"] == proposal["address_1"]
        assert len(review["values_sha256"]) == 64
        p = _payload(auth_client, vid)
        assert p.status_code == 200
        assert p.json()["payload"]["Address_2"] == "MOHIARY CHANDIBAGAN, ANDUL, Natibpur"

    def test_unfixable_overflow_blocks_without_proposal(self, auth_client, bc_on):
        vid = _create(auth_client, address_1="X" * 95, address_2="Y" * 55)
        r = _payload(auth_client, vid)
        assert r.status_code == 409
        f = r.json()["detail"]["findings"][0]
        assert f["reason_code"] == "ADDRESS_OVERFLOW"
        assert f["automation_class"] == "BLOCK_SUBMISSION"
        assert f["proposal"] is None
        assert "edit the address by hand" in f["detail"]
        # text untouched on the record
        stored = auth_client.get(f"/vendors/{vid}").json()
        assert (stored["address_1"], stored["address_2"]) == ("X" * 95, "Y" * 55)

    def test_single_fragment_too_long_blocks_never_cut(self, auth_client, bc_on):
        long_fragment = "Z" * 110  # one comma-less fragment, longer than any line
        vid = _create(auth_client, address_1=long_fragment, address_2="")
        r = _payload(auth_client, vid)
        assert r.status_code == 409
        f = r.json()["detail"]["findings"][0]
        assert f["reason_code"] == "ADDRESS_OVERFLOW"
        assert "fragment_too_long" in f["detail"]
        assert auth_client.get(f"/vendors/{vid}").json()["address_1"] == long_fragment


class TestLegacyAddress34:
    """T-ADR-07 / BC-12: Address 3/4 are never joined into Address 2."""

    def test_blocked_with_lossless_proposal(self, auth_client, bc_on):
        vid = _create(auth_client, address_1="F-192", address_2="Phase 8B",
                      address_3="Sector 74", address_4="Industrial Area")
        r = _payload(auth_client, vid)
        assert r.status_code == 409
        f = r.json()["detail"]["findings"][0]
        assert f["constraint"] == "BC_NO_ADDRESS_3_4"
        assert f["proposal"] == {"address_1": "F-192",
                                 "address_2": "Phase 8B, Sector 74, Industrial Area"}

    def test_confirm_clears_3_4_and_payload_has_no_join(self, auth_client, bc_on):
        vid = _create(auth_client, address_1="F-192", address_2="Phase 8B",
                      address_3="Sector 74", address_4="Industrial Area")
        assert _confirm(auth_client, vid, "F-192", "Phase 8B, Sector 74, Industrial Area").status_code == 200
        v = auth_client.get(f"/vendors/{vid}").json()
        assert v["address_3"] == "" and v["address_4"] == ""
        p = _payload(auth_client, vid).json()["payload"]
        assert p["Address_2"] == "Phase 8B, Sector 74, Industrial Area"


class TestExtractionRebalanceNeedsOneClick:
    """An extraction-time rebalance (recorded in raw_extraction provenance)
    whose lines are still the machine's must be confirmed before push."""

    A1 = "3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK"
    A2 = "MOHIARY CHANDIBAGAN, ANDUL, Natibpur"

    def _raw(self):
        return {"fields": {"address_1": {"value": self.A1, "provenance": [
            {"layer": "semantic"},
            {"layer": "bc_representation", "reason_code": "ADDRESS_BC_LENGTH_REBALANCE",
             "automation_class": "MANUAL_REVIEW", "constraint": "BC_ADDRESS_2_MAX_LENGTH",
             "constraint_value": 50,
             "original_address_1": "3RD FLOOR, PART A BLOCK B", "original_address_2": LONG_A2,
             "final_address_1": self.A1, "final_address_2": self.A2},
        ]}}}

    def test_unconfirmed_rebalance_blocks_push(self, auth_client, bc_on):
        vid = _create(auth_client, address_1=self.A1, address_2=self.A2, raw_extraction=self._raw())
        r = _payload(auth_client, vid)
        assert r.status_code == 409
        f = r.json()["detail"]["findings"][0]
        assert f["reason_code"] == "ADDRESS_BC_LENGTH_REBALANCE"
        assert f["automation_class"] == "MANUAL_REVIEW"
        assert f["confirmed"] is False
        assert f["before"] == {"address_1": "3RD FLOOR, PART A BLOCK B", "address_2": LONG_A2}
        assert f["proposal"] == {"address_1": self.A1, "address_2": self.A2}

    def test_one_click_confirm_then_push(self, auth_client, bc_on):
        vid = _create(auth_client, address_1=self.A1, address_2=self.A2, raw_extraction=self._raw())
        assert _confirm(auth_client, vid, self.A1, self.A2).status_code == 200
        r = _payload(auth_client, vid)
        assert r.status_code == 200, r.text
        assert r.json()["findings"][0]["confirmed"] is True

    def test_case18_edit_after_confirm_rechecks(self, auth_client, bc_on):
        vid = _create(auth_client, address_1=self.A1, address_2=self.A2, raw_extraction=self._raw())
        assert _confirm(auth_client, vid, self.A1, self.A2).status_code == 200
        # a human edit that breaks the limit: the confirmation no longer
        # applies and the gate blocks again
        auth_client.patch(f"/vendors/{vid}", json={"address_2": LONG_A2})
        r = _payload(auth_client, vid)
        assert r.status_code == 409
        f = r.json()["detail"]["findings"][0]
        assert f["reason_code"] == "ADDRESS_BC_LENGTH_REBALANCE"
        assert f["confirmed"] is False  # the old confirmation no longer counts
        # a human edit that fits is accepted as human-authored
        auth_client.patch(f"/vendors/{vid}", json={"address_2": "ANDUL, Natibpur"})
        assert _payload(auth_client, vid).status_code == 200


class TestConfirmRejectsUnsafeInput:
    def _vid(self, auth_client):
        return _create(auth_client, address_1="3RD FLOOR, PART A BLOCK B", address_2=LONG_A2)

    def test_new_text_rejected(self, auth_client, bc_on):
        r = _confirm(auth_client, self._vid(auth_client), "3RD FLOOR", "ANYWHERE ELSE")
        assert r.status_code == 422

    def test_reordered_fragments_rejected(self, auth_client, bc_on):
        r = _confirm(auth_client, self._vid(auth_client),
                     "PART A BLOCK B, 3RD FLOOR, SRIJAN INDUSTRIAL LOGISTIC PARK",
                     "MOHIARY CHANDIBAGAN, ANDUL, Natibpur")
        assert r.status_code == 422

    def test_dropped_fragment_rejected(self, auth_client, bc_on):
        r = _confirm(auth_client, self._vid(auth_client),
                     "3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK", "ANDUL, Natibpur")
        assert r.status_code == 422

    def test_over_limit_layout_rejected(self, auth_client, bc_on):
        r = _confirm(auth_client, self._vid(auth_client), "3RD FLOOR, PART A BLOCK B", LONG_A2)
        assert r.status_code == 422

    def test_client_cannot_self_confirm_on_create(self, auth_client, bc_on):
        vid = _create(auth_client, address_1="3RD FLOOR, PART A BLOCK B", address_2=LONG_A2,
                      address_review={"values_sha256": "x", "confirmed_by_user_id": 999})
        assert auth_client.get(f"/vendors/{vid}").json()["address_review"] is None


class TestOtherFields:
    def test_county_over_limit_blocks(self, auth_client, bc_on):
        vid = _create(auth_client, state="Dadra and Nagar Haveli and Daman and Diu")
        r = _payload(auth_client, vid)
        assert r.status_code == 409
        f = [x for x in r.json()["detail"]["findings"] if x["field"] == "state"][0]
        assert f["reason_code"] == "FIELD_TOO_LONG"
        assert f["constraint"] == "BC_COUNTY_MAX_LENGTH"
        assert f["proposal"] is None  # no abbreviation configured (Q21)

    def test_unmapped_country_needs_review_and_is_never_sent_as_name(self, auth_client, bc_on):
        vid = _create(auth_client, country="Narnia")
        r = _payload(auth_client, vid)
        assert r.status_code == 409
        assert "INVALID_COUNTRY" in _codes(r)

    def test_invalid_pin_blocks(self, auth_client, bc_on):
        vid = _create(auth_client, pin_code="71130")
        assert "INVALID_PIN" in _codes(_payload(auth_client, vid))

    def test_gate_endpoint_reports_without_payload(self, auth_client, bc_on):
        vid = _create(auth_client, address_2=LONG_A2)
        r = auth_client.get(f"/business-central/vendors/{vid}/gate")
        assert r.status_code == 200
        assert r.json()["blocked"] is True
        assert "payload" not in r.json()
