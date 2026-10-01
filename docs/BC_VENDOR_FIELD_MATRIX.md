# BC Vendor Field Matrix

Companion to [BC_VENDOR_CONSTRAINTS_RESEARCH.md](BC_VENDOR_CONSTRAINTS_RESEARCH.md). Source IDs (`[Sxx]`) are listed in [BC_VENDOR_RESEARCH_SOURCES.md](BC_VENDOR_RESEARCH_SOURCES.md). Constraint IDs (`C-xxx-nn`) are defined in [BC_VENDOR_CONSTRAINT_REGISTRY.md](BC_VENDOR_CONSTRAINT_REGISTRY.md).

**Target version: BC 22 on-prem, India localization (IN).** The server path is `/BC220/`. Lengths are from the BC 22 source `[S02][S05]` and the India apps `[S12]–[S17]`. Where the current Microsoft Learn page `[S01]` shows a different length, both are given.

## Legend

**Scope tags**

| Tag | Meaning |
|---|---|
| **STD** | Standard BC (W1 base application) |
| **IN** | India localization app (India Tax Base / India GST / India TDS) |
| **CFG** | Configuration-dependent (valid values live in the tenant's setup tables) |
| **EXT** | Extension-dependent (a tenant or partner extension, not Microsoft's) |
| **CUSTOM** | Our own business rule |
| **TENANT?** | UNKNOWN / REQUIRES TENANT VERIFICATION |

**Source class** (values from the brief)

| Class | Meaning |
|---|---|
| DOCUMENT_EXTRACTED | Read off a vendor document |
| DERIVED | Computed from another value |
| MASTER_DATA_LOOKUP | Must match an existing BC setup record |
| CONFIGURATION | Company policy value, not per-vendor evidence |
| USER_INPUT | Only a human can decide it |
| AUTO_DEFAULT | BC fills it |
| VALIDATION_ONLY | Used to check other values, never sent |

**OData name (VendorCard page, BC 22)**
- **(O)** Observed. The name is used by the repo's `bc_mapper.py`, whose docstring says the names came from a live `GET …/VendorCard` on BC220 `[S36a]`.
- **(E)** Expected. OData property names on UI pages come from the page control name with non-alphanumerics replaced by `_` (the observed names follow this rule, e.g., control `MobilePhoneNo` becomes `MobilePhoneNo`). Confirm against `…/ODataV4/$metadata` (open question Q1).

---

## 1. Vendor core, identity and contact (table 23 "Vendor")

| Field (caption) | Field no. | OData (VendorCard) | API v2.0 `vendors` | Type [len] BC 22 | Required? | Allowed values / lookup | Default | Source class | Repo field | Scope | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| No. | 1 | `No` (O) | `number` | Code[20] | PK. Blank on insert → No. Series | `Purchases & Payables Setup."Vendor Nos."` must be set (`TestField`) | Next number of the default vendor series | AUTO_DEFAULT | `bc_no` (after push) | STD+CFG | Manual numbers only if the series allows them `[S02]`. The tenant shows two prefixes (`VEN/`, `EMPV/`); see C-CFG-02. |
| Name | 2 | `Name` (O) | `displayName` | Text[100] | Not table-mandatory; our business rule requires it | Free text | – | DOCUMENT_EXTRACTED (GST "Legal Name") | `vendor_name` | STD | `master` mapper assumes 50, which is wrong. OnValidate copies to Search Name `[S02]`. |
| Search Name | 3 | `Search_Name` (E) | – | Code[100] | – | Uppercased copy of Name | = Name | AUTO_DEFAULT | – | STD | Don't send |
| Name 2 | 4 | `Name_2` (E) | – | Text[50] | Optional | Free text | – | DOCUMENT_EXTRACTED (GST "Trade Name") | – (not extracted) | STD | Candidate home for the trade name; company convention needed (Q18) |
| Blocked | 39 | `Blocked` (E) | `blocked` | Enum "Vendor Blocked" | – | `" "`, `Payment`, `All` `[S22]` | `" "` | CONFIGURATION | – | STD | Changing Blocked (to anything other than `All`) while Privacy Blocked is on asks for confirmation in the UI and raises an error in web-service sessions (`not GuiAllowed`) `[S02]` |
| Contact | 8 | `Control16` (E; the control is named `Control16`, not `Contact`) | – | Text[100] | Optional | Free text | – | USER_INPUT | – | STD | `master` mapper assumes 50 (wrong). OnValidate may create a Contact person if Marketing Setup has a Bus. Rel. Code `[S02]`. |
| Phone No. | 9 | `Phone_No` (O) | `phoneNumber` | Text[30] | Optional | No letters (`must not contain letters`) | – | DOCUMENT_EXTRACTED | `telephone_1` | STD | `[S02]` |
| Mobile Phone No. | 5061 | `MobilePhoneNo` (O) | – | Text[30] | Optional | No letters | – | DOCUMENT_EXTRACTED | `telephone_2` | STD | `[S02]` |
| E-Mail | 102 | `E_Mail` (O) | `email` | Text[80] | Optional | Each `;`-separated address: no spaces, exactly one `@`, not starting or ending with `@` | – | DOCUMENT_EXTRACTED | `email` | STD | `[S02][S11]` |
| Home Page | 103 | `Home_Page` (O) | `website` | **Text[80] in BC 22**; Text[255] in the current version `[S01]` | Optional | Free text | – | DERIVED (repo derives it from the e-mail domain) | `website` | STD | A derived value must not be pushed unless a human confirmed it |
| Registration Number (caption "Registration No.") | 25 | `Registration_Number` (E) | – | Text[50] **but OnValidate errors if > 20 chars** | Optional | Free text | – | DOCUMENT_EXTRACTED (Udyam no., 19 chars) | `udyam_no` (not mapped) | STD | Company convention needed for what goes here (Q18) |
| VAT Registration No. | 86 | `VAT_Registration_No` (E) | `taxRegistrationNumber` | Text[20] | Optional | VAT format rules per country | – | – | – | STD | Not GSTIN. India uses GST Registration No. Don't put the GSTIN here unless the company decides to. |
| Partner Type | 132 | `Partner_Type` (E) | – | Enum | Optional | `" "`, `Company`, `Person` | `" "` | DERIVED (PAN 4th char: `P` → Person, others → Company) | `company_type` (indirect) | STD | Suggestion only |
| Primary Contact No. | 5049 | `Primary_Contact_No` (E) | – | Code[20] | Optional | Contact linked to this vendor's company contact, else error | – | USER_INPUT | – | STD | Needs the vendor to exist first |
| Privacy Blocked | 150 | `Privacy_Blocked` (E) | – | Boolean | – | – | false | CONFIGURATION | – | STD | Don't send |

## 2. Address (table 23)

| Field (caption, en-US UI caption) | Field no. | OData | API v2.0 | Type [len] | Required? | Lookup / behaviour | Source class | Repo field | Scope | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| Address | 5 | `Address` (O) | `addressLine1` | **Text[100]** | Optional | Free text, no semantics, no validation | DOCUMENT_EXTRACTED + segmentation | `address_1` | STD | `master` mapper assumes 50 (wrong) |
| Address 2 | 6 | `Address_2` (O) | `addressLine2` | **Text[50]** | Optional | Free text, no semantics, no validation | DOCUMENT_EXTRACTED + segmentation | `address_2` (+`address_3`,`address_4` joined on `master`) | STD | The tightest address field; see C-ADR-03 |
| Country/Region Code | 35 | `Country_Region_Code` (O) | `country` | Code[10] | Optional | Must exist in `Country/Region`. Changing it (from a non-blank value) clears Post Code, City, County unless `G/L Setup."Req.Country/Reg. Code in Addr."` | MASTER_DATA_LOOKUP | `country` (sends the name "India") | STD+CFG | The tenant's code may be `IN` or `INDIA` (Q4) |
| City | 7 | `City` (O) | `city` | Text[30] | Optional | Relation to `Post Code`.City with `ValidateTableRelation=false`. `ValidateCity` only runs when `GuiAllowed`, so it is not validated through OData `[S04]`. | DOCUMENT_EXTRACTED / DERIVED (PIN directory) | `city` | STD | |
| County (UI: "State") | 92 | `County` (O) | `state` | Text[30] | Optional | Free text. The caption comes from the country's CaptionClass (`'5,1,'+Country`). | DOCUMENT_EXTRACTED | `state` | STD | Not the India GST State Code (see §4) |
| Post Code (UI: "ZIP Code") | 91 | `Post_Code` (O) | `postalCode` | Code[20] | Optional | Relation to `Post Code` with `ValidateTableRelation=false`. **If the PIN exists in the `Post Code` table, validation overwrites City, County and Country from that record. If it doesn't exist, it's accepted silently.** `[S04]` | DOCUMENT_EXTRACTED | `pin_code` | STD+CFG | Q6 |

## 3. Posting, payment and other configuration (table 23)

These relate to other BC tables. An unknown value gives: `The field <X> of table Vendor contains a value (<v>) that cannot be found in the related table (<T>).`

| Field | Field no. | OData | API v2.0 | Type [len] | Required? | Lookup table | Source class | Repo | Scope | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| Vendor Posting Group | 21 | `Vendor_Posting_Group` (O) | – | Code[20] | **Not at insert; required at posting** (`Vend.TestField("Vendor Posting Group")` `[S09]`) | Vendor Posting Group | CONFIGURATION (template / company policy) | env `BC_VENDOR_POSTING_GROUP` | STD+CFG | The only observed tenant value is `EMPLOAN` (looks like an employee-loan group), so confirm the trade-vendor group (Q8) |
| Gen. Bus. Posting Group | 88 | `Gen_Bus_Posting_Group` (O) | – | Code[20] | Not at insert. Used with the item/G-L Gen. Prod. Posting Group to find General Posting Setup when purchase documents post (setup-dependent). | Gen. Business Posting Group. **OnValidate auto-sets VAT Bus. Posting Group from `Def. VAT Bus. Posting Group`** `[S02]` | CONFIGURATION | env | STD+CFG | |
| VAT Bus. Posting Group | 110 | `VAT_Bus_Posting_Group` (O) | – | Code[20] | Setup-dependent (India GST doesn't use VAT) | VAT Business Posting Group | CONFIGURATION | env | STD+CFG | |
| Currency Code | 22 | `Currency_Code` (E) | `currencyCode`/`currencyId` | Code[10] | Optional (blank = LCY) | Currency | CONFIGURATION | – | STD+CFG | Don't send `INR` for domestic vendors. LCY is blank; `INR` fails unless a Currency record `INR` exists. |
| Payment Terms Code | 27 | `Payment_Terms_Code` (E) | `paymentTermsId` | Code[10] | Optional | Payment Terms | CONFIGURATION | – | STD+CFG | MSME vendors may need a policy (see §5 of the main report) |
| Payment Method Code | 47 | `Payment_Method_Code` (E) | `paymentMethodId` | Code[10] | Optional | Payment Method | CONFIGURATION | – | STD+CFG | |
| Purchaser Code | 29 | `Purchaser_Code` (E) | – | Code[20] | Optional; OnInsert sets a default purchaser if blank | Salesperson/Purchaser where `Blocked=false` | CONFIGURATION / USER_INPUT | – | STD+CFG | |
| Responsibility Center / Location Code | 5700 / 5701 | `Responsibility_Center` / `Location_Code` (E) | – | Code[10] | Optional | Responsibility Center / Location | CONFIGURATION | – | STD+CFG | |
| Language Code | 24 | `Language_Code` (E) | – | Code[10] | Optional | Language | CONFIGURATION | – | STD+CFG | |
| Global Dimension 1/2 Code | 16/17 | `Global_Dimension_1_Code`… (E) | via `defaultDimensions` | Code[20] | Optional unless Default Dimension rules demand them | Dimension Value | CONFIGURATION | – | STD+CFG | |
| Prices Including VAT | 82 | (E) | – | Boolean | – | – | CONFIGURATION | – | STD | |
| Application Method | 80 | (E) | – | Enum | – | `Manual`, `Apply to Oldest` | CONFIGURATION | – | STD | |
| Company Size Code | 135 | (E) | – | Code[20] | Optional | Company Size (Payment Practices) | DERIVED? (Udyam class) / CONFIGURATION | – | STD+CFG | Possible home for MSME class. Company decision. |
| Preferred Bank Account Code | 288 | `Preferred_Bank_Account_Code` (E) | – | Code[20] | Optional | **Vendor Bank Account.Code of the same vendor** | DERIVED (after the bank account is created) | – | STD | Must be set after the bank account exists |
| IC Partner Code, Territory, Shipment Method, Shipping Agent, Fin. Charge Terms, Base Calendar, Document Sending Profile, Over-Receipt Code, Cash Flow Payment Terms | various | (E) | – | Code[10–20] | Optional | Own setup tables | CONFIGURATION | – | STD+CFG | Not needed for onboarding. Leave to template. |

## 4. India localization fields on Vendor (only if the India apps are installed: Q1)

| Field | Field no. (app) | OData (E) | API v2.0 | Type [len] | Rules (BC-enforced) | Source class | Repo field | Scope |
|---|---|---|---|---|---|---|---|---|
| State Code | 18547 (Tax Base) | `State_Code` | – | Code[10] → `State` table | Setting it while GST Vendor Type ∉ {Import, Unregistered} requires GST Registration No. to be **blank** at that moment. Error for Import. `[S12]` | MASTER_DATA_LOOKUP (via GSTIN digits 1–2 → `State."State Code (GST Reg. No.)"`) | – (only `state` name text) | IN+CFG |
| P.A.N. No. | 18544 (Tax Base) | `P_A_N_No` | – | Code[20] | If GSTIN present, must equal GSTIN[3..12] (`From position 3 to 12 in GST Registration No. should be same as it is in PAN No.`) `[S12]` | DOCUMENT_EXTRACTED | `pan` → custom `PAN_Number` today | IN |
| P.A.N. Status | 18545 (Tax Base) | `P_A_N_Status` | – | Enum `" "`, `PANAPPLIED`, `PANNOTAVBL`, `PANINVALID` | **OnValidate overwrites P.A.N. No. with the status text.** Never send it when a real PAN is known. `[S15]` | USER_INPUT (only when PAN is unavailable) | – | IN |
| P.A.N. Reference No. | 18546 | `P_A_N_Reference_No` | – | Code[20] | Required at TDS posting when P.A.N. Status ≠ blank `[S17]` | USER_INPUT | – | IN |
| Assessee Code | 18543 | `Assessee_Code` | – | Code[10] → `Assessee Code` table (type Company/Others) | Required for TDS `[S20]` | MASTER_DATA_LOOKUP (DERIVED suggestion from PAN 4th char) | – | IN+CFG |
| GST Registration No. | 18080 (GST) | `GST_Registration_No` | – | Code[20]; BC requires exactly 15 | Needs State Code and P.A.N. No. (with blank status) already set. Checks the state-code prefix against `State."State Code (GST Reg. No.)"`, PAN at positions 3–12, and per-position character classes. **No checksum.** Auto-sets GST Vendor Type to Registered if it is blank, Import or Unregistered. `[S12][S13]` | DOCUMENT_EXTRACTED | `gst_no` → custom `GST_Number` today | IN |
| GST Vendor Type | 18081 (GST) | `GST_vendor_Type` (control name is literally `"GST vendor Type"`) | – | Enum `" "`, `Registered`, `Composite`, `Unregistered`, `Import`, `Exempted`, `SEZ` | Registered/Composite/SEZ/Exempted need GSTIN or ARN. Unregistered clears GSTIN and ARN and requires State Code. Import clears GSTIN and ARN and requires a blank State Code. Blank clears GSTIN. `[S12][S14]` | DERIVED (REG-06 registration type) / USER_INPUT | – | IN |
| ARN No. | 18084 (GST) | `ARN_No` | – | Code[20] | Must be blank for Import/Unregistered `[S12]` | DOCUMENT_EXTRACTED (rare) | – | IN |
| Aggregate Turnover | 18083 (GST) | `Aggregate_Turnover` | – | Enum `More than 20 lakh` (value 0, the default), `Less than 20 lakh` | Only changeable when GST Vendor Type = Unregistered, else error `[S12][S18]` | USER_INPUT | – | IN |
| Associated Enterprises | 18082 (GST) | `Associated_Enterprises` | – | Boolean | Only for Import | USER_INPUT | – | IN |
| Govt. Undertaking | 18090 (GST) | `Govt_Undertaking` | – | Boolean | If true, the GSTIN is only length-checked | USER_INPUT | – | IN |
| Composition, Transporter, Subcontractor, Vendor Location, Commissioner's Permission No. | 18085–18089 | (E) | – | Boolean / Code[10] / Text[50] | Vendor Location relates to a Location with `Subcontracting Location = true` | USER_INPUT | – | IN |

## 5. TDS sub-tables (India TDS; separate records keyed by vendor)

| Table | Key | Fields | Rules | Source class | Scope |
|---|---|---|---|---|---|
| Allowed Sections (18687) | Vendor No, TDS Section | TDS Section Code[10] → TDS Section; Default Section; Threshold Overlook; Surcharge Overlook; Non Resident Payments; Nature of Remittance; Act Applicable | Section chosen "depending on the kind of services provided by the vendor" `[S20]` | USER_INPUT (business decision; not on the documents) | IN+CFG |
| TDS Concessional Code (18688) | Vendor No., Section, Concessional Code, Certificate No., Start Date, End Date | Section must be one of this vendor's Allowed Sections; End Date ≥ Start Date | Lower-deduction certificate data `[S17][S20]` | DOCUMENT_EXTRACTED (from a sec. 197 certificate, which isn't in the current packet) + USER_INPUT | IN+CFG |

## 6. Vendor Bank Account (table 288, separate record)

| Field | Field no. | OData (if the card page is published) | API v2.0 | Type [len] | Required? | Rules | Source class | Repo field | Scope |
|---|---|---|---|---|---|---|---|---|---|
| Vendor No. | 1 | `Vendor_No` | **Not exposed** (API v2.0 `bankAccounts` is the company's own Bank Account `[S07]`) | Code[20], NotBlank, → Vendor | PK | Vendor must exist first | DERIVED | `bc_no` | STD |
| Code | 2 | `Code` | – | Code[20], **NotBlank** | PK | Must be generated by our rule (e.g., `PRIMARY` or IFSC-derived). Unique per vendor. | DERIVED (CUSTOM rule) | – | STD+CUSTOM |
| Name | 3 | `Name` | – | Text[100] | Optional | Bank name | DERIVED (IFSC → bank lookup) / DOCUMENT_EXTRACTED | `bank_name` | STD |
| Address / City / Post Code | 6/8/9 | … | – | Text[100] / Text[30] / Code[20] | Optional | Same Post Code behaviour as the vendor | DOCUMENT_EXTRACTED (branch) | `branch_address` | STD |
| Bank Branch No. | 13 | `Bank_Branch_No` | – | Text[20] | Optional | Free text | **Candidate for IFSC**. Tenant decision (Q11). | `ifsc_swift_code` | STD+TENANT? |
| Bank Account No. | 14 | `Bank_Account_No` | – | Text[30] | **Either Bank Account No. or IBAN is required for payment export** (`You must specify either a Bank Account No. or an IBAN.`) | Free text | DOCUMENT_EXTRACTED (cheque) | `account_number` | STD |
| SWIFT Code | 25 | `SWIFT_Code` | – | Code[20] → SWIFT Code (not validated) | Optional | International only | DOCUMENT_EXTRACTED (rare) | `ifsc_swift_code` (ambiguous) | STD |
| IBAN | 24 | `IBAN` | – | Code[50] | Optional | `CheckIBAN` | – (not used in India) | – | STD |
| Currency Code / Country/Region Code | 16/17 | … | – | Code[10] | Optional | Lookup | CONFIGURATION | – | STD |
| (account type CA/SB/CC) | – | – | – | – | – | **No standard field** | – | `account_type` | – |
| (account holder name) | – | – | – | – | – | **No standard field** (Name = bank name). Holder name is a cross-check value. | VALIDATION_ONLY | – (not extracted) | CUSTOM |
| (IFSC) | – | – | – | – | – | **No standard field in BC 22 IN Vendor Bank Account** (no India extension of table 288 exists in `in-22` `[S05]`) | – | `ifsc_swift_code` | TENANT? |

## 7. Tenant custom fields seen on the Vendor Card (screenshot `[S36c]`)

| Caption | OData | Type / length | Required? | Values | Notes | Scope |
|---|---|---|---|---|---|---|
| PAN Number | `PAN_Number` (O) | Unknown (repo assumes 20) | Unknown | Unknown | Not the India-loc `P.A.N. No.`. Only affects India tax logic if the extension copies it. | EXT / TENANT? |
| GST Number | `GST_Number` (O) | Unknown (repo assumes 20) | Unknown | Unknown | Not the India-loc `GST Registration No.` | EXT / TENANT? |
| Vendor Status | Unknown | Enum? (dropdown) | Unknown | Unknown | Possibly an onboarding/approval status | EXT / TENANT? |
| Assesse Type | Unknown | Enum? (dropdown, shows `' '`) | Unknown | Unknown | Possibly a copy of TDS assessee type | EXT / TENANT? |
| Deduction Certificate | Unknown | Text? | Unknown | Unknown | Possibly the sec. 197 lower-deduction certificate no. | EXT / TENANT? |

## 8. Portal fields with no standard BC destination

| Portal field (`models.Vendor`) | Why no destination | Recommendation |
|---|---|---|
| `address_3`, `address_4` | BC has only Address and Address 2 | Stop populating them on `ocr-testing` (already the case). Remove the join in the `master` mapper. |
| `tan_no` | TAN is the **deductor's** number (the company's), not a vendor attribute | Keep for the request form only. Don't push. |
| `esic_no` | No vendor field | Request form only, or a custom field |
| `udyam_no` | No standard field. Registration Number (≤ 20 chars) could hold it, by convention | Company decision (Q18) |
| `nature_of_business`, `company_type` | No direct field | Use to suggest Partner Type / Assessee Code; don't push raw text |
| `tds_applicable` | Drives whether Allowed Sections are created | USER_INPUT + section choice |
| `account_type` | No field in Vendor Bank Account | Request form only |
| `ifsc_swift_code` | Mixes two concepts | Split into `ifsc` and `swift`; map per Q11 |

---

## 9. Length / data-type matrix (brief §2 format)

"API limit" means the BC OData page and API v2.0, where the field is exposed. Both are bound to the table field, so the table length is the enforced limit, and a longer value is rejected by the server. `master`'s `bc_mapper.py` records this error as `Application_StringExceededLength` `[S36a]`.

"UI limit" is the Vendor Card control, which enforces the same length.

"Import limit" is split in two:
- **(a)** the portal's Excel request form: no limit, because it is just a spreadsheet.
- **(b)** a BC configuration package: table length, plus OnValidate rules only when "Validate Field" is on `[S30]`.

| Field | BC Field | Data Type | Max Length | Required | API Limit | UI Limit | Import Limit | Source | Notes |
|---|---|---|---|---|---|---|---|---|---|
| Vendor name | Vendor.Name | Text | 100 | Business rule | 100 (OData, API `displayName`) | 100 | (a) none (b) 100 | S02 | `master` mapper uses 50, which is wrong |
| Name 2 | Vendor."Name 2" | Text | 50 | No | 50 (OData only) | 50 | (a) none (b) 50 | S02 | |
| Address 1 | Vendor.Address | Text | 100 | No | 100 | 100 | (a) none (b) 100 | S02 | `master` mapper uses 50, which is wrong |
| Address 2 | Vendor."Address 2" | Text | **50** | No | 50 | 50 | (a) none (b) 50 | S02 | New segmenter puts the longer part here (C-ADR-03) |
| City | Vendor.City | Text | 30 | No | 30 | 30 | (a) none (b) 30 | S02 | May be overwritten by the Post Code record |
| State | Vendor.County | Text | 30 | No | 30 | 30 | (a) none (b) 30 | S02 | "Dadra and Nagar Haveli and Daman and Diu" is 40 chars and **doesn't fit** (C-LEN-06) |
| State (GST) | Vendor."State Code" | Code | 10 | Conditional (GSTIN) | 10 (OData) | 10 | (b) 10 | S15 | Must be a `State` record code |
| Country | Vendor."Country/Region Code" | Code | 10 | No | 10 | 10 | (b) 10 | S02 | Code, not name |
| Post Code | Vendor."Post Code" | Code | 20 | No | 20 | 20 | (b) 20 | S02 | PIN is 6 |
| Contact | Vendor.Contact | Text | 100 | No | 100 | 100 | (b) 100 | S02 | `master` mapper uses 50, which is wrong |
| Phone | Vendor."Phone No." | Text | 30 | No | 30, no letters | 30, no letters | (b) 30 (letters rule only if validated) | S02 | |
| Mobile | Vendor."Mobile Phone No." | Text | 30 | No | 30, no letters | same | same | S02 | |
| Email | Vendor."E-Mail" | Text | 80 | No | 80 + format | same | (b) 80 (+format if validated) | S02, S11 | |
| Website | Vendor."Home Page" | Text | 80 (BC 22) / 255 (current) | No | 80 | 80 | (b) 80 | S02, S01 | Version-dependent |
| GSTIN | Vendor."GST Registration No." | Code | 20 (must be 15) | Conditional | 20 storage; 15 enforced by OnValidate | same | (b) 20; 15 only if validated | S13 | |
| GSTIN (custom) | `GST_Number` | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | S36a | Q2 |
| PAN | Vendor."P.A.N. No." | Code | 20 (PAN is 10) | Conditional (GSTIN, TDS) | 20 | 20 | (b) 20 | S15 | |
| PAN (custom) | `PAN_Number` | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | S36a | Q2 |
| ARN | Vendor."ARN No." | Code | 20 | Conditional | 20 | 20 | (b) 20 | S14 | |
| Registration no. | Vendor."Registration Number" | Text | **50 storage / 20 validated** | No | 20 (OnValidate) | 20 | (b) 50 if "Validate Field" is cleared, else 20 | S02 | Example of a limit that depends on the path |
| Bank account no. | "Vendor Bank Account"."Bank Account No." | Text | 30 | For payments (or IBAN) | 30 (OData card page); **no API v2.0** | 30 | (b) 30 | S05 | Indian accounts are ≤ 18 digits |
| IFSC | (none standard) / "Bank Branch No." | Text | 20 if Bank Branch No. | – | 20 | 20 | (b) 20 | S05 | Q11 |
| Bank name | "Vendor Bank Account".Name | Text | 100 | No | 100 | 100 | (b) 100 | S05 | |
| Branch | "Vendor Bank Account".Address | Text | 100 | No | 100 | 100 | (b) 100 | S05 | |
| Bank account code | "Vendor Bank Account".Code | Code | 20 | **Yes (NotBlank)** | 20 | 20 | (b) 20 | S05 | Generated |
| Registration numbers (Udyam) | – | – | – | – | – | – | – | – | 19 chars; no standard field |

### Longest Indian state/UT names vs County Text[30]

Measured on the repo's own `indian_state` enum values (`validation_rules.yaml`):

| Name | Length | Fits County (30)? |
|---|---|---|
| Dadra and Nagar Haveli and Daman and Diu | 40 | **No** |
| Andaman and Nicobar Islands | 27 | Yes |
| Jammu and Kashmir | 17 | Yes |

So a state value can legitimately exceed a BC limit, and this is caught by the length gate, never truncated. The India-loc `State Code` (Code[10]) avoids the problem when the India apps are installed.
