"""Business Central manual-push endpoints (vendor)."""

from __future__ import annotations

import pytest

from app.config.config import settings

VENDOR_PAYLOAD = {
    "vendor_name": "M.B. Control & Systems Pvt. Ltd.",
    "address_1": "Srijan Industrial Logistic Park",
    "address_2": "Block B, 3rd Floor",
    "city": "Howrah",
    "state": "West Bengal",
    "country": "India",
    "pin_code": "711302",
    "telephone_1": "9831330473",
    "email": "enquiry@mbcontrol.com",
    "pan": "AABCM7980K",
    "gst_no": "19AABCM7980K1ZU",
}


@pytest.fixture
def bc_enabled():
    prev = settings.BC_ENABLED
    settings.BC_ENABLED = True
    yield
    settings.BC_ENABLED = prev


@pytest.fixture
def bc_disabled():
    # Force the disabled state regardless of what the loaded .env has.
    prev = settings.BC_ENABLED
    settings.BC_ENABLED = False
    yield
    settings.BC_ENABLED = prev


def _create_vendor(auth_client) -> int:
    r = auth_client.post("/vendors", json=VENDOR_PAYLOAD)
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestDisabled:
    def test_payload_503_when_disabled(self, auth_client, bc_disabled):
        vid = _create_vendor(auth_client)
        assert auth_client.get(f"/business-central/vendors/{vid}/payload").status_code == 503

    def test_mark_pushed_503_when_disabled(self, auth_client, bc_disabled):
        vid = _create_vendor(auth_client)
        r = auth_client.patch(f"/business-central/vendors/{vid}/mark-pushed", json={"bc_no": "X"})
        assert r.status_code == 503


class TestPayload:
    def test_requires_auth(self, client, bc_enabled):
        assert client.get("/business-central/vendors/1/payload").status_code == 401

    def test_payload_shape_and_field_mapping(self, auth_client, bc_enabled):
        vid = _create_vendor(auth_client)
        r = auth_client.get(f"/business-central/vendors/{vid}/payload")
        assert r.status_code == 200
        body = r.json()

        assert body["vendor_id"] == vid
        assert body["already_pushed"] is False
        assert body["method"] == "POST"
        assert body["target_url"].endswith("/VendorCard")

        p = body["payload"]
        assert p["No"] == ""
        assert p["Name"] == VENDOR_PAYLOAD["vendor_name"]
        assert p["Address"] == VENDOR_PAYLOAD["address_1"]
        assert p["Address_2"] == VENDOR_PAYLOAD["address_2"]
        assert p["City"] == "Howrah"
        assert p["County"] == "West Bengal"          # BC calls state "County"
        assert p["Country_Region_Code"] == "India"
        assert p["Post_Code"] == "711302"
        assert p["Phone_No"] == "9831330473"
        assert p["E_Mail"] == VENDOR_PAYLOAD["email"]
        assert p["PAN_Number"] == "AABCM7980K"
        assert p["GST_Number"] == "19AABCM7980K1ZU"

    def test_blank_fields_are_omitted(self, auth_client, bc_enabled):
        r = auth_client.post("/vendors", json={"vendor_name": "Bare Co"})
        vid = r.json()["id"]
        p = auth_client.get(f"/business-central/vendors/{vid}/payload").json()["payload"]
        assert "E_Mail" not in p and "GST_Number" not in p and "Post_Code" not in p
        assert p["Name"] == "Bare Co"

    def test_posting_groups_included_only_when_configured(self, auth_client, bc_enabled, monkeypatch):
        vid = _create_vendor(auth_client)
        p = auth_client.get(f"/business-central/vendors/{vid}/payload").json()["payload"]
        assert "Vendor_Posting_Group" not in p

        monkeypatch.setattr(settings, "BC_VENDOR_POSTING_GROUP", "EMPLOAN")
        p = auth_client.get(f"/business-central/vendors/{vid}/payload").json()["payload"]
        assert p["Vendor_Posting_Group"] == "EMPLOAN"


def _fragments(*lines):
    """Comma-delimited address fragments, in order -- the unit the BC address
    layer moves. Two layouts hold the same address iff these lists match."""
    return [p.strip() for line in lines for p in (line or "").split(",") if p.strip()]


# The real address that hit BC's Application_StringExceededLength: Address 2,
# 3 and 4 used to be joined into one 100-character Address_2.
INCIDENT_ADDRESS = {
    "vendor_name": "Peenya Control Systems Pvt Ltd",
    "address_1": "Building D, Part C, Unit No. 12, 1st Floor",
    "address_2": "Peenya Industrial Estate",
    "address_3": "Phase I, Tumkur Road, Industrial Area",
    "address_4": "Nandini Layout, Yeshwanthpur, Peenya",
    "city": "Bengaluru",
    "state": "Karnataka",
}


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setattr(settings, "BC_ENABLED", True)
    monkeypatch.setattr(settings, "BC_PAYLOAD_GATE_ENABLED", True)


class TestAddressOverflow:
    """Address / Address 2 overflow is handled by the BC address layer's
    whole-fragment rebalance and the payload gate -- NEVER by truncation
    (docs/ADDRESS_SEGMENTATION_PLAN.md, C-NRM-08, T-GATE-02). Rewrite of the
    old test_long_joined_address_is_truncated_to_fit, which asserted a cut
    Address_2: the same real incident address must now keep every character."""

    def test_case_a_safe_rebalance_needs_one_click_and_loses_nothing(self, auth_client, gate_on):
        """A legacy multi-line address that CAN fit by moving whole fragments:
        one-click review, proposal is the same text, nothing cut or split."""
        original = {
            "vendor_name": "Peenya Fasteners Pvt Ltd",
            "address_1": "Plot 5",
            "address_2": "Peenya Industrial Estate",
            "address_3": "Phase I, Tumkur Road",
            "address_4": "Nandini Layout",
            "city": "Bengaluru", "state": "Karnataka",
        }
        vid = auth_client.post("/vendors", json=original).json()["id"]

        r = auth_client.get(f"/business-central/vendors/{vid}/payload")
        assert r.status_code == 409  # not pushable until confirmed
        f = r.json()["detail"]["findings"][0]
        assert f["reason_code"] == "ADDRESS_BC_LENGTH_REBALANCE"
        assert f["automation_class"] == "MANUAL_REVIEW"
        proposal = f["proposal"]
        assert len(proposal["address_1"]) <= 100 and len(proposal["address_2"]) <= 50

        # No character lost, no fragment split, order preserved.
        src = _fragments(original["address_1"], original["address_2"],
                         original["address_3"], original["address_4"])
        assert _fragments(proposal["address_1"], proposal["address_2"]) == src

        # The stored record is untouched until the reviewer confirms.
        stored = auth_client.get(f"/vendors/{vid}").json()
        assert stored["address_3"] == original["address_3"]

        # One click -> payload carries exactly the confirmed lines.
        assert auth_client.post(f"/business-central/vendors/{vid}/address-review/confirm",
                                json=proposal).status_code == 200
        r = auth_client.get(f"/business-central/vendors/{vid}/payload")
        assert r.status_code == 200, r.text
        assert r.json()["payload"]["Address"] == proposal["address_1"]
        assert r.json()["payload"]["Address_2"] == proposal["address_2"]

    def test_case_b_incident_address_blocked_never_truncated(self, auth_client, gate_on):
        """The real incident address has NO legal whole-fragment layout
        (42 + 101 chars; the best split leaves Address at 107 or Address 2 at
        53). It must be blocked with the text intact -- not cut to fit."""
        vid = auth_client.post("/vendors", json=INCIDENT_ADDRESS).json()["id"]

        r = auth_client.get(f"/business-central/vendors/{vid}/payload")
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert "payload" not in detail
        f = detail["findings"][0]
        assert f["reason_code"] == "ADDRESS_OVERFLOW"
        assert f["automation_class"] == "BLOCK_SUBMISSION"
        assert f["proposal"] is None

        # Every original character is still on the record and in the finding.
        stored = auth_client.get(f"/vendors/{vid}").json()
        for key in ("address_1", "address_2", "address_3", "address_4"):
            assert stored[key] == INCIDENT_ADDRESS[key]
            assert f["before"][key] == INCIDENT_ADDRESS[key]

    def test_incident_address_with_gate_off_is_refused_not_joined_or_cut(self, auth_client, bc_enabled):
        """Gate off: the mapper still never joins Address 3/4 into Address_2
        (the join behind the incident) and never drops or shortens them -- it
        refuses with a 409 instead."""
        vid = auth_client.post("/vendors", json=INCIDENT_ADDRESS).json()["id"]
        r = auth_client.get(f"/business-central/vendors/{vid}/payload")
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert sorted(f["field"] for f in detail["findings"]) == ["address_3", "address_4"]
        stored = auth_client.get(f"/vendors/{vid}").json()
        assert stored["address_3"] == INCIDENT_ADDRESS["address_3"]

    @pytest.mark.parametrize("gate", [False, True])
    def test_no_truncation_concept_in_response(self, auth_client, monkeypatch, gate):
        """T-GATE-01: the truncated_fields / _truncated_fields concept is gone
        in both gate states."""
        monkeypatch.setattr(settings, "BC_ENABLED", True)
        monkeypatch.setattr(settings, "BC_PAYLOAD_GATE_ENABLED", gate)
        vid = _create_vendor(auth_client)
        body = auth_client.get(f"/business-central/vendors/{vid}/payload").json()
        assert "truncated_fields" not in body
        assert "_truncated_fields" not in body["payload"]

    def test_payload_404_for_missing_vendor(self, auth_client, bc_enabled):
        assert auth_client.get("/business-central/vendors/999999/payload").status_code == 404


class TestMarkPushed:
    def test_marks_and_is_idempotent(self, auth_client, bc_enabled):
        vid = _create_vendor(auth_client)

        r = auth_client.patch(f"/business-central/vendors/{vid}/mark-pushed", json={"bc_no": "EMPV/0123"})
        assert r.status_code == 200
        assert r.json() == {"vendor_id": vid, "bc_status": "pushed", "bc_no": "EMPV/0123"}

        # reflected on the record
        v = auth_client.get(f"/vendors/{vid}").json()
        assert v["bc_status"] == "pushed" and v["bc_no"] == "EMPV/0123"

        # payload endpoint now flags it
        assert auth_client.get(f"/business-central/vendors/{vid}/payload").json()["already_pushed"] is True

        # second mark -> 409
        r2 = auth_client.patch(f"/business-central/vendors/{vid}/mark-pushed", json={"bc_no": "EMPV/9999"})
        assert r2.status_code == 409

    def test_mark_pushed_404_for_missing_vendor(self, auth_client, bc_enabled):
        r = auth_client.patch("/business-central/vendors/999999/mark-pushed", json={"bc_no": "X"})
        assert r.status_code == 404

    def test_bc_no_required(self, auth_client, bc_enabled):
        vid = _create_vendor(auth_client)
        assert auth_client.patch(f"/business-central/vendors/{vid}/mark-pushed", json={}).status_code == 422
