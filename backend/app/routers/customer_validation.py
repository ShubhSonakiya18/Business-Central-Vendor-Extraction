"""Customer Excel validation endpoint (read-only review flow).

POST /customer-validation/excel takes an already-filled Customer Detail Excel,
checks its GSTIN against the live GST registry through the existing
verify_gstin() service, and returns the field-by-field comparison. It saves
nothing, creates no customer and never pushes to Business Central -- see
app/services/customer_excel_validation.py.

Authenticated: every call can spend GST API quota.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.models.model import User
from app.services.auth_services.dependencies import get_current_user
from app.services.customer_excel_validation import (
    MAX_UPLOAD_BYTES,
    ExcelValidationError,
    validate_customer_excel,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/customer-validation", tags=["customer-validation"])


@router.post("/excel")
def validate_excel(
    file: UploadFile = File(..., description="Filled Customer Detail Excel (.xlsx / .xlsm)"),
    user: User = Depends(get_current_user),
):
    # Sync handler on purpose: verify_gstin() makes a blocking HTTP call, so
    # FastAPI runs this in its threadpool. Read one byte past the limit so an
    # oversized upload is detected without reading all of it.
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    try:
        return validate_customer_excel(file.filename or "", content)
    except ExcelValidationError as exc:
        logger.info("customer excel rejected for user=%s: %s", user.id, exc)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
