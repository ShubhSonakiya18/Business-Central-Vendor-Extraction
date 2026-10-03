"""GST verification: Decentro GSTIN_DETAILED (primary) with the gstinapi.in fallback.

Nothing here touches the network: `requests.post/get` are replaced by a fake
that records every call and returns whatever the test queued. conftest.py also
forces GSTIN_API_ENABLED off for every test; the `configured` fixture turns it
back on together with dummy credentials.

Fixtures cover only fields Decentro DOCUMENTS. `additionalPlacesOfBusinessInState`
has no documented entry shape, so it is tested only through generic defensive
cases -- exact-shape tests are added after a real staging response is captured
(docs/GSTIN_VERIFICATION.md, "Pending live verification").
"""

from __future__ import annotations

import json
import logging

import pytest
import requests

from app.config.config import Settings, settings
from app.models.model import Vendor  # noqa: F401  (imported so model metadata loads, as elsewhere)
from app.services import gstin_verification as gv
from app.services.extraction_pipeline.models import ExtractionResult, FieldResult
from app.services.gstin_verification import GstinVerificationResult, verify_gstin

GSTIN = "29AAAAA0000A1Z5"          # dummy, well-formed (15 characters)
CLIENT_ID = "dummy-client-id-0001"
CLIENT_SECRET = "SECRET-client-VALUE-123"
MODULE_SECRET = "SECRET-module-VALUE-456"
API_KEY = "SECRET-apikey-VALUE-789"
SECRETS = (CLIENT_SECRET, MODULE_SECRET, API_KEY)
STAGING = "https://in.staging.decentro.tech"


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class FakeHttp:
    """Records every call; `post_result` / `get_result` are a FakeResponse, an
    exception to raise, or None (= the test did not expect that call)."""

    def __init__(self):
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self.post_result = None
        self.get_result = None

    @staticmethod
    def _resolve(result, what):
        if result is None:
            raise AssertionError(f"unexpected HTTP {what} call")
        if isinstance(result, Exception):
            raise result
        return result

    def post(self, url, **kwargs):
        self.post_calls.append({"url": url, **kwargs})
        return self._resolve(self.post_result, "POST (Decentro)")

    def get(self, url, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        return self._resolve(self.get_result, "GET (gstinapi.in)")


@pytest.fixture
def http(monkeypatch):
    fake = FakeHttp()
    monkeypatch.setattr(gv.requests, "post", fake.post)
    monkeypatch.setattr(gv.requests, "get", fake.get)
    return fake


@pytest.fixture
def configured(monkeypatch):
    """Verification on, both providers configured, staging URL."""
    monkeypatch.setattr(settings, "GSTIN_API_ENABLED", True)
    monkeypatch.setattr(settings, "DECENTRO_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "DECENTRO_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setattr(settings, "DECENTRO_MODULE_SECRET", MODULE_SECRET)
    monkeypatch.setattr(settings, "DECENTRO_BASE_URL", STAGING)
    monkeypatch.setattr(settings, "GSTIN_API_KEY", API_KEY)


def decentro_sample() -> dict:
    """The GSTIN_DETAILED success body from Decentro's API reference, with
    dummy values. Includes the fields we deliberately do NOT keep (emailId,
    dinOrPan, charges, pdf) so the exclusions are tested."""
    return {
        "kycStatus": "SUCCESS",
        "status": "SUCCESS",
        "message": "KYC Details for GSTIN_DETAILED retrieved successfully",
        "kycResult": {
            "gstin": GSTIN,
            "legalName": "DUMMY TRADERS PRIVATE LIMITED",
            "stateJurisdiction": "LGSTO 045 - Bengaluru",
            "centralJurisdiction": "RANGE-AED2",
            "centralJurisdictionCode": "YT0201",
            "constitutionOfBusiness": "Private Limited Company",
            "taxpayerType": "Regular",
            "natureOfBusiness": ["Export", "Supplier of Services", "Import"],
            "natureOfCoreBusinessActivity": "Service Provider and Others",
            "annualAggregateTurnover": "Slab: Rs. 5 Cr. to 25 Cr.",
            "gstnStatus": "Active",
            "tradeName": "DUMMY TRADERS",
            "registrationDate": "04/09/2020",
            "principalPlaceOfBusiness": "Indiranagar, Bengaluru, Bengaluru Urban, Karnataka, 560038",
            "pan": "AAAAA0000A",
            "registrationType": "NORMAL COMPOSITE CASUAL",
            "mandatoryEInvoicing": "Yes",
            "businessDetails": [{"hsn": "998311", "type": "Services", "description": "Management consulting"}],
            "filingStatus": [{
                "filingYear": "2024-25", "filingPeriod": "April", "filingMethod": "ONLINE",
                "filingDate": "20/05/2024", "filingGstType": "GSTR3B",
                "filingAnnualReturn": "N", "filingStatus": "Filed",
            }],
            "cinData": {
                "charges": [{"someChargeField": "CHARGE-DETAIL-NOT-KEPT"}],
                "directors": [{"endDate": "-", "dinOrPan": "DIN-0000001", "beginDate": "01/01/2020",
                               "name": "DUMMY DIRECTOR"}],
                "companyMasterData": {
                    "companyCategory": "Company limited by Shares", "emailId": "contact@dummy.invalid",
                    "classOfCompany": "Private", "cin": "U00000KA2020PTC000000",
                    "companyName": "DUMMY TRADERS PRIVATE LIMITED", "dateOfIncorporation": "04/09/2020",
                    "registeredAddress": "Indiranagar, Bengaluru, Karnataka, 560038",
                    "paidUpCapitalInInr": "100000", "authorisedCapitalInInr": "500000",
                },
            },
            "pdf": "PDF-CONTENT-NOT-KEPT",
        },
        "responseKey": "success_gstin_detailed",
        "responseCode": "S00000",
        "requestTimestamp": "2024-06-09 17:42:21 IST",
        "responseTimestamp": "2024-06-09 17:42:22 IST",
        "decentroTxnId": "DTXN-0001",
    }


def ok(payload=None) -> FakeResponse:
    return FakeResponse(200, decentro_sample() if payload is None else payload)


def gstinapi_ok(status="Active") -> FakeResponse:
    return FakeResponse(200, {"success": True, "data": {
        "status": status, "legal_name": "FALLBACK LEGAL NAME", "trade_name": "FALLBACK TRADE",
        "address": "1 Fallback Road", "city": "Pune", "pincode": "411001",
    }})


def kyc_with(**overrides) -> dict:
    payload = decentro_sample()
    payload["kycResult"].update(overrides)
    return payload


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

class TestConfiguration:
    def test_decentro_base_url_defaults_to_staging(self):
        assert Settings.model_fields["DECENTRO_BASE_URL"].default == STAGING

    def test_document_type_and_pdf_are_fixed_not_settings(self):
        """GSTIN_DETAILED and generate_pdf=false cannot be reconfigured away."""
        assert gv._DECENTRO_DOCUMENT_TYPE == "GSTIN_DETAILED"
        assert gv._DECENTRO_GENERATE_PDF is False
        names = set(Settings.model_fields)
        assert not {n for n in names if "DOCUMENT_TYPE" in n or "GENERATE_PDF" in n}


# ---------------------------------------------------------------------------
# request construction
# ---------------------------------------------------------------------------

class TestRequest:
    def test_one_gstin_detailed_call_with_documented_body(self, configured, http):
        http.post_result = ok()
        result = verify_gstin(GSTIN.lower())          # normalised to upper case
        assert result.provider == "decentro"

        assert len(http.post_calls) == 1               # exactly one Decentro attempt
        assert http.get_calls == []                    # and no fallback call
        call = http.post_calls[0]
        assert call["url"] == f"{STAGING}/kyc/public_registry/validate"
        body = call["json"]
        assert body["document_type"] == "GSTIN_DETAILED"
        assert body["id_number"] == GSTIN
        assert body["consent"] == "Y"
        assert len(body["consent_purpose"]) > 20
        assert body["generate_pdf"] is False
        assert body["reference_id"]

    def test_base_url_comes_from_settings(self, configured, http, monkeypatch):
        monkeypatch.setattr(settings, "DECENTRO_BASE_URL", "https://example.invalid/")
        http.post_result = ok()
        verify_gstin(GSTIN)
        assert http.post_calls[0]["url"] == "https://example.invalid/kyc/public_registry/validate"

    def test_auth_headers_are_client_id_and_secret_only(self, configured, http):
        http.post_result = ok()
        verify_gstin(GSTIN)
        headers = http.post_calls[0]["headers"]
        assert set(headers) == {"client_id", "client_secret", "Content-Type"}
        assert headers["client_id"] == CLIENT_ID
        assert headers["client_secret"] == CLIENT_SECRET
        # module_secret is configured, yet never sent
        assert MODULE_SECRET not in headers.values()
        assert "module_secret" not in headers

    def test_reference_id_is_unique_and_does_not_contain_the_gstin(self, configured, http):
        http.post_result = ok()
        verify_gstin(GSTIN)
        verify_gstin(GSTIN)
        first, second = (c["json"]["reference_id"] for c in http.post_calls)
        assert first != second
        assert GSTIN not in first and GSTIN not in second

    def test_no_retry_on_failure(self, configured, http):
        http.post_result = FakeResponse(503, {})
        http.get_result = gstinapi_ok()
        verify_gstin(GSTIN)
        assert len(http.post_calls) == 1               # one Decentro attempt, then the fallback


# ---------------------------------------------------------------------------
# response parsing
# ---------------------------------------------------------------------------

class TestParsing:
    def test_full_documented_sample(self, configured, http):
        http.post_result = ok()
        r = verify_gstin(GSTIN)

        assert (r.checked, r.active, r.record_found, r.provider) == (True, True, True, "decentro")
        assert r.document_type == "GSTIN_DETAILED"
        assert (r.legal_name, r.trade_name, r.status) == (
            "DUMMY TRADERS PRIVATE LIMITED", "DUMMY TRADERS", "Active")
        assert r.address == "Indiranagar, Bengaluru, Bengaluru Urban, Karnataka, 560038"
        assert (r.city, r.state, r.pincode) == ("Bengaluru Urban", "Karnataka", "560038")
        assert (r.taxpayer_type, r.constitution_of_business, r.registration_date, r.pan) == (
            "Regular", "Private Limited Company", "04/09/2020", "AAAAA0000A")
        assert r.registration_type == "NORMAL COMPOSITE CASUAL"
        assert r.nature_of_business == ["Export", "Supplier of Services", "Import"]
        assert r.nature_of_core_business_activity == "Service Provider and Others"
        assert r.annual_aggregate_turnover == "Slab: Rs. 5 Cr. to 25 Cr."
        assert r.mandatory_e_invoicing == "Yes"
        assert (r.state_jurisdiction, r.central_jurisdiction, r.central_jurisdiction_code) == (
            "LGSTO 045 - Bengaluru", "RANGE-AED2", "YT0201")
        assert r.business_details == [{"hsn": "998311", "type": "Services",
                                       "description": "Management consulting"}]
        assert r.filing_status == [{
            "filing_year": "2024-25", "filing_period": "April", "filing_method": "ONLINE",
            "filing_date": "20/05/2024", "filing_gst_type": "GSTR3B",
            "filing_annual_return": "N", "filing_status": "Filed"}]
        assert r.company_master_data["cin"] == "U00000KA2020PTC000000"
        assert r.company_master_data["registered_address"] == "Indiranagar, Bengaluru, Karnataka, 560038"
        assert r.company_master_data["paid_up_capital_in_inr"] == "100000"
        assert r.directors == [{"name": "DUMMY DIRECTOR", "begin_date": "01/01/2020", "end_date": "-"}]
        assert (r.provider_reference_id, r.response_code) == ("DTXN-0001", "S00000")
        assert r.primary_error == ""

    def test_excluded_fields_never_reach_the_normalized_output(self, configured, http):
        http.post_result = ok()
        dumped = json.dumps(verify_gstin(GSTIN).to_dict())
        for excluded in ("dinOrPan", "din_or_pan", "DIN-0000001", "contact@dummy.invalid",
                         "email_id", "CHARGE-DETAIL-NOT-KEPT", "PDF-CONTENT-NOT-KEPT"):
            assert excluded not in dumped, excluded

    def test_optional_fields_missing(self, configured, http):
        http.post_result = ok({"status": "SUCCESS", "kycStatus": "SUCCESS",
                               "kycResult": {"gstnStatus": "Active", "legalName": "ONLY NAME"}})
        r = verify_gstin(GSTIN)
        assert (r.checked, r.active, r.legal_name) == (True, True, "ONLY NAME")
        assert (r.directors, r.business_details, r.filing_status) == ([], [], [])
        assert r.company_master_data == {}
        assert (r.annual_aggregate_turnover, r.mandatory_e_invoicing) == ("", "")
        assert (r.additional_places_of_business, r.additional_places_unrecognized) == ([], 0)

    def test_optional_fields_null_or_wrong_type(self, configured, http):
        http.post_result = ok(kyc_with(
            tradeName=None, natureOfBusiness=None, businessDetails=None, filingStatus="oops",
            cinData=None, annualAggregateTurnover=None, mandatoryEInvoicing=None,
            principalPlaceOfBusiness=None, taxpayerType={"unexpected": "dict"}))
        r = verify_gstin(GSTIN)
        assert r.checked and r.record_found
        assert (r.trade_name, r.address, r.taxpayer_type) == ("", "", "")
        assert (r.nature_of_business, r.business_details, r.filing_status, r.directors) == ([], [], [], [])
        assert r.company_master_data == {}

    def test_empty_lists_and_missing_directors(self, configured, http):
        sample = decentro_sample()
        sample["kycResult"]["cinData"] = {"charges": [], "directors": [], "companyMasterData": {}}
        sample["kycResult"]["natureOfBusiness"] = []
        http.post_result = ok(sample)
        r = verify_gstin(GSTIN)
        assert (r.directors, r.nature_of_business, r.company_master_data) == ([], [], {})

    def test_unexpected_extra_fields_are_ignored(self, configured, http):
        sample = decentro_sample()
        sample["kycResult"]["brandNewField"] = {"a": [1, 2, 3]}
        sample["somethingElse"] = "x"
        http.post_result = ok(sample)
        r = verify_gstin(GSTIN)
        assert r.checked and r.legal_name == "DUMMY TRADERS PRIVATE LIMITED"
        assert "brandNewField" not in json.dumps(r.to_dict())

    def test_address_that_does_not_split_keeps_the_full_text(self, configured, http):
        http.post_result = ok(kyc_with(principalPlaceOfBusiness="Some Odd Address Text"))
        r = verify_gstin(GSTIN)
        assert r.address == "Some Odd Address Text"
        assert (r.city, r.state, r.pincode) == ("", "", "")


# ---------------------------------------------------------------------------
# additional places of business (PROVISIONAL shape -- generic cases only)
# ---------------------------------------------------------------------------

class TestAdditionalPlaces:
    PLACE = "Plot 9, Industrial Estate, Hosur, Krishnagiri, Tamil Nadu, 635109"

    def _verify(self, http, **kyc):
        http.post_result = ok(kyc_with(**kyc))
        return verify_gstin(GSTIN)

    def test_absent_means_none(self, configured, http):
        r = self._verify(http)
        assert (r.additional_places_of_business, r.additional_places_unrecognized) == ([], 0)

    @pytest.mark.parametrize("value", [None, []])
    def test_null_or_empty_list_means_none(self, configured, http, value):
        r = self._verify(http, additionalPlacesOfBusinessInState=value)
        assert (r.additional_places_of_business, r.additional_places_unrecognized) == ([], 0)

    def test_string_entry_is_normalized(self, configured, http):
        r = self._verify(http, additionalPlacesOfBusinessInState=[self.PLACE])
        assert r.additional_places_unrecognized == 0
        assert r.additional_places_of_business == [{
            "address": self.PLACE, "city": "Krishnagiri", "state": "Tamil Nadu",
            "pincode": "635109", "nature_of_business": ""}]

    def test_multiple_string_entries_all_kept_in_order(self, configured, http):
        places = [self.PLACE, "Shop 2, Main Road, Pune, Maharashtra, 411001"]
        r = self._verify(http, additionalPlacesOfBusinessInState=places)
        assert [p["address"] for p in r.additional_places_of_business] == places
        assert r.additional_places_unrecognized == 0

    def test_unrecognised_entries_are_counted_never_dropped_or_faked(self, configured, http, caplog):
        entries = [{"x": "SECRET-ENTRY-CONTENT"}, 42, "", None, self.PLACE]
        with caplog.at_level(logging.WARNING):
            r = self._verify(http, additionalPlacesOfBusinessInState=entries)
        # one real location, and NO empty placeholder for the rest
        assert [p["address"] for p in r.additional_places_of_business] == [self.PLACE]
        assert all(p["address"] for p in r.additional_places_of_business)
        assert r.additional_places_unrecognized == 4
        # nothing is silently lost: normalized + unrecognized == entries received
        assert len(r.additional_places_of_business) + r.additional_places_unrecognized == len(entries)
        # warned about it, with types and a count only -- never the content
        assert "4 of 5 entries not recognized" in caplog.text
        assert "SECRET-ENTRY-CONTENT" not in caplog.text

    def test_non_list_value_is_one_unrecognized_entry(self, configured, http):
        r = self._verify(http, additionalPlacesOfBusinessInState={"x": 1})
        assert (r.additional_places_of_business, r.additional_places_unrecognized) == ([], 1)


# ---------------------------------------------------------------------------
# registry answers -- valid results that must NOT trigger the fallback
# ---------------------------------------------------------------------------

class TestRegistryAnswersAreNotProviderFailures:
    @pytest.mark.parametrize("status", ["Cancelled", "Suspended", "Inactive"])
    def test_inactive_statuses_are_valid_answers(self, configured, http, status):
        http.post_result = ok(kyc_with(gstnStatus=status))
        r = verify_gstin(GSTIN)
        assert (r.checked, r.active, r.record_found, r.status) == (True, False, True, status)
        assert r.provider == "decentro" and r.primary_error == ""
        assert http.get_calls == []                    # fallback NOT used

    def test_not_found_by_response_code_is_a_valid_answer(self, configured, http):
        http.post_result = FakeResponse(200, {
            "status": "FAILURE", "kycStatus": "FAILURE", "responseCode": "E00021",
            "responseKey": "error_invalid_pan", "message": "No records found for the given ID",
            "decentroTxnId": "DTXN-NF"})
        r = verify_gstin(GSTIN)
        assert (r.checked, r.active, r.record_found, r.status) == (True, False, False, "Not found")
        assert (r.provider, r.provider_reference_id, r.response_code) == ("decentro", "DTXN-NF", "E00021")
        assert http.get_calls == []                    # fallback must not hide it

    def test_not_found_by_message_alone(self, configured, http):
        http.post_result = FakeResponse(200, {"status": "FAILURE", "message": "No records found for the given ID"})
        r = verify_gstin(GSTIN)
        assert r.checked and not r.record_found
        assert http.get_calls == []

    def test_valid_decentro_result_is_never_overwritten_by_fallback(self, configured, http):
        http.post_result = ok()
        http.get_result = gstinapi_ok("Cancelled")      # would differ -- must not be called
        r = verify_gstin(GSTIN)
        assert (r.provider, r.status, r.legal_name) == ("decentro", "Active", "DUMMY TRADERS PRIVATE LIMITED")
        assert http.get_calls == []


# ---------------------------------------------------------------------------
# provider failures -- these DO fall back, observably
# ---------------------------------------------------------------------------

class TestProviderFailuresFallBack:
    @pytest.mark.parametrize("status,category", [
        (400, "request_rejected"), (401, "auth_rejected"), (403, "auth_rejected"),
        (402, "insufficient_balance"), (429, "rate_limited"),
        (500, "server_error"), (503, "server_error"), (404, "unexpected_http_status"),
    ])
    def test_http_failures(self, configured, http, caplog, status, category):
        http.post_result = FakeResponse(status, {})
        http.get_result = gstinapi_ok()
        with caplog.at_level(logging.WARNING):
            r = verify_gstin(GSTIN)
        assert (r.checked, r.provider) == (True, "gstinapi")
        assert category in r.primary_error and f"HTTP {status}" in r.primary_error
        assert len(http.get_calls) == 1
        assert f"category={category}" in caplog.text

    def test_credits_exhausted_behind_a_401_is_reported_as_balance(self, configured, http, caplog):
        http.post_result = FakeResponse(401, {"responseKey": "error_module_credits_exhausted"})
        http.get_result = gstinapi_ok()
        with caplog.at_level(logging.WARNING):
            r = verify_gstin(GSTIN)
        assert "insufficient_balance" in r.primary_error
        assert any(rec.levelno == logging.ERROR and "insufficient_balance" in rec.getMessage()
                   for rec in caplog.records)

    @pytest.mark.parametrize("exc,category", [
        (requests.exceptions.Timeout("slow"), "timeout"),
        (requests.exceptions.ConnectTimeout("slow"), "timeout"),
        (requests.exceptions.ConnectionError("refused"), "connection_error"),
        (requests.exceptions.RequestException("other"), "request_error"),
    ])
    def test_network_failures(self, configured, http, exc, category):
        http.post_result = exc
        http.get_result = gstinapi_ok()
        r = verify_gstin(GSTIN)
        assert (r.provider, r.checked) == ("gstinapi", True)
        assert category in r.primary_error

    @pytest.mark.parametrize("response,category", [
        (FakeResponse(200, None, bad_json=True), "malformed_response"),
        (FakeResponse(200, ["not", "a", "dict"]), "malformed_response"),
        (FakeResponse(200, {}), "malformed_response"),
        (FakeResponse(200, {"message": "no status key"}), "malformed_response"),
        (FakeResponse(200, {"status": "SUCCESS"}), "malformed_response"),           # no kycResult
        (FakeResponse(200, {"status": "SUCCESS", "kycResult": "text"}), "malformed_response"),
        (FakeResponse(200, {"status": "FAILURE", "responseCode": "E00099"}), "provider_failure"),
        (FakeResponse(200, {"status": "SUCCESS", "kycStatus": "FAILURE"}), "provider_failure"),
    ])
    def test_malformed_or_rejected_200s(self, configured, http, response, category):
        http.post_result = response
        http.get_result = gstinapi_ok()
        r = verify_gstin(GSTIN)
        assert (r.provider, r.checked) == ("gstinapi", True)
        assert category in r.primary_error

    def test_fallback_is_observable_in_the_result(self, configured, http):
        http.post_result = FakeResponse(401, {})
        http.get_result = gstinapi_ok()
        r = verify_gstin(GSTIN)
        assert r.provider == "gstinapi"
        assert r.primary_error == "Decentro auth_rejected (HTTP 401)"
        assert r.to_dict()["primary_error"] == r.primary_error
        assert r.document_type == ""                     # the fallback is not GSTIN_DETAILED

    def test_every_failure_is_logged_not_just_the_first(self, configured, http, caplog):
        http.post_result = FakeResponse(500, {})
        http.get_result = gstinapi_ok()
        with caplog.at_level(logging.WARNING):
            verify_gstin(GSTIN)
            verify_gstin(GSTIN)
            verify_gstin(GSTIN)
        assert caplog.text.count("Decentro GSTIN_DETAILED verification failed") == 3

    def test_auth_failure_is_logged_at_error_and_5xx_at_warning(self, configured, http, caplog):
        http.get_result = gstinapi_ok()
        with caplog.at_level(logging.WARNING):
            http.post_result = FakeResponse(401, {})
            verify_gstin(GSTIN)
            http.post_result = FakeResponse(503, {})
            verify_gstin(GSTIN)
        levels = {rec.getMessage().split("category=")[1].split()[0]: rec.levelno
                  for rec in caplog.records if "category=" in rec.getMessage()}
        assert levels == {"auth_rejected": logging.ERROR, "server_error": logging.WARNING}

    def test_decentro_not_configured_uses_fallback_and_says_so(self, configured, http, monkeypatch):
        monkeypatch.setattr(settings, "DECENTRO_CLIENT_ID", "")
        http.get_result = gstinapi_ok()
        r = verify_gstin(GSTIN)
        assert http.post_calls == []
        assert r.provider == "gstinapi"
        assert "Decentro not configured" in r.primary_error


# ---------------------------------------------------------------------------
# nothing available / nothing to verify
# ---------------------------------------------------------------------------

class TestUnavailableAndInvalidInput:
    def test_both_providers_failing(self, configured, http):
        http.post_result = FakeResponse(503, {})
        http.get_result = FakeResponse(500, {})
        r = verify_gstin(GSTIN)
        assert r.checked is False
        assert "Decentro server_error (HTTP 503)" in r.error
        assert "gstinapi.in unexpected HTTP 500" in r.error
        assert "Decentro server_error" in r.primary_error

    def test_decentro_down_and_fallback_not_configured(self, configured, http, monkeypatch):
        monkeypatch.setattr(settings, "GSTIN_API_KEY", "")
        http.post_result = requests.exceptions.ConnectionError("refused")
        r = verify_gstin(GSTIN)
        assert (r.checked, r.error) == (False, "Decentro connection_error")
        assert http.get_calls == []

    def test_nothing_configured(self, configured, http, monkeypatch):
        monkeypatch.setattr(settings, "DECENTRO_CLIENT_ID", "")
        monkeypatch.setattr(settings, "GSTIN_API_KEY", "")
        r = verify_gstin(GSTIN)
        assert r.checked is False and "no GSTIN verification provider" in r.error
        assert (http.post_calls, http.get_calls) == ([], [])

    def test_feature_off_makes_no_calls(self, configured, http, monkeypatch):
        monkeypatch.setattr(settings, "GSTIN_API_ENABLED", False)
        r = verify_gstin(GSTIN)
        assert r.checked is False and "disabled" in r.error
        assert (http.post_calls, http.get_calls) == ([], [])

    @pytest.mark.parametrize("value", [None, "", "   ", "29AAAAA0000A1Z", "29AAAAA0000A1Z55"])
    def test_missing_or_malformed_gstin_makes_no_calls(self, configured, http, value):
        r = verify_gstin(value)
        assert r.checked is False and "not 15 characters" in r.error
        assert (http.post_calls, http.get_calls) == ([], [])


# ---------------------------------------------------------------------------
# secrets never leak
# ---------------------------------------------------------------------------

class TestSecretsNeverLeak:
    @pytest.mark.parametrize("scenario", ["success", "401", "timeout_with_secret_text", "both_down"])
    def test_no_secret_in_logs_errors_or_results(self, configured, http, caplog, scenario):
        if scenario == "success":
            http.post_result = ok()
        elif scenario == "401":
            http.post_result = FakeResponse(401, {"message": f"bad {CLIENT_SECRET}"})
            http.get_result = gstinapi_ok()
        elif scenario == "timeout_with_secret_text":
            # exception text that happens to carry credentials must not be echoed
            http.post_result = requests.exceptions.Timeout(f"{CLIENT_SECRET} {MODULE_SECRET}")
            http.get_result = gstinapi_ok()
        else:
            http.post_result = requests.exceptions.RequestException(f"{CLIENT_SECRET}")
            http.get_result = FakeResponse(500, {})
        with caplog.at_level(logging.DEBUG):
            r = verify_gstin(GSTIN)
        everything = caplog.text + json.dumps(r.to_dict())
        for secret in SECRETS:
            assert secret not in everything


# ---------------------------------------------------------------------------
# consumers: vendor extraction + onboarding schema
# ---------------------------------------------------------------------------

def _extraction_result() -> ExtractionResult:
    res = ExtractionResult()
    res.fields["gst_number"] = FieldResult(key="gst_number", value=GSTIN, confidence=0.9,
                                           validation_status="valid")
    return res


def _normalized(**overrides) -> GstinVerificationResult:
    base = dict(checked=True, active=True, record_found=True, provider="decentro",
                document_type="GSTIN_DETAILED", legal_name="X", status="Active",
                address="", additional_places_of_business=[
                    {"address": "Plot 9, Hosur", "city": "", "state": "", "pincode": "",
                     "nature_of_business": ""}])
    base.update(overrides)
    return GstinVerificationResult(**base)


class TestVendorExtractionConsumer:
    @staticmethod
    def _apply(monkeypatch, verification):
        from app.services import extraction

        monkeypatch.setattr(gv, "verify_gstin", lambda _g: verification)
        res = _extraction_result()
        extraction._apply_gstin_verification(res)
        return res

    def test_normalized_result_is_kept_with_additional_places(self, monkeypatch):
        res = self._apply(monkeypatch, _normalized())
        assert res.gst_verification["provider"] == "decentro"
        assert res.gst_verification["additional_places_of_business"][0]["address"] == "Plot 9, Hosur"
        assert res.to_dict()["gst_verification"] == res.gst_verification
        assert "GST registry: active" in res.fields["gst_number"].notes

    def test_unchecked_result_adds_nothing(self, monkeypatch):
        res = self._apply(monkeypatch, GstinVerificationResult(checked=False, error="x"))
        assert res.gst_verification is None
        assert "gst_verification" not in res.to_dict()
        assert res.fields["gst_number"].notes == []

    def test_cancelled_keeps_the_not_active_marker_the_compare_page_colours_on(self, monkeypatch):
        res = self._apply(monkeypatch, _normalized(active=False, status="Cancelled"))
        f = res.fields["gst_number"]
        assert "GST registry: NOT active (Cancelled)" in f.notes
        assert f.validation_status == "warning"

    def test_not_found_is_flagged(self, monkeypatch):
        res = self._apply(monkeypatch, _normalized(active=False, record_found=False, status="Not found"))
        f = res.fields["gst_number"]
        assert any("NOT active" in n and "not found" in n for n in f.notes)
        assert "GSTIN was not found in the live GST registry" in f.validation_messages

    def test_fallback_is_called_out_on_the_field(self, monkeypatch):
        res = self._apply(monkeypatch, _normalized(
            provider="gstinapi", document_type="", primary_error="Decentro auth_rejected (HTTP 401)"))
        assert any("checked via fallback (gstinapi.in)" in n and "auth_rejected" in n
                   for n in res.fields["gst_number"].notes)

    def test_unrecognised_additional_places_are_called_out(self, monkeypatch):
        res = self._apply(monkeypatch, _normalized(additional_places_unrecognized=2))
        assert any("2 additional place(s) of business not recognised" in n
                   for n in res.fields["gst_number"].notes)

    def test_principal_address_overwrite_still_works(self, monkeypatch):
        res = self._apply(monkeypatch, _normalized(address="12 Park Street, Kolkata, West Bengal, 700016"))
        assert res.fields["address_1"].source_document == "gst_registry"
        assert res.fields["pin_code"].value == "700016"


class TestOnboardingConsumer:
    def test_schema_exposes_the_normalized_model(self, monkeypatch):
        from app.services.onboarding_mapper import to_onboarding_schema

        monkeypatch.setattr(gv, "verify_gstin", lambda _g: _normalized(
            provider="gstinapi", document_type="", primary_error="Decentro timeout"))
        out = to_onboarding_schema(_extraction_result())["gst_verification"]
        assert set(out) == set(GstinVerificationResult(checked=False).to_dict())
        assert (out["provider"], out["primary_error"]) == ("gstinapi", "Decentro timeout")
        assert out["additional_places_of_business"][0]["address"] == "Plot 9, Hosur"
