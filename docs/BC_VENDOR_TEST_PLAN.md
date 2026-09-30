# BC Vendor Test Plan

Companion to [BC_VENDOR_CONSTRAINTS_RESEARCH.md](BC_VENDOR_CONSTRAINTS_RESEARCH.md). Every test names the constraint it protects ([BC_VENDOR_CONSTRAINT_REGISTRY.md](BC_VENDOR_CONSTRAINT_REGISTRY.md)) and the finding code it expects ([BC_VENDOR_VALIDATION_DESIGN.md §2](BC_VENDOR_VALIDATION_DESIGN.md#2-error-taxonomy)).

## 1. Test levels

| Level | Where | Runs | Needs BC? |
|---|---|---|---|
| **L1 Unit** | `backend/tests/` (pytest, existing style, no OCR) | Every commit | No |
| **L2 Config** | `backend/tests/test_config_loader.py` + new `test_bc_target_profile.py` | Every commit | No |
| **L3 Property** | Address fit invariants over the eval corpora + generated fragments | Every commit | No |
| **L4 Golden payload** | Intended BC record / submission plan for fixed inputs, compared to checked-in JSON | Every commit | No |
| **L5 BC contract** | Against a **BC sandbox/test company** (Q15) on the BC220 server, from a VPN host | On demand / nightly | Yes |
| **L6 End-to-end** | Real ground-truth document sets (`app/eval/ground_truth/`) through all 14 stages, stopping before L5 unless a sandbox exists | Weekly / before release | Optional |
| **L7 Security** | Log scanning, retention, masking | Every commit (static) + release | No |

## 2. Metrics to track (per release)

| Metric | Today | Target |
|---|---|---|
| Truncated values sent to BC | Possible (`master` `_fit_to_bc_width`) | **0** (hard) |
| Records pushed with open BLOCK/REVIEW findings | Possible | **0** (hard) |
| Eval addresses whose BC-fit status is FIT without shift / REBALANCED / OVERFLOW | Not measured (5 of 136 expected A2 > 50) | Report all three; OVERFLOW = 0 on the corpora |
| Identifier cross-doc comparisons done with fuzzy logic | GSTIN, PAN, Udyam | **0** |
| Real GSTINs passing checksum | 1 known real (`19AABCM7980K1ZU`) | 100% of registry-verified samples |
| BC read-back diffs after creation | Not measured | Every diff explained (Post Code overwrite, GST type side effect) |

## 3. Fixture work required first

- Only **4 of 56** distinct GSTIN-shaped strings in `backend/` pass the mod-36 check (validation design §11.1).
- Before enabling `gstin_checksum` at `severity: error`, either:
  - regenerate synthetic fixtures with valid check characters (write a `make_gstin(state, pan, entity='1')` test helper that computes char 15); or
  - mark tests that deliberately use invalid GSTINs.
- `backend/tests/test_business_central.py::test_long_joined_address_is_truncated_to_fit` (on `master`) asserts truncation. It must be rewritten to assert **blocking** (see T-GATE-02).

## 4. Test catalogue

### 4.1 Field length and data type (L1, L4)

| ID | Constraint | Given / When / Then |
|---|---|---|
| T-LEN-01 | C-LEN-01 | Name of 100 chars → no finding. Name of 101 → `FIELD_TOO_LONG` (limit 100). Name of 51–100 → **no** finding (regression for the wrong 50 in `master`). |
| T-LEN-02 | C-LEN-03/04 | Address 1 of 100 / Address 2 of 50 → OK. Address 2 of 51 → handled by the address-fit tests (§4.3). |
| T-LEN-03 | C-LEN-05/06 | City 31 → `FIELD_TOO_LONG`. State "Dadra and Nagar Haveli and Daman and Diu" (40) → `FIELD_TOO_LONG` on County, never truncated. |
| T-LEN-04 | C-LEN-09/10/11 | Contact 100 OK; phone 31 → error; e-mail 81 → error. |
| T-LEN-05 | C-LEN-12, C-LOC-03 | Home Page 81 chars with the BC 22 profile → error. Same value with a (future) BC 25+ profile (255) → OK. Proves limits come from the profile. |
| T-LEN-06 | C-LEN-13 | Registration Number 21 chars → error even though storage is 50. |
| T-LEN-07 | C-LEN-18 | Leading/trailing spaces don't count. `" 560058 "` passes the Post Code length. |
| T-TYP-01 | C-TYP-02 | Phone `98452-20916` OK; `98452 2O916` (letter O) → `INVALID_PHONE`. |
| T-TYP-02 | C-TYP-03 | `a@b.com;c@d.in` OK; `a @b.com` → `INVALID_EMAIL`; `a@@b.com` → `INVALID_EMAIL`. |
| T-TYP-03 | C-TYP-04, C-GST-11 | Payload never contains a blank enum. GST Vendor Type unset → key **absent**, not `" "`. |
| T-TYP-04 | C-TYP-06 | Account `0012345678901` stays a string in JSON and in Excel (leading zeros kept). |

### 4.2 Identifiers (L1)

| ID | Constraint | Given / When / Then |
|---|---|---|
| T-GST-01 | C-GST-06 | `19AABCM7980K1ZU` passes checksum. Change the 15th char → `INVALID_GSTIN (checksum)`. |
| T-GST-02 | C-GST-06 | For each char position 1–14 of a valid GSTIN, a single-char substitution fails the checksum (most OCR single-char errors are caught). |
| T-GST-03 | C-GST-19 | Prefixes `97`, `99` accepted. `25`, `28` → warning. `00`, `39`–`96` → error. |
| T-GST-04 | C-GST-04 | GSTIN[3..12] ≠ PAN → `GSTIN_PAN_MISMATCH` (exact; case-insensitive only after uppercase). |
| T-PAN-01 | C-PAN-02 | `AADXP7742H` (4th char `X`) → `INVALID_PAN`. `AADCP7742H` OK. |
| T-PAN-02 | C-PAN-03 | Name "PEENYA CONTROL SYSTEMS PVT LTD" with PAN 5th char `P` → no finding. With `Q` → `NAME_PAN_INITIAL_MISMATCH` (warning). |
| T-BNK-01 | C-NRM-02, C-BNK-03 | Raw `50100 23456 7891` → normalized `50100234567891`, OK. Raw `12O456789` → `INVALID_BANK_ACCOUNT` (**not** `12456789`). |
| T-BNK-02 | C-NRM-03 | Raw IFSC `1CIC0001234` → candidate `ICIC0001234` + provenance note + review. Not auto-accepted unless present in the IFSC master fixture. |
| T-BNK-03 | C-BNK-04 | `ICIC1001234` (5th char ≠ 0) → `INVALID_IFSC`. |

### 4.3 Address fit (L1, L3)

| ID | Constraint | Given / When / Then |
|---|---|---|
| T-ADR-01 | C-ADR-03 | Canonical `bc_floor_block_park_localities` → A1 = `3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK` (58), A2 = `MOHIARY CHANDIBAGAN, ANDUL, Natibpur` (36), finding `ADDRESS_BC_LENGTH_REBALANCE`. |
| T-ADR-02 | C-ADR-03 | `ho24_five_locality_run…` live output → A1 50 / A2 47, `ADDRESS_BC_LENGTH_REBALANCE`. |
| T-ADR-03 | C-ADR-10 | Empty A1 with 5 fragments → A1 gets the leading fragments until A2 ≤ 50. |
| T-ADR-04 | C-ADR-03 | A single fragment of 60 chars that falls in A2 → moved into A1 if A1 stays ≤ 100, else `ADDRESS_OVERFLOW`. |
| T-ADR-05 | C-ADR-03 | Total > 152 chars (100 + ", " + 50) → `ADDRESS_OVERFLOW`, values unchanged, **no truncation**. |
| T-ADR-06 | C-ADR-03 (property) | For every case in `address_*.yaml` and 10k generated fragment lists: (a) `J(A1')+", "+J(A2')` equals the original join; (b) fragment order unchanged; (c) if not OVERFLOW then lengths ≤ 100/50; (d) the boundary moved the minimum distance. |
| T-ADR-07 | C-ADR-04 | `address_3`/`address_4` non-empty (legacy records) → the payload builder never joins them into Address 2. It emits `ADDRESS_OVERFLOW` or a re-segmentation request instead. |
| T-ADR-08 | C-ADR-01 | Semantic regression: the existing `test_address_segmenter.py` suite still passes unchanged (the fit is a post-pass). |

### 4.4 Cross-document (L1)

| ID | Constraint | Given / When / Then |
|---|---|---|
| T-XD-01 | C-XD-01 | GST cert `19AABCM7980K1ZU`, Udyam `19AABCM7980K1ZV` → `CROSS_DOCUMENT_MISMATCH` (today: "consistent", ratio 93.3). |
| T-XD-02 | C-XD-01 | PAN `AABCM7980K` vs `AABCM798OK` → mismatch (today: ratio 90 → consistent). |
| T-XD-03 | C-XD-04 | "M B CONTROL & SYSTEMS PVT LTD" vs "M.B.CONTROL & SYSTEM PVT LTD" → consistent (names stay fuzzy). |
| T-XD-04 | C-XD-07 | GSTIN prefix 29 (Karnataka) + PIN 700019 (West Bengal) → `GSTIN_STATE_MISMATCH`. |
| T-XD-05 | C-XD-08 | Cheque account ≠ Udyam account → review with both values shown. |

### 4.5 Master data, defaults, duplicates (L1 with snapshot fixtures; L5 live)

| ID | Constraint | Given / When / Then |
|---|---|---|
| T-MD-01 | C-MD-01 | Snapshot has country code `IN` (name India) → "India" resolves to `IN`. Snapshot has only `INDIA` → resolves to `INDIA`. Neither → `INVALID_COUNTRY`. |
| T-MD-02 | C-MD-02, C-GST-03 | GSTIN `29…` + State snapshot row (`KA`, GST code `29`) → `State_Code = KA`. No row with `29` → `MASTER_DATA_NOT_FOUND`. |
| T-MD-03 | C-MD-06 | Domestic vendor → Currency key absent (never `INR`). |
| T-MD-04 | C-MD-09 | Rule file contains `<confirm with finance>` → `CONFIGURATION_MISSING`; nothing sent. |
| T-CFG-01 | C-CFG-05, §5 | Two class rules match → `TEMPLATE_AMBIGUOUS`. |
| T-DUP-01 | C-DUP-03 | Snapshot vendor with the same GSTIN → `DUPLICATE_GSTIN` (block). |
| T-DUP-02 | C-DUP-04 | Same PAN, different GSTIN → `DUPLICATE_PAN` (review, not block). |
| T-DUP-03 | C-DUP-05 | Same bank account on another vendor → `DUPLICATE_BANK_ACCOUNT`. |
| T-DUP-04 | C-DUP-07 | Simulated timeout after POST → executor runs the GSTIN lookup, finds the vendor, and resumes at step 2 (no second POST). |

### 4.6 Pre-submission gate and payload (L4)

| ID | Constraint | Given / When / Then |
|---|---|---|
| T-GATE-01 | C-NRM-08 | Any over-length value → payload endpoint returns 409/422 with findings. **No `_truncated_fields` concept exists anymore.** |
| T-GATE-02 | C-NRM-08 | Rewrite of `test_long_joined_address_is_truncated_to_fit`: the same input now yields `ADDRESS_BC_LENGTH_REBALANCE` or `ADDRESS_OVERFLOW`, never a cut value. |
| T-GATE-03 | §3 of the validation design | Record with an open `MANUAL_REVIEW` → gate refuses. After recorded resolution → gate passes. |
| T-GATE-04 | C-API-03 | Target profile `verified_against_metadata: false` for `PAN_Number` → gate refuses with `TENANT_FIELD_UNKNOWN`. |
| T-GATE-05 | C-NRM-09 | Derived website unconfirmed → absent from the payload. |
| T-PLAN-01 | C-GST-01/02/12 | Submission plan order is exactly: POST core → PATCH State_Code → PATCH P_A_N_No → PATCH GST_Registration_No → PATCH type/assessee → POST bank → PATCH preferred bank. |
| T-PLAN-02 | C-PAN-04 | Plan never contains `P_A_N_Status` when a PAN exists. |
| T-PLAN-03 | C-GST-13 | Registered vendor → no `Aggregate_Turnover` in the plan. |

### 4.7 BC contract tests (L5, sandbox company, VPN host)

Each test creates a uniquely named vendor in the **sandbox** and reads it back.

| ID | Purpose | Expected |
|---|---|---|
| T-BC-01 | Discover truth (Q1, Q2, Q4) | Save `$metadata` and one `VendorCard?$top=1` response as fixtures. The target profile check passes. |
| T-BC-02 | Lengths (C-LEN-01/03/04) | POST Name 100 / Address 100 / Address 2 50 → 201. Address 2 51 → 400 with the string-length error (record the exact code/message). |
| T-BC-03 | No. Series (C-REQ-01, C-CFG-02) | POST with `No: ""` → which prefix? Record it. |
| T-BC-04 | Templates (C-API-02) | Vendor created via OData has no template values (confirms the pipeline must send them). |
| T-BC-05 | Post Code overwrite (C-ADR-05) | PIN present in the sandbox Post Code table with City X; send City Y → read back X or Y. Record which (validation order evidence). |
| T-BC-06 | India ordering (C-GST-01/02/12, Q13) | (a) single PATCH with State, PAN and GSTIN together; (b) the separate-step plan. Record whether (a) works. Keep (b) as the default regardless. |
| T-BC-07 | GST rules (C-GST-03/04) | GSTIN with the wrong state prefix → `The GST Registration No. for the state … should start with …`. PAN mismatch → the position 3–12 error. |
| T-BC-08 | Checksum gap (C-GST-06) | A GSTIN with a wrong check char but correct shape → **accepted by BC** (proves the need for our check). |
| T-BC-09 | P.A.N. Status side effect (C-PAN-04) | PATCH `P_A_N_Status = PANAPPLIED` → P.A.N. No. becomes `PANAPPLIED`. |
| T-BC-10 | Bank account (C-BNK-01/05/08) | POST the bank account on the published page, then set Preferred Bank Account Code → 200. Confirm where IFSC lands. |
| T-BC-11 | Approval (C-WF-01) | If `VENDAPW` is enabled: vendor usage is restricted until approved. Record the behaviour. |
| T-BC-12 | Permissions (C-API-07) | Push account: insert/modify on Vendor, Vendor Bank Account, and the India fields. |
| T-BC-13 | Callback (C-API-06) | Sending `Contact` with Marketing Setup configured → observe whether a contact is created or a callback error occurs. |

### 4.8 Security (L7)

| ID | Constraint | Check |
|---|---|---|
| T-SEC-01 | C-SEC-02 | Run the full test suite with log capture. Assert no full account number, PAN or raw OCR text appears in any log line (regex scan). |
| T-SEC-02 | C-SEC-01 | Vendor list API/UI returns masked account numbers (last 4). |
| T-SEC-03 | C-SEC-03 | Purge job removes `uploads/<run_id>`, `document_set.json` and `extraction.json` after the retention window. `raw_extraction` is redacted. |
| T-SEC-04 | C-SEC-05 | Config validation fails in `ENV=production` if `BC_ODATA_BASE` starts with `http://`. |
| T-SEC-05 | C-SEC-07 | A non-authorized role can't fetch the payload or mark pushed. |
| T-SEC-06 | C-SEC-04 | With `GSTIN_API_ENABLED=false`, no outbound HTTP call is made (mock `requests`). |

### 4.9 End-to-end regression (L6)

- Run the `mb_control_systems` ground truth through stages 1–11. Assert the intended BC record equals a reviewed golden file, with zero BLOCK findings and the expected REVIEW findings (derived website, etc.).
- Add at least **5 more real vendors** (multi-state, proprietorship, unregistered, SEZ if available) as ground truth. Current accuracy evidence is one vendor, which is too thin for BC-facing automation.

## 5. Exit criteria before enabling automated submission

1. All L1–L4 tests are green. L5 has run once on the sandbox, and every open question it answers is recorded in research report §27.
2. `T-GATE-*` prove that no truncation and no push with open findings are possible.
3. Target profile `verified_against_metadata: true` for every mapped property.
4. Finance has signed off `vendor_class_rules.yaml` (posting groups, payment terms, series).
5. Security tests T-SEC-01…05 are green.
