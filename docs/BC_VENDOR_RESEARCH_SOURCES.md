# BC Vendor Research: Sources

Companion to [BC_VENDOR_CONSTRAINTS_RESEARCH.md](BC_VENDOR_CONSTRAINTS_RESEARCH.md). Every factual claim in the research set cites one of the IDs below (for example, `[S02]`).

Research date: 2026-09-29.

Target system: the tenant runs **Business Central 22 on-premises**. The repo's OData base URL is `http://ntz-srv-bcdb:2248/BC220/ODataV4`, so the source used for field lengths and trigger behaviour is **BC 22, India localization**, not the current SaaS version. Where the two differ, the docs say so.

## How to read the source tiers

| Tier | Meaning | Examples |
|---|---|---|
| **A: Official Microsoft source code** | Microsoft's own AL, published by Microsoft | `microsoft/ALAppExtensions` (India GST, TDS and Tax Base apps) |
| **A-: Version-exact source mirror** | Microsoft-shipped AL for a specific build, mirrored from the released artifacts by a well-known community maintainer. Used because the BC 22 BaseApp source is not published on a Microsoft-owned GitHub repo. Every India rule quoted from it was cross-checked against Tier A and is identical. | `StefanMaron/MSDyn365BC.Code.History`, branch `in-22` |
| **B: Official Microsoft documentation** | Microsoft Learn | Table/API reference, India localization, admin guides |
| **C: Official Indian government** | Income Tax Department | PAN structure |
| **D: Secondary / community** | Used only where no official page was found, and labelled as such wherever cited | GSTIN checksum algorithm, GST state-code list, IFSC format summary |
| **R: Repository evidence** | This repo, at the stated commits | Code and config lines |

## A / A-: Source code

| ID | What | Link | Used for |
|---|---|---|---|
| S02 | BC 22 IN, `Vendor.Table.al` (table 23) | https://github.com/StefanMaron/MSDyn365BC.Code.History/blob/in-22/BaseApp/Source/Base%20Application/PurchasesPayables/Vendor.Table.al | All BC 22 field types and lengths; triggers for No., Name, City, Post Code, Country, Phone, E-Mail, Registration Number, OnInsert, OnDelete |
| S03 | BC 22 IN, `VendorCard.Page.al` (page 26) | https://github.com/StefanMaron/MSDyn365BC.Code.History/blob/in-22/BaseApp/Source/Base%20Application/PurchasesPayables/VendorCard.Page.al | Control order and names (OData property names), template-on-new logic (`GuiAllowed`) |
| S04 | BC 22 IN, `PostCode.Table.al` | https://github.com/StefanMaron/MSDyn365BC.Code.History/blob/in-22/BaseApp/Source/Base%20Application/Foundation/PostCode.Table.al | `ValidatePostCode`, `ValidateCity`, `CheckClearPostCodeCityCounty` |
| S05 | BC 22 IN, `VendorBankAccount.Table.al` (table 288) | https://github.com/StefanMaron/MSDyn365BC.Code.History/blob/in-22/BaseApp/Source/Base%20Application/BankMgt/VendorBankAccount.Table.al | Bank account field lengths, key, delete rule, "Bank Account No. or IBAN" rule |
| S06 | BC 22 IN, `VendorTemplMgt.Codeunit.al` and `VendorTempl.Table.al` | https://github.com/StefanMaron/MSDyn365BC.Code.History/blob/in-22/BaseApp/Source/Base%20Application/VendorTemplMgt.Codeunit.al | How templates are selected and applied (only fills empty fields; RecordRef assignment) and which fields a template can hold |
| S07 | BC 22 IN, `APIV2Vendors.Page.al` and `APIV2BankAccounts.Page.al` | https://github.com/StefanMaron/MSDyn365BC.Code.History/blob/in-22/APIV2/Source/_Exclude_APIV2_/src/pages/APIV2Vendors.Page.al | Fields exposed by API v2.0 `vendors`; `bankAccounts` is the company's own `Bank Account`, not vendor bank accounts |
| S08 | BC 22 IN, `GraphMgtGeneralTools.Codeunit.al` | https://github.com/StefanMaron/MSDyn365BC.Code.History/blob/in-22/BaseApp/Source/Base%20Application/Integration/Graph/GraphMgtGeneralTools.Codeunit.al | `ProcessNewRecordFromAPI` applies Config. Templates to API-created records |
| S09 | BC 22 IN, `GenJnlPostLine.Codeunit.al` | https://github.com/StefanMaron/MSDyn365BC.Code.History/blob/in-22/BaseApp/Source/Base%20Application/FinancialMgt/GeneralLedger/GenJnlPostLine.Codeunit.al | `Vend.TestField("Vendor Posting Group")` at posting |
| S10 | BC 22 IN, `WorkflowSetup.Codeunit.al` | https://github.com/StefanMaron/MSDyn365BC.Code.History/blob/in-22/BaseApp/Source/Base%20Application/OtherCapabilities/Workflow/WorkflowSetup.Codeunit.al | Vendor Approval Workflow (`VENDAPW`): restrict record usage until approved |
| S11 | BC 22 IN, `MailManagement.Codeunit.al` | https://github.com/StefanMaron/MSDyn365BC.Code.History/blob/in-22/BaseApp/Source/Base%20Application/MailManagement.Codeunit.al | E-mail validation rules |
| S12 | Microsoft, India GST: `GSTPurchaseSubscribers.codeunit.al` | https://github.com/microsoft/ALAppExtensions/blob/main/Apps/IN/INGST/app/GSTPurchase/src/Codeunit/GSTPurchaseSubscribers.codeunit.al | Vendor validations for GST Registration No., GST Vendor Type, State Code, P.A.N. No., ARN No., Aggregate Turnover, Associated Enterprises (identical in the `in-22` mirror) |
| S13 | Microsoft, India GST: `GSTBaseValidation.Codeunit.al` | https://github.com/microsoft/ALAppExtensions/blob/main/Apps/IN/INGST/app/GSTBase/src/Codeunit/GSTBaseValidation.Codeunit.al | `CheckGSTRegistrationNo`: length 15, state-code prefix, PAN match, per-position character classes, **no checksum** |
| S14 | Microsoft, India GST: `GSTVendorExt.TableExt.al`, `GSTVendorType.enum.al`, `GSTVendorCardExt.PageExt.al` | https://github.com/microsoft/ALAppExtensions/blob/main/Apps/IN/INGST/app/GSTPurchase/src/tableextension/GSTVendorExt.TableExt.al | India GST vendor fields, types, enum values, card placement |
| S15 | Microsoft, India Tax Base: `VendorExt.TableExt.al`, `PANStatus.enum.al`, `State.table.al`, `GSTStateExt.TableExt.al` | https://github.com/microsoft/ALAppExtensions/blob/main/Apps/IN/INTaxBase/app/src/tableextension/VendorExt.TableExt.al | P.A.N. No., P.A.N. Status (and its overwrite side effect), State Code, Assessee Code, State table structure |
| S16 | Microsoft, India Tax Base: `VendorCardExt.PageExt.al` | https://github.com/microsoft/ALAppExtensions/blob/main/Apps/IN/INTaxBase/app/src/pageextension/VendorCardExt.PageExt.al | "State Code" added to the General group; "Tax Information" group layout |
| S17 | Microsoft, India TDS: `AllowedSections.Table.al`, `TDSConcessionalCode.Table.al`, `TDSVendorCard.PageExt.al`, `TDSValidations.Codeunit.al` | https://github.com/microsoft/ALAppExtensions/blob/main/Apps/IN/INTDS/app/TDSBase/src/table/AllowedSections.Table.al | TDS sections are a separate vendor sub-table; PAN checks at TDS posting |
| S18 | BC 22 IN, `AggregateTurnover.enum.al` (India GST) | https://github.com/StefanMaron/MSDyn365BC.Code.History/blob/in-22/INGST/Source/India%20GST/GSTPurchase/src/Enum/AggregateTurnover.enum.al | Enum values; value 0 = "More than 20 lakh" is the default |

## B: Microsoft Learn

| ID | Page | Link | Used for |
|---|---|---|---|
| S01 | Table Vendor (current version) | https://learn.microsoft.com/en-us/dynamics365/business-central/application/base-application/table/microsoft.purchases.vendor.vendor | Current-version lengths (e.g., Home Page 255 now vs 80 in BC 22) |
| S19 | India: Purchase from Registered Vendors | https://learn.microsoft.com/en-us/dynamics365/business-central/localfunctionality/india/gst-purchase-from-registered-vendor | Registered vendor setup: GST Vendor Type, GST Registration No., State Code |
| S20 | India: TDS overview | https://learn.microsoft.com/en-us/dynamics365/business-central/localfunctionality/india/tds-overview | Assessee Code, PAN (higher TDS rate if missing), Allowed Sections, concessional codes |
| S21 | Register a new vendor | https://learn.microsoft.com/en-us/dynamics365/business-central/purchasing-how-register-new-vendors | Template selection; vendors with posted transactions can't be deleted |
| S22 | Block vendors | https://learn.microsoft.com/en-us/dynamics365/business-central/payables-how-block-vendors | Blocked options |
| S23 | API v2.0 vendor resource | https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/resources/dynamics_vendor | Property list (no posting groups, no India fields, no bank accounts) |
| S24 | Configure API Templates | https://learn.microsoft.com/en-us/dynamics365/business-central/admin-configuring-api-template | API templates fill only empty properties, by order and conditions |
| S25 | OData web services: data modification | https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/webservices/use-odata-to-modify-data | POST runs OnNewRecord/OnInsert; PATCH needs If-Match; Insert/Modify permissions |
| S26 | Troubleshooting OData/SOAP on pages | https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/webservices/web-service-troubleshooting-soap-odata-ui-pages | "page structure and fields might also change … not something you can depend on being stable" |
| S27 | Handling UI interaction in web service endpoints | https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/webservices/handling-ui-interaction-when-working-with-web-services | Confirm dialogs raise errors in web-service sessions; Messages are suppressed |
| S28 | Code data type | https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/developer/methods-auto/code/code-data-type | Code values are uppercased and trimmed |
| S29 | Change log / field monitoring | https://learn.microsoft.com/en-us/dynamics365/business-central/across-log-changes | Auditing vendor/bank changes; monitoring sensitive fields |
| S30 | Prepare a configuration package | https://learn.microsoft.com/en-us/dynamics365/business-central/admin-how-to-prepare-a-configuration-package | The "Validate Field" option can be cleared (validation skipped) |
| S31 | Use approval workflows | https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows | Records are locked for processing while pending approval |
| S37 | Developing a custom API | https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/developer/devenv-develop-custom-api | Custom API page pattern (SystemId key, DelayedInsert) |

## C: Official Indian government

| ID | Page | Link | Used for |
|---|---|---|---|
| S32 | Income Tax Department: How PAN is formed | https://www.incometaxindia.gov.in/w/how-pan-is-formed-and-how-it-gets-its-unique-identity- | PAN positions; 4th character = holder type (A, B, C, F, G, H, J, L, P, T); 5th character = first letter of name/surname; 10th = check letter |

## D: Secondary / community (labelled wherever used)

| ID | Page | Link | Used for | Caveat |
|---|---|---|---|---|
| S33 | Indian Financial System Code (Wikipedia; RBI maintains the codes) | https://en.wikipedia.org/wiki/Indian_Financial_System_Code | IFSC = 4 letters + `0` + 6 alphanumerics | Verify against RBI's own IFSC master before using it for auto-acceptance |
| S34 | GST state code list (ClearTax) | https://cleartax.in/s/gst-state-code-jurisdiction | Codes 01–38 (25 discontinued after the DNH/DD merger), 97 Other Territory, 99 Other Country/Centre | Not a government page. The tenant's `State` table is the actual BC constraint. |
| S35 | GSTIN check digit (DEV Community) | https://dev.to/tarun_vaghasia_a387e1ac9b/how-gstin-checksum-validation-works-and-why-it-isnt-enough-3l8e | Mod-36 check-character algorithm; checksum ≠ active registration | GSTN has not published it as a formal spec that we could locate. Test it against the known-good GSTINs in the ground truth before enforcing it as BLOCK. |

## R: Repository evidence

| ID | What |
|---|---|
| S36a | `master` @ `5677e46` (2026-09-21): `backend/app/services/bc_mapper.py`, `backend/app/routers/business_central.py`, `scripts/push_to_bc.ps1`, `docs/BC_VENDOR_PUSH_GUIDE.md`, `backend/app/services/gstin_verification.py`, `backend/app/services/extraction.py` |
| S36b | `ocr-testing` @ `a0e0fc8` (2026-09-29): `backend/app/services/extraction_pipeline/**`, `backend/config/*.yaml`, `backend/app/models/model.py`, `backend/app/schemas/vendor_schema.py`, `backend/app/eval/*.yaml`, `docs/ADDRESS_SEGMENTATION_RESEARCH.md` |
| S36c | Screenshot of the live Vendor Card (VEN/0023, PEENYA CONTROL SYSTEMS PVT LTD) supplied by the user. It shows en-US captions, custom General-group fields (PAN Number, GST Number, Vendor Status, Assesse Type, Deduction Certificate) and a "Request Approval" action. |

## Measurements taken during this research (reproducible)

| ID | Measurement | How |
|---|---|---|
| M1 | `resolve_address_blob(..., multiline=True)` on `ocr-testing@a0e0fc8` produces Address 2 = 69 chars for the canonical `bc_floor_block_park_localities` address, at confidence `high` | `python -c` run from `backend/` (see research report §7.2) |
| M2 | Expected Address 2 > 50 chars in 5 of 136 eval cases (`address_vendor_lines` 1/20, `address_line_cases` 3/74, `address_holdout_cases` 1/30, `address_cases` 0/12). Expected Address 1 is never > 43 chars. | YAML scan of `backend/app/eval/*.yaml` on `ocr-testing` |
| M3 | `rapidfuzz.fuzz.ratio`: GSTIN with 1 differing char = 93.3; with 2 differing chars = 86.7; PAN with 1 = 90.0; account no. with 1 = 92.9. All are above the configured 85 threshold, so they are treated as "consistent". | `python -c` with `rapidfuzz==3.14.5` (the pinned version) |
| M4 | No GSTIN checksum logic exists anywhere in `backend/`. `config.py` comments claim a "regex/checksum format check". | `git grep -i checksum` on `ocr-testing` |
| M5 | The mod-36 check character (validation design §11.1) passes the verified ground-truth GSTIN `19AABCM7980K1ZU` and detects **all 525** single-character substitutions of it. It fails the live-card GSTIN `29AADCP7742H1ZS` (stored in the custom "GST Number" field). Only 4 of the 56 distinct GSTIN-shaped strings in `backend/` (mostly synthetic fixtures) pass. | `python` brute-force over `0-9A-Z` at each of the 15 positions; `git grep` of GSTIN-shaped strings |
