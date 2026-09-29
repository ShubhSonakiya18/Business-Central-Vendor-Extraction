# BC Vendor Validation Design

Companion to [BC_VENDOR_CONSTRAINTS_RESEARCH.md](BC_VENDOR_CONSTRAINTS_RESEARCH.md). Constraint IDs are in [BC_VENDOR_CONSTRAINT_REGISTRY.md](BC_VENDOR_CONSTRAINT_REGISTRY.md) and sources in [BC_VENDOR_RESEARCH_SOURCES.md](BC_VENDOR_RESEARCH_SOURCES.md).

This is a **design**, not an implementation. No production code was changed for this research.

---

## 1. Design principles

1. **Preserve the original.** Every field carries `raw` (as extracted), `normalized`, and `bc_value` (what would be sent). None of them overwrites another. (C-NRM-07)
2. **Never truncate, invent, or guess silently.**
   - A value that violates a BC constraint is reported with the exact rule, the actual value and the limit, then routed to review.
   - The only automatic changes allowed:
     - the whitespace/case normalizations in §8;
     - the order-preserving address boundary shift in §7;
     - look-ups that resolve a value to an **existing** BC code.

   Every automatic change is recorded as provenance.
3. **Identifiers are compared exactly.** GSTIN, PAN, IFSC, account number and Udyam number either match character-for-character after normalization or they don't. Fuzzy similarity is only for names and addresses. (C-XD-01)
4. **Fail closed on unknown tenant facts.** If the BC target profile says a field's length or OData name is unverified, the submission gate treats that field as blocking until someone confirms it. (C-LOC-*)
5. **BC is the final validator, not the first.** Everything BC would reject is checked earlier, with a better message. BC errors that still happen are mapped to the same taxonomy (§2).
6. **Order-independent writes.** India GST validations depend on field order, and OData doesn't document the validation order within a request. Dependent fields go in separate requests (§6). (C-API-05)

---

## 2. Error taxonomy

Each finding has `code`, `class`, `severity`, `field`, `constraint_id`, `message`, `evidence` (raw value, source document/page), and `automation` (§3).

### 2.1 Extraction errors: class `EXTRACTION` (stages 1–3)

| Code | Meaning | Typical cause | Default automation |
|---|---|---|---|
| `FIELD_NOT_FOUND` | Required field has no candidate | Document missing, caption not matched | MANUAL_REVIEW |
| `LOW_CONFIDENCE` | Winner score below `min_accept` (0.60 today) | Weak label/position evidence | MANUAL_REVIEW |
| `CAPTION_LEAK` | Value is another field's caption | Layout mis-read (see `onboarding_mapper._is_caption_leak`) | MANUAL_REVIEW |
| `OCR_AMBIGUOUS_CHAR` | Value contains OCR-ambiguous glyphs in positions that must be digits or letters | `O/0`, `I/1`, `S/5`, `B/8`, `Z/2`, `G/6` | MANUAL_REVIEW |
| `DOCUMENT_UNREADABLE` | File couldn't be loaded or OCR'd | Corrupt file, unsupported type | BLOCK_SUBMISSION |
| `DOCUMENT_TYPE_UNKNOWN` | Classifier returned `other` | Unexpected document | AUTO_PASS (warning) |

### 2.2 Validation errors: class `VALIDATION` (stages 4–6, field-level)

| Code | Meaning | Constraint | Default automation |
|---|---|---|---|
| `FIELD_REQUIRED` | Business-required or BC-required value missing | C-REQ-02/04/05, C-PAN-05 | BLOCK_SUBMISSION |
| `FIELD_TOO_LONG` | Longer than the BC target length (after trim) | C-LEN-* | BLOCK_SUBMISSION |
| `INVALID_FORMAT` | Generic format/enum failure | C-TYP-04 | BLOCK_SUBMISSION |
| `INVALID_GSTIN` | Length, character class, state prefix or **checksum** failure | C-GST-05/06/19, C-LEN-14 | BLOCK_SUBMISSION |
| `INVALID_PAN` | Regex or holder-type failure | C-PAN-01/02, C-LEN-15 | BLOCK_SUBMISSION |
| `INVALID_PIN` | Not `[1-9][0-9]{5}` | C-NRM-05 | BLOCK_SUBMISSION |
| `INVALID_IFSC` | Not `[A-Z]{4}0[A-Z0-9]{6}`, or repaired and not confirmed | C-BNK-04, C-NRM-03 | BLOCK_SUBMISSION / MANUAL_REVIEW |
| `INVALID_BANK_ACCOUNT` | Non-digit residue after removing spaces/hyphens, or length out of range | C-BNK-03, C-NRM-02 | BLOCK_SUBMISSION |
| `INVALID_EMAIL` | Fails BC's rule (spaces, `@` count) or ours | C-TYP-03 | MANUAL_REVIEW |
| `INVALID_PHONE` | Contains letters, or not a valid Indian number | C-TYP-02 | MANUAL_REVIEW |
| `INVALID_STATE` | Not a recognised state, or can't map to a BC `State` code | C-MD-02 | MANUAL_REVIEW |
| `INVALID_COUNTRY` | Can't map to a BC `Country/Region` code | C-MD-01 | MANUAL_REVIEW |

### 2.3 Business-rule errors: class `BUSINESS_RULE` (stages 5, 7, 9)

| Code | Meaning | Constraint | Default automation |
|---|---|---|---|
| `CROSS_DOCUMENT_MISMATCH` | Same field differs between documents (exact rule for identifiers) | C-XD-01/03/04/08 | MANUAL_REVIEW (BLOCK for identifiers) |
| `GSTIN_PAN_MISMATCH` | GSTIN[3..12] ≠ PAN | C-GST-04 | BLOCK_SUBMISSION |
| `GSTIN_STATE_MISMATCH` | GSTIN state code ≠ address/PIN state | C-XD-07 | MANUAL_REVIEW |
| `PIN_STATE_MISMATCH` | PIN directory state ≠ extracted state (exists today) | C-ADR-07 | MANUAL_REVIEW |
| `NAME_PAN_INITIAL_MISMATCH` | PAN 5th char ≠ first letter of the name | C-PAN-03 | MANUAL_REVIEW (warning) |
| `GSTIN_NOT_ACTIVE` | Registry says not Active (optional check) | C-GST-16 | MANUAL_REVIEW |
| `INVALID_GST_VENDOR_TYPE` | Type inconsistent with GSTIN/ARN/State Code | C-GST-08/09/10 | BLOCK_SUBMISSION |
| `MISSING_TDS_CONFIGURATION` | TDS applicable but no Assessee Code or Section decided | C-TDS-01/02 | MANUAL_REVIEW |
| `ADDRESS_REBALANCED` | Boundary moved to fit BC widths (content unchanged) | C-ADR-03 | MANUAL_REVIEW (warning, one click) |
| `ADDRESS_OVERFLOW` | No boundary satisfies 100/50 | C-ADR-03 | BLOCK_SUBMISSION |
| `DERIVED_VALUE_UNCONFIRMED` | Inferred value (website from e-mail, city from PIN) not yet confirmed | C-NRM-09 | MANUAL_REVIEW |
| `DUPLICATE_VENDOR` | Normalized name matches an existing BC vendor | C-DUP-06 | MANUAL_REVIEW |
| `DUPLICATE_GSTIN` | GSTIN already on a BC vendor (or portal record) | C-DUP-03/08 | BLOCK_SUBMISSION |
| `DUPLICATE_PAN` | PAN already on a BC vendor | C-DUP-04 | MANUAL_REVIEW |
| `DUPLICATE_BANK_ACCOUNT` | Account number already on another vendor | C-DUP-05 | MANUAL_REVIEW |

### 2.4 Configuration errors: class `CONFIGURATION` (stages 8–9)

| Code | Meaning | Constraint | Default automation |
|---|---|---|---|
| `MASTER_DATA_NOT_FOUND` | A code (posting group, state, country, assessee…) doesn't exist in BC | C-MD-* | MANUAL_REVIEW (admin) |
| `CONFIGURATION_MISSING` | No template/config supplies a value BC needs to post (e.g., Vendor Posting Group) | C-REQ-03, C-CFG-05 | MANUAL_REVIEW |
| `NO_SERIES_MISSING` | Vendor Nos. not set, exhausted, or wrong series | C-REQ-01, C-CFG-01/02 | BLOCK_SUBMISSION |
| `TEMPLATE_AMBIGUOUS` | More than one template rule matches | §5 | MANUAL_REVIEW |
| `TENANT_FIELD_UNKNOWN` | A mapped OData property or length is not confirmed in `$metadata` | C-API-03, C-LEN-17 | BLOCK_SUBMISSION |

### 2.5 Business Central errors: class `BC` (stage 12; mapped from BC responses)

| Code | Typical BC response | Constraint |
|---|---|---|
| `BC_STRING_TOO_LONG` | `Application_StringExceededLength` (observed per repo comment `[S36a]`) | C-LEN-* (should have been caught earlier) |
| `BC_TABLE_RELATION` | "…contains a value (…) that cannot be found in the related table (…)" | C-MD-* |
| `BC_TESTFIELD` | "… must have a value in …" / "must be equal to …" | C-GST-01/12, C-REQ-01 |
| `BC_GST_VALIDATION` | e.g., "PAN No. must be entered.", "The GST Registration No. for the state %1 should start with %2.", "From position 3 to 12 in GST Registration No. should be same as it is in PAN No." `[S12][S13]` | C-GST-* |
| `BC_CALLBACK_NOT_ALLOWED` | "…attempted to issue a client callback to show a confirmation dialog box." `[S27]` | C-API-06 |
| `BC_PERMISSION` | HTTP 401/403 | C-API-07 |
| `BC_VALIDATION_FAILED` | Any other 400 | – |

### 2.6 Integration errors: class `INTEGRATION` (stages 12–14)

| Code | Meaning | Handling |
|---|---|---|
| `API_VALIDATION_FAILED` | Umbrella for a rejected write whose BC message isn't mapped | Store the BC message verbatim, then review |
| `INT_UNREACHABLE` | Network/VPN failure before a request was accepted | Retry is safe |
| `INT_TIMEOUT_UNKNOWN_OUTCOME` | Timeout after sending a POST | **Don't retry blindly.** Look up by GSTIN first. (C-DUP-07) |
| `INT_PARTIAL_CREATE` | Vendor created but a later step (tax fields, bank) failed | Resume from the failed step with the recorded vendor No. |
| `INT_VERIFY_MISMATCH` | Read-back differs from what was sent (Post Code overwrite, GST Vendor Type side effect…) | Review, and show the diff |
| `MANUAL_REVIEW_REQUIRED` | Record-level roll-up: at least one open review item | – |

---

## 3. Automation vs human review

Every finding gets exactly one of these classes:

| Class | Meaning |
|---|---|
| **AUTO_PASS** | Nothing to do |
| **AUTO_FIX** | Deterministic, lossless change (whitespace, case, address boundary shift). Recorded in provenance. The address shift also raises a warning. |
| **AUTO_LOOKUP** | Value resolved from an existing BC record or a company config file (never invented) |
| **MANUAL_REVIEW** | A human must confirm or edit before submission |
| **BLOCK_SUBMISSION** | Cannot be submitted until the underlying data changes |

Decision table (including the brief's examples):

| Situation | Class |
|---|---|
| GSTIN fails format or checksum | **BLOCK_SUBMISSION** |
| GSTIN[3..12] ≠ PAN | **BLOCK_SUBMISSION** |
| GSTIN differs by any character between GST certificate and Udyam | **BLOCK_SUBMISSION** (until a human picks the correct one) |
| Vendor Posting Group missing from documents but provided by a configured template/config rule | **AUTO_LOOKUP** |
| Vendor Posting Group missing from both template and configuration | **MANUAL_REVIEW** (admin) |
| Address 2 > 50 but a boundary shift fits both lines | **AUTO_FIX** + warning `ADDRESS_REBALANCED` (one-click confirm) |
| Address exceeds BC limits and no boundary fits | **BLOCK_SUBMISSION** (`ADDRESS_OVERFLOW`). **Never truncate.** |
| State "Dadra and Nagar Haveli and Daman and Diu" (40) > County 30 | **BLOCK_SUBMISSION** until the company's abbreviation rule exists, then AUTO_FIX via a config map |
| Country "India" in documents | **AUTO_LOOKUP** → tenant code (`IN`/`INDIA`) |
| State Code for GST | **AUTO_LOOKUP** from GSTIN digits → `State` record, else MANUAL_REVIEW |
| PIN exists in BC Post Code table with a different City spelling | AUTO_PASS at submit; **MANUAL_REVIEW** at post-create verification if BC overwrote the city |
| IFSC repaired by `fix_ifsc_confusions` | **MANUAL_REVIEW**, or AUTO_PASS only if the repaired IFSC exists in the RBI master |
| Account number contains a letter after removing spaces/hyphens | **BLOCK_SUBMISSION** |
| Website derived from e-mail domain | **MANUAL_REVIEW** (omit from the payload unless confirmed) |
| GST Vendor Type not extracted | **MANUAL_REVIEW**, or AUTO_FIX from the mapped registration type once §C-GST-15 is proven |
| TDS applicable, section unknown | **MANUAL_REVIEW** (vendor is created; TDS sections are a later step) |
| Existing BC vendor with the same GSTIN | **BLOCK_SUBMISSION** |
| Existing BC vendor with the same PAN, different GSTIN | **MANUAL_REVIEW** |
| Existing BC vendor with the same bank account | **MANUAL_REVIEW** (fraud check) |
| Custom tenant field of unknown length/meaning | **BLOCK_SUBMISSION** for that field until Q2/Q3 are answered |

A record may be pushed only if it has **zero BLOCK findings and zero open MANUAL_REVIEW findings**. Every MANUAL_REVIEW resolution is stored: who, when, old value, new value.

---

## 4. The BC target profile (single source of truth for BC constraints)

**Problem today.**
- `master` hard-codes widths in `bc_mapper._BC_FIELD_MAX_LEN`. Three are wrong for BC 22 (Name, Address and Contact are 100, not 50) and two are guesses (the custom PAN_Number/GST_Number).
- `ocr-testing` has no widths at all.

**Proposal.** One data file per BC target, matching the repo's config-driven style:

`backend/config/bc_targets/bc22_in_vendorcard.yaml`:

```yaml
target: bc22_in_vendorcard
bc_version: "22"                 # server path /BC220/
endpoint_page: VendorCard        # OData page published as a web service
verified_against_metadata: false # flipped by the $metadata check (below)

vendor_fields:
  Name:            {portal: vendor_name, type: text, max_len: 100, scope: STD}
  Address:         {portal: address_1,   type: text, max_len: 100, scope: STD}
  Address_2:       {portal: address_2,   type: text, max_len: 50,  scope: STD}
  City:            {portal: city,        type: text, max_len: 30,  scope: STD}
  County:          {portal: state,       type: text, max_len: 30,  scope: STD}
  Post_Code:       {portal: pin_code,    type: code, max_len: 20,  scope: STD}
  Country_Region_Code: {portal: country, type: code, max_len: 10,  lookup: country_region, scope: STD}
  Phone_No:        {portal: telephone_1, type: text, max_len: 30,  rule: no_letters}
  MobilePhoneNo:   {portal: telephone_2, type: text, max_len: 30,  rule: no_letters}
  E_Mail:          {portal: email,       type: text, max_len: 80,  rule: bc_email}
  Home_Page:       {portal: website,     type: text, max_len: 80,  requires_confirmation_if_derived: true}
  PAN_Number:      {portal: pan,    type: unknown, max_len: null, scope: EXT, verified: false}   # Q2
  GST_Number:      {portal: gst_no, type: unknown, max_len: null, scope: EXT, verified: false}   # Q2

india_tax_fields:              # written in a separate PATCH, in this order (§6)
  - {odata: State_Code,          portal: state_code_bc, type: code, max_len: 10, lookup: state_by_gst_code}
  - {odata: P_A_N_No,            portal: pan,           type: code, max_len: 20}
  - {odata: GST_Registration_No, portal: gst_no,        type: code, max_len: 20, exact_len: 15}
  - {odata: GST_vendor_Type,     portal: gst_vendor_type, type: enum,
     values: [Registered, Composite, Unregistered, Import, Exempted, SEZ]}   # never " "
  - {odata: Assessee_Code,       portal: assessee_code, type: code, max_len: 10, lookup: assessee_code}

posting_defaults_from: vendor_class_rules   # §5

bank_account:
  page: VendorBankAccountCard     # must be published (Q12)
  code_rule: "PRIMARY"            # company convention
  fields:
    Name:             {portal: bank_name,      max_len: 100}
    Bank_Account_No:  {portal: account_number, max_len: 30}
    Bank_Branch_No:   {portal: ifsc,           max_len: 20}   # Q11: or a custom IFSC field
    Address:          {portal: branch_address, max_len: 100}
```

**Metadata check, at startup and in CI against the sandbox:**
1. Fetch `…/ODataV4/$metadata`.
2. For every mapped property:
   - confirm the property exists on the entity type;
   - read its `MaxLength` facet (BC's OData metadata normally carries `MaxLength` on string properties; *confirm on BC220*);
   - compare it with `max_len`.
3. Any mismatch or missing property makes the payload endpoint return `TENANT_FIELD_UNKNOWN`. The check also covers C-API-03: control names can change between BC versions `[S26]`.

---

## 5. Defaults, templates and "vendor class" rules

BC facts that shape this:
- The VendorCard OData path applies **no** vendor template (C-API-02).
- BC 22 IN vendor templates can't hold GST/TDS fields (C-CFG-03).
- Templates skip OnValidate (C-CFG-04).

So the pipeline resolves defaults itself and sends them explicitly.

`backend/config/bc_targets/vendor_class_rules.yaml` (company-owned, reviewed by finance):

```yaml
# Evaluated top to bottom; first match wins; more than one match is TEMPLATE_AMBIGUOUS.
classes:
  - name: domestic_registered
    when: {gstin_present: true, country: India}
    bc_template_code: VEND-DOM     # informational: the BC template this mirrors
    set:
      Vendor_Posting_Group: "<confirm with finance>"   # Q8 -- do NOT ship a guess
      Gen_Bus_Posting_Group: "<confirm>"
      Payment_Terms_Code: "<confirm>"
      GST_vendor_Type: Registered    # only until C-GST-15 derives it from the certificate
  - name: domestic_unregistered
    when: {gstin_present: false, country: India}
    set: {GST_vendor_Type: Unregistered}
    require_user: [Aggregate_Turnover]
```

Rules for the rule file:
- A value in `set:` must exist in BC; the stage-8 lookup verifies it.
- A placeholder like `<confirm…>` is a `CONFIGURATION_MISSING` block, never sent.
- If the company prefers BC-side templates, the rule can name `bc_template_code`. The push then reads that template (`Vendor Templ.` via a published page) and copies its non-empty values into the payload, so BC templates stay the single place finance edits.

---

## 6. Submission plan (dependency-ordered, multi-step, idempotent)

This design follows from:
- **C-GST-01/02/12**: State Code, then P.A.N. No., then GST Registration No., then GST Vendor Type.
- **C-BNK-01/08**: the bank account comes after the vendor, and Preferred Bank Account after the bank account.
- **C-API-05**: validation order within a request is undocumented.
- **C-DUP-07**: an unknown outcome must not cause a duplicate.

| Step | Call | Body | Failure handling |
|---|---|---|---|
| 0. Preflight (read-only) | `GET VendorCard?$filter=GST_Registration_No eq '<gstin>'` (or the custom `GST_Number`), same for PAN; `GET` Vendor Bank Accounts filtered by account no.; `GET` the lookup lists (countries, states, posting groups) | – | Any match → DUPLICATE_*. Lookup miss → MASTER_DATA_NOT_FOUND. |
| 1. Create vendor core | `POST VendorCard` | `No: ""`, Name, Address, Address_2, **Country_Region_Code first**, Post_Code, City, County, Phone_No, E_Mail, posting groups and other codes from §5 | Success → store the returned `No` immediately (state `CREATED_CORE`). Timeout → INT_TIMEOUT_UNKNOWN_OUTCOME, then re-run step 0 by GSTIN before any retry. |
| 2a. India: State | `PATCH VendorCard('<No>')` with `If-Match` | `{State_Code}` | BC_* → INT_PARTIAL_CREATE |
| 2b. India: PAN | `PATCH` | `{P_A_N_No}` (never `P_A_N_Status` when a PAN exists) | same |
| 2c. India: GSTIN | `PATCH` | `{GST_Registration_No}` | same (BC runs its GST checks here) |
| 2d. India: type & TDS | `PATCH` | `{GST_vendor_Type}` (only if not Registered, since BC sets Registered itself), `{Assessee_Code}` | same |
| 3. Bank account | `POST` Vendor Bank Account page | `{Vendor_No, Code, Name, Bank_Account_No, <IFSC field>, …}` | same |
| 4. Preferred bank | `PATCH VendorCard('<No>')` | `{Preferred_Bank_Account_Code: Code}` | same |
| 5. TDS sections (optional, human-decided) | `POST` Allowed Sections page | `{Vendor_No, TDS_Section, Default_Section}` | Skipped unless a reviewer chose a section |
| 6. Read-back | `GET VendorCard('<No>')` and the bank account | – | Field-by-field diff vs intended → INT_VERIFY_MISMATCH (§13 of the pipeline doc) |

Steps 2a–2d collapse into one PATCH only after a sandbox test proves the server validates them in the order needed (Q13). Until then they stay separate. The push record keeps a per-step status, so a failed run resumes from the failed step using the stored vendor No. Nothing is created twice.

---

## 7. Address fit: the minimal change to the existing segmenter

**Research result.**
- BC attaches **no** meaning to Address vs Address 2 (C-ADR-01), so the team's premise/locality convention is compatible with BC and should stay.
- BC 22 does constrain widths: **Address ≤ 100, Address 2 ≤ 50** (C-LEN-03/04).
- The redesigned segmenter on `ocr-testing@a0e0fc8` puts the (usually short) premise run in Address 1 and **everything else** in Address 2. When no premise fragment leads, it leaves Address 1 empty and puts the whole leftover in Address 2, unless the first fragment is a road, which then becomes Address 1 alone (C-ADR-10).
- Measured: the canonical `bc_floor_block_park_localities` case yields Address 2 = **69 chars at confidence `high`** (M1). 5 of 136 expected Address 2 values in the eval corpora exceed 50, while Address 1 never exceeds 43 (M2).

So a **length-aware post-pass** is required. The segmentation logic itself does not need to be redesigned.

**Algorithm: order-preserving boundary shift.** It runs after `segment_leftover()`, on the same fragment list, before the BC payload.

```
input : fragments f[0..n-1] in source order (the segmenter's own fragments)
        b = segmenter's boundary (A1 = f[0:b], A2 = f[b:n])
        MAX1 = 100, MAX2 = 50 (from the BC target profile), SEP = ", "
J(xs) = SEP.join(xs)

if len(J(f[0:b])) <= MAX1 and len(J(f[b:n])) <= MAX2:     -> keep (no finding)
if len(J(f[b:n])) > MAX2:
    for nb in b+1 .. n:                                    # move boundary right only
        if len(J(f[0:nb])) > MAX1: break
        if len(J(f[nb:n])) <= MAX2: -> use nb, finding ADDRESS_REBALANCED
if len(J(f[0:b])) > MAX1:
    for nb in b-1 .. 0:                                    # move boundary left only
        if len(J(f[nb:n])) > MAX2: break
        if len(J(f[0:nb])) <= MAX1: -> use nb, finding ADDRESS_REBALANCED
otherwise -> finding ADDRESS_OVERFLOW (BLOCK), values unchanged
```

Invariants, all testable:
- `J(A1') + SEP + J(A2') == J(A1) + SEP + J(A2)` when both are non-empty: lossless, with the same reconstruction check the segmenter already tests.
- No fragment is reordered, split, dropped or edited.
- The result is the **smallest** move from the semantic boundary, so the premise-first convention survives wherever it fits.
- Deterministic: a pure function of the fragments and limits.

Worked examples (computed with the rule above):

| Case | Segmenter output (A1 / A2 lengths) | After fit | Finding |
|---|---|---|---|
| `bc_floor_block_park_localities` | `3RD FLOOR, PART A BLOCK B` (25) / `SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY CHANDIBAGAN, ANDUL, Natibpur` (69) | `3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK` (58) / `MOHIARY CHANDIBAGAN, ANDUL, Natibpur` (36) | ADDRESS_REBALANCED |
| `ho24_five_locality_run…` (live segmenter output) | `SEZ UNIT 4, BRIGADE TECH GARDENS` (32) / `KADUBEESANAHALLI, DODDANEKKUNDI, MARATHAHALLI, BELLANDUR, VARTHUR` (65) | `SEZ UNIT 4, BRIGADE TECH GARDENS, KADUBEESANAHALLI` (50) / `DODDANEKKUNDI, MARATHAHALLI, BELLANDUR, VARTHUR` (47) | ADDRESS_REBALANCED |
| No premise fragment (A1 empty) | `` (0) / `SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY CHANDIBAGAN, ANDUL, Natibpur, NEAR RAILWAY STATION` (89; live segmenter output, confidence `low`) | `SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY CHANDIBAGAN` (52) / `ANDUL, Natibpur, NEAR RAILWAY STATION` (37) | ADDRESS_REBALANCED |
| Screenshot vendor (Peenya) | `BUILDING D` (10) / `4TH PHASE MAIN ROAD, PEENYA INDUSTRIAL AREA` (43) | unchanged | – |

Where it lives: a new pure function, e.g. `extract/bc_address_fit.py::fit_to_bc(fragments, boundary, limits)`, called from the BC payload builder (or the resolver when a BC target is configured). It doesn't touch `_split_by_role`.

Alternatives considered and rejected:
- **Truncation.** Forbidden by the data-integrity rule, and loses data.
- **Joining overflow into Address 2** (the `master` approach). Makes overflow worse.
- **Using Name 2 or Contact for address overflow.** Semantically wrong, and it prints on documents.
- **Abbreviation dictionaries** ("INDUSTRIAL" → "INDL"). They change content. At most a *company-approved* optional pass, flagged for review.

---

## 8. Normalization policy

| Category | Operations | Fields | Rule |
|---|---|---|---|
| **SAFE** (AUTO_FIX, logged) | Trim; collapse internal whitespace; replace newline/tab with `", "` in addresses; uppercase identifiers; remove spaces inside identifiers (`29 AADCP 7742H1ZS` → `29AADCP7742H1ZS`); remove `+91`/`91` prefix from a 12-digit mobile; lowercase e-mail; titlecase city/state for display; map a state alias to its canonical name via the existing table | All / as listed | Keep `raw` alongside |
| **CANDIDATE REPAIR** (MANUAL_REVIEW unless proven) | OCR glyph swaps in fixed-shape identifiers (`fix_ifsc_confusions`); re-spacing glued names (`split_corporate_suffix`, `expand_known_phrase`); de-gluing address fragments | IFSC, vendor name, company type, address | Record the original and the rule that fired. Auto-accept only with independent confirmation (e.g., the IFSC exists in the RBI master, or the name matches another document exactly after repair). |
| **NEVER MODIFY** (validate only) | Deleting characters, reordering, truncating, guessing a missing character, changing digits | GSTIN, PAN, account number, IFSC (beyond the candidate rule), Udyam no., PIN, bank name when read from a document | A failure is a finding, never a rewrite. **`digits_only` on `account_number` must be replaced by "remove spaces/hyphens, then require `^[0-9]{9,18}$`"** (C-NRM-02). |
| **DERIVED** (flagged) | Value computed from another field (website from e-mail, PAN from GSTIN, city from PIN district, country from GSTIN, BC State Code from GSTIN digits) | as listed | Provenance `derived_from_<field>`. Needs confirmation where the result isn't a strict function of a validated value (website, city). |

---

## 9. OCR/extraction risk profile per field

Confidence thresholds: the only one in the repo today is `min_accept: 0.60` (field_dictionary defaults). Anything else below is labelled **proposed policy**.

| Field | OCR risk | Regex / structural validation | Cross-document | Confidence threshold | Manual review when | BC validates? |
|---|---|---|---|---|---|---|
| GSTIN | High on scans; low on REG-06 PDFs with a text layer | Regex (exists) + **checksum (new)** + state-code allow-list | Exact vs Udyam/others; exact GSTIN[3..12] vs PAN | 0.60 (existing). *Proposed: identifiers need checksum pass, not a score.* | Any failure | Yes (length, prefix, PAN, char classes; **not checksum**), only if the India apps are installed |
| PAN | High (`0/O`, `1/I`, `5/S`) | Regex + holder type (new) | Exact vs GSTIN slice, PAN card, Udyam | same | Any failure | No format check; only the GSTIN match |
| IFSC | High on cheques | Regex; RBI master lookup (proposed) | Exact vs Udyam bank block (if present) | same | Repaired, or not in the RBI master | No |
| Account number | **Highest**: MICR band noise, `O/0`, dropped digits | Raw-value regex (no digit stripping) | Exact vs Udyam bank block | *Proposed: always human-confirmed on first push* (fraud-sensitive) | Always, until a second source confirms it | Length only (30) |
| PIN | Medium | `[1-9][0-9]{5}` + PIN directory | PIN state vs address state vs GSTIN state | same | Mismatch | No (BC may overwrite City/County from its Post Code table) |
| Vendor name | Medium (glued words, caption leaks) | Non-empty; caption-leak filter (exists) | Fuzzy vs Udyam/registry legal name | same | Below the similarity threshold, or a repair fired | No |
| Address | Medium (line wraps, missing commas) | Segmenter confidence; BC fit (§7) | Warn only | *Proposed: `low` segmenter confidence → review* | Rebalanced, overflow, low confidence | Length only |
| Udyam no. | Low–medium | Regex (exists) | Exact | same | Failure | No |
| E-mail / phone | Low | Regex + BC rules | – | same | Failure | Yes (format rules) |

---

## 10. Cross-document authority and comparison

| Field | Authoritative source | Also seen on | Comparison | Legitimately different? | On disagreement |
|---|---|---|---|---|---|
| GSTIN | GST certificate | Udyam, invoices | **Exact** | No | BLOCK until a human chooses |
| PAN | GSTIN[3..12] / PAN card | GST cert, Udyam | **Exact** | No | BLOCK |
| Legal name | GST "Legal Name" | Udyam "Name of Enterprise", registry | Fuzzy after suffix normalization (existing 0.85) | Minor punctuation only | Review |
| Trade name | GST "Trade Name" | Cheque holder line | Not compared with legal name | Yes | – |
| Principal address | GST certificate | Udyam (may list the plant/unit) | Informational | Yes (unit vs head office) | Warn |
| State | GSTIN digits | Address state, PIN directory | Exact after canonicalization | No | Review |
| Bank account / IFSC | Cancelled cheque | Udyam bank block | **Exact** | Yes (different account), but must be a human decision | Review |
| Account holder name | Cheque | – | Fuzzy vs legal/trade name | Proprietor's own name for proprietorships | Review |
| Udyam no. | Udyam certificate | – | Single source | – | – |

Implementation note: `validator.compare_across_documents` should use exact equality when the field's `value_type` is `alphanumeric` or `numeric` (GSTIN, PAN, Udyam, account number, IFSC), and fuzzy only for `text`. With the current fuzzy rule, GSTINs 2 characters apart score 86.7 and pass as "consistent" (M3).

---

## 11. New validators to add (YAML, in the repo's style)

```yaml
# validation_rules.yaml (additions -- sketch)
gstin_checksum:
  type: derived            # new derived rule implemented once in validator.py
  rule: gstin_check_char   # mod-36 check character, see §11.1
  source: gst_number
  severity: error
  message: GSTIN check character (15th) does not match -- likely an OCR misread

pan_holder_type:
  type: regex
  pattern: '[A-Z]{3}[ABCFGHJLPT][A-Z][0-9]{4}[A-Z]'
  severity: error
  message: PAN 4th character is not a valid holder type (A/B/C/F/G/H/J/L/P/T)

account_number_raw:
  type: regex              # run on the value BEFORE digit stripping
  pattern: '[0-9][0-9\s\-]{7,22}[0-9]'
  severity: error
  message: Account number contains non-digit characters (possible OCR misread)

bc_email:
  type: derived
  rule: bc_email_rules     # no spaces; exactly one '@' per ';'-separated address
  source: email
  severity: error
  message: Business Central will reject this e-mail address

phone_no_letters:
  type: regex
  pattern: '[^A-Za-z]*'
  severity: error
  message: Business Central rejects phone numbers containing letters

gstin_state_code:          # replace the 01-38 range
  # allow-list: 01-24, 26, 27, 29-38, 97, 99; warn on 25 and 28 (legacy)
```

BC length checks are **not** added as per-field validators. They come from the BC target profile (§4) and run in stage 11, so one file drives both the check and the payload.

### 11.1 GSTIN check character (reference implementation, for calibration)

```python
_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

def gstin_check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = _GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36]
```

Calibration done during this research:
- **Passes:** the verified ground-truth GSTIN `19AABCM7980K1ZU` (M.B. Control & Systems).
- **Fails:** the GSTIN on the live BC vendor card, `29AADCP7742H1ZS` (in the custom "GST Number" field). It is either test data or an invalid GSTIN, and nothing stopped it being saved. The primary evidence that BC doesn't check the check character is its source `[S13]`.
- **Fixtures:** only **4 of the 56** distinct GSTIN-shaped strings in `backend/` pass. Most test fixtures are synthetic, so enabling this validator as `error` requires updating fixtures first (test plan §3).

The algorithm source is a secondary one `[S35]`. Enforce it as BLOCK only after it has passed on every real, registry-verified GSTIN you hold.

---

## 12. Record lifecycle states (portal side)

```
EXTRACTED ──> VALIDATED ──(any BLOCK/REVIEW)──> NEEDS_REVIEW ──(all resolved)──┐
     │                                                                       │
     └────────────(no findings)────────────────────────────────────────────> READY_FOR_BC
READY_FOR_BC ──> PUSHING ──> CREATED_CORE ──> TAX_FIELDS_SET ──> BANK_SET ──> CREATED
                    │              │                 │               │
                    └──────────────┴─────────────────┴───────────────┴──> PARTIAL (resume)
CREATED ──(read-back ok)──> VERIFIED
CREATED ──(read-back diff)──> VERIFY_MISMATCH (review)
```

This replaces today's `bc_status ∈ {not_pushed, pushed, failed}`. Today "pushed" is set from a BC No. an operator types in, with no read-back (C-WF-05).
