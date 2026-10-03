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

  1. Decentro's KYC validate API, document_type GSTIN_DETAILED (primary,
     STAGING for now -- see docs/GSTIN_VERIFICATION.md). ONE call returns the
     registry's business data plus the detailed KYB data. The document type and
     generate_pdf=false are fixed constants below, deliberately not settings, so
     the integration cannot be silently downgraded to basic GSTIN or start
     generating PDFs. Authentication is client_id + client_secret, as the
     GSTIN_DETAILED documentation lists; DECENTRO_MODULE_SECRET is NOT sent
     (it stays in Settings only so existing .env files still load).
  2. gstinapi.in (fallback). Used only when Decentro is not configured or the
     CALL failed (network error, HTTP 400/401/402/429/5xx, malformed response).
     A successful Decentro answer is never replaced by the fallback, whatever
     the business status: Active, Cancelled, Suspended and "no record found"
     are all valid verification results.

     A fallback is never mistaken for "Decentro works": every Decentro failure
     is logged with a category, and the fallback's result carries
     `primary_error` saying why Decentro did not answer.

Usage:
    from app.services.gstin_verification import verify_gstin
    result = verify_gstin("19AABCM7980K1ZU")
    if result.checked and not result.active:
        # flag for review -- GSTIN is registered but cancelled/suspended
        ...
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import requests

from app.config.config import settings

logger = logging.getLogger(__name__)

# Decentro's KYC "Validate Document" endpoint: id_number (not "gstin") and
# consent as the STRING "Y" (a boolean is rejected with error_invalid_consent).
_DECENTRO_ENDPOINT = "{base}/kyc/public_registry/validate"
_GSTINAPI_ENDPOINT = "https://www.gstinapi.in/v1/gstin/{gstin}"
_TIMEOUT_S = 10

# Fixed on purpose -- NOT settings. GSTIN_DETAILED is mandatory for the primary
# provider (one call gives the registry data AND the KYB data; a settings value
# could silently fall back to basic GSTIN), and no PDF is wanted or stored.
_DECENTRO_DOCUMENT_TYPE = "GSTIN_DETAILED"
_DECENTRO_GENERATE_PDF = False

# Decentro's documented "no record" answer: HTTP 200, kycStatus FAILURE,
# responseCode E00021 ("No records found for the given ID"). A valid result,
# not a provider failure.
_NOT_FOUND_RESPONSE_CODE = "E00021"


@dataclass
class GstinVerificationResult:
    """Normalized GST verification result. Provider responses are mapped into
    this model and nothing else is kept -- no raw provider object is stored.
    Every new field defaults to empty, so a provider that doesn't supply it
    (gstinapi.in, or an older Decentro response) still produces a valid result."""

    checked: bool               # True if the API call actually ran and returned an answer
    active: bool = False        # True if the registry marks this GSTIN as active
    legal_name: str = ""        # registered legal name, for comparison against the extracted vendor/customer name
    trade_name: str = ""        # registered trade name, if different from the legal name
    status: str = ""            # raw registry status string (e.g. "Active", "Cancelled", "Not found")
    address: str = ""           # registered PRINCIPAL place of business, single-line
    city: str = ""              # registered city
    state: str = ""             # registered state
    pincode: str = ""           # registered PIN code
    error: str = ""             # set when checked=False -- why no result is available
    provider: str = ""          # "decentro" | "gstinapi" -- which one actually answered

    # -- diagnostics ---------------------------------------------------------
    document_type: str = ""             # "GSTIN_DETAILED" when Decentro answered
    record_found: bool = False          # False when the registry says the GSTIN doesn't exist
    reference_id: str = ""              # OUR unique reference for the Decentro call
    provider_reference_id: str = ""     # Decentro's decentroTxnId, for audit / support
    response_code: str = ""             # Decentro's responseCode
    primary_error: str = ""             # why Decentro did not answer, when the FALLBACK did

    # -- registration data (GSTIN_DETAILED) ---------------------------------------
    taxpayer_type: str = ""
    constitution_of_business: str = ""
    registration_date: str = ""
    pan: str = ""
    registration_type: str = ""
    nature_of_business: list = field(default_factory=list)
    nature_of_core_business_activity: str = ""
    annual_aggregate_turnover: str = ""
    mandatory_e_invoicing: str = ""
    gross_total_income: str = ""
    is_field_visit_conducted: str = ""
    state_jurisdiction: str = ""
    central_jurisdiction: str = ""
    central_jurisdiction_code: str = ""

    # -- KYB data (GSTIN_DETAILED) -----------------------------------------------
    business_details: list = field(default_factory=list)     # [{hsn, type, description}]
    filing_status: list = field(default_factory=list)        # [{filing_year, filing_period, ...}]
    company_master_data: dict = field(default_factory=dict)  # cinData.companyMasterData, minus emailId
    directors: list = field(default_factory=list)            # [{name, begin_date, end_date}], never DIN/PAN

    # -- additional places of business ------------------------------------------------
    # PROVISIONAL (docs/GSTIN_VERIFICATION.md): Decentro names this field but does
    # not document its entry shape. Every entry ends up in exactly ONE of these two:
    # a normalized location, or the unrecognized count. Until a real staging
    # response confirms the dict shape, a non-zero unrecognized count means the
    # integration is NOT fully verified.
    additional_places_of_business: list = field(default_factory=list)  # [{address, city, state, pincode, nature_of_business}]
    additional_places_unrecognized: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


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


# --- parsing helpers (tolerant: missing / null / empty / unexpected never raise) --

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _snake(name: str) -> str:
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def _s(value: Any) -> str:
    """Scalar -> trimmed string; None, dicts, lists and anything else -> ""."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [t for t in (_s(v) for v in value) if t]


def _dict_list(value: Any, keys: tuple[str, ...]) -> list[dict]:
    """[{camelKey: v}] -> [{snake_key: str}], one dict per dict entry."""
    if not isinstance(value, list):
        return []
    return [{_snake(k): _s(item.get(k)) for k in keys} for item in value if isinstance(item, dict)]


_BUSINESS_DETAIL_KEYS = ("hsn", "type", "description")
_FILING_STATUS_KEYS = (
    "filingYear", "filingPeriod", "filingMethod", "filingDate",
    "filingGstType", "filingAnnualReturn", "filingStatus",
)
# cinData.companyMasterData: emailId is deliberately NOT here (contact data, no use).
_COMPANY_MASTER_KEYS = (
    "cin", "companyName", "dateOfIncorporation", "registeredAddress", "companyCategory",
    "classOfCompany", "paidUpCapitalInInr", "authorisedCapitalInInr",
)
# cinData.directors[]: dinOrPan is deliberately NOT here (personal identifier).
_DIRECTOR_KEYS = ("name", "beginDate", "endDate")


def _parse_additional_places(raw: Any) -> tuple[list[dict], int]:
    """additionalPlacesOfBusinessInState -> (normalized locations, unrecognized count).

    PROVISIONAL: Decentro names this field but does not document its entry
    shape, so only a plain, non-empty string entry is treated as a location.
    Every other entry is COUNTED as unrecognized -- never silently dropped, and
    never turned into an empty placeholder location. Field names for dict
    entries (address, nature of business) are added once a real staging
    response confirms them. An absent field is "no additional places"."""
    if raw is None:
        return [], 0
    if not isinstance(raw, list):
        logger.warning("Decentro additionalPlacesOfBusinessInState is %s, not a list; "
                       "reported as 1 unrecognized entry", type(raw).__name__)
        return [], 1
    places: list[dict] = []
    unrecognized = 0
    unrecognized_types: set[str] = set()
    for entry in raw:
        text = entry.strip() if isinstance(entry, str) else ""
        if text:
            city, state, pincode = _split_address(text)
            places.append({"address": text, "city": city, "state": state,
                           "pincode": pincode, "nature_of_business": ""})
        else:
            unrecognized += 1
            unrecognized_types.add(type(entry).__name__)
    if unrecognized:
        # Type names and a count only -- never the entry's content.
        logger.warning("Decentro additionalPlacesOfBusinessInState: %d of %d entries not "
                       "recognized (entry types: %s)", unrecognized, len(raw),
                       ", ".join(sorted(unrecognized_types)))
    return places, unrecognized


def _normalize_decentro(data: dict, kyc: dict, reference_id: str) -> GstinVerificationResult:
    """Decentro GSTIN_DETAILED `kycResult` -> the normalized model."""
    status = _s(kyc.get("gstnStatus"))
    address = _s(kyc.get("principalPlaceOfBusiness"))
    city, state, pincode = _split_address(address)

    cin = kyc.get("cinData")
    cin = cin if isinstance(cin, dict) else {}
    master = cin.get("companyMasterData")
    master = master if isinstance(master, dict) else {}
    places, unrecognized = _parse_additional_places(kyc.get("additionalPlacesOfBusinessInState"))

    return GstinVerificationResult(
        checked=True,
        active=status.lower() == "active",
        legal_name=_s(kyc.get("legalName")),
        trade_name=_s(kyc.get("tradeName")),
        status=status,
        address=address,
        city=city,
        state=state,
        pincode=pincode,
        provider="decentro",
        document_type=_DECENTRO_DOCUMENT_TYPE,
        record_found=True,
        reference_id=reference_id,
        provider_reference_id=_s(data.get("decentroTxnId")),
        response_code=_token(data.get("responseCode")),
        taxpayer_type=_s(kyc.get("taxpayerType")),
        constitution_of_business=_s(kyc.get("constitutionOfBusiness")),
        registration_date=_s(kyc.get("registrationDate")),
        pan=_s(kyc.get("pan")),
        registration_type=_s(kyc.get("registrationType")),
        nature_of_business=_str_list(kyc.get("natureOfBusiness")),
        nature_of_core_business_activity=_s(kyc.get("natureOfCoreBusinessActivity")),
        annual_aggregate_turnover=_s(kyc.get("annualAggregateTurnover")),
        mandatory_e_invoicing=_s(kyc.get("mandatoryEInvoicing")),
        gross_total_income=_s(kyc.get("grossTotalIncome")),
        is_field_visit_conducted=_s(kyc.get("isFieldVisitConducted")),
        state_jurisdiction=_s(kyc.get("stateJurisdiction")),
        central_jurisdiction=_s(kyc.get("centralJurisdiction")),
        central_jurisdiction_code=_s(kyc.get("centralJurisdictionCode")),
        business_details=_dict_list(kyc.get("businessDetails"), _BUSINESS_DETAIL_KEYS),
        filing_status=_dict_list(kyc.get("filingStatus"), _FILING_STATUS_KEYS),
        company_master_data={_snake(k): _s(master.get(k)) for k in _COMPANY_MASTER_KEYS} if master else {},
        directors=_dict_list(cin.get("directors"), _DIRECTOR_KEYS),
        additional_places_of_business=places,
        additional_places_unrecognized=unrecognized,
    )


# --- Decentro call -----------------------------------------------------------

_TOKEN_NOT_OK = re.compile(r"[^A-Za-z0-9_.\-]")


def _token(value: Any) -> str:
    """A short, safe identifier (responseCode / responseKey) for logs and error
    text. Anything else a provider sends back is never echoed."""
    return _TOKEN_NOT_OK.sub("", _s(value))[:64]


# Failures that mean OUR configuration is wrong (not a transient outage) are
# logged at ERROR so they are not mistaken for ordinary fallback noise.
_ERROR_LEVEL_CATEGORIES = {"auth_rejected", "insufficient_balance"}


def _http_failure_category(status_code: int) -> str:
    if status_code == 400:
        return "request_rejected"
    if status_code in (401, 403):
        return "auth_rejected"
    if status_code == 402:
        return "insufficient_balance"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "server_error"
    return "unexpected_http_status"


def _decentro_failure(
    category: str, gstin: str, reference_id: str,
    http_status: Optional[int] = None, response_code: str = "", response_key: str = "",
) -> GstinVerificationResult:
    """A PROVIDER failure (not a registry answer): logged on every occurrence,
    returned as checked=False so verify_gstin() falls back. Only the category,
    HTTP status and Decentro's short responseCode / responseKey are logged or
    returned -- never headers, the request body, or exception text."""
    message = f"Decentro {category}"
    if http_status is not None:
        message += f" (HTTP {http_status})"
    if response_code:
        message += f" [{response_code}]"
    logger.log(
        logging.ERROR if category in _ERROR_LEVEL_CATEGORIES else logging.WARNING,
        "Decentro %s verification failed: category=%s http=%s response_code=%s "
        "response_key=%s reference_id=%s gstin=%s",
        _DECENTRO_DOCUMENT_TYPE, category, http_status, response_code or "-",
        response_key or "-", reference_id, gstin,
    )
    return GstinVerificationResult(
        checked=False, error=message, document_type=_DECENTRO_DOCUMENT_TYPE,
        reference_id=reference_id, response_code=response_code,
    )


def _verify_via_decentro(gstin: str) -> Optional[GstinVerificationResult]:
    """ONE GSTIN_DETAILED call, never retried (a retry could double-bill).

    Returns None (not a failure result) when Decentro isn't configured at all,
    so the caller falls back. Otherwise: checked=True for ANY registry answer
    (Active, Cancelled, Suspended, or "no record found" -- the fallback must not
    hide those), checked=False only for a provider/API failure."""
    if not settings.DECENTRO_CLIENT_ID or not settings.DECENTRO_CLIENT_SECRET:
        return None

    reference_id = f"gst-{uuid.uuid4().hex}"
    url = _DECENTRO_ENDPOINT.format(base=settings.DECENTRO_BASE_URL.rstrip("/"))
    # client_id + client_secret are the documented GSTIN_DETAILED credentials.
    # module_secret is NOT sent: only add it if Decentro confirms this account
    # needs it, and record that confirmation in docs/GSTIN_VERIFICATION.md.
    headers = {
        "client_id": settings.DECENTRO_CLIENT_ID,
        "client_secret": settings.DECENTRO_CLIENT_SECRET,
        "Content-Type": "application/json",
    }
    body = {
        "reference_id": reference_id,
        "document_type": _DECENTRO_DOCUMENT_TYPE,
        "id_number": gstin,
        "consent": "Y",
        "consent_purpose": "GSTIN verification for vendor onboarding",
        "generate_pdf": _DECENTRO_GENERATE_PDF,
    }
    try:
        response = requests.post(url, headers=headers, json=body, timeout=_TIMEOUT_S)
    except requests.Timeout:
        return _decentro_failure("timeout", gstin, reference_id)
    except requests.ConnectionError:
        return _decentro_failure("connection_error", gstin, reference_id)
    except requests.RequestException as exc:
        logger.warning("Decentro request raised %s", type(exc).__name__)
        return _decentro_failure("request_error", gstin, reference_id)

    try:
        data = response.json()
    except ValueError:
        data = None
    data = data if isinstance(data, dict) else {}
    response_code = _token(data.get("responseCode"))
    response_key = _token(data.get("responseKey"))

    if response.status_code != 200:
        category = _http_failure_category(response.status_code)
        if "credit" in response_key.lower():
            # e.g. HTTP 401 + error_module_credits_exhausted: the account has no
            # credits left for this module -- not a wrong credential.
            category = "insufficient_balance"
        return _decentro_failure(
            category, gstin, reference_id,
            http_status=response.status_code, response_code=response_code, response_key=response_key,
        )
    if not data:
        return _decentro_failure("malformed_response", gstin, reference_id, http_status=200)

    # A genuine registry "no record": a VALID answer, so no fallback.
    if response_code == _NOT_FOUND_RESPONSE_CODE or "no records found" in _s(data.get("message")).lower():
        return GstinVerificationResult(
            checked=True, active=False, status="Not found", provider="decentro",
            document_type=_DECENTRO_DOCUMENT_TYPE, record_found=False,
            reference_id=reference_id, response_code=response_code,
            provider_reference_id=_s(data.get("decentroTxnId")),
        )

    if "status" not in data:
        return _decentro_failure("malformed_response", gstin, reference_id,
                                 http_status=200, response_code=response_code)
    if _s(data.get("status")).upper() != "SUCCESS" or _s(data.get("kycStatus")).upper() == "FAILURE":
        return _decentro_failure("provider_failure", gstin, reference_id, http_status=200,
                                 response_code=response_code, response_key=response_key)

    kyc = data.get("kycResult")
    if not isinstance(kyc, dict):
        return _decentro_failure("malformed_response", gstin, reference_id,
                                 http_status=200, response_code=response_code)
    return _normalize_decentro(data, kyc, reference_id)


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
        record_found=True,
    )


def verify_gstin(gstin: str) -> GstinVerificationResult:
    """Look up `gstin` in the live GST registry: Decentro (GSTIN_DETAILED) first,
    gstinapi.in only when Decentro is not configured or its CALL failed.

    A successful Decentro answer -- including Cancelled / Suspended / "not found"
    -- is returned as is and never replaced by the fallback. Returns
    checked=False (never raises) when the feature is disabled, the GSTIN is
    empty/malformed, neither provider is configured, or both calls fail -- a
    failed live check must never block or crash extraction, it is an additional
    signal layered on top of the existing format validation.

    When the fallback answers, its result carries `primary_error` (why Decentro
    did not), so a fallback is never mistaken for a working primary provider."""
    if not settings.GSTIN_API_ENABLED:
        return _disabled_result("GSTIN live verification is disabled (GSTIN_API_ENABLED=false)")
    gstin = (gstin or "").strip().upper()
    if len(gstin) != 15:
        return _disabled_result(f"GSTIN {gstin!r} is not 15 characters -- skipping live check")

    decentro_result = _verify_via_decentro(gstin)
    if decentro_result is not None and decentro_result.checked:
        return decentro_result

    primary_error = (
        decentro_result.error if decentro_result is not None
        else "Decentro not configured (DECENTRO_CLIENT_ID / DECENTRO_CLIENT_SECRET)"
    )
    gstinapi_result = _verify_via_gstinapi(gstin)
    if gstinapi_result is not None:
        gstinapi_result.primary_error = primary_error
        if not gstinapi_result.checked:
            # Both providers failed: report both reasons.
            gstinapi_result.error = f"{primary_error}; fallback: {gstinapi_result.error}"
        return gstinapi_result

    # Decentro was configured but failed, and gstinapi.in isn't configured --
    # surface Decentro's error rather than a generic "nothing configured".
    if decentro_result is not None:
        return decentro_result

    return _disabled_result(
        "no GSTIN verification provider is configured "
        "(set DECENTRO_CLIENT_ID/DECENTRO_CLIENT_SECRET or GSTIN_API_KEY)"
    )
