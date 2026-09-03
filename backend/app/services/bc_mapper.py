"""Map a saved Vendor row to a Business Central VendorCard OData payload.

Field names are BC's own (from GET .../VendorCard on the BC220 server), which
differ from the portal's field names and the Excel form labels. `No` is sent
empty -- BC assigns it from its No. Series.

Only fields the portal actually has are included. Blank values are omitted
rather than sent as "", so BC keeps its own defaults. Posting groups come from
config and are sent only when configured.

TODO (needs confirmation against the live BC company before enabling POST):
  - Is `Vendor_Posting_Group` mandatory on insert? An existing vendor had it
    populated ("EMPLOAN") while Gen/VAT groups were empty.
  - `nature_of_business` has no obvious VendorCard field -- dropped for now.
  - Bank details (bank_name / ifsc / account_number) are not on VendorCard;
    they belong to a separate VendorBankAccount entity, handled later.
"""

from __future__ import annotations

from app.config.config import settings
from app.models.model import Vendor

# portal Vendor attribute  ->  BC VendorCard field
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


def vendor_to_bc_payload(vendor: Vendor) -> dict:
    """Build the JSON body for a POST to .../VendorCard."""
    payload: dict[str, str] = {"No": ""}

    for attr, bc_field in _FIELD_MAP.items():
        value = getattr(vendor, attr, None)
        if value:
            payload[bc_field] = str(value).strip()

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
