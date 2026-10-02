"""Map a saved Vendor or Customer row to a Business Central OData payload
(VendorCard / CustomerCard respectively).

Field names are BC's own (from GET .../VendorCard or .../CustomerCard on the
BC220 server), which differ from the portal's field names and the Excel/
onboarding form labels. `No` is sent empty -- BC assigns it from its own No.
Series.

Only fields the portal actually has are included. Blank values are omitted
rather than sent as "", so BC keeps its own defaults. Posting groups come from
config and are sent only when configured.

This module is a LOSSLESS SERIALIZER (docs/ADDRESS_SEGMENTATION_PLAN.md,
constraint C-NRM-08 "never truncate"). It copies each stored value into its
BC field exactly as stored (surrounding whitespace trimmed, nothing else). It
never shortens, slices, abbreviates or drops a value to fit a BC column width:
  - BC field widths live in backend/config/bc_targets/bc22_in_vendorcard.yaml
    and are enforced by the payload gate (services/bc_payload_gate.py), which
    runs BEFORE this mapper and blocks or asks for review instead of cutting.
  - A value the gate approved is therefore exactly the value serialized here.
  - Address 3/4 have no BC field. They are never joined into Address_2 (that
    join is what produced a 100-character Address_2 and BC's
    Application_StringExceededLength). A record still carrying Address 3/4
    text is refused (BcPayloadError) rather than silently dropped -- the gate
    proposes a lossless re-layout for such records.

TODO (needs confirmation against the live BC company before enabling POST):
  - Is `Vendor_Posting_Group` / `Customer_Posting_Group` mandatory on insert?
    An existing vendor had it populated ("EMPLOAN") while Gen/VAT groups were
    empty -- the customer equivalent has never been checked against a real
    BC220 CustomerCard at all, since (unlike the vendor payload) nothing has
    exercised this one against a live company yet.
  - `nature_of_business` has no obvious VendorCard field -- dropped for now.
  - Bank details (bank_name / ifsc / account_number) are not on VendorCard;
    they belong to a separate VendorBankAccount entity, handled later.
  - Customer's salesperson/payment_terms are BC "Code" fields needing real
    master-data codes, not free text -- see _CUSTOMER_FIELD_MAP below for why
    they're deliberately left unmapped.
"""

from __future__ import annotations

from app.config.config import settings
from app.models.model import Customer, Vendor


class BcPayloadError(ValueError):
    """The record holds data this mapper cannot represent in a BC payload
    without losing it (e.g. Address 3/4 text). Raised instead of silently
    dropping or joining it; the router turns it into a 409."""

    def __init__(self, message: str, fields: list[str]):
        super().__init__(message)
        self.fields = fields


# portal Vendor attribute  ->  BC VendorCard field. A standard BC VendorCard has
# only Address and Address_2 (no Address_3/Address_4), mapped 1:1 from
# address_1 / address_2. Address 3/4 are handled in vendor_to_bc_payload().
_FIELD_MAP: dict[str, str] = {
    "vendor_name": "Name",
    "address_1": "Address",
    "address_2": "Address_2",
    "city": "City",
    "state": "County",
    "country": "Country_Region_Code",
    "pin_code": "Post_Code",
    "telephone_1": "Phone_No",
    "telephone_2": "MobilePhoneNo",
    "email": "E_Mail",
    "website": "Home_Page",
    "pan": "PAN_Number",
    "gst_no": "GST_Number",
}

# Portal lines with no BC VendorCard field (C-ADR-04). Never joined, never
# dropped: a non-empty value makes vendor_to_bc_payload() refuse.
_UNMAPPABLE_ADDRESS_LINES = ("address_3", "address_4")


def vendor_to_bc_payload(vendor: Vendor) -> dict:
    """Build the JSON body for a POST to .../VendorCard.

    Every mapped value is copied as stored (trimmed); nothing is shortened.
    Over-length values are the payload gate's job to block before this runs.

    Country_Region_Code: with BC_PAYLOAD_GATE_ENABLED it is the BC code from
    the target profile (e.g. "India" -> "IN"), never the name; an unmapped
    country is left out (the gate raises INVALID_COUNTRY). With the gate off
    the stored value is sent as before -- the tenant's India code (IN vs
    INDIA) is still unverified (plan Q4).

    Raises BcPayloadError when address_3/address_4 hold text: BC has no field
    for them, and joining them into Address_2 or leaving them out would both
    lose or corrupt the address.
    """
    leftover = [
        attr for attr in _UNMAPPABLE_ADDRESS_LINES
        if str(getattr(vendor, attr, "") or "").strip()
    ]
    if leftover:
        raise BcPayloadError(
            "Address 3/4 have no Business Central field. Move their text into "
            "Address / Address 2 (or confirm the proposed re-layout) before pushing; "
            "they are never joined into Address 2 or dropped.",
            fields=leftover,
        )

    payload: dict[str, str] = {"No": ""}
    for attr, bc_field in _FIELD_MAP.items():
        value = getattr(vendor, attr, None)
        if value:
            payload[bc_field] = str(value).strip()

    if settings.BC_PAYLOAD_GATE_ENABLED:
        country = (getattr(vendor, "country", "") or "").strip()
        if country:
            from app.services.bc_target_profile import load_profile

            code = load_profile(settings.BC_TARGET_PROFILE).country_code(country)
            if code:
                payload["Country_Region_Code"] = code
            else:
                # unmapped: the gate raises INVALID_COUNTRY; never send the name
                payload.pop("Country_Region_Code", None)

    if settings.BC_GEN_BUS_POSTING_GROUP:
        payload["Gen_Bus_Posting_Group"] = settings.BC_GEN_BUS_POSTING_GROUP
    if settings.BC_VAT_BUS_POSTING_GROUP:
        payload["VAT_Bus_Posting_Group"] = settings.BC_VAT_BUS_POSTING_GROUP
    if settings.BC_VENDOR_POSTING_GROUP:
        payload["Vendor_Posting_Group"] = settings.BC_VENDOR_POSTING_GROUP

    return payload


def vendor_card_url() -> str:
    """The OData URL an operator POSTs the payload to (used by push_to_bc.ps1
    and shown in the UI)."""
    company = settings.BC_COMPANY.replace("'", "''")
    return f"{settings.BC_ODATA_BASE}/Company('{company}')/VendorCard"


# portal Customer attribute -> BC CustomerCard field. Same TODO as
# _FIELD_MAP above: field names are standard BC Customer-table captions, not
# yet confirmed against the live BC220 CustomerCard page.
#
# Deliberately NOT mapped here, same reasoning as vendor's dropped
# nature_of_business:
#   - salesperson, payment_terms map to BC "Code" fields (Salesperson_Code,
#     Payment_Terms_Code) that must match existing BC master-data codes --
#     sending the portal's free-text value would likely fail validation
#     rather than silently do the wrong thing, so it's left out until there's
#     a real code list to map against.
#   - region, customer_agreement, type have no obvious CustomerCard field.
_CUSTOMER_FIELD_MAP: dict[str, str] = {
    "company_name": "Name",
    "contact_name": "Contact",
    "billing_address": "Address",
    "city": "City",
    "state": "County",
    "country": "Country_Region_Code",
    "zip_code": "Post_Code",
    "phone_number": "Phone_No",
    "email_id_to": "E_Mail",
    "pan_number": "PAN_Number",
    "gst_registration_number": "GST_Number",
}


def customer_to_bc_payload(customer: Customer) -> dict:
    """Build the JSON body for a POST to .../CustomerCard. Mirrors
    vendor_to_bc_payload: blank values omitted rather than sent as "", `No`
    sent empty so BC assigns it from its own No. Series, and every value is
    copied as stored -- never shortened."""
    payload: dict[str, str] = {"No": ""}

    for attr, bc_field in _CUSTOMER_FIELD_MAP.items():
        value = getattr(customer, attr, None)
        if value:
            payload[bc_field] = str(value).strip()

    if settings.BC_GEN_BUS_POSTING_GROUP:
        payload["Gen_Bus_Posting_Group"] = settings.BC_GEN_BUS_POSTING_GROUP
    if settings.BC_VAT_BUS_POSTING_GROUP:
        payload["VAT_Bus_Posting_Group"] = settings.BC_VAT_BUS_POSTING_GROUP
    if settings.BC_CUSTOMER_POSTING_GROUP:
        payload["Customer_Posting_Group"] = settings.BC_CUSTOMER_POSTING_GROUP

    return payload


def customer_card_url() -> str:
    """The OData URL an operator POSTs the customer payload to."""
    company = settings.BC_COMPANY.replace("'", "''")
    return f"{settings.BC_ODATA_BASE}/Company('{company}')/CustomerCard"
