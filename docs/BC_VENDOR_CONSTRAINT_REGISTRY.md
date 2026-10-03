# BC Vendor Constraint Registry

Companion to [BC_VENDOR_CONSTRAINTS_RESEARCH.md](BC_VENDOR_CONSTRAINTS_RESEARCH.md). Sources: [BC_VENDOR_RESEARCH_SOURCES.md](BC_VENDOR_RESEARCH_SOURCES.md). Error codes: [BC_VENDOR_VALIDATION_DESIGN.md §2](BC_VENDOR_VALIDATION_DESIGN.md#2-error-taxonomy).

**Target: Business Central 22 on-prem, India localization.** Rows marked *TENANT?* must be confirmed on the live server (see research report §27).

## Column key

| Column | Values |
|---|---|
| **Type** | `STD` standard BC · `IN` India localization · `CFG` configuration-dependent · `EXT` extension-dependent · `CUSTOM` our rule · `TENANT?` unknown / requires tenant verification · `REC` recommendation/inference |
| **Sev** | `BLOCKER` (BC will reject, or the data is legally wrong) · `HIGH` (BC accepts but the vendor is wrong or unusable) · `MED` · `LOW` |
| **Stage** | Pipeline stage from [BC_VENDOR_PIPELINE_INTEGRATION.md](BC_VENDOR_PIPELINE_INTEGRATION.md): 1 Ingest · 2 OCR · 3 Extract · 4 Normalize · 5 Address seg. · 6 Field validation · 7 Cross-doc · 8 BC master data · 9 Template/defaults · 10 Form/Excel · 11 Pre-submission · 12 Submission · 13 Post-create verify · 14 Audit |
| **Auto** | `AUTO_PASS` · `AUTO_FIX` · `AUTO_LOOKUP` · `MANUAL_REVIEW` · `BLOCK_SUBMISSION` |

---

## FIELD_LENGTH

Every length check follows the same rule:
- **Never truncate.** Keep the original value, report `FIELD_TOO_LONG` with the actual and allowed lengths, and route to review.
- Limits come from a single BC target profile (see validation design §4), not from constants scattered in code.

| ID | Field | BC component | Constraint | Type | Sev | Source | Stage | Validation method | Auto-fix? | Review? | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-LEN-01 | Name | Vendor.Name | ≤ 100 chars | STD | BLOCKER | S02 | 6, 11 | `len(v) <= 100` | No | Yes | BLOCK_SUBMISSION | FIELD_TOO_LONG | `master` `bc_mapper._BC_FIELD_MAX_LEN` says 50, which wrongly flags or truncates 51–100-char legal names |
| C-LEN-02 | Name 2 | Vendor."Name 2" | ≤ 50 | STD | BLOCKER | S02 | 11 | length | No | Yes | BLOCK_SUBMISSION | FIELD_TOO_LONG | Only if used for the trade name |
| C-LEN-03 | Address | Vendor.Address | ≤ 100 | STD | BLOCKER | S02 | 5, 11 | length | **Boundary shift only** (C-ADR-03) | Yes (if shifted or still too long) | MANUAL_REVIEW (one click) if shifted; BLOCK_SUBMISSION if still too long | ADDRESS_BC_LENGTH_REBALANCE / ADDRESS_OVERFLOW | `master` mapper says 50 (wrong) |
| C-LEN-04 | Address 2 | Vendor."Address 2" | ≤ 50 | STD | BLOCKER | S02 | 5, 11 | length | **Boundary shift only** (C-ADR-03) | Yes (if shifted or still too long) | MANUAL_REVIEW (one click) if shifted; BLOCK_SUBMISSION if still too long | ADDRESS_BC_LENGTH_REBALANCE / ADDRESS_OVERFLOW | Measured: canonical case = 69 chars (M1) |
| C-LEN-05 | City | Vendor.City | ≤ 30 | STD | BLOCKER | S02 | 6, 11 | length | No | Yes | BLOCK_SUBMISSION | FIELD_TOO_LONG | |
| C-LEN-06 | State (County) | Vendor.County | ≤ 30 | STD | BLOCKER | S02 | 6, 11 | length | No | Yes | BLOCK_SUBMISSION | FIELD_TOO_LONG | "Dadra and Nagar Haveli and Daman and Diu" = 40 chars. The company must decide an abbreviation (Q21 in research report §27). |
| C-LEN-07 | Post Code | Vendor."Post Code" | Code ≤ 20 | STD | LOW | S02 | 6 | length | – | – | AUTO_PASS | FIELD_TOO_LONG | PIN is 6 digits |
| C-LEN-08 | Country/Region Code | Vendor."Country/Region Code" | Code ≤ 10, **a code, not a name** | STD | BLOCKER | S02 | 8 | lookup (C-MD-01) | Lookup only | If not found | AUTO_LOOKUP | INVALID_COUNTRY | |
| C-LEN-09 | Contact | Vendor.Contact | ≤ 100 | STD | MED | S02 | 11 | length | No | Yes | BLOCK_SUBMISSION | FIELD_TOO_LONG | `master` mapper says 50 (wrong) |
| C-LEN-10 | Phone / Mobile | "Phone No.", "Mobile Phone No." | ≤ 30 each | STD | MED | S02 | 6 | length | No | Yes | BLOCK_SUBMISSION | FIELD_TOO_LONG | |
| C-LEN-11 | E-Mail | Vendor."E-Mail" | ≤ 80 | STD | MED | S02 | 6 | length | No | Yes | BLOCK_SUBMISSION | FIELD_TOO_LONG | |
| C-LEN-12 | Home Page | Vendor."Home Page" | ≤ 80 in BC 22 (≤ 255 in current BC) | STD (version-dependent) | MED | S02, S01 | 11 | length from the target profile | No | Yes | BLOCK_SUBMISSION | FIELD_TOO_LONG | |
| C-LEN-13 | Registration No. | Vendor."Registration Number" | Storage Text[50], **OnValidate errors above 20** | STD | MED | S02 | 11 | `len <= 20` | No | Yes | BLOCK_SUBMISSION | FIELD_TOO_LONG | Udyam no. (19) fits |
| C-LEN-14 | GSTIN | "GST Registration No." | Code[20], BC requires exactly 15 | IN | BLOCKER | S13 | 6 | `len == 15` | No | Yes | BLOCK_SUBMISSION | INVALID_GSTIN | |
| C-LEN-15 | PAN | "P.A.N. No." | Code[20]; PAN is 10 | IN | BLOCKER | S15, S32 | 6 | `len == 10` | No | Yes | BLOCK_SUBMISSION | INVALID_PAN | |
| C-LEN-16 | Bank fields | Vendor Bank Account | Code ≤ 20 (NotBlank), Name ≤ 100, Bank Account No. ≤ 30, Bank Branch No. ≤ 20, SWIFT Code ≤ 20, Address ≤ 100, City ≤ 30 | STD | BLOCKER | S05 | 11 | length | No | Yes | BLOCK_SUBMISSION | FIELD_TOO_LONG | |
| C-LEN-17 | Custom PAN_Number / GST_Number | Tenant extension | **Unknown**; repo assumes 20 | EXT / TENANT? | HIGH | S36a | 11 | read `MaxLength` from `$metadata` | – | – | – | TENANT_FIELD_UNKNOWN | Q2 |
| C-LEN-18 | All Text/Code | AL runtime | Limits are in **characters**. Code values are trimmed before the length count. | STD | LOW | S28 | 6, 11 | measure after trim | Trim only | No | AUTO_FIX | – | |

## DATA_TYPE / FORMAT

| ID | Field | BC component | Constraint | Type | Sev | Source | Stage | Method | Auto-fix? | Review? | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-TYP-01 | All Code fields | AL Code type | BC uppercases and trims. `"India"` becomes `"INDIA"`, which may not be a valid code. | STD | HIGH | S28 | 4, 8 | Normalize ourselves, then look up the code | Uppercase/trim | – | AUTO_FIX | – | Don't rely on BC-side coercion for identifiers |
| C-TYP-02 | Phone, Mobile | Vendor OnValidate | Must not contain letters (`must not contain letters`) | STD | MED | S02 | 6 | `not any(c.isalpha())` | Strip a `+91`/`91` prefix only | Yes if letters | AUTO_FIX / MANUAL_REVIEW | INVALID_PHONE | |
| C-TYP-03 | E-Mail | MailManagement | Per `;`-separated address: no spaces, exactly one `@`, not starting or ending with `@` | STD | MED | S11 | 6 | Mirror BC's rule plus our regex | Lowercase/trim | Yes | MANUAL_REVIEW | INVALID_EMAIL | Our regex is stricter (needs a TLD). That's fine. |
| C-TYP-04 | Enums (Blocked, GST Vendor Type, P.A.N. Status, Aggregate Turnover, Partner Type) | Enum | Exact member names. Blank member is `" "`. | STD/IN | HIGH | S14, S15, S18, S22 | 11 | Allow-list per enum | No | Yes | BLOCK_SUBMISSION | INVALID_FORMAT | **Omit** an enum instead of sending blank: blank GST Vendor Type clears the GSTIN (C-GST-12). The exact OData enum wire format must be confirmed via `$metadata` (Q1). |
| C-TYP-05 | Address and name text | – | No line breaks, tabs or control chars | CUSTOM | LOW | – | 4 | Regex | Replace newline with `", "` | No | AUTO_FIX | – | BC doesn't forbid them, but they print badly and break OData diffs |
| C-TYP-06 | Numeric identifiers (account no., PIN, phone) | JSON / Excel | Must travel as **strings** (leading zeros; Excel's 15-digit float precision) | CUSTOM | HIGH | S36b | 10, 12 | Type assertion | – | – | AUTO_PASS | INVALID_FORMAT | Repo writes strings today. Keep it that way. |

## REQUIRED_FIELD / CONDITIONAL_REQUIRED (non-India)

| ID | Field | BC component | Constraint | Type | Sev | Source | Stage | Method | Auto-fix? | Review? | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-REQ-01 | No. | Vendor.OnInsert | Blank No. needs `Purchases & Payables Setup."Vendor Nos."` (`TestField`) | STD+CFG | BLOCKER | S02 | 8 | Preflight read of the setup (or first-POST error) | – | Admin | CONFIGURATION | NO_SERIES_MISSING | |
| C-REQ-02 | Name | – | Required by our business rule (BC doesn't enforce it) | CUSTOM | BLOCKER | – | 6 | non-empty | No | Yes | BLOCK_SUBMISSION | FIELD_REQUIRED | Already `non_empty` in the repo |
| C-REQ-03 | Vendor Posting Group | Gen. Jnl.-Post Line | Not needed to insert, **needed to post** (`Vend.TestField("Vendor Posting Group")`) | STD+CFG | HIGH | S09 | 9, 11 | Must be resolved from template/config before a vendor counts as "ready" | Template / config lookup | If unresolved | AUTO_LOOKUP / MANUAL_REVIEW | CONFIGURATION_MISSING | |
| C-REQ-04 | Vendor Bank Account key | table 288 | Vendor No. and Code are NotBlank | STD | BLOCKER | S05 | 12 | Code generated by rule | Generate | No | AUTO_FIX | FIELD_REQUIRED | |
| C-REQ-05 | Bank Account No. / IBAN | table 288 | One of the two is needed for payment export | STD | HIGH | S05 | 11 | non-empty | No | Yes | BLOCK_SUBMISSION (bank step) | FIELD_REQUIRED | |
| C-REQ-06 | Tenant custom fields | Tenant extension | Mandatory status unknown | TENANT? | HIGH | S36c | 11 | Discover via `$metadata` and a sandbox POST | – | – | – | TENANT_FIELD_UNKNOWN | Q3 |
| C-REQ-07 | Preferred Bank Account Code | Vendor field 288 | Must reference an existing Vendor Bank Account of **this** vendor | STD | HIGH | S02 | 12 | Set after the bank record is created | Sequence | No | AUTO_PASS | BC_TABLE_RELATION | |
| C-REQ-08 | Primary Contact No. | Vendor field 5049 | Contact must belong to the vendor's company contact | STD | MED | S02 | – | Don't send in automation | – | – | – | – | |

## GST (India localization; applies only if the India apps are installed, C-LOC-01)

| ID | Field | BC component | Constraint | Type | Sev | Source | Stage | Method | Auto-fix? | Review? | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-GST-01 | GST Registration No. | GST Purchase Subscribers | Validating a non-blank GSTIN needs **State Code already set** (`TestField`) | IN | BLOCKER | S12 | 12 | Request ordering (validation design §6) | Sequence | No | AUTO_PASS | BC_TESTFIELD | |
| C-GST-02 | GST Registration No. | same | Needs **P.A.N. No. already set and P.A.N. Status blank**, else `PAN No. must be entered.` | IN | BLOCKER | S12 | 12 | Ordering, and PAN present | Sequence | If PAN missing | BLOCK_SUBMISSION | BC_GST_VALIDATION | |
| C-GST-03 | GSTIN ↔ State | CheckGSTRegistrationNo | GSTIN[1..2] must equal `State."State Code (GST Reg. No.)"` of the vendor's State Code | IN+CFG | BLOCKER | S13, S15 | 8 | Derive State Code **from** the GSTIN digits via a State lookup | Lookup | If no State maps | AUTO_LOOKUP | INVALID_STATE / MASTER_DATA_NOT_FOUND | |
| C-GST-04 | GSTIN ↔ PAN | same | GSTIN[3..12] must equal P.A.N. No. | IN | BLOCKER | S13 | 6, 7 | Exact compare (repo `gstin_contains_pan`) | No | Yes | BLOCK_SUBMISSION | INVALID_GSTIN / CROSS_DOCUMENT_MISMATCH | Already implemented, exact |
| C-GST-05 | GSTIN shape | same | Length 15; positions 3–7 and 12 alpha; 8–11 numeric; 13 and 15 alphanumeric | IN | BLOCKER | S13 | 6 | Repo regex is stricter (13 = `[1-9A-Z]`, 14 = `Z`) | No | Yes | BLOCK_SUBMISSION | INVALID_GSTIN | |
| C-GST-06 | GSTIN checksum | – | **BC does not check the 15th (check) character.** We must. | CUSTOM | HIGH | S13, S35 (D) | 6 | Mod-36 check character | No | Yes | BLOCK_SUBMISSION (after calibration) | INVALID_GSTIN | Not implemented today despite the comment in `config.py` (M4). Calibrate on known-good GSTINs first. |
| C-GST-07 | GST Vendor Type | same | Validating a GSTIN auto-sets GST Vendor Type to `Registered` if it is blank, Import or Unregistered | IN | MED | S12 | 12, 13 | Post-create read-back | – | If unexpected | AUTO_PASS | INT_VERIFY_MISMATCH | Side effect |
| C-GST-08 | GST Vendor Type | same | Registered/Composite/SEZ/Exempted need GSTIN **or** ARN | IN | BLOCKER | S12 | 11 | Rule | No | Yes | BLOCK_SUBMISSION | INVALID_GST_VENDOR_TYPE | |
| C-GST-09 | GST Vendor Type = Unregistered | same | Clears GSTIN and ARN; requires State Code | IN | HIGH | S12 | 11 | Rule | No | Yes | BLOCK_SUBMISSION | INVALID_GST_VENDOR_TYPE | Unregistered vendor with a GSTIN extracted means the documents contradict the chosen type |
| C-GST-10 | GST Vendor Type = Import | same | Clears GSTIN/ARN; State Code must be blank; Associated Enterprises allowed only here | IN | HIGH | S12 | 11 | Rule | No | Yes | BLOCK_SUBMISSION | INVALID_GST_VENDOR_TYPE | Out of scope for Indian-document onboarding |
| C-GST-11 | GST Vendor Type = blank | same | **Clears the GSTIN** | IN | BLOCKER | S12 | 12 | Never send blank (C-TYP-04) | – | – | AUTO_PASS | – | Ordering hazard |
| C-GST-12 | State Code change | same | For non-Import/Unregistered, State Code can only be validated while GSTIN is **blank**. Order must be State Code, then PAN, then GSTIN, then type. | IN | BLOCKER | S12 | 12 | Multi-step writes | Sequence | No | AUTO_PASS | BC_TESTFIELD | Also blocks later state edits unless the GSTIN is cleared first |
| C-GST-13 | Aggregate Turnover | same | Changeable only for Unregistered. Enum default (value 0) is "More than 20 lakh". | IN | MED | S12, S18 | 11 | Omit for registered vendors | – | – | AUTO_PASS | INVALID_FORMAT | |
| C-GST-14 | ARN No. | same | Must be blank for Import/Unregistered | IN | LOW | S12 | 11 | Rule | – | – | AUTO_PASS | INVALID_FORMAT | |
| C-GST-15 | GST Vendor Type source | – | Not currently extracted. The GST certificate states the registration type (e.g., Regular/Composition/SEZ), so it can be DERIVED with a mapping. | REC | HIGH | S19 | 3, 6 | New field + mapping table | No | Yes (until the mapping is proven) | MANUAL_REVIEW | INVALID_GST_VENDOR_TYPE | Verify the caption on your certificate samples |
| C-GST-16 | GSTIN active status | – | BC doesn't check registration status | CUSTOM | MED | S35, S36a | 7 | Optional registry lookup (`gstin_verification.py`) | No | If not Active | MANUAL_REVIEW | GSTIN_NOT_ACTIVE | Third-party call (C-SEC-04) |
| C-GST-17 | Multiple GSTINs | – | One vendor record holds one GSTIN. Other-state registrations go in Order Addresses (India loc allows GST Reg. No. there) or separate vendors. | IN + REC | MED | S12 | 7 | Detect multiple GSTINs with the same PAN | No | Yes | MANUAL_REVIEW | – | Business decision |
| C-GST-18 | State table | India Tax Base `State` + GST ext. | Every state used needs `State Code (GST Reg. No.)` populated | IN+CFG | BLOCKER | S15 | 8 | Preflight read of States | – | Admin | CONFIGURATION | MASTER_DATA_NOT_FOUND | Q5 |
| C-GST-19 | GST state-code set | – | Valid prefixes 01–38 (25 discontinued after the 2020 DNH+DD merger; 28 is the pre-bifurcation AP code), plus 97 (Other Territory) and 99 | CUSTOM | MED | S34 (D) | 6 | Allow-list | No | Yes | MANUAL_REVIEW | INVALID_GSTIN | Repo accepts 01–38 (incl. 25/28) and rejects 97/99 |

## PAN (India)

| ID | Field | BC component | Constraint | Type | Sev | Source | Stage | Method | Auto-fix? | Review? | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-PAN-01 | PAN format | – | `[A-Z]{5}[0-9]{4}[A-Z]`. **BC doesn't validate PAN format** (only the match with the GSTIN). | CUSTOM | BLOCKER | S15, S32 | 6 | Regex (exists) | No | Yes | BLOCK_SUBMISSION | INVALID_PAN | |
| C-PAN-02 | PAN 4th char | – | Holder type ∈ {A, B, C, F, G, H, J, L, P, T} | CUSTOM | HIGH | S32 | 6 | Allow-list | No | Yes | BLOCK_SUBMISSION | INVALID_PAN | Not in the repo today |
| C-PAN-03 | PAN 5th char | – | First letter of the name (non-individuals) or surname (individuals) | CUSTOM | LOW | S32 | 7 | Compare with the normalized legal name | No | Yes (warning) | MANUAL_REVIEW | NAME_PAN_INITIAL_MISMATCH | Warning only: "M/s", "The", abbreviations |
| C-PAN-04 | P.A.N. Status | India Tax Base | **Validating the status overwrites P.A.N. No.** with the status text | IN | BLOCKER | S15 | 12 | Never send P.A.N. Status when a PAN is known | – | – | AUTO_PASS | – | |
| C-PAN-05 | PAN missing | India TDS | Higher TDS rate. The status path needs P.A.N. Reference No. at TDS posting. | IN | HIGH | S17, S20 | 11 | If no PAN: stop and ask | No | Yes | MANUAL_REVIEW | FIELD_REQUIRED | |
| C-PAN-06 | PAN → Partner Type / Assessee Code | – | 4th char `C` suggests Company; `P` suggests Individual/Person | REC | LOW | S32 | 9 | Suggestion plus lookup | Suggest | Yes | AUTO_LOOKUP | – | Assessee codes are tenant-defined |

## TDS (India)

| ID | Field | BC component | Constraint | Type | Sev | Source | Stage | Method | Auto-fix? | Review? | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-TDS-01 | Assessee Code | Vendor ext. | "needs to be filled on the vendor master" for TDS; relates to the Assessee Code table | IN+CFG | HIGH | S20, S15 | 8, 9 | Lookup | Suggest | Yes | AUTO_LOOKUP / MANUAL_REVIEW | MISSING_TDS_CONFIGURATION | |
| C-TDS-02 | Allowed Sections | table 18687 | Separate records per (Vendor, Section). The section depends on the service type, which isn't on the documents. | IN | HIGH | S17, S20 | 9, 12 | USER_INPUT | No | Yes | MANUAL_REVIEW | MISSING_TDS_CONFIGURATION | Portal only has `tds_applicable` Yes/No |
| C-TDS-03 | Concessional codes | table 18688 | Section must be in Allowed Sections; End Date ≥ Start Date; certificate no. | IN | MED | S17 | 12 | Rule | No | Yes | MANUAL_REVIEW | – | Maybe the tenant's "Deduction Certificate" field (Q3) |
| C-TDS-04 | PAN checks at TDS posting | TDS Validations | Blank PAN, status and reference gives `The deductee P.A.N. No. is invalid.` | IN | HIGH | S17 | 11 | Ensure the PAN is set | – | – | – | – | Fails at posting, not at creation |
| C-TDS-05 | TDS via API | API v2.0 | Not exposed. Needs a published page or a custom API. | IN | MED | S07 | 12 | – | – | – | – | – | |

## MASTER_DATA

| ID | Field | BC component | Constraint | Type | Sev | Source | Stage | Method | Auto-fix? | Review? | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-MD-01 | Country/Region Code | Country/Region | Must be an existing code. The repo sends the **name** "India". | STD+CFG | BLOCKER | S02 | 8 | Look up by name/ISO in a synced Country/Region list | Lookup | If none | AUTO_LOOKUP | INVALID_COUNTRY | Q4 |
| C-MD-02 | State Code | State | Derive from GSTIN digits; fallback from the PIN's state via State.Description | IN+CFG | BLOCKER | S15 | 8 | Lookup | Lookup | If none/ambiguous | AUTO_LOOKUP | INVALID_STATE | |
| C-MD-03 | Post Code | Post Code | Existing PIN record **overwrites City/County/Country**; a missing PIN is accepted silently | STD+CFG | HIGH | S04 | 8, 13 | Preflight read; post-create diff | – | If overwritten differently | AUTO_PASS / MANUAL_REVIEW | INT_VERIFY_MISMATCH | Q6 |
| C-MD-04 | Posting groups | Vendor/Gen./VAT Bus. Posting Group | Must exist. Gen. Bus. auto-sets VAT Bus. from its default. | STD+CFG | BLOCKER | S02 | 8, 9 | Lookup | From template/config | If unresolved | AUTO_LOOKUP | MASTER_DATA_NOT_FOUND | |
| C-MD-05 | Other codes | Payment Terms, Payment Method, Currency, Purchaser (non-blocked), Location, Resp. Center, Language, Dimensions, Company Size | Must exist | STD+CFG | BLOCKER | S02 | 8 | Lookup | From template/config | If unresolved | AUTO_LOOKUP | MASTER_DATA_NOT_FOUND | |
| C-MD-06 | Currency | Currency | Blank = LCY. Don't send `INR` unless it exists as a Currency. | STD+CFG | HIGH | S02 | 9 | Rule | Omit | No | AUTO_PASS | MASTER_DATA_NOT_FOUND | |
| C-MD-07 | Assessee Code / TDS Section / Concessional Code | India tables | Must exist | IN+CFG | HIGH | S15, S17 | 8 | Lookup | – | Yes | AUTO_LOOKUP | MASTER_DATA_NOT_FOUND | |
| C-MD-08 | No. Series | No. Series | Open, not exhausted, the right series for trade vendors | STD+CFG | HIGH | S02 | 8 | Admin confirmation | – | Admin | CONFIGURATION | NO_SERIES_MISSING | C-CFG-02 |
| C-MD-09 | Any code | – | **Never invent a code.** An unresolvable code is an error, not a guess. | CUSTOM | BLOCKER | brief §5 | 8 | – | – | Yes | MANUAL_REVIEW | MASTER_DATA_NOT_FOUND | |

## ADDRESS

| ID | Field | BC component | Constraint | Type | Sev | Source | Stage | Method | Auto-fix? | Review? | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-ADR-01 | Address / Address 2 | Vendor | BC gives them **no semantics**: both are free text, optional, unvalidated. "Address 1 = premise, Address 2 = locality" is **our** rule. | STD (fact) / CUSTOM (semantics) | – | S02 | 5 | – | – | – | – | – | |
| C-ADR-02 | Address / Address 2 | Vendor | Both may be empty | STD | LOW | S02 | 5 | – | – | – | AUTO_PASS | – | |
| C-ADR-03 | Address split | Vendor | Must satisfy len(A1) ≤ 100 **and** len(A2) ≤ 50. If A2 overflows, move the single boundary right (whole fragments, order kept, nothing dropped) until A2 ≤ 50 with A1 ≤ 100. If impossible, block. | STD (limits) + CUSTOM (method) | BLOCKER | S02, M1, M2 | 5, 11 | Deterministic rebalance | **Boundary shift only** | Yes (flagged) | MANUAL_REVIEW (one click); BLOCK_SUBMISSION when no shift fits | ADDRESS_BC_LENGTH_REBALANCE / ADDRESS_OVERFLOW | Keeps the premise-first semantics wherever it fits |
| C-ADR-04 | Address 3/4 | – | BC has none. Joining them into Address 2 (the `master` mapper) overflows it. | STD | HIGH | S02, S36a | 11 | Remove the join | – | – | – | – | `ocr-testing` no longer fills 3/4 |
| C-ADR-05 | City/County/Country | Post Code | Overwritten from the Post Code table if the PIN exists | STD+CFG | HIGH | S04 | 13 | Read-back diff | – | If different | MANUAL_REVIEW | INT_VERIFY_MISMATCH | e.g., "Bengaluru" vs a table's "BANGALORE" |
| C-ADR-06 | Country change | Vendor OnValidate | Changing from a non-blank country clears Post Code, City, County | STD+CFG | MED | S02, S04 | 12 | Send Country in the first request; never change it afterwards | – | – | AUTO_PASS | – | |
| C-ADR-07 | City | Vendor | Not validated through web services (`ValidateCity` exits when not `GuiAllowed`) | STD | MED | S04 | 6 | Our own PIN-district check (exists) | – | – | AUTO_PASS | PIN_STATE_MISMATCH | |
| C-ADR-08 | County vs State Code | – | County (free text) and India State Code (lookup) must describe the same state | CUSTOM | MED | S15 | 7 | Compare | – | Yes | MANUAL_REVIEW | INVALID_STATE | |
| C-ADR-09 | Additional addresses | Order Address | Other places of business go in Order Addresses | IN + REC | LOW | S12 | – | Out of scope v1 | – | – | – | – | |
| C-ADR-10 | Empty Address 1 | – | Semantic segmentation leaves A1 empty when no premise fragment leads. The A1 backfill then fills it before the BC check: fragment 0 alone when it is a thoroughfare, otherwise the first 1–2 fragments. The BC rebalance (C-ADR-03) applies only if Address 2 is still over 50 after that. | CUSTOM | HIGH | S36b | 5 | Backfill, then C-ADR-03 if needed | Boundary shift | No (logged) | AUTO_FIX | ADDRESS_1_BACKFILLED | Corrected 2026-09-30 (docs/ADDRESS_SEGMENTATION_PLAN.md §4) |

## BANK

| ID | Field | BC component | Constraint | Type | Sev | Source | Stage | Method | Auto-fix? | Review? | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-BNK-01 | Vendor Bank Account | table 288 | Separate record, created **after** the vendor exists | STD | BLOCKER | S05 | 12 | Step 3 of the push | – | – | AUTO_PASS | INT_PARTIAL_CREATE | |
| C-BNK-02 | Code | table 288 | NotBlank, unique per vendor; we must generate it | STD+CUSTOM | HIGH | S05 | 12 | Rule, e.g. `PRIMARY` or `<IFSC 4-char bank code>-<last 4>` | Generate | No | AUTO_FIX | – | Company convention |
| C-BNK-03 | Account number | – | Digits only, length 9–18 (repo heuristic, **not** an RBI rule) | CUSTOM | HIGH | – | 6 | Regex on the raw value (see C-NRM-02) | No | Yes | BLOCK_SUBMISSION | INVALID_BANK_ACCOUNT | |
| C-BNK-04 | IFSC | – | 4 letters + `0` + 6 alphanumerics; ideally present in RBI's IFSC master | CUSTOM | HIGH | S33 (D) | 6 | Regex (exists) + optional directory lookup | See C-NRM-03 | Yes | BLOCK_SUBMISSION | INVALID_IFSC | |
| C-BNK-05 | IFSC destination | table 288 | **No IFSC field** in BC 22 IN. Candidates: Bank Branch No. (Text[20]), a custom field, or SWIFT Code (wrong semantics). | TENANT? | HIGH | S05 | 12 | Company decision | – | – | – | TENANT_FIELD_UNKNOWN | Q11 |
| C-BNK-06 | Bank name | table 288 Name | Derive from the IFSC bank code via a lookup table, not from OCR of the logo | CUSTOM | MED | S33, S36b README | 4 | Lookup | Lookup | If absent | AUTO_LOOKUP | – | README lists this as the planned fix |
| C-BNK-07 | Holder name | – | Cheque account-holder name should match the vendor legal/trade name | CUSTOM | HIGH | – | 7 | Fuzzy compare (names only) | No | Yes | MANUAL_REVIEW | CROSS_DOCUMENT_MISMATCH | Fraud control. Holder name isn't extracted today. |
| C-BNK-08 | Preferred Bank Account Code | Vendor | Set after the bank record exists | STD | MED | S02 | 12 | Step 4 | – | – | AUTO_PASS | BC_TABLE_RELATION | |
| C-BNK-09 | Delete | table 288 OnDelete | Can't delete while open vendor ledger entries use it | STD | LOW | S05 | – | – | – | – | – | – | |
| C-BNK-10 | API | API v2.0 | No vendor-bank-account entity. Needs the published card page or a custom API. | STD | HIGH | S07 | 12 | – | – | – | – | – | Q12 |
| C-BNK-11 | Account type (CA/SB/CC) | – | No BC field | STD | LOW | S05 | 10 | Keep on the request form only | – | – | – | – | |

## DUPLICATE

| ID | Field | BC component | Constraint | Type | Sev | Source | Stage | Method | Auto-fix? | Review? | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-DUP-01 | No. | Vendor PK | Unique (native) | STD | – | S02 | 12 | – | – | – | – | BC_VALIDATION_FAILED | |
| C-DUP-02 | Name, GSTIN, PAN, bank acct | – | **BC has no native uniqueness check** on any of these (no unique keys, no validation) | STD (fact) | HIGH | S02, S12 | 8 | Our pre-check | – | – | – | – | |
| C-DUP-03 | GSTIN | – | Exact match with an existing BC vendor: block creation | CUSTOM | BLOCKER | – | 8 | OData `$filter` on the GSTIN field | No | Yes | BLOCK_SUBMISSION | DUPLICATE_GSTIN | |
| C-DUP-04 | PAN | – | Same PAN + different GSTIN is legitimate (one GSTIN per state), so review, not block | CUSTOM | MED | S12 | 8 | `$filter` on PAN | No | Yes | MANUAL_REVIEW | DUPLICATE_PAN | |
| C-DUP-05 | Bank account | – | Same account number on another vendor is a strong fraud/duplicate signal | CUSTOM | HIGH | – | 8 | Query Vendor Bank Accounts | No | Yes | MANUAL_REVIEW | DUPLICATE_BANK_ACCOUNT | |
| C-DUP-06 | Name | – | Exact normalized-name match: review. **No fuzzy blocking.** | CUSTOM | MED | – | 8 | Normalized equality | No | Yes | MANUAL_REVIEW | DUPLICATE_VENDOR | |
| C-DUP-07 | Retries | – | A timed-out POST may have created the vendor, so re-check by GSTIN before retrying | CUSTOM | BLOCKER | S25 | 12 | Idempotency key = GSTIN (or PAN + name) | – | – | – | INT_TIMEOUT_UNKNOWN_OUTCOME | |
| C-DUP-08 | Portal uniqueness | `vendors.gst_no` / `udyam_no` unique | Covers portal records only, not vendors created directly in BC | CUSTOM | MED | S36b | 8 | Add a BC-side check | – | – | – | DUPLICATE_GSTIN | |

## API / UI / IMPORT

| ID | Area | BC component | Constraint | Type | Sev | Source | Stage | Method | Auto-fix? | Review? | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-API-01 | API v2.0 coverage | `vendors` entity | No posting groups, no India tax fields, no bank accounts | STD | HIGH | S07, S23 | 12 | Use the VendorCard OData page (today) or a custom API page | – | – | – | – | |
| C-API-02 | Templates | VendorCard OData vs API v2.0 | VendorCard OData does **not** apply vendor templates (template selection runs only when `GuiAllowed`). API v2.0 applies **API templates** (Config. Tmpl. Selection Rules) to empty properties. | STD | HIGH | S03, S08, S24 | 9 | Resolve defaults ourselves and send them explicitly | – | – | – | – | |
| C-API-03 | Field names | OData on UI pages | Property names come from page control names (`MobilePhoneNo`, expected `Control16` for Contact, `GST_vendor_Type`). Page structure can change between versions. | STD | HIGH | S03, S26 | 11 | Read `$metadata` at startup; fail closed if a mapped property is missing | – | – | – | TENANT_FIELD_UNKNOWN | |
| C-API-04 | PATCH | OData | Requires an `If-Match` header (ETag or `*`) | STD | MED | S25 | 12 | Client behaviour | – | – | – | API_VALIDATION_FAILED | |
| C-API-05 | Validation order | OData page write | Order of field validation within one request is **not documented** | TENANT? | BLOCKER (for India fields) | S25 (silent) | 12 | **Multi-step writes** so order never matters | – | – | – | BC_GST_VALIDATION | Q13 |
| C-API-06 | UI callbacks | Web-service session | `Confirm` fails with a callback error; `Message` is suppressed | STD | MED | S27 | 12 | Avoid fields whose triggers confirm (Blocked with Privacy Blocked, Contact) | – | – | – | BC_CALLBACK_NOT_ALLOWED | |
| C-API-07 | Permissions | Page properties + permission sets | InsertAllowed/ModifyAllowed and user permissions on Vendor, Vendor Bank Account, India tables | STD+CFG | HIGH | S25 | 12 | Sandbox test | – | Admin | – | BC_PERMISSION | Q14 |
| C-API-08 | Error body | OData | 400 with `error.code`/`error.message` (e.g., `Application_StringExceededLength`, observed per the repo) | STD | MED | S36a | 12 | Parse and map to the taxonomy | – | – | – | BC_* | |
| C-API-09 | Returned No. | OData POST response | Response carries the created record (incl. `No`). Record it programmatically. | STD | HIGH | S25 | 12, 13 | – | – | – | – | – | Today the operator types it by hand |
| C-UI-01 | Templates | Vendor Card GUI | 1 template is applied automatically; more than 1 opens a selection dialog | STD | LOW | S21, S06 | 9 | – | – | – | – | – | Different from OData |
| C-UI-02 | Captions | en-US UI | "State" = County, "ZIP Code" = Post Code. Map by **field**, not caption. | STD | LOW | S36c | 10, 12 | – | – | – | – | – | |
| C-IMP-01 | Config packages | RapidStart | "Validate Field" can be cleared, which **bypasses** OnValidate rules (e.g., GST checks) | STD | HIGH | S30 | 12 | Don't use packages for onboarding, or keep validation on | – | – | – | – | |
| C-IMP-02 | Excel request form | Portal | Not a BC import. BC applies no validation to it. | CUSTOM | HIGH | S36b | 10 | Show a BC-fit status per field on the form | – | – | – | – | |
| C-IMP-03 | Excel typing | openpyxl/Excel | Identifiers must be written as text | CUSTOM | MED | S36b | 10 | Keep `str` values | – | – | AUTO_PASS | – | |

## SECURITY

| ID | Area | Constraint | Type | Sev | Source | Stage | Method | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C-SEC-01 | Sensitive fields | Bank account no., IFSC + account pair, PAN, GSTIN, phone, e-mail are personal/financial data. BC classifies P.A.N. No. as `EndUserIdentifiableInformation`. | STD/CUSTOM | HIGH | S15 | all | Mask in lists and logs (last 4 digits) | – | – | |
| C-SEC-02 | Logging | No raw OCR text, account numbers or full PANs in logs | CUSTOM | HIGH | S36a, S36b | 1–14 | Logging filter + test | – | – | A grep of the `logger.*` calls found none that log account numbers or PANs. The GSTIN is logged in `gstin_verification.py`, and customer creation logs `gst=`. Exception tracebacks can still carry values. |
| C-SEC-03 | Retention | `uploads/<run_id>/`, `outputs/<run_id>/document_set.json` (all OCR spans), `extraction.json`, and DB `vendors.raw_extraction` keep full identifiers indefinitely | CUSTOM | HIGH | S36b | 1, 14 | Retention policy; purge after push | – | – | |
| C-SEC-04 | Third-party API | `gstin_verification.py` sends the GSTIN to gstinapi.in. This contradicts the README's "no network calls". | CUSTOM | MED | S36a | 7 | Keep opt-in; document; send only the GSTIN | – | – | GSTINs are public-registry data. Low risk, but disclose it. |
| C-SEC-05 | Transport | `BC_ODATA_BASE` is `http://…`: payloads (soon including bank data) cross the network unencrypted | CUSTOM | HIGH | S36a | 12 | HTTPS on the BC service tier | – | – | |
| C-SEC-06 | Payload handling | Push guide suggests email or clipboard to move the payload JSON | CUSTOM | HIGH (once bank data is included) | S36a | 12 | Direct call from an allowed host, or an encrypted share | – | – | |
| C-SEC-07 | Access control | Any authenticated portal user can fetch payloads and mark pushed | CUSTOM | MED | S36a | 12, 14 | Role check; verify the BC No. by read-back | – | – | |
| C-SEC-08 | BC audit | Enable Change Log / field monitoring for Vendor Bank Account and the GST/PAN fields | STD+CFG | MED | S29 | 14 | Admin | – | – | |
| C-SEC-09 | Repo hygiene | `docs/BC_VENDOR_PUSH_GUIDE.md` names the VPN host IP and domain account (no password) | CUSTOM | LOW | S36a | – | Move to a private runbook | – | – | |

## WORKFLOW / CONFIGURATION / LOCALIZATION

| ID | Area | Constraint | Type | Sev | Source | Stage | Method | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C-WF-01 | Approval | Vendor Approval Workflow (`VENDAPW`) **restricts record usage** until approved. The live card shows "Request Approval". | STD+CFG | HIGH | S10, S31, S36c | 13 | Automation creates; humans approve. Never auto-approve. | – | – | Q10 |
| C-WF-02 | Deletion | Vendors with posted transactions can't be deleted | STD | HIGH | S21 | 11 | Only create after full validation. Consider creating as `Blocked = All` until reviewed (company decision). | – | – | |
| C-WF-03 | Contacts | Marketing Setup can auto-create contacts on insert/Contact entry | STD+CFG | LOW | S02 | 12 | Don't send Contact | – | – | |
| C-WF-04 | Post-creation edits | Changing GSTIN/State/PAN later is order-constrained (C-GST-12) and tax-sensitive | IN | MED | S12 | – | Out of scope for automation (create-only) | – | – | |
| C-WF-05 | Status sync | Portal "pushed" isn't reconciled with BC (a vendor deleted in BC stays "pushed") | CUSTOM | MED | S36a | 13, 14 | Read-back verification and periodic reconcile | – | INT_VERIFY_MISMATCH | |
| C-CFG-01 | Vendor Nos. | Purchases & Payables Setup."Vendor Nos." must be set | STD+CFG | BLOCKER | S02 | 8 | Preflight | CONFIGURATION | NO_SERIES_MISSING | |
| C-CFG-02 | Multiple series | Evidence of several vendor series (`VEN/0023` on the card, `EMPV/0123` in the repo guide). The OData insert always uses the **default** series. | TENANT? | HIGH | S36a, S36c | 8 | Confirm which series trade vendors use | – | – | Q7 |
| C-CFG-03 | Templates (India) | BC 22 IN has **no India extension of "Vendor Templ."**, so templates can't carry GST Vendor Type, Assessee Code etc. (unless a tenant extension adds them) | IN (fact) / TENANT? | HIGH | S06 | 9 | Company config file for those defaults | – | – | Q9 |
| C-CFG-04 | Template application | Vendor templates copy values by RecordRef assignment **without OnValidate** and only into empty fields | STD | MED | S06 | 9 | Know that template values skip validation | – | – | |
| C-CFG-05 | Posting-group policy | Posting groups differ by vendor class (domestic, import, employee, MSME?) | CFG | HIGH | S36a | 9 | Rules: class → template/config | – | – | Q8 |
| C-CFG-06 | Address setup | G/L Setup "Req. Country/Reg. Code in Addr.", Country address format and County caption | STD+CFG | LOW | S04 | 8 | Read once | – | – | |
| C-CFG-07 | Web services | VendorCard is published. Vendor Bank Account Card, States and Countries must also be published (or a custom API) for full automation. | CFG | HIGH | S36a | 12 | Admin | – | – | Q12 |
| C-LOC-01 | India apps | Unknown whether India Tax Base / GST / TDS are installed. The card shows custom "PAN Number"/"GST Number" in General, not the standard "Tax Information" group. | TENANT? | BLOCKER | S16, S36c | – | `$metadata` check | – | – | Q1 |
| C-LOC-02 | Custom vs standard fields | If both exist, only the **standard** India fields drive GST/TDS calculation | TENANT? + REC | HIGH | S12–S17 | 12 | Write the standard fields; mirror into custom ones only if the tenant requires it | – | – | Q2 |
| C-LOC-03 | Version | BC 22 vs current: e.g., Home Page 80 vs 255 | STD | MED | S01, S02 | 11 | Target profile per BC version | – | – | |
| C-LOC-04 | Custom fields | Vendor Status, Assesse Type, Deduction Certificate: meaning, mandatory status and values unknown | EXT / TENANT? | MED | S36c | 11 | Ask the BC admin | – | – | Q3 |

## CROSS_DOCUMENT

| ID | Field | Constraint | Type | Sev | Source | Stage | Method | Auto-fix? | Review? | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-XD-01 | GSTIN, PAN, Udyam, IFSC, account no. | **Compare identifiers exactly** after normalization. The current fuzzy threshold of 0.85 treats GSTINs 2 characters apart and PANs 1 character apart as "consistent". | CUSTOM | BLOCKER | M3 | 7 | Exact equality for `value_type` alphanumeric/numeric | No | Yes | MANUAL_REVIEW / BLOCK_SUBMISSION | CROSS_DOCUMENT_MISMATCH | Bug in `validator.compare_across_documents` |
| C-XD-02 | GSTIN | GST certificate is authoritative | CUSTOM | – | S36b | 7 | Precedence list (exists) | – | – | – | – | |
| C-XD-03 | PAN | GSTIN[3..12] = PAN card PAN = Udyam PAN | CUSTOM | BLOCKER | S13 | 7 | Exact | No | Yes | BLOCK_SUBMISSION | CROSS_DOCUMENT_MISMATCH | |
| C-XD-04 | Legal name | GST "Legal Name" is authoritative; Udyam "Name of Enterprise" should match after suffix normalization | CUSTOM | MED | – | 7 | Normalized fuzzy (names only) | No | If below threshold | MANUAL_REVIEW | CROSS_DOCUMENT_MISMATCH | |
| C-XD-05 | Trade vs legal name | May legitimately differ | CUSTOM | LOW | – | 7 | Don't compare trade name with legal name | – | – | AUTO_PASS | – | |
| C-XD-06 | Address | GST principal place of business is the BC address. Udyam plant address may differ. | CUSTOM | LOW | – | 7 | Warn only | – | – | AUTO_PASS | – | |
| C-XD-07 | State triangle | GSTIN state code ⇔ address state ⇔ PIN state must all agree | CUSTOM | HIGH | S13, S15 | 7 | Rule (partly exists: PIN↔state) | No | Yes | MANUAL_REVIEW | GSTIN_STATE_MISMATCH / PIN_STATE_MISMATCH | |
| C-XD-08 | Bank details | Cheque is authoritative. Udyam bank details (if printed) are compared exactly. | CUSTOM | HIGH | – | 7 | Exact | No | Yes | MANUAL_REVIEW | CROSS_DOCUMENT_MISMATCH | |
| C-XD-09 | Registry name | Live-registry legal name vs extracted name | CUSTOM | MED | S36a | 7 | Normalized fuzzy | No | If mismatch | MANUAL_REVIEW | CROSS_DOCUMENT_MISMATCH | Only when the registry check is enabled |

## NORMALIZATION

| ID | Field | Constraint | Type | Sev | Source | Stage | Method | Auto-fix? | Review? | Auto | Error code | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-NRM-01 | All | Safe: trim, collapse whitespace, uppercase identifiers, remove spaces inside identifiers, strip a leading `+91`/`91` from mobiles, lowercase e-mail | CUSTOM | – | – | 4 | Existing ops | Yes | No | AUTO_FIX | – | |
| C-NRM-02 | Account number | `digits_only` **deletes** non-digits. OCR `O`→`0` or `I`→`1` confusions shorten the number silently (e.g., `12O456789` becomes `12456789`, which still passes 9–18). | CUSTOM | BLOCKER | S36b | 4 | Allow removal of spaces/hyphens only; any other non-digit is INVALID_BANK_ACCOUNT | No | Yes | BLOCK_SUBMISSION | INVALID_BANK_ACCOUNT | Violates the no-silent-change rule |
| C-NRM-03 | IFSC | `fix_ifsc_confusions` rewrites chars 1–4 and forces char 5 to `0` **with no provenance note** | CUSTOM | HIGH | S36b | 4 | Keep the repair as a **candidate**: record the original, flag it, and auto-accept only if the repaired code exists in the RBI IFSC master | Candidate only | Yes | MANUAL_REVIEW | INVALID_IFSC | |
| C-NRM-04 | Vendor name | `split_corporate_suffix` re-spaces and re-cases suffix tokens | CUSTOM | MED | S36b | 4 | Keep the original and add a note | Yes (with note) | Show the diff | AUTO_FIX | – | Legal names should round-trip |
| C-NRM-05 | PIN | `digits_only` then regex. Removed letters make the regex fail, so it's caught. | CUSTOM | LOW | S36b | 4, 6 | Existing | – | – | AUTO_PASS | INVALID_PIN | |
| C-NRM-06 | Country | Invalid country is replaced by the default "India" (with a note) | CUSTOM | LOW | S36b | 4 | Prefer deriving it from the GSTIN (Indian GSTIN ⇒ India), then look up the BC code | Yes | No | AUTO_LOOKUP | INVALID_COUNTRY | |
| C-NRM-07 | All | Keep the **original extracted value** next to every normalized or derived value | CUSTOM | HIGH | brief §26 | 3, 4 | Data model | – | – | – | – | |
| C-NRM-08 | All | **Never truncate** | CUSTOM | BLOCKER | brief §26 | 11 | `master` `_fit_to_bc_width` must be removed | – | – | – | FIELD_TOO_LONG | |
| C-NRM-09 | Website | Derived from the e-mail domain. It's an inference, not evidence. | CUSTOM | MED | S36b | 4, 11 | Push only if a human confirmed it | – | Yes | MANUAL_REVIEW | DERIVED_VALUE_UNCONFIRMED | |
