# GST verification: Decentro GSTIN_DETAILED (primary), gstinapi.in (fallback)

**Status: implemented and unit-tested. NOT yet verified against a real Decentro staging response.**
See [Pending live verification](#pending-live-verification) before relying on the detailed fields.

Code: `backend/app/services/gstin_verification.py`. Tests: `backend/tests/test_gstin_verification.py`.

## What it does

When `GSTIN_API_ENABLED=true`, a GSTIN extracted from a document is checked against the live GST
registry. The vendor flow (`POST /extract`) and the customer flow (`POST /onboarding/extract`) share
the same service, one call each. The result is normalized into `GstinVerificationResult`
(`to_dict()`), and **no raw provider response is stored**.

```
Decentro raw response -> GstinVerificationResult (normalized) -> validation / address work -> BC mapper
```

Business Central mapping is unchanged. The vendor flow still replaces the extracted address with
the registry's **principal** place of business (`_overwrite_address_from_registry`, unchanged).
Additional places of business are now kept in the normalized result for later address comparison;
nothing consumes them automatically yet. Address segmentation is not touched.

## Environment: STAGING today

| Setting | Value | Notes |
|---|---|---|
| `DECENTRO_BASE_URL` | `https://in.staging.decentro.tech` | The one environment switch |
| `DECENTRO_CLIENT_ID` / `DECENTRO_CLIENT_SECRET` | from the Decentro **staging** dashboard | Never committed |
| `DECENTRO_MODULE_SECRET` | blank | **Not sent**, see Authentication |
| `GSTIN_API_KEY` | gstinapi.in key | Fallback only |
| `GSTIN_API_ENABLED` | `false` by default | Each lookup spends quota |

**Fixed in code, deliberately not settings:** `document_type = "GSTIN_DETAILED"` and
`generate_pdf = false`. Nobody can silently downgrade the primary provider to basic `GSTIN` or start
generating PDFs by editing an env file.

**Switching environments later** is an env-file change only: the production base URL plus production
credentials, in an untracked env file (`ENV_FILE`, see `PROMOTION.md`). Nothing in the code changes.
**Production credentials must never be committed.** Production pricing and rate limits are
account-specific and must be confirmed with Decentro before rollout; this project makes no claim
about them.

## Why GSTIN_DETAILED

Decentro's `GSTIN_DETAILED` document type returns the registry data plus KYB data in **one** call
(one `POST /kyc/public_registry/validate`, never a basic call followed by a detailed one). The aim is
not only "does this GSTIN exist" but also legal and trade name, the principal and additional places of
business, and KYB data for future validation and enrichment. We make no claim here about its cost or
speed relative to basic `GSTIN`.

## Authentication

Decentro's GSTIN_DETAILED reference lists `client_id` and `client_secret` as the headers, so those
are what is sent. `module_secret` is **not** sent, even if `DECENTRO_MODULE_SECRET` is set (it stays in
`Settings` only so existing `.env` files keep loading). The earlier GSTIN integration (2026-10-01) did
send it. If Decentro explicitly confirms that this account/module requires it, add it back and record
the confirmation here:

> module_secret confirmation: _none recorded yet_

## Request

`POST {DECENTRO_BASE_URL}/kyc/public_registry/validate`, timeout 10 s, **one attempt, no retries**
(a retry could double-bill):

```json
{"reference_id": "gst-<uuid4 hex>", "document_type": "GSTIN_DETAILED", "id_number": "<GSTIN>",
 "consent": "Y", "consent_purpose": "GSTIN verification for vendor onboarding", "generate_pdf": false}
```

`reference_id` is unique per call and does not contain the GSTIN.

## Normalized fields

Every documented `GSTIN_DETAILED` business/KYB field in the agreed scope is retained or explicitly
excluded:

| Decentro `kycResult` field | Normalized field | Decision |
|---|---|---|
| `gstin`, `legalName`, `tradeName`, `gstnStatus`, `principalPlaceOfBusiness` | `legal_name`, `trade_name`, `status`, `address` (+ `city`, `state`, `pincode` parsed from the address) | retained |
| `taxpayerType`, `constitutionOfBusiness`, `registrationDate`, `pan`, `registrationType` | `taxpayer_type`, `constitution_of_business`, `registration_date`, `pan`, `registration_type` | retained |
| `natureOfBusiness[]`, `natureOfCoreBusinessActivity` | `nature_of_business`, `nature_of_core_business_activity` | retained |
| `annualAggregateTurnover`, `mandatoryEInvoicing`, `grossTotalIncome`, `isFieldVisitConducted` | snake_case equivalents (strings) | retained |
| `stateJurisdiction`, `centralJurisdiction`, `centralJurisdictionCode` | snake_case equivalents | retained |
| `businessDetails[]` | `business_details` (`hsn`, `type`, `description`) | retained |
| `filingStatus[]` | `filing_status` (year, period, method, date, gst type, annual return, status) | retained |
| `cinData.companyMasterData` | `company_master_data` (cin, company name, incorporation date, registered address, category, class, capital) | retained, **except `emailId`** |
| `cinData.directors[]` | `directors` (`name`, `begin_date`, `end_date`) | retained, **except `dinOrPan`** |
| `additionalPlacesOfBusinessInState` | `additional_places_of_business` | retained, **provisional** (below) |
| `cinData.companyMasterData.emailId` | | **excluded**: contact data with no current use |
| `cinData.directors[].dinOrPan` | | **excluded**: personal identifier |
| `cinData.charges[]` | | **out of scope**: not in the agreed KYB scope; never added automatically |
| `pdf` | | **excluded**: `generate_pdf` is always false |

Top-level response metadata (not business data):

| Field | Treatment |
|---|---|
| `status`, `kycStatus` | classify the outcome only; not stored |
| `responseCode` | stored as `response_code`; logged |
| `responseKey` | logged on provider failures; not stored |
| `message` | used only to recognise "no records found"; not stored |
| `requestTimestamp`, `responseTimestamp` | not stored |
| `decentroTxnId` | stored as `provider_reference_id` (audit / Decentro support) |

Diagnostic fields: `provider` (`decentro` / `gstinapi`), `document_type`, `record_found`,
`reference_id`, `provider_reference_id`, `response_code`, `primary_error`.

The parser is tolerant: missing, null, empty or unexpected fields never raise.

## Fallback rules

| Decentro outcome | Result | gstinapi.in used? |
|---|---|---|
| HTTP 200, success, **any** `gstnStatus` (Active, Cancelled, Suspended...) | verification result | **No** |
| HTTP 200, `responseCode` `E00021` / "No records found" | `checked=true`, `record_found=false`, status "Not found" | **No** |
| Not configured | | yes |
| HTTP 400, 401/403, 402, 429, 5xx, timeout, connection error, malformed or unexpected body | provider failure | **yes** |

A cancelled or not-found GSTIN is a valid answer and is never hidden by the fallback. If both
providers fail, the result is `checked=false` with both reasons in `error`; extraction is never blocked.

**A fallback is never mistaken for a working Decentro.** Every Decentro failure is logged on every
occurrence with a category (`auth_rejected`, `request_rejected`, `insufficient_balance`, `rate_limited`,
`server_error`, `timeout`, `connection_error`, `request_error`, `malformed_response`,
`provider_failure`, `unexpected_http_status`); auth and balance failures at ERROR, the rest at
WARNING. When gstinapi.in answers, `provider` is `"gstinapi"`, `primary_error` says why Decentro did
not answer, and the vendor `gst_number` field gets a note ("checked via fallback (gstinapi.in);
primary provider: ..."). Repeated `primary_error` values or log lines mean Decentro is **not** working.

Logs never contain headers, request bodies, secrets or exception text (only the exception type).

## Additional places of business: provisional

Decentro names `additionalPlacesOfBusinessInState` but does not document its entry shape, so the
normalizer does not guess field names. Every entry ends up in exactly one place:

- **normalized** into `additional_places_of_business` (`address`, `city`, `state`, `pincode`,
  `nature_of_business`). Today only a plain string entry qualifies; `nature_of_business` is empty
  until the real shape is confirmed;
- **counted** in `additional_places_unrecognized`, with a warning that logs entry types and a count,
  never content. No placeholder location is created, and the vendor field gets a note.

`additional_places_unrecognized` is a **temporary diagnostic**. It does not satisfy the requirement to
preserve additional business addresses.

## Pending live verification

The current staging credentials return **HTTP 401 with `responseKey: error_module_credits_exhausted`**
(observed 2026-10-04), so the account has no credits for this module. Until that is resolved on
Decentro's side every lookup uses gstinapi.in, visible through `primary_error` and the logs. It is not
yet known whether GSTIN_DETAILED needs separate enablement, or whether `module_secret` is needed.

The integration is **verified** only after one real staging `GSTIN_DETAILED` response shows
`provider="decentro"`, `document_type="GSTIN_DETAILED"` and an empty `primary_error`, and:

1. `additionalPlacesOfBusinessInState`'s real shape, including the per-location address and
   nature-of-business field names, is confirmed and added to the normalizer;
2. `cinData.directors`, `businessDetails`, `filingStatus`, `cinData.companyMasterData`, the
   jurisdiction fields and `registrationType` match what the parser expects;
3. every actual additional location that has an address is in `additional_places_of_business`, with
   `additional_places_unrecognized == 0`. **If any required location is still unrecognized, the
   verification is incomplete;**
4. a sanitized fixture is made from the real response (no real GSTIN, PAN, names or addresses) and
   exact-shape tests are added.

`charges[]` may be inspected for information, but is not added unless explicitly required later.
Until then the parser and its tests are provisional.
