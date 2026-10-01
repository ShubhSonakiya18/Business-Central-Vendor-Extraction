"""Live GSTIN verification against the GST registry.

Separate concern from `extraction_pipeline.extract.validator`'s GSTIN checks:
that module only verifies the STRING is well-formed (regex shape, embedded
PAN matches) -- it never leaves the machine and cannot tell a syntactically
valid but fake/cancelled GSTIN from a real, active one. This module makes one
outbound call to confirm the GSTIN is actually registered and active, and
returns the registry's legal name / status for a human reviewer to compare
against what was extracted from the document.

Shared by both the vendor and customer onboarding flows (same GSTIN shape,
same registry) -- call `verify_gstin()` from onboarding_mapper.py once a
format-valid GSTIN has been extracted, for either flow.

Gated by settings.GSTIN_API_ENABLED (default False) -- this must not fire
during ordinary extraction runs/tests unless explicitly turned on, the same
lesson already learned the hard way with Gemini's per-project quota (see
CLAUDE.md).

Two providers, tried in order:

  1. Decentro's KYC validate API (primary). Response shape confirmed against
     a real Decentro staging call (2026-10-01, GSTIN 19AABCM7980K1ZU): the
     registry fields sit under "kycResult", status is "gstnStatus" (e.g.
     "Active"), and the registered address comes back as one combined line
     in "principalPlaceOfBusiness" ("...CITY, STATE, PIN") rather than
     separate city/pincode fields -- parsed out of that line here.
  2. gstinapi.in (fallback). Used only when Decentro is not configured
     (missing client_id/client_secret) or its call does not succeed --
     keeps verification working if Decentro's credentials aren't set up yet
     or its API has an outage, without a code change to fall back.

Usage:
    from app.services.gstin_verification import verify_gstin
    result = verify_gstin("19AABCM7980K1ZU")
    if result.checked and not result.active:
        # flag for review -- GSTIN is registered but cancelled/suspended
        ...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests

from app.config.config import settings

logger = logging.getLogger(__name__)

# Decentro's KYC "Validate Document" endpoint -- confirmed against a real
# staging call (2026-10-01): wants document_type="GSTIN", id_number (not
# "gstin"), and consent as the STRING "Y" (not a boolean -- a boolean gets
# rejected with error_invalid_consent on this endpoint).
_DECENTRO_ENDPOINT = "{base}/kyc/public_registry/validate"
_GSTINAPI_ENDPOINT = "https://www.gstinapi.in/v1/gstin/{gstin}"
_TIMEOUT_S = 10


@dataclass
class GstinVerificationResult:
    checked: bool               # True if the API call actually ran and returned data
    active: bool = False        # True if the registry marks this GSTIN as active
    legal_name: str = ""        # registered legal name, for comparison against the extracted vendor/customer name
    trade_name: str = ""        # registered trade name, if different from the legal name
    status: str = ""            # raw registry status string (e.g. "Active", "Cancelled")
    address: str = ""           # registered principal place of business, single-line
    city: str = ""              # registered city
    state: str = ""             # registered state
    pincode: str = ""           # registered PIN code
    error: str = ""             # set when checked=False -- why no result is available
    provider: str = ""          # "decentro" | "gstinapi" -- which one actually answered


def _disabled_result(reason: str) -> GstinVerificationResult:
    return GstinVerificationResult(checked=False, error=reason)


def _split_address(principal_place: str) -> tuple[str, str, str]:
    """Decentro returns the registered address as one combined line, e.g.
    "1ST FLOOR, 31/1 AHIRIPUKUR ROAD, KOLKATA, Kolkata, West Bengal, 700019"
    -- city/state/PIN aren't broken out separately anywhere else in the
    response, so pull them from the last three comma-separated segments
    (PIN last, state second-to-last, city the segment before that)."""
    parts = [p.strip() for p in principal_place.split(",") if p.strip()]
    if len(parts) < 3:
        return "", "", ""
    pincode = parts[-1] if parts[-1].isdigit() else ""
    if not pincode:
        return "", "", ""
    state = parts[-2]
    city = parts[-3]
    return city, state, pincode


def _verify_via_decentro(gstin: str) -> Optional[GstinVerificationResult]:
    """Returns None (not a failure result) when Decentro isn't configured at
    all, so the caller knows to silently fall back rather than surface this
    as the final error."""
    if not settings.DECENTRO_CLIENT_ID or not settings.DECENTRO_CLIENT_SECRET:
        return None

    url = _DECENTRO_ENDPOINT.format(base=settings.DECENTRO_BASE_URL.rstrip("/"))
    headers = {
        "client_id": settings.DECENTRO_CLIENT_ID,
        "client_secret": settings.DECENTRO_CLIENT_SECRET,
        "module_secret": settings.DECENTRO_MODULE_SECRET,
        "Content-Type": "application/json",
    }
    body = {
        "reference_id": f"gstin-verify-{gstin}",
        "document_type": "GSTIN",
        "id_number": gstin,
        "consent": "Y",
        "consent_purpose": "GSTIN verification for vendor onboarding",
    }
    try:
        response = requests.post(url, headers=headers, json=body, timeout=_TIMEOUT_S)
    except requests.RequestException as exc:
        logger.warning("Decentro GSTIN verification request failed for %s: %s", gstin, exc)
        return _disabled_result(f"Decentro request failed: {exc}")

    if response.status_code == 429:
        logger.warning("Decentro GSTIN verification quota exhausted (429) for %s", gstin)
        return _disabled_result("Decentro API quota exhausted (HTTP 429)")
    if response.status_code != 200:
        logger.warning("Decentro GSTIN verification returned HTTP %s for %s", response.status_code, gstin)
        return _disabled_result(f"Decentro unexpected HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError:
        return _disabled_result("Decentro response was not valid JSON")

    if str(data.get("status", "")).upper() != "SUCCESS":
        return _disabled_result(str(data.get("message") or "Decentro reported failure"))

    result = data.get("kycResult") or {}
    status = str(result.get("gstnStatus") or "").strip()
    legal_name = str(result.get("legalName") or "").strip()
    trade_name = str(result.get("tradeName") or "").strip()
    address = str(result.get("principalPlaceOfBusiness") or "").strip()
    city, state, pincode = _split_address(address)

    return GstinVerificationResult(
        checked=True,
        active=status.lower() == "active",
        legal_name=legal_name,
        trade_name=trade_name,
        status=status,
        address=address,
        city=city,
        state=state,
        pincode=pincode,
        provider="decentro",
    )


def _verify_via_gstinapi(gstin: str) -> Optional[GstinVerificationResult]:
    """Fallback provider. Returns None (not a failure result) when
    GSTIN_API_KEY isn't configured, so the caller can report whichever
    provider's error is more informative."""
    if not settings.GSTIN_API_KEY:
        return None

    url = _GSTINAPI_ENDPOINT.format(gstin=gstin)
    headers = {"x-api-key": settings.GSTIN_API_KEY, "accept": "application/json"}
    try:
        response = requests.get(url, headers=headers, params={"include": "profile"}, timeout=_TIMEOUT_S)
    except requests.RequestException as exc:
        logger.warning("gstinapi.in verification request failed for %s: %s", gstin, exc)
        return _disabled_result(f"gstinapi.in request failed: {exc}")

    if response.status_code == 429:
        logger.warning("gstinapi.in verification quota exhausted (429) for %s", gstin)
        return _disabled_result("gstinapi.in quota exhausted (HTTP 429)")
    if response.status_code != 200:
        logger.warning("gstinapi.in verification returned HTTP %s for %s", response.status_code, gstin)
        return _disabled_result(f"gstinapi.in unexpected HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError:
        return _disabled_result("gstinapi.in response was not valid JSON")

    # gstinapi.in's profile response nests the registry fields under "data"
    # (confirmed against a real live response, GSTIN 19AABCM7980K1ZU) -- kept
    # defensive (dict.get chains) with "profile" as a fallback shape.
    if not data.get("success", True):
        return _disabled_result(str(data.get("message") or "gstinapi.in reported failure"))
    profile = data.get("data") or data.get("profile") or {}
    status = str(profile.get("status") or profile.get("gstin_status") or "").strip()
    legal_name = str(profile.get("legal_name") or profile.get("lgnm") or "").strip()
    trade_name = str(profile.get("trade_name") or profile.get("tradeNam") or "").strip()
    address = str(profile.get("address") or profile.get("pradr") or "").strip()
    city = str(profile.get("city") or "").strip()
    pincode = str(profile.get("pincode") or "").strip()

    return GstinVerificationResult(
        checked=True,
        active=status.lower() == "active",
        legal_name=legal_name,
        trade_name=trade_name,
        status=status,
        address=address,
        city=city,
        pincode=pincode,
        provider="gstinapi",
    )


def verify_gstin(gstin: str) -> GstinVerificationResult:
    """Look up `gstin` in the live GST registry: Decentro first, falling
    back to gstinapi.in if Decentro isn't configured or its call doesn't
    succeed. Returns checked=False (never raises) when the feature is
    disabled, the GSTIN is empty/malformed, neither provider is configured,
    or both calls fail -- a failed live check must never block or crash
    extraction, it is an additional signal layered on top of the existing
    format validation, not a replacement for it."""
    if not settings.GSTIN_API_ENABLED:
        return _disabled_result("GSTIN live verification is disabled (GSTIN_API_ENABLED=false)")
    gstin = (gstin or "").strip().upper()
    if len(gstin) != 15:
        return _disabled_result(f"GSTIN {gstin!r} is not 15 characters -- skipping live check")

    decentro_result = _verify_via_decentro(gstin)
    if decentro_result is not None and decentro_result.checked:
        return decentro_result

    gstinapi_result = _verify_via_gstinapi(gstin)
    if gstinapi_result is not None:
        if gstinapi_result.checked:
            return gstinapi_result
        # Both tried and failed (or only this one was configured and failed):
        # surface its error, since it's the one that actually ran last.
        return gstinapi_result

    # Decentro was configured but failed, and gstinapi.in isn't configured --
    # surface Decentro's error rather than a generic "nothing configured".
    if decentro_result is not None:
        return decentro_result

    return _disabled_result(
        "no GSTIN verification provider is configured "
        "(set DECENTRO_CLIENT_ID/DECENTRO_CLIENT_SECRET or GSTIN_API_KEY)"
    )
