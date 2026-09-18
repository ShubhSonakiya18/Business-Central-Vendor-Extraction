"""Live GSTIN verification against the GST registry, via gstinapi.in.

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

Gated by settings.GSTIN_API_ENABLED (default False): the vendor's free-tier
key is capped at 50 requests total, so this must not fire during ordinary
extraction runs/tests unless explicitly turned on -- the same lesson already
learned the hard way with Gemini's 20-request/day quota (see CLAUDE.md).

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

import requests

from app.config.config import settings

logger = logging.getLogger(__name__)

_ENDPOINT = "https://www.gstinapi.in/v1/gstin/{gstin}"
_TIMEOUT_S = 10


@dataclass
class GstinVerificationResult:
    checked: bool               # True if the API call actually ran and returned data
    active: bool = False        # True if the registry marks this GSTIN as active
    legal_name: str = ""        # registered legal name, for comparison against the extracted vendor/customer name
    status: str = ""            # raw registry status string (e.g. "Active", "Cancelled")
    error: str = ""             # set when checked=False -- why no result is available


def _disabled_result(reason: str) -> GstinVerificationResult:
    return GstinVerificationResult(checked=False, error=reason)


def verify_gstin(gstin: str) -> GstinVerificationResult:
    """Look up `gstin` in the live GST registry. Returns checked=False (never
    raises) when the feature is disabled, the GSTIN is empty/malformed, the
    API key is missing, or the call fails for any reason -- a failed live
    check must never block or crash extraction, it is an additional signal
    layered on top of the existing format validation, not a replacement for
    it."""
    if not settings.GSTIN_API_ENABLED:
        return _disabled_result("GSTIN live verification is disabled (GSTIN_API_ENABLED=false)")
    if not settings.GSTIN_API_KEY:
        return _disabled_result("GSTIN_API_KEY is not configured")
    gstin = (gstin or "").strip().upper()
    if len(gstin) != 15:
        return _disabled_result(f"GSTIN {gstin!r} is not 15 characters -- skipping live check")

    url = _ENDPOINT.format(gstin=gstin)
    headers = {"x-api-key": settings.GSTIN_API_KEY, "accept": "application/json"}
    try:
        response = requests.get(url, headers=headers, params={"include": "profile"}, timeout=_TIMEOUT_S)
    except requests.RequestException as exc:
        logger.warning("GSTIN verification request failed for %s: %s", gstin, exc)
        return _disabled_result(f"request failed: {exc}")

    if response.status_code == 429:
        logger.warning("GSTIN verification quota exhausted (429) for %s", gstin)
        return _disabled_result("API quota exhausted (HTTP 429)")
    if response.status_code != 200:
        logger.warning("GSTIN verification returned HTTP %s for %s", response.status_code, gstin)
        return _disabled_result(f"unexpected HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError:
        return _disabled_result("response was not valid JSON")

    # gstinapi.in's profile response nests the registry fields under
    # "profile" -- kept defensive (dict.get chains, no assumed shape) since
    # the exact field names have not been confirmed against a live response
    # for every GSTIN status yet (see TODO-style note in bc_mapper.py for a
    # similar "unconfirmed against live server" caveat in this codebase).
    profile = data.get("profile") or data.get("data") or {}
    status = str(profile.get("gstin_status") or profile.get("status") or "").strip()
    legal_name = str(profile.get("legal_name") or profile.get("lgnm") or "").strip()

    return GstinVerificationResult(
        checked=True,
        active=status.lower() == "active",
        legal_name=legal_name,
        status=status,
    )
