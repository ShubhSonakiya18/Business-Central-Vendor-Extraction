"""Customer-onboarding document extraction endpoint.

Handler stays thin, per the convention in routers/extraction.py: parsing and
response shaping only. The actual OCR/extraction pipeline call lives in
app/services/onboarding_extraction.py.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from ..services import onboarding_extraction
from ..services.onboarding_extraction import OnboardingExtractionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding")

# FastAPI's auto-generated schema for List[UploadFile] describes each item as
# `{"type": "string", "contentMediaType": "application/octet-stream"}`
# (OpenAPI 3.1 style). The Swagger UI build bundled with this FastAPI version
# only recognises the older `format: "binary"` convention to decide whether a
# field gets a file-picker widget, so without this override /docs renders
# `documents` as plain text boxes instead of file inputs -- runtime request
# parsing is untouched either way (that's governed entirely by the
# `List[UploadFile]` type hint below); this only patches what /docs displays.
_DOCUMENTS_REQUEST_BODY = {
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "properties": {
                    "documents": {
                        "type": "array",
                        "items": {"type": "string", "format": "binary"},
                        "title": "Documents",
                    }
                },
                "required": ["documents"],
            }
        }
    },
    "required": True,
}


@router.post("/extract", openapi_extra={"requestBody": _DOCUMENTS_REQUEST_BODY})
def extract_onboarding_fields(documents: List[UploadFile] = File(...)):
    """Extract customer-onboarding fields from one or more uploaded documents
    (cancelled cheque, GST certificate, Udyam certificate, PAN card, etc.).

    Runs the same local OCR/extraction pipeline this backend already uses
    elsewhere (see /extract), then reshapes the result into the
    customer-onboarding form's fixed schema (see
    onboarding_mapper.to_onboarding_schema). A field with no source anywhere
    in the uploaded documents comes back as an empty string rather than
    guessed; anything low-confidence, ambiguous, or format-invalid is named in
    `fields_needing_review` instead of being silently trusted.
    """
    try:
        return onboarding_extraction.process(documents)
    except OnboardingExtractionError as error:
        return JSONResponse(
            {"error": error.message, "detail": error.detail},
            status_code=400,
        )
