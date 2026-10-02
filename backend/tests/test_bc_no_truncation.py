"""Regression guard: Business Central payloads are NEVER truncated.

docs/ADDRESS_SEGMENTATION_PLAN.md (C-NRM-08, T-GATE-01/02). A previous change
reintroduced `_fit_to_bc_width()` in bc_mapper.py, which silently cut Name,
Address, City, County, phone fields etc. to BC column widths -- even after the
payload gate had approved them. These tests fail if any such mechanism returns:

  * over-limit non-address fields -> FIELD_TOO_LONG at the gate, value kept;
  * the mapper serializes every value exactly as stored, gate on or off;
  * a gate-approved value is exactly the value in the payload;
  * no truncation helper or truncated_fields concept exists in the code.

Limits are read from the BC target profile, never hard-coded here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.config import settings
from app.models.model import Customer, Vendor
from app.services.bc_mapper import customer_to_bc_payload, vendor_to_bc_payload
from app.services.bc_payload_gate import gate_vendor
from app.services.bc_target_profile import load_profile

PROFILE = load_profile("bc22_in_vendorcard")


def _over(constraint_id: str, fill: str = "A") -> str:
    """A value one character longer than the profile's limit."""
    return fill * (PROFILE.limit(constraint_id) + 1)


# (vendor attribute, profile constraint, BC payload field) for every
# non-address field the profile constrains and the mapper sends.
NON_ADDRESS_FIELDS = [
    ("vendor_name", "BC_NAME_MAX_LENGTH", "Name"),
    ("city", "BC_CITY_MAX_LENGTH", "City"),
    ("state", "BC_COUNTY_MAX_LENGTH", "County"),
    ("telephone_1", "BC_PHONE_MAX_LENGTH", "Phone_No"),
    ("telephone_2", "BC_MOBILE_PHONE_MAX_LENGTH", "MobilePhoneNo"),
    ("email", "BC_EMAIL_MAX_LENGTH", "E_Mail"),
    ("website", "BC_HOME_PAGE_MAX_LENGTH", "Home_Page"),
]

BASE = {
    "vendor_name": "Example Industries Pvt Ltd",
    "address_1": "UNIT 7",
    "address_2": "SRIJAN INDUSTRIAL LOGISTIC PARK",
    "city": "Howrah",
    "state": "West Bengal",
    "country": "India",
    "pin_code": "711302",
}


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setattr(settings, "BC_ENABLED", True)
    monkeypatch.setattr(settings, "BC_PAYLOAD_GATE_ENABLED", True)


# ---------------------------------------------------------------------------
# Item 12: over-limit non-address fields -> FIELD_TOO_LONG, never shortened
# ---------------------------------------------------------------------------

class TestNonAddressOverflowIsAFinding:
    @pytest.mark.parametrize("attr,constraint,bc_field", NON_ADDRESS_FIELDS,
                             ids=[f[0] for f in NON_ADDRESS_FIELDS])
    def test_over_limit_value_blocked_and_unchanged(self, auth_client, gate_on, attr, constraint, bc_field):
        original = _over(constraint, "B")
        vid = auth_client.post("/vendors", json={**BASE, attr: original}).json()["id"]

        r = auth_client.get(f"/business-central/vendors/{vid}/payload")
        assert r.status_code == 409
        findings = [f for f in r.json()["detail"]["findings"] if f["field"] == attr]
        assert len(findings) == 1
        f = findings[0]
        assert f["reason_code"] == "FIELD_TOO_LONG"
        assert f["automation_class"] == "BLOCK_SUBMISSION"
        assert f["constraint"] == constraint
        assert f["proposal"] is None or attr == "state"  # only County may carry an abbreviation proposal

        stored = auth_client.get(f"/vendors/{vid}").json()[attr]
        assert stored == original
        assert len(stored) > PROFILE.limit(constraint)

    @pytest.mark.parametrize("attr,constraint,bc_field", NON_ADDRESS_FIELDS,
                             ids=[f[0] for f in NON_ADDRESS_FIELDS])
    def test_value_exactly_at_limit_passes(self, attr, constraint, bc_field):
        at_limit = "C" * PROFILE.limit(constraint)
        result = gate_vendor(Vendor(**{**BASE, attr: at_limit}), PROFILE)
        assert not [f for f in result.findings if f.field == attr]

    def test_non_address_fields_never_enter_the_address_rebalance(self):
        """A long City must not be 'fixed' by moving text into Address lines."""
        vendor = Vendor(**{**BASE, "city": _over("BC_CITY_MAX_LENGTH")})
        result = gate_vendor(vendor, PROFILE)
        codes = {(f.field, f.reason_code) for f in result.findings}
        assert ("city", "FIELD_TOO_LONG") in codes
        assert not any(f.reason_code.startswith("ADDRESS_") for f in result.findings)


# ---------------------------------------------------------------------------
# Item 13 + 15: the mapper is lossless, gate on AND off
# ---------------------------------------------------------------------------

def _long_vendor() -> Vendor:
    """Values that the old _fit_to_bc_width() would have cut."""
    return Vendor(
        vendor_name=_over("BC_NAME_MAX_LENGTH", "N"),
        address_1="Building D, Part C, Unit No. 12, 1st Floor, " + "Q" * 80,
        address_2="Peenya Industrial Estate, Phase I, Tumkur Road, Industrial Area",
        city=_over("BC_CITY_MAX_LENGTH", "C"),
        state=_over("BC_COUNTY_MAX_LENGTH", "S"),
        telephone_1=_over("BC_PHONE_MAX_LENGTH", "9"),
        telephone_2=_over("BC_MOBILE_PHONE_MAX_LENGTH", "8"),
        email="x" * 90 + "@example.com",
        website="https://example.com/" + "w" * 90,
        country="India",
        pin_code="560058",
    )


@pytest.mark.parametrize("gate", [False, True], ids=["gate_off", "gate_on"])
class TestMapperIsLossless:
    def test_every_value_serialized_exactly(self, monkeypatch, gate):
        monkeypatch.setattr(settings, "BC_PAYLOAD_GATE_ENABLED", gate)
        vendor = _long_vendor()
        payload = vendor_to_bc_payload(vendor)
        expected = {
            "Name": vendor.vendor_name, "Address": vendor.address_1,
            "Address_2": vendor.address_2, "City": vendor.city, "County": vendor.state,
            "Phone_No": vendor.telephone_1, "MobilePhoneNo": vendor.telephone_2,
            "E_Mail": vendor.email, "Home_Page": vendor.website,
        }
        for bc_field, value in expected.items():
            assert payload[bc_field] == value, f"{bc_field} was modified by the mapper"
        assert "_truncated_fields" not in payload

    def test_customer_payload_is_lossless(self, monkeypatch, gate):
        monkeypatch.setattr(settings, "BC_PAYLOAD_GATE_ENABLED", gate)
        customer = Customer(
            company_name="C" * 150, contact_name="P" * 150,
            billing_address="Long billing address, " * 8,
            city="Y" * 45, state="Z" * 45, phone_number="1" * 40,
            email_id_to="e" * 90 + "@example.com",
        )
        payload = customer_to_bc_payload(customer)
        assert payload["Name"] == customer.company_name
        assert payload["Contact"] == customer.contact_name
        assert payload["Address"] == customer.billing_address.strip()
        assert payload["City"] == customer.city
        assert payload["County"] == customer.state
        assert payload["Phone_No"] == customer.phone_number
        assert payload["E_Mail"] == customer.email_id_to
        assert "_truncated_fields" not in payload


# ---------------------------------------------------------------------------
# Item 14: gate-approved value == serialized value
# ---------------------------------------------------------------------------

class TestGateMapperConsistency:
    def test_values_at_every_limit_pass_gate_and_reach_payload_unchanged(self, gate_on):
        vendor = Vendor(
            vendor_name="N" * PROFILE.limit("BC_NAME_MAX_LENGTH"),
            address_1="A" * PROFILE.limit("BC_ADDRESS_1_MAX_LENGTH"),
            address_2="B" * PROFILE.limit("BC_ADDRESS_2_MAX_LENGTH"),
            city="C" * PROFILE.limit("BC_CITY_MAX_LENGTH"),
            state="S" * PROFILE.limit("BC_COUNTY_MAX_LENGTH"),
            telephone_1="9" * PROFILE.limit("BC_PHONE_MAX_LENGTH"),
            telephone_2="8" * PROFILE.limit("BC_MOBILE_PHONE_MAX_LENGTH"),
            email="e" * PROFILE.limit("BC_EMAIL_MAX_LENGTH"),
            website="w" * PROFILE.limit("BC_HOME_PAGE_MAX_LENGTH"),
            country="India", pin_code="711302",
        )
        gate = gate_vendor(vendor, PROFILE)
        assert not gate.blocked, gate.to_dict()

        payload = vendor_to_bc_payload(vendor)
        for attr, bc_field in [("vendor_name", "Name"), ("address_1", "Address"),
                               ("address_2", "Address_2"), ("city", "City"), ("state", "County"),
                               ("telephone_1", "Phone_No"), ("telephone_2", "MobilePhoneNo"),
                               ("email", "E_Mail"), ("website", "Home_Page"), ("pin_code", "Post_Code")]:
            assert payload[bc_field] == getattr(vendor, attr), f"{bc_field} changed after gate approval"
        assert payload["Country_Region_Code"] == PROFILE.country_code("India")

    def test_api_payload_equals_stored_record(self, auth_client, gate_on):
        vid = auth_client.post("/vendors", json=BASE).json()["id"]
        r = auth_client.get(f"/business-central/vendors/{vid}/payload")
        assert r.status_code == 200, r.text
        p = r.json()["payload"]
        stored = auth_client.get(f"/vendors/{vid}").json()
        assert p["Name"] == stored["vendor_name"]
        assert p["Address"] == stored["address_1"]
        assert p["Address_2"] == stored["address_2"]
        assert p["City"] == stored["city"]
        assert p["County"] == stored["state"]
        assert p["Post_Code"] == stored["pin_code"]


# ---------------------------------------------------------------------------
# Item 19: no truncation mechanism exists anywhere in the BC path
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[2]
_FORBIDDEN = ("_fit_to_bc_width", "_BC_FIELD_MAX_LEN", "_truncated_fields", "truncated_fields")


def test_no_truncation_mechanism_in_code():
    roots = [_REPO / "backend" / "app", _REPO / "ar-portal" / "src"]
    hits = []
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix not in (".py", ".js", ".jsx") or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for name in _FORBIDDEN:
                if name in text:
                    hits.append(f"{path.relative_to(_REPO)}: {name}")
    assert not hits, "BC truncation mechanism reintroduced:\n" + "\n".join(hits)
