"""Business Central push -- manual flow (vendor).

The portal does not call BC directly (the BC OData endpoint is only reachable
from inside the VPN). Instead:

  1. GET /business-central/vendors/{id}/payload
       -> the ready-to-POST VendorCard JSON + the target URL
  2. An operator runs scripts/push_to_bc.ps1 on a VPN machine, which POSTs it
     to BC and prints the assigned No.
  3. PATCH /business-central/vendors/{id}/mark-pushed { bc_no: "EMPV/0123" }
       -> records the No. so the vendor is not pushed again

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
from app.services.bc_mapper import vendor_card_url, vendor_to_bc_payload

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

    return {
        "vendor_id": vendor.id,
        "already_pushed": vendor.bc_status == "pushed",
        "bc_no": vendor.bc_no,
        "target_url": vendor_card_url(),
        "method": "POST",
        "payload": vendor_to_bc_payload(vendor),
    }


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
