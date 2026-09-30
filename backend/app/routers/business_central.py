"""Business Central push -- manual flow (vendor and customer).

The portal does not call BC directly (the BC OData endpoint is only reachable
from inside the VPN). Instead, per record kind:

  1. GET /business-central/vendors/{id}/payload
     GET /business-central/customers/{id}/payload
       -> the ready-to-POST VendorCard / CustomerCard JSON + the target URL
  2. An operator runs scripts/push_to_bc.ps1 on a VPN machine, which POSTs it
     to BC and prints the assigned No. (the script itself is generic -- it
     just POSTs whatever {target_url, payload} JSON file it's given, vendor
     or customer alike).
  3. PATCH /business-central/vendors/{id}/mark-pushed { bc_no: "EMPV/0123" }
     PATCH /business-central/customers/{id}/mark-pushed { bc_no: "..." }
       -> records the No. so the record is not pushed again

Everything here is gated by settings.BC_ENABLED.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.config import settings
from app.database.db import get_db
from app.models.model import User
from app.services import records_crud as crud
from app.services.auth_services.dependencies import get_current_user
from app.services.bc_mapper import (
    customer_card_url,
    customer_to_bc_payload,
    vendor_card_url,
    vendor_to_bc_payload,
)
from app.services.bc_payload_gate import ConfirmationRejected, confirm_address, gate_vendor
from app.services.bc_target_profile import load_profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/business-central", tags=["business-central"])


def _require_enabled() -> None:
    if not settings.BC_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Business Central integration is disabled (BC_ENABLED=false).",
        )


class MarkPushedRequest(BaseModel):
    bc_no: str = Field(..., min_length=1, description="The No. Business Central assigned, e.g. EMPV/0123")


class AddressConfirmRequest(BaseModel):
    address_1: str = Field(..., description="The Address line the reviewer approves")
    address_2: str = Field("", description="The Address 2 line the reviewer approves")


def _require_gate() -> None:
    if not settings.BC_PAYLOAD_GATE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The BC payload gate is disabled (BC_PAYLOAD_GATE_ENABLED=false).",
        )


@router.get("/vendors/{vendor_id}/payload")
def vendor_bc_payload(
    vendor_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_enabled()
    vendor = crud.get_vendor(db, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")

    gate = None
    if settings.BC_PAYLOAD_GATE_ENABLED:
        # Stage-11 gate (docs/ADDRESS_SEGMENTATION_PLAN.md): no payload while
        # any BLOCK finding or unconfirmed MANUAL_REVIEW finding is open.
        gate = gate_vendor(vendor, load_profile(settings.BC_TARGET_PROFILE))
        if gate.blocked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "Vendor is not ready for Business Central.",
                        "vendor_id": vendor.id, **gate.to_dict()},
            )

    body = {
        "vendor_id": vendor.id,
        "already_pushed": vendor.bc_status == "pushed",
        "bc_no": vendor.bc_no,
        "target_url": vendor_card_url(),
        "method": "POST",
        "payload": vendor_to_bc_payload(vendor),
    }
    if gate is not None:
        body["findings"] = gate.to_dict()["findings"]
    return body


@router.get("/vendors/{vendor_id}/gate")
def vendor_bc_gate(
    vendor_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The gate's findings for a vendor, without building the payload -- for
    the review screen's before/after panel."""
    _require_enabled()
    _require_gate()
    vendor = crud.get_vendor(db, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {"vendor_id": vendor.id,
            **gate_vendor(vendor, load_profile(settings.BC_TARGET_PROFILE)).to_dict()}


@router.post("/vendors/{vendor_id}/address-review/confirm")
def confirm_vendor_address(
    vendor_id: int,
    body: AddressConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """One-click confirmation of an Address / Address 2 re-layout. Accepts
    only a lossless, order-preserving re-layout of the stored text that fits
    BC's limits (422 otherwise); arbitrary edits go through PATCH /vendors."""
    _require_enabled()
    _require_gate()
    vendor = crud.get_vendor(db, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    if vendor.bc_status == "pushed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"message": "Vendor is already pushed.", "bc_no": vendor.bc_no})
    profile = load_profile(settings.BC_TARGET_PROFILE)
    try:
        review = confirm_address(vendor, body.address_1, body.address_2, user.id, profile)
    except ConfirmationRejected as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    db.commit()
    db.refresh(vendor)
    logger.info("vendor %s address layout confirmed by user %s", vendor.id, user.id)
    return {"vendor_id": vendor.id, "address_review": review,
            **gate_vendor(vendor, profile).to_dict()}


@router.patch("/vendors/{vendor_id}/mark-pushed")
def mark_vendor_pushed(
    vendor_id: int,
    body: MarkPushedRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_enabled()
    vendor = crud.get_vendor(db, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    if vendor.bc_status == "pushed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Vendor is already marked as pushed.", "bc_no": vendor.bc_no},
        )

    vendor.bc_no = body.bc_no.strip()
    vendor.bc_status = "pushed"
    vendor.bc_synced_at = datetime.now(timezone.utc)
    vendor.bc_error = None
    db.commit()
    db.refresh(vendor)

    logger.info("vendor %s marked pushed to BC as %s by user %s", vendor.id, vendor.bc_no, user.id)
    return {"vendor_id": vendor.id, "bc_status": vendor.bc_status, "bc_no": vendor.bc_no}


@router.get("/customers/{customer_id}/payload")
def customer_bc_payload(
    customer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_enabled()
    customer = crud.get_customer(db, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    return {
        "customer_id": customer.id,
        "already_pushed": customer.bc_status == "pushed",
        "bc_no": customer.bc_no,
        "target_url": customer_card_url(),
        "method": "POST",
        "payload": customer_to_bc_payload(customer),
    }


@router.patch("/customers/{customer_id}/mark-pushed")
def mark_customer_pushed(
    customer_id: int,
    body: MarkPushedRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_enabled()
    customer = crud.get_customer(db, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if customer.bc_status == "pushed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Customer is already marked as pushed.", "bc_no": customer.bc_no},
        )

    customer.bc_no = body.bc_no.strip()
    customer.bc_status = "pushed"
    customer.bc_synced_at = datetime.now(timezone.utc)
    customer.bc_error = None
    db.commit()
    db.refresh(customer)

    logger.info("customer %s marked pushed to BC as %s by user %s", customer.id, customer.bc_no, user.id)
    return {"customer_id": customer.id, "bc_status": customer.bc_status, "bc_no": customer.bc_no}
