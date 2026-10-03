# Address Segmentation Plan: Semantic Truth + Business Central Representation

**Status (2026-09-30):** implemented through step 14 on branch `ocr-testing`, behind two flags that are both **off** by default (`BC_ADDRESS_LAYER_ENABLED`, `BC_PAYLOAD_GATE_ENABLED`). With both off, behaviour is unchanged. Still open:
- **Enabling the flags.** Step 9's shadow run over 239 saved real runs gave 208 unchanged, 13 one-click rebalances and 15 BLOCKs (11 distinct long addresses no whole-fragment split can fit).
- **The `address_holdout_cases.yaml` migration** (step 8). It needs a decision, because that file is a frozen holdout.
- **Step 15**, the `master` merge.
- **Steps 16–17**, which are optional or depend on the tenant.
- **The frontend panel** has been built but not yet walked through in a browser.

The design text below is unchanged from the approved version, except where a later decision is noted.

**Citations used below:**
- RESEARCH / REGISTRY / DESIGN / MATRIX / PIPELINE / TESTPLAN = `docs/BC_VENDOR_*.md`
- ASR = `docs/ADDRESS_SEGMENTATION_RESEARCH.md`
- Code references are verified line numbers on this branch.

## Rule categories

Every rule in this plan carries one of these tags:

| Tag | Meaning | Maps from research label |
|---|---|---|
| **MICROSOFT_BC_CONSTRAINT** | Enforced by Business Central itself; documented in research source S02/S04/S28 | STD, and STD+CFG |
| **PROJECT_BUSINESS_RULE** | Our company's rule; BC does not require it | CUSTOM |
| **SEMANTIC_RULE** | What an address fragment means (Layer 1) | CUSTOM (C-ADR-01 "our rule") |
| **PRESENTATION_FALLBACK** | How we fill fields when the semantic result looks incomplete; not a meaning | CUSTOM |

**TENANT VERIFICATION REQUIRED** is added to any of the above when the value depends on our BC tenant and is not yet known. No value marked this way is presented as fact.

Automation classes come from DESIGN §3: `AUTO_PASS`, `AUTO_FIX`, `AUTO_LOOKUP`, `MANUAL_REVIEW`, `BLOCK_SUBMISSION`.

"MANUAL_REVIEW / BLOCK" in this plan means: `BLOCK_SUBMISSION`, and the fix is a human edit on the review screen. The edited values then go through the BC checks again.

---

## 0. Current behaviour and fact check

### 0.1 Current behaviour

| Step | Code | Behaviour today |
|---|---|---|
| Normalization | `normalizer.py:18,158` via `field_matcher.py:577–588` | Newlines are collapsed to spaces **before** address resolution. The row-join restores commas. Effect on real multi-line captions: **UNVERIFIED**. |
| Entry point | `semantic_engine.py:374` → `resolve_address_blob` | **Bails out at 365** when city, state and PIN were captioned separately. **No segmentation and no length check** runs on that path. |
| Geography | `address_resolver.py` `_drop_trailing_country` 170, `_strip_pin` 143, `_match_state` 182, `_pick_city` 255 | Geography is removed before segmentation. Country = the extracted token, else "India" (415–422). The only recognised country tokens are the India variants (59). |
| Semantics | `address_segmenter.py` `segment_leftover` 985, `_split_by_role` 950–978 | A1 = the initial contiguous run of A1-role fragments. If that run is empty and fragment 0 is a thoroughfare, fragment 0 becomes A1 (1063–1065). Otherwise A1 = "" and confidence is forced to `low` (1066–1068). |
| Backfill | `address_resolver.py:476` → `_fallback_populate_address_1` 481–509 | Moves 1 fragment when there are ≤2, else 2. **Not logged.** |
| Write-back | `semantic_engine.py:378, 402–425` | Empty resolver values are skipped (411), so stale A2/A3/A4 values survive. `r.country` is never written back. |
| Provenance | `FieldResult.notes` (`models.py:353`); `_flag` → `needs_review` (`semantic_engine.py:538–555`); stored in `Vendor.raw_extraction` (`model.py:100`, from `ar-portal/src/api.js:272`) | Reason codes exist only in the docs (DESIGN §2), not in code. |
| BC payload | `bc_mapper.py:41, 57, 60–74` | No length limits. Address 2+3+4 are joined into Address 2. `Country_Region_Code = "India"`. |

Your cases run through today's code:

| # | Input | Today's A1 | Today's A2 | Note |
|---|---|---|---|---|
| 1 | F-192 case | `F-192` | `Phase 8B, Industrial Area, Sector 74` | |
| 2 | Mauli Baidwan | `Mauli Baidwan, Circular Road` | `Sector 80` | Backfilled. Confidence is `low` purely because there is no premise. |
| 3 | Sector 67 | `Sector 67` | "" | |
| 11 | Flat 402 | `Flat 402, Tower B` | `Sunrise Apartments, Block C, Sector 10` | |
| 12 | Leading unknown | `Unknown Fragment, F-192` | `Phase 8B, Industrial Area, Sector 74` | F-192 gets there by the positional backfill, not by scanning forward. |
| – | Howrah baseline | 25 chars | **69 chars** | Confidence `high`. |

### 0.2 Fact check of claims in the brief

1. **"Address 2 limit wrong somewhere".** Address 2 = 50 is correct in every place. What is wrong is `master` setting Address, Name and Contact to 50; BC allows 100 (C-LEN-01/03/09).
2. **"The master fit is not order-preserving".** It is order-preserving, but lossy: the tail is lost, and `address_3/4` go first (RESEARCH §7.3).
3. **"Truncation is silent".** Partly true: it is reported as `truncated_fields`, but push is still allowed (C-NRM-08).
4. **"A1 can be empty".** Only at the semantic layer. The backfill fills it end to end. C-ADR-10 and the DESIGN L318 example (the no-premise case = 52/37 after backfill, with no rebalance) need correcting.
5. **"Country must be `IN`".** The docs only require a code. `IN` vs `INDIA` is Q4: **TENANT VERIFICATION REQUIRED**.
6. **"Fuzzy ≥ 85 is used on addresses".** Addresses are never compared across documents. Only `state` uses `fuzz.ratio` (`validator.py:185`).
7. **Doc inconsistencies:**
   - The class of the rebalance is MANUAL_REVIEW in DESIGN L71, but AUTO_FIX in DESIGN L135, RESEARCH L717, C-LEN-04, C-ADR-03 and C-ADR-10. Resolved: MANUAL_REVIEW, and renamed to `ADDRESS_BC_LENGTH_REBALANCE`.
   - Other stale doc text: M1 cites a nonexistent "§7.6"; ASR §28.1 still describes Address 3/4 packing; a test docstring says "61 cases" (there are 74); the comment at `field_dictionary.yaml:247–249` is stale; `address_holdout_cases.yaml` still uses 4 lines.

---

## 1. Updated architecture

There are two layers plus one presentation step, and they are never mixed:

- **Layer 1 answers:** "What does each fragment mean?"
- **Layer 2 answers:** "Can that be represented within BC's actual field constraints?"

**SEMANTIC ROLE ≠ FINAL BC FIELD.** Every fragment carries both:
- `semantic_role`: set once by Layer 1. It is **never** rewritten afterwards.
- `final_bc_field`: set by the last step that placed the fragment.

Example:
- `Phase 8B` has `semantic_role = ADDRESS_2`.
- If a BC-length rebalance moves it, `final_bc_field = ADDRESS_1` and `moved_by = ADDRESS_BC_LENGTH_REBALANCE`, while `semantic_role` stays `ADDRESS_2`.
- This record exists so that nobody later "fixes" the classifier to treat Phase as an Address 1 concept.

```
RAW ADDRESS
  │  LAYER 1 — SEMANTIC ADDRESS TRUTH (existing code, unchanged)
  ├─ 1 GEOGRAPHY EXTRACTION           city / state / country / PIN removed from line candidates
  ├─ 2 FRAGMENT CLASSIFICATION        tier per fragment
  ├─ 3 SEMANTIC ROLE ASSIGNMENT       tier → ADDRESS_1 | ADDRESS_2
  ├─ 4 CONTIGUOUS SEMANTIC SEGMENTATION   semantic_boundary = initial A1-role run (never reopens)
  │  PRESENTATION FALLBACK
  ├─ 5 A1 EMPTY?
  │     ├─ NO  → continue
  │     └─ YES → fragment 0 thoroughfare? → A1 = fragment 0            (rule leading_thoroughfare) → STOP
  │              otherwise                 → A1 = first 1–2 fragments  (rule first_1_2_fragments)
  │              AUTO_FIX, ADDRESS_1_BACKFILLED
  │  LAYER 2 — BUSINESS CENTRAL REPRESENTATION
  ├─ 6 BC CONSTRAINT VALIDATION       within limits? YES → AUTO_PASS (no rebalance, no review)
  ├─ 7 DETERMINISTIC REBALANCE        whole fragments, single boundary, one direction, once
  │        safe + lossless + order-preserving?
  │          ├─ YES → apply → ADDRESS_BC_LENGTH_REBALANCE → MANUAL_REVIEW (one click)
  │          └─ NO  → values unchanged → ADDRESS_OVERFLOW → MANUAL_REVIEW / BLOCK
  ├─ 8 FINAL VALIDATION               invariants S-01…S-08 + BC-01…BC-12; failure = BLOCK
  ├─ 9 MANUAL REVIEW DECISION         one-click confirm (hash-bound) or manual edit
  └─ 10 BC PUSH                       payload gate re-runs 6–8 on stored values (check-only);
                                      requires no BLOCK and no OPEN MANUAL_REVIEW (§7 closure matrix)
```

Mapping to the research pipeline (PIPELINE): steps 1–8 run in **PIPELINE stage 5** at extraction time. Steps 9–10 correspond to the review UI and to **stage 11** (the payload gate) followed by **stage 12** (push). The gate is check-only: it never rewrites stored values.

---

## 2. Exact pipeline stages and operation order

| # | Stage | Input → output | Runs | May change |
|---|---|---|---|---|
| 1 | Geography extraction | raw → geography values + line-candidate segments | once | geography only |
| 2 | Fragment classification | segments → `Fragment(text, index, tier, …)` | once | nothing in the layout |
| 3 | Semantic role assignment | tier → `semantic_role` | once | nothing in the layout |
| 4 | Semantic segmentation | roles → `semantic_boundary` | once | nothing (record created, immutable) |
| 5 | A1-empty fallback | `semantic_boundary == 0` and n ≥ 1 → `presentation_boundary` | **at most once**; exactly one variant | boundary only, moving right |
| 6 | BC validation | layout + profile → FIT / list of violated constraint IDs | once (plus once in the gate) | nothing |
| 7 | Rebalance | only if 6 ≠ FIT → final boundary | **at most once** | boundary only, one direction |
| 8 | Final validation | final layout → pass / `ADDRESS_INVARIANT_VIOLATION` | once (plus once in the gate) | nothing |
| 9 | Review decision | findings → class; confirmation | per finding | nothing (a human edit restarts at 6) |
| 10 | Push | gate result | once | nothing |

**Why this order:**
- **1 before everything.** Geography must be out of the candidate set before anything can move fragments. Steps 5 and 7 only ever index into the post-geography fragment list, so geography cannot be moved into A1 or A2 by construction.
- **2–4 before 5.** The fallback must know the semantic result. It must never feed back into it: steps 2–4 are not re-run.
- **5 before 6.** The BC check must judge the representation that would actually be pushed. If the BC check ran first on an empty A1, the length rule would decide how many fragments go into A1. That would bypass the 1–2-fragment business rule and produce a review code for what is an auto-fix case. Rejected.
- **6 before 7.** Rebalancing is only allowed when a constraint actually fails ("If everything fits → AUTO_PASS").
- **5 after 7 was rejected.** A backfill after the rebalance could break a limit that had just been satisfied, which would force a second check and a second rebalance: a loop.

**Loop and oscillation prevention (all are enforced, not just intended):**
- Each of steps 5 and 7 runs at most once per pipeline run. The orchestrator has no loop around them.
- Step 5 moves the boundary **right** only.
- Step 7 moves the boundary in **one direction** only and never back across a fragment that step 5 moved. So if step 5 fired, step 7 may only move right. If A1 is over its limit after a backfill, that is `ADDRESS_OVERFLOW`, never a left shift that would hand the backfilled fragment back.
- A1 never becomes empty after step 5, so step 5 never needs to re-run.
- Idempotence: running steps 5–8 on a final layout gives the same layout and adds no provenance entries.
- A human edit is a new input. It restarts at step 6 with fragments recovered from the edited text; it does not re-run steps 1–5.

---

## 3. Semantic rules retained (Layer 1, unchanged)

All of these are **SEMANTIC_RULE**.

**What goes to Address 1:**
- **Premise/unit identifiers → A1.** Tier `premises_unit`. This includes:
  - SCF, SCO and Booth (`segmentation_keywords.yaml:57–63`);
  - F-192-style designators (designator regex, `segmentation_keywords.yaml:172`);
  - "UNIT 7", "PLOT 45", "SHOP 3".
- **Internal structural identifiers → A1.** Tier `structural`, with head keywords `part, block, blk, wing, tower, twr, annexe, annex, bldg` (`:78`). "Block"/"Wing" are head-only, so they are always followed by their designator ("BLOCK B").
  - "Tower" as a **head** ("TOWER A") is structural → A1.
  - "Tower" as a **tail** of a name ("… TOWERS") is `building_name` (`:92`) → A2.

**What goes to Address 2:**
- **Phase/Ph → A2** (`_ADDRESS_2_STRUCTURAL_KEYWORDS`, `address_segmenter.py:914`).
- **Also → A2** (`_TIER_ROLE` 919–929): `building_name`, `estate_zone`, `thoroughfare`, `landmark`, `locality`, `village_po`, and `unknown`.

**Boundary and ordering rules:**
- **The boundary never reopens.** A1 = the initial contiguous A1-role run only.
  - `A1, A1, A2, A1, A2` → A1 = `A1, A1`, A2 = `A2, A1, A2`.
  - No later A1-like fragment is pulled backwards.
  - A leading `unknown` gives `semantic_boundary = 0`; there is no forward scan.
- **Also retained:**
  - Geography is extracted first and never appears in the address lines.
  - Address 3/4 are never populated.
  - No LLM fallback anywhere.
  - Fully deterministic.
  - Source order is preserved.
  - No fragment is lost or duplicated.
  - OCR de-glue (626–636) and comma-less boundary injection (758–828) stay as they are.
  - The classifier and the keyword file are unchanged.

---

## 4. A1-empty fallback (step 5): PRESENTATION_FALLBACK, AUTO_FIX

**Trigger:** `semantic_boundary == 0` and at least 1 non-geographic fragment exists.

**Exactly one variant fires:**

| Variant | Condition | Result | Where the code is today |
|---|---|---|---|
| `leading_thoroughfare` | fragment 0 has tier `thoroughfare` | presentation boundary = 1 → **STOP** | inside `_split_by_role` (975–977); the code stays there, but its provenance is logged as a fallback |
| `first_1_2_fragments` | otherwise | boundary = 1 if n ≤ 2, else 2 | `_fallback_populate_address_1` (481–509), re-expressed on fragments with the same output |

**Guarantees:**
- Only the first 1–2 fragments move.
- Order is preserved.
- Nothing is duplicated or lost.
- No semantic reclassification; segmentation is not re-run.
- City, State, Country and PIN are untouched.
- A3 and A4 stay empty.

**Examples:**

| Before (A1 / A2) | After (A1 / A2) |
|---|---|
| "" / `Sector 67` | `Sector 67` / "" |
| "" / `Ward 07, Sector 67` | `Ward 07` / `Sector 67` |
| "" / `Ward 07, Sector 67, Industrial Area` | `Ward 07, Sector 67` / `Industrial Area` |
| "" / `A, B, C, D` | `A, B` / `C, D` |
| "" / `MG Road, B, C, D` | `MG Road` / `B, C, D` (leading_thoroughfare, stops) |

**Geography safety.** Three layers of protection, each tested:
1. **Structural.** The fallback receives only the `fragments` list produced after the geography peel. It has no access to the geography values and no string-level operation on the original address.
2. **Guard.** Step 8's check S-06/BC-07 fails the record if any A1/A2 fragment equals (casefolded) an extracted city, state, country or PIN value, or one of their aliases (`cities.txt` alias section, state aliases).
   - Honest limit: a place name the resolver did not recognise is, by definition, an address fragment.
   - Exception for comma-less text: the peel matches whole comma segments, so a place name the resolver *does* know can stay glued to the address text (`… ZOO ROAD GUWAHATI ASSAM`). Nothing is peeled, moved or rewritten for it. Instead the record gets `GEOGRAPHY_UNRESOLVED` (§7, D5) and a human fixes City/State and the line. A strict, PIN-verified extraction of a trailing `CITY STATE PIN` suffix is designed but **deferred and not implemented** (§18).
   - A district that was not chosen as the city stays a fragment legitimately (e.g. `Tikamgarh` in eval case `two_districts_pin_disambiguates`). The guard therefore compares against the **extracted values**, not against every gazetteer name.
3. **No reopening.** Nothing in steps 5–8 calls the resolver's geography functions again.

**What gets logged:** `ADDRESS_1_BACKFILLED`, AUTO_FIX, **no review**.
- The segmenter's `low` confidence from `no_premise_identifier` is kept as a semantic note.
- It **does not create a review finding**.

---

## 5. BC constraint layer (step 6)

Only constraints already documented in the research are used. **Nothing new about Microsoft BC is asserted.**

| Constraint ID | What it checks | Value | Category | Source | Used in |
|---|---|---|---|---|---|
| `BC_ADDRESS_1_MAX_LENGTH` | len(Address) | 100 | MICROSOFT_BC_CONSTRAINT | C-LEN-03, S02 | step 6, gate |
| `BC_ADDRESS_2_MAX_LENGTH` | len(Address 2) | 50 | MICROSOFT_BC_CONSTRAINT | C-LEN-04, S02 | step 6, gate |
| `BC_NO_ADDRESS_3_4` | Address 3/4 have no BC field | empty | MICROSOFT_BC_CONSTRAINT | C-ADR-04 | step 8, gate |
| `BC_CITY_MAX_LENGTH` | len(City) | 30 | MICROSOFT_BC_CONSTRAINT | C-LEN-05 | gate |
| `BC_COUNTY_MAX_LENGTH` | len(County = state) | 30 | MICROSOFT_BC_CONSTRAINT | C-LEN-06 | gate |
| `BC_POST_CODE_MAX_LENGTH` | len(Post Code) | 20 (Code type) | MICROSOFT_BC_CONSTRAINT | C-LEN-07 | gate |
| `BC_COUNTRY_CODE_MAX_LENGTH` | len(Country/Region Code) | 10, must be a code | MICROSOFT_BC_CONSTRAINT | C-LEN-08 | gate |
| `BC_COUNTRY_CODE_MAP` | India → code | `IN` or `INDIA` | MICROSOFT_BC_CONSTRAINT + TENANT VERIFICATION REQUIRED (Q4) | C-MD-01 | payload |
| `BC_CODE_UPPERCASE` | BC uppercases and trims Code fields | – | MICROSOFT_BC_CONSTRAINT | C-TYP-01, S28 | payload (we normalise first) |
| Post Code overwrite | an existing PIN in BC overwrites City/County/Country | – | MICROSOFT_BC_CONSTRAINT + TENANT (Q6) | C-MD-03, C-ADR-05 | P4 read-back |
| Country change clears fields | never change Country after insert | – | MICROSOFT_BC_CONSTRAINT | C-ADR-06 | payload order |
| A1/A2 have no BC meaning | – | – | MICROSOFT_BC_CONSTRAINT (fact) | C-ADR-01/02 | justifies rebalancing |
| Never truncate | – | – | PROJECT_BUSINESS_RULE | C-NRM-08 | everywhere |

**Scope of the checks:**
- **Step 6** checks the two address-line limits on the joined text, using the profile separator `", "`.
- **The gate** additionally checks the other field constraints above. Those produce `FIELD_TOO_LONG` (single-value fields only, never Address / Address 2), `INVALID_COUNTRY` or `INVALID_PIN` findings. They never cause a rebalance, and **never modify geography**.
- The country name → code mapping happens only when the payload is built. The stored `country` value is never changed.

**Target path:**
- The profile describes one verified path: **OData V4 VendorCard**.
- The Excel request form has no widths of its own, but its values end up in BC, so the same profile applies.
- No import path (configuration packages / RapidStart) is used or profiled.

**If everything fits → AUTO_PASS. No rebalance, no review.**

---

## 6. BC rebalancing (step 7)

**Safe rebalance.** A candidate layout is safe **only if all 12 hold**:
1. Every original non-geographic fragment appears exactly once (checked by fragment index).
2. Source order is preserved (indices strictly increase across A1, then A2).
3. No fragment is invented, and no fragment text is edited.
4. No fragment is deleted.
5. No fragment is duplicated.
6. Geography stays outside A1/A2.
7. A1 ≤ `BC_ADDRESS_1_MAX_LENGTH`.
8. A2 ≤ `BC_ADDRESS_2_MAX_LENGTH`.
9. It is deterministic: the same fragments, boundary and profile always give the same result.
10. It is auditable: one provenance entry with before, after, moved indices and the triggering constraint.
11. No `semantic_role` changes; only `final_bc_field` and `moved_by` change.
12. The semantic boundary is not reopened:
    - A1 stays a contiguous prefix.
    - The move is the smallest possible.
    - It is a single move in one direction.
    - It never reverses a step-5 move.
    - No A1-role fragment from after the semantic boundary is pulled back out of order.

**If any condition fails:** values are left exactly as step 5 produced them, and the result is `ADDRESS_OVERFLOW` → MANUAL_REVIEW / BLOCK.

**Unit of movement.** Only complete comma-delimited fragments move.
- **Never** `Address2[:50]`.
- **Never** drop characters.
- **Never** split a fragment (e.g. `Industrial Area` is never cut).
- Word-level splitting and abbreviations are **not** part of this plan. They would need explicit company approval as a separate PROJECT_BUSINESS_RULE.

**Algorithm** (pure function; `max1`, `max2`, `sep` come from the profile; `b` is the boundary after step 5; `floor` = the step-5 boundary if step 5 fired, else 1):

```
rebalance(frags, b, max1, max2, sep, floor):
    J = λ i,j: sep.join(frags[i:j]); n = len(frags)
    if n == 0 or (len(J(0,b)) <= max1 and len(J(b,n)) <= max2): return b, FIT
    if len(J(b,n)) > max2 and len(J(0,b)) <= max1:            # A2 too long → RIGHT only
        for nb in b+1 .. n:
            if len(J(0,nb)) > max1: break                       # A1 would break its limit
            if len(J(nb,n)) <= max2: return nb, REBALANCED      # first fit = minimal move
    elif len(J(0,b)) > max1 and len(J(b,n)) <= max2:          # A1 too long → LEFT only
        for nb in b-1 down to floor:                            # never undoes step 5, never empties A1
            if len(J(nb,n)) > max2: break
            if len(J(0,nb)) <= max1: return nb, REBALANCED
    return b, OVERFLOW                                          # both too long, or no whole-fragment fit
```

**Consequences of the algorithm:**
- **A single fragment over the limit.** A fragment longer than `max1` can never be placed. A fragment of 51–100 characters fits only in A1, and only if the whole prefix before it also fits. Otherwise → OVERFLOW (`detail: fragment_too_long`) → MANUAL_REVIEW / BLOCK.
- **Total over the combined limit.** Over `max1 + len(sep) + max2` (152 today) → OVERFLOW.
- **Granularity.** Some addresses under 152 characters still cannot fit because of where the fragment breaks fall → OVERFLOW.
- **Termination.** At most n iterations and one direction, so it always terminates.

**Measured:**

| Case | Before (A1 / A2) | After (A1 / A2) |
|---|---|---|
| Canonical Howrah | 25 / 69 | **58 / 36** (`SRIJAN INDUSTRIAL LOGISTIC PARK` moves; its `semantic_role` stays ADDRESS_2) |
| Corpus variant | 25 / 70 | 58 / 37 |
| `ho24` | 32 / 65 | 50 / 47 |

**Gate mode (stage 11):**
- Fragments are recovered from the stored A1 + A2 (+ legacy A3 + A4) by splitting on `","`. This round-trips exactly, because fragments never contain commas.
- The boundary comes from the stored A1.
- The same function runs, but its result is only a **proposal** attached to the finding. Stored values are never rewritten by the gate.

---

## 7. Automation classification (exact decision table)

| Situation | Classification | Reason code |
|---|---|---|
| A1 empty → controlled backfill (either variant) | **AUTO_FIX + LOGGED REASON CODE** | `ADDRESS_1_BACKFILLED` |
| A2 exceeds BC limit and safe deterministic rebalance succeeds | **MANUAL_REVIEW — ONE CLICK** | `ADDRESS_BC_LENGTH_REBALANCE` |
| A2 exceeds BC limit and safe rebalance fails | **MANUAL_REVIEW / BLOCK** | `ADDRESS_OVERFLOW` |
| Individual fragment itself exceeds BC limit and cannot be placed safely | **MANUAL_REVIEW / BLOCK** | `ADDRESS_OVERFLOW` (`detail: fragment_too_long`) |
| A1/A2 fit BC limits | **AUTO_PASS** | – |
| Silent truncation | **NEVER ALLOWED** (no code path; grep test) | – |

**Additional rows** (consistent with the above):

| Situation | Classification | Reason code |
|---|---|---|
| A1 > 100 at the semantic boundary, safe left shift exists | MANUAL_REVIEW — one click | `ADDRESS_BC_LENGTH_REBALANCE` (constraint `BC_ADDRESS_1_MAX_LENGTH`) |
| Backfill followed by a rebalance | MANUAL_REVIEW — one click (the stricter class wins) | both codes, two provenance entries |
| Step-8 invariant fails (code defect) | BLOCK_SUBMISSION | `ADDRESS_INVARIANT_VIOLATION` |
| Stage 11: stored/edited A1 or A2 over its limit, safe whole-fragment re-layout exists | MANUAL_REVIEW — one click (confirming writes the proposal) | `ADDRESS_BC_LENGTH_REBALANCE` (constraint `BC_ADDRESS_1_MAX_LENGTH` / `BC_ADDRESS_2_MAX_LENGTH`) |
| Stage 11: stored/edited A1 or A2 over its limit, no safe re-layout | MANUAL_REVIEW / BLOCK (edit by hand) | `ADDRESS_OVERFLOW` (`detail: fragment_too_long` when one fragment cannot be placed) |
| Stage 11: legacy `address_3/4` non-empty | one-click proposal if safe, else MANUAL_REVIEW / BLOCK | `ADDRESS_BC_LENGTH_REBALANCE` / `ADDRESS_OVERFLOW`, constraint `BC_NO_ADDRESS_3_4` |
| OCR de-glue / inferred comma-less boundaries | AUTO_FIX (logged) | `ADDRESS_OCR_REPAIRED` |
| Inferred boundaries **and** every fragment `unknown` | MANUAL_REVIEW | `LOW_CONFIDENCE` |
| Source text has no comma and no line break, **and** City or State was not extracted, or the last 1–3 words of the last fragment are a known state/city name | MANUAL_REVIEW (text unchanged; never peeled, moved or auto-fixed) | `GEOGRAPHY_UNRESOLVED` |
| A1 and A2 both empty after the geography peel | MANUAL_REVIEW | `FIELD_NOT_FOUND` |
| Name, City, County, Post Code, Phone, Mobile, E-Mail or Home Page over its profile limit; bad PIN; unmapped country; PIN↔state mismatch; city derived from PIN | as in REGISTRY | `FIELD_TOO_LONG`, `INVALID_PIN`, `INVALID_COUNTRY`, `PIN_STATE_MISMATCH`, `DERIVED_VALUE_UNCONFIRMED` |

**Terminology — length findings.** `FIELD_TOO_LONG` is used only for single-value fields, which have no whole-fragment re-layout (Name, City, County, Post Code, Phone, Mobile, E-Mail, Home Page; C-LEN-01, 05–07, 10–12). Address and Address 2 **never** produce `FIELD_TOO_LONG`. Their length is handled only by `ADDRESS_BC_LENGTH_REBALANCE` (a safe re-layout exists) and `ADDRESS_OVERFLOW` (none exists), at extraction time and at the gate alike. One situation has exactly one reason code.

**One-click flow:**
1. Extraction applies the AFTER values and opens the finding.
2. The review page shows BEFORE and AFTER, with **Confirm** or **Edit manually**.
3. Confirm stores the reviewer, the time and a SHA-256 of the trimmed final A1/A2.
4. At push, the gate re-runs steps 6–8 (**final BC validation after confirmation**). The finding stays closed only while the stored values of its covered fields (closure matrix below) still match the fingerprint.
5. An edit after confirmation re-opens the checks. Edited values are human-authored; they close a finding only as the closure matrix allows.

**Push rule:** zero BLOCK findings and zero **open** MANUAL_REVIEW findings (DESIGN L151). This applies to **every** MANUAL_REVIEW reason code, not only the rebalance.

**Closure rule.** Every finding has exactly one closure mechanism, named in the matrix below:

- **Confirm.** Allowed only for a finding a human can genuinely judge by looking at it. The reviewer confirms that one reason code. The confirmation stores the reason code, the reviewer, the time and a **fingerprint**: SHA-256 of the trimmed values of the finding's covered fields, joined with `\n`, in the matrix order. (For `ADDRESS_BC_LENGTH_REBALANCE` this is exactly today's `A1\nA2` hash, so existing confirmations stay valid.) A confirmation counts only while the stored values still produce the same fingerprint. Any change to a covered field invalidates it.
- **Correct.** A covered field is changed and the gate's re-check of the **stored** values no longer finds the condition. An edit that leaves the condition in place does not close the finding. Findings that can only be corrected cannot be confirmed away.
- **Recompute.** Findings the gate computes from stored values are recomputed on every payload request and disappear when their condition is gone.

Every edited value is human-authored and goes through steps 6–8 and the other gate checks again, whatever finding it closed. Anything not closed is **open**, and the payload endpoint answers 409 with the open findings. Records without `raw_extraction` (entered by hand) carry no extraction-time findings; only gate-computed findings apply to them.

**Reason-code closure matrix:**

| Reason code | Class | Raised at | Covered fields (fingerprint order) | Gate re-check on stored values | Closure | Confirmable |
|---|---|---|---|---|---|---|
| `ADDRESS_1_BACKFILLED` | AUTO_FIX | extraction (step 5) | – | – | none needed (logged in provenance, never a review finding) | – |
| `ADDRESS_OCR_REPAIRED` | AUTO_FIX | extraction (segmenter) | – | – | none needed (logged in provenance, never a review finding) | – |
| `ADDRESS_BC_LENGTH_REBALANCE` | MANUAL_REVIEW | extraction (step 7) | address_1, address_2 | steps 6–8 | confirm the split; or correct (an edit after which steps 6–8 pass) | **Yes** |
| `ADDRESS_BC_LENGTH_REBALANCE` | MANUAL_REVIEW | gate (stage 11: over-limit or legacy A3/A4) | address_1, address_2, address_3, address_4 | steps 6–8 | confirm the proposal (the lossless re-layout is written, A3/A4 cleared); or correct by hand | **Yes** (only the gate's own lossless proposal) |
| `LOW_CONFIDENCE` | MANUAL_REVIEW | extraction | address_1, address_2 | none (no stored-value signal) | confirm the split as read; or correct (any edit of a covered field) | **Yes** |
| `GEOGRAPHY_UNRESOLVED` | MANUAL_REVIEW | extraction | address_1, address_2, city, state, pin_code | City and State non-empty, and the last 1–3 words of the stored last line are not a known state/city | correct; confirm is allowed **only once City and State are non-empty** (the reviewer accepts that a trailing name is a real locality, e.g. `NEHRU NAGAR`) | **Partly** (never while City or State is empty) |
| `FIELD_NOT_FOUND` (address) | MANUAL_REVIEW | extraction | address_1, address_2 | A1 or A2 non-empty | correct only | **No** |
| `INVALID_COUNTRY` | MANUAL_REVIEW | gate | country | country maps to a profile code | recompute (fix the value or the profile mapping) | **No** (BC would reject the record) |
| `ADDRESS_OVERFLOW` | BLOCK_SUBMISSION | extraction (step 7) / gate | address_1, address_2 (+ legacy 3/4) | steps 6–8 | correct only (edit until a whole-fragment layout fits) | **No** |
| `ADDRESS_INVARIANT_VIOLATION` | BLOCK_SUBMISSION (system error) | extraction (step 8) / gate | address_1, address_2, city, state, country, pin_code | steps 6–8 including BC-07 | correct only; the record stays blocked until a re-run of steps 6–8 on the stored values passes. Investigated as a defect, never reviewed away | **No** |
| `FIELD_TOO_LONG` | BLOCK_SUBMISSION | gate | the one field | profile length | recompute (edit the value) | **No** |
| `INVALID_PIN` | BLOCK_SUBMISSION | gate | pin_code | 6-digit Indian PIN | recompute (edit the value) | **No** |

**Implementation status (2026-10-03).** The gate already enforces this for `ADDRESS_BC_LENGTH_REBALANCE` (both rows) and for every gate-computed finding. Enforcing the extraction-time `LOW_CONFIDENCE`, `GEOGRAPHY_UNRESOLVED` and `FIELD_NOT_FOUND` findings at push is approved policy that is **not yet implemented**. Today they are shown on the review page only.

---

## 8. Provenance and audit (extending the existing mechanism)

Nothing parallel is built. The plan extends what exists today:

1. **`FieldResult.provenance: list[dict]`** (`models.py:333`, added to `to_dict`) on `address_1`. It holds the semantic layout once, then one entry per transformation, **including AUTO_FIX entries**. `FieldResult.notes` keeps its one-line summaries.
2. **`_flag` entries** (`semantic_engine.py:538`) gain the optional keys `reason_code`, `automation_class` and `provenance_index`.
   - Only MANUAL_REVIEW and BLOCK findings are flagged.
   - AUTO_FIX never appears in `needs_review` / `fields_needing_review`.
   - Existing entries have no `automation_class` and keep their meaning (informational).
3. Everything travels in the extraction result, which is already persisted in **`Vendor.raw_extraction`**. That column is the immutable extraction-time record.
4. **Reviewer confirmation** goes in a new **`Vendor.address_review` JSON** column (Alembic migration). It stores the reason code, final A1/A2, the hash, `confirmed_by_user_id` and `confirmed_at`. With the §7 closure rule it holds one confirmation per confirmable reason code: `{"confirmations": {"<REASON_CODE>": {"fields": [...], "values_sha256": "...", "confirmed_by_user_id": n, "confirmed_at": "..."}}}`. The existing top-level keys are still written for `ADDRESS_BC_LENGTH_REBALANCE` and are read as that reason's confirmation, so records confirmed before this change stay confirmed (no data migration).

**Semantic layout** (recorded once):
```json
{"layer": "semantic", "semantic_boundary": 2,
 "fragments": [
   {"index": 0, "text": "3RD FLOOR", "tier": "structural", "semantic_role": "ADDRESS_1"},
   {"index": 1, "text": "PART A BLOCK B", "tier": "structural", "semantic_role": "ADDRESS_1"},
   {"index": 2, "text": "SRIJAN INDUSTRIAL LOGISTIC PARK", "tier": "estate_zone", "semantic_role": "ADDRESS_2"},
   {"index": 3, "text": "MOHIARY CHANDIBAGAN", "tier": "locality", "semantic_role": "ADDRESS_2"},
   "..."],
 "semantic_address_1": "3RD FLOOR, PART A BLOCK B",
 "semantic_address_2": "SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY CHANDIBAGAN, ANDUL, Natibpur"}
```

**BC rebalance entry:**
```json
{"layer": "bc_representation", "transformation": "bc_boundary_shift_right",
 "reason_code": "ADDRESS_BC_LENGTH_REBALANCE", "automation_class": "MANUAL_REVIEW",
 "constraint": "BC_ADDRESS_2_MAX_LENGTH", "constraint_value": 50, "profile": "bc22_in_vendorcard",
 "boundary_before": 2, "boundary_after": 3,
 "moved_fragments": [{"index": 2, "semantic_role": "ADDRESS_2", "final_bc_field": "ADDRESS_1"}],
 "original_address_1": "3RD FLOOR, PART A BLOCK B",
 "original_address_2": "SRIJAN INDUSTRIAL LOGISTIC PARK, MOHIARY CHANDIBAGAN, ANDUL, Natibpur",
 "final_address_1": "3RD FLOOR, PART A BLOCK B, SRIJAN INDUSTRIAL LOGISTIC PARK",
 "final_address_2": "MOHIARY CHANDIBAGAN, ANDUL, Natibpur",
 "manual_review_required": true, "review": null}
```

**Backfill entry:**
```json
{"layer": "presentation_fallback", "transformation": "first_1_2_fragments",
 "reason_code": "ADDRESS_1_BACKFILLED", "automation_class": "AUTO_FIX", "constraint": null,
 "boundary_before": 0, "boundary_after": 2,
 "moved_fragments": [{"index": 0, "semantic_role": "ADDRESS_2", "final_bc_field": "ADDRESS_1"},
                     {"index": 1, "semantic_role": "ADDRESS_2", "final_bc_field": "ADDRESS_1"}],
 "original_address_1": "", "original_address_2": "Mauli Baidwan, Circular Road, Sector 80",
 "final_address_1": "Mauli Baidwan, Circular Road", "final_address_2": "Sector 80",
 "manual_review_required": false}
```

**Chaining and confirmation:**
- When there are several entries, each entry's `original_*` equals the previous entry's `final_*`.
- On confirmation, `review` becomes `{confirmed_by_user_id, confirmed_at, values_sha256}`. This is mirrored into `Vendor.address_review`.

---

## 9. Configuration and constraint registry

There is no existing code registry; the research registry exists only as documentation (REGISTRY). The plan therefore adds **one** config file that mirrors it by constraint ID:
`backend/config/bc_targets/bc22_in_vendorcard.yaml`

```yaml
target: {product: BC, version: "22 (build: TENANT VERIFICATION REQUIRED, Q20)", localization: IN,
         entity: VendorCard, path: odata_v4}
separator: ", "
constraints:
  BC_ADDRESS_1_MAX_LENGTH:    {bc_field: Address,             portal: address_1, value: 100, category: MICROSOFT_BC_CONSTRAINT, registry: C-LEN-03}
  BC_ADDRESS_2_MAX_LENGTH:    {bc_field: Address_2,           portal: address_2, value: 50,  category: MICROSOFT_BC_CONSTRAINT, registry: C-LEN-04}
  BC_CITY_MAX_LENGTH:         {bc_field: City,                portal: city,      value: 30,  category: MICROSOFT_BC_CONSTRAINT, registry: C-LEN-05}
  BC_COUNTY_MAX_LENGTH:       {bc_field: County,              portal: state,     value: 30,  category: MICROSOFT_BC_CONSTRAINT, registry: C-LEN-06}
  BC_POST_CODE_MAX_LENGTH:    {bc_field: Post_Code,           portal: pin_code,  value: 20,  category: MICROSOFT_BC_CONSTRAINT, registry: C-LEN-07}
  BC_COUNTRY_CODE_MAX_LENGTH: {bc_field: Country_Region_Code, portal: country,   value: 10,  category: MICROSOFT_BC_CONSTRAINT, registry: C-LEN-08}
  BC_NO_ADDRESS_3_4:          {portal: [address_3, address_4], value: empty, category: MICROSOFT_BC_CONSTRAINT, registry: C-ADR-04}
country_codes: {India: IN}     # TENANT VERIFICATION REQUIRED (Q4): IN or INDIA
county_abbreviations: {}       # empty until the company decides (Q21)
verified_against_metadata: false
```

**Loader:** `backend/app/services/bc_target_profile.py`.
- It validates that every ID is present and fails loudly when one is missing.
- There are **no fallback literals** in code.
- It exposes `AddressLimits(address_1_max, address_2_max, separator)`.
- A grep test fails if an address limit literal appears outside the YAML.

**Settings in `config.py`** (same pattern as `BC_ENABLED`, line 75):
- `BC_TARGET_PROFILE`
- `BC_ADDRESS_LAYER_ENABLED = False`
- `BC_PAYLOAD_GATE_ENABLED = False`

**`$metadata` check:**
- The operator saves `$metadata` over the VPN (the backend cannot reach BC).
- `python -m app.cli.check_bc_metadata --metadata-file <xml>` compares VendorCard `MaxLength` values against the profile.
- Whether VendorCard exposes `MaxLength` at all is TENANT VERIFICATION REQUIRED. The fallback is sandbox test T-BC-02.

**Unchanged:** `segmentation_keywords.yaml` and all role mappings.

---

## 10. Invariants

**Semantic invariants (existing, kept):**

| ID | Invariant |
|---|---|
| S-01 | No fragment lost |
| S-02 | No fragment duplicated |
| S-03 | Source order preserved |
| S-04 | Semantic boundary = initial A1-role run; it never reopens |
| S-05 | `unknown` is never semantically A1 |
| S-06 | Geography never in A1/A2 |
| S-07 | A3/A4 empty |
| S-08 | The backfill moves only fragment 0 (thoroughfare variant) or the first 1–2 fragments, never reorders, and fires at most once |

**BC invariants (new):**

| ID | Invariant | How it is checked |
|---|---|---|
| BC-01 | Final A1 ≤ configured Address 1 maximum | FIT/REBALANCED ⇒ holds; also with random limits |
| BC-02 | Final A2 ≤ configured Address 2 maximum | same |
| BC-03 | No silent truncation | Final A1 + sep + A2 equals the source join; no `[:` slicing in the BC modules (grep test) |
| BC-04 | No source fragment loss | index multiset |
| BC-05 | No source fragment duplication | index multiset |
| BC-06 | Source order preserved | strictly increasing indices |
| BC-07 | Geography never enters A1/A2 | no fragment equals an extracted geography value or alias |
| BC-08 | Every BC-driven transformation has a reason code | every boundary change ↔ exactly one provenance entry |
| BC-09 | Semantic role is preserved when the final field changes | `semantic_role` identical before and after steps 5–7 for every fragment |
| BC-10 | An unsafe BC transformation cannot reach push automatically | OVERFLOW / violation ⇒ BLOCK ⇒ payload endpoint returns 409 |
| BC-11 | Manual-review transformations need explicit confirmation | without a matching `address_review` hash ⇒ 409 |
| BC-12 | A3/A4 remain empty | resolver output, engine write-back, and payload (never joined) |

**Algorithm properties:**
- minimal move;
- one direction;
- step 7 never reverses step 5;
- each step runs at most once;
- idempotent;
- deterministic;
- flag on with a fitting address produces the same result as flag off.

---

## 11. Test strategy

### 11.1 Named cases

New file `backend/app/eval/address_bc_layer_cases.yaml`, run by `tests/test_address_bc_layer.py`. Each case asserts the semantic layout, the final layout, the class, the reason code and the provenance.

| # | Case | Expected |
|---|---|---|
| 1 | `F-192, Phase 8B, Industrial Area, Sector 74, SAS Nagar, Punjab 160055` | A1 `F-192`, A2 `Phase 8B, Industrial Area, Sector 74`. No rebalance, no review. AUTO_PASS. |
| 2 | A1 "" / A2 `Sector 67` | A1 `Sector 67`, A2 "". AUTO_FIX `ADDRESS_1_BACKFILLED`. |
| 3 | A1 "" / A2 `Ward 07, Sector 67, Industrial Area` | A1 `Ward 07, Sector 67`, A2 `Industrial Area`. `ADDRESS_1_BACKFILLED`. |
| 3b | `Mauli Baidwan, Circular Road, Sector 80, SAS Nagar, Punjab 140308` | A1 `Mauli Baidwan, Circular Road`, A2 `Sector 80`. AUTO_FIX. **No review finding**, even though confidence is `low`. |
| 3c | `MG Road, B, C, D` | A1 `MG Road`, A2 `B, C, D`. Rule `leading_thoroughfare`. The generic backfill does not also fire. |
| 4 | `Sector 67, SAS Nagar, Punjab 160062` and `Ward 07, Sector 67, SAS Nagar, Punjab, 160062, India` | `SAS Nagar`, `Punjab`, `160062` and `India` never appear in A1/A2, and City/State/PIN/Country are unchanged by steps 5–8. |
| 5 | A1 `UNIT 7`, A2 exactly 50 characters | AUTO_PASS, no rebalance. |
| 6 | A2 = 51 characters, made of whole fragments | Rebalance → `ADDRESS_BC_LENGTH_REBALANCE`, MANUAL_REVIEW one click. |
| 7 | Howrah baseline (25/69) → 58/36 | MANUAL_REVIEW one click. |
| 7b | `UNIT 7` + 70-character + 55-character fragments (total 135 < 152) | No safe layout: values unchanged, `ADDRESS_OVERFLOW`, BLOCK. |
| 7c | Total > 152 | `ADDRESS_OVERFLOW`, values unchanged. |
| 8 | One 110-character comma-less fragment | Not truncated. `ADDRESS_OVERFLOW` `fragment_too_long`, BLOCK. |
| 8b | A 60-character fragment in A2 with a short A1 | Moves to A1 (it fits only there); one click. |
| 9 | Fragments A, B, C, D with rebalance | Possible output A1 `A, B`, A2 `C, D`. Asserts that `B, A` or `A, C` can never occur, over every rebalance output. |
| 10 | `Phase 8B` moved to A1 by a rebalance | `semantic_role = ADDRESS_2`, `final_bc_field = ADDRESS_1`, `moved_by = ADDRESS_BC_LENGTH_REBALANCE`. The classifier still returns ADDRESS_2 for `Phase 8B`. |
| 11 | `Flat 402, Tower B, Sunrise Apartments, Block C, Sector 10` | A1 `Flat 402, Tower B`, A2 `Sunrise Apartments, Block C, Sector 10`. |
| 12 | `Unknown Fragment, F-192, Phase 8B, Industrial Area, Sector 74, …` | Semantic boundary 0 (F-192 is not promoted by a scan). The backfill takes the first 2 by position. Provenance marks F-192 as `moved_by = ADDRESS_1_BACKFILLED`. |
| 13 | Every case | `address_3 == address_4 == ""`, including after the engine write-back when the matcher had stale values. |
| 14 | Captioned `country = India` vs no country (config default) | The extracted value takes precedence and the default is used only when absent. Steps 5–8 and the gate never change `country`, `city`, `state` or `pin_code`. The payload maps name → code without changing the stored value. |
| 15 | Backfill then rebalance | Two ordered entries. Class MANUAL_REVIEW. |
| 16 | A1 over 100 after a backfill | `ADDRESS_OVERFLOW`, **not** a left shift (no oscillation). |
| 17 | Bail path (city/state/PIN captioned) with A2 of 60 characters | The BC layer still runs, giving a rebalance or an overflow finding. |
| 18 | Confirm, then edit A2 | The hash no longer matches, so the gate re-checks. |

### 11.2 Invariant and property tests

File: `tests/test_address_bc_invariants.py`.
- Inputs: the 136 corpus expectations plus 10,000 seeded random fragment lists (stdlib `random`, fixed seed; **no new dependency**).
- Limits: both the profile limits and random limits.
- Checks: S-01…S-08, BC-01…BC-12, and the algorithm properties.

### 11.3 Existing tests: none are weakened

| Existing test / corpus | Conflict? | Action |
|---|---|---|
| `test_address_segmenter.py`, all classes (TestClassification, TestBoundaryInjection, TestGrouping, TestTailSplitConservatism, TestConfidence, TestDesegment, TestInvariants, TestBackCompat, TestAddress1FallbackPopulation, TestPerformance) | None. The semantic layer is unchanged; the fallback wrapper gives identical output. | Keep as is. Fix the stale "61 cases" docstring. |
| `address_line_cases.yaml` (74; 3 expect A2 > 50, M2) | Its expectations are **semantic**, and they stay true. | Keep as is. Add a separate `bc_expect` block (final A1/A2, class, code) to those 3 cases instead of changing `expect`. |
| `address_vendor_lines.yaml` (20; 1 expects A2 > 50) | Same | Same |
| `address_holdout_cases.yaml` (30; still 4 lines, with 21 non-empty `address_3`) | **Conflicts** with "A3/A4 never populated" (a rule already in force on this branch). | Migrate to 2 lines by hand review, not by running the code. Record every changed case in the commit message. Keep the order and content of each fragment (the old A2+A3+A4 in order becomes the new A2). |
| `address_cases.yaml` (12, non-multiline) | None; that path is untouched | Keep |
| `test_eval_address_block.py` (A3/A4 absent) | None; consistent | Keep |
| `test_business_central.py:80` `Country_Region_Code == "India"` | **Conflicts**: it encodes the name-not-code defect (C-LEN-08, C-MD-01) | Migrate to expect the profile code. The underlying invariant ("country mapped") is kept. |
| `test_business_central.py:77` Address_2 | None (no A3/A4 in that fixture) | Keep. Add a test that A3/A4 are never joined. |
| `master` `test_long_joined_address_is_truncated_to_fit` | **Conflicts** with no-truncation | At merge, rewrite it to assert `ADDRESS_BC_LENGTH_REBALANCE` or `ADDRESS_OVERFLOW` and an untruncated value (T-GATE-02). |
| `test_vendor_customer_api.py`, `test_onboarding_mapper.py` | None | Keep. Add `address_review` passthrough tests. |
| `test_validator.py` | Only if the cross-document state method changes (Appendix A, phase P3) | Migrate only in P3, with a reason given per case. |

### 11.4 Commands (run at every step)

```
cd backend
pytest tests -q                                             # all backend regression tests
pytest tests/test_address_segmenter.py -q                   # segmenter + resolver + fallback
python -m app.eval.eval_address --multiline --cases app/eval/address_line_cases.yaml
python -m app.eval.eval_address --multiline --cases app/eval/address_vendor_lines.yaml
python -m app.eval.eval_address --cases app/eval/address_cases.yaml
python -m app.eval.eval_address --multiline --cases app/eval/address_holdout_cases.yaml   # after migration
```

Each eval command runs twice: once with the flag off (100% must be unchanged) and once with the flag on (semantic expectations still 100%, plus the `bc_expect` checks).

**Shadow metric:** counts of AUTO_PASS / BACKFILLED / BC_LENGTH_REBALANCE / OVERFLOW over the corpora and the saved `outputs/` runs.

---

## 12. Files, modules and functions likely to change

### New files

| File | Contents |
|---|---|
| `extract/address_representation.py` | Types: `SemanticLayout` (frozen), `LayoutFragment` (`index`, `text`, `tier`, `semantic_role`, `final_bc_field`, `moved_by`), `AddressLayout`, `AddressTransform`, `AddressFinding`, `AddressDecision`. Functions: `apply_a1_fallback(sem)`, `represent_address(sem, limits, geography, mode="apply"\|"check")` (orchestrates steps 5–9), `layout_from_stored(a1, a2, a3="", a4="")`. |
| `extract/bc_address_fit.py` | Layer 2 only; no semantic knowledge. `check_constraints(layout, limits)`, `rebalance(layout, limits, floor)`, `validate_final(sem, final, geography, limits)`. |
| `services/bc_target_profile.py` | `load_profile(name)`, `BcTargetProfile.limit(id)`, `.address_limits()`, `.country_code(name)` |
| `config/bc_targets/bc22_in_vendorcard.yaml` | The constraint registry values |
| `services/bc_payload_gate.py` | `gate_vendor(vendor, profile) -> list[AddressFinding]`, check-only |
| `cli/check_bc_metadata.py` | `$metadata` diff |
| `alembic/versions/<rev>_vendor_address_review.py` | `vendors.address_review` JSON, nullable |
| Tests | `test_address_bc_layer.py`, `test_address_bc_invariants.py`, `test_bc_payload_gate.py`, `test_bc_target_profile.py`; eval file `address_bc_layer_cases.yaml` |

### Modified files

| File | Functions / classes | Change |
|---|---|---|
| `extract/address_segmenter.py` | `SegmentedAddress` (178), `segment_leftover` (1062) | Additive only: `semantic_boundary` (length of the initial A1-role run; 0 when the thoroughfare rule fired) and `fallback_applied`. `_split_by_role` is untouched. |
| `extract/address_resolver.py` | `ResolvedAddress` (74), `resolve_address_blob` (456–476), `_fallback_populate_address_1` (481) | When the flag is on: build a `SemanticLayout` from `seg_result` and call `represent_address`. A1/A2 come from the final layout; A3/A4 are always "". New attributes: `representation`, `findings`. The wrapper is kept for the flag-off path. |
| `extract/semantic_engine.py` | `_flag` (538), `_resolve_combined_address` (319–434), new `_represent_captioned_address` | Write back A2 even when empty, and A3/A4 = "". Attach provenance and flag findings. Write back `r.country` only when a country token was extracted and the field is empty or default-filled. A fully peeled blob is not left in `address_1`; it gets `FIELD_NOT_FOUND`. The bail path (365/369) is sent through steps 5–8, with the boundary taken from the captions. |
| `extraction_pipeline/models.py` | `FieldResult` (333) | New `provenance` field, included in `to_dict` |
| `services/bc_mapper.py` | `_ADDRESS_2_JOIN_FIELDS` (57), `vendor_to_bc_payload` (60) | Remove the join. Country code comes from the profile. |
| `routers/business_central.py` | `GET /vendors/{id}/payload` (58–76); new `POST /vendors/{id}/address-review/confirm` | Run the gate and return 409 with findings when blocked. |
| `models/model.py`, `schemas/vendor_schema.py`, `services/records_crud.py:16` | Vendor, schema, `_PASSTHROUGH` | Add `address_review` |
| `config/config.py` | settings | Profile name and flags |
| `ar-portal/src/api.js`, `pages/VendorConfirmPage.jsx`, `pages/RecordDetailPage.jsx` | – | BEFORE/AFTER panel with Confirm / Edit; send `address_review`; show gate findings |
| `try_address.py`, `scripts/try_gstin.py` | – | Print the semantic layout, the final layout and the provenance |
| `tests/test_business_central.py`, eval YAMLs | – | As in §11.3 |
| Docs | – | Rename `ADDRESS_REBALANCED` → `ADDRESS_BC_LENGTH_REBALANCE` (DESIGN L71/135/298/302/316–318, REGISTRY C-LEN-04/C-ADR-03/C-ADR-10, RESEARCH L328/702/717/803, TESTPLAN T-ADR-01/02/T-GATE-02, PIPELINE L102). Fix the AUTO_FIX wording and the stale items from §0.2. |
| Phase P3 (optional) | `validator.py` `compare_across_documents` (170), `validation_rules.yaml` | Appendix A |

**Untouched:**
- the classifier, keywords, `_TIER_ROLE` and `_split_by_role`;
- the geography functions and data files;
- the non-multiline resolver path;
- the customer payload;
- GSTIN verification;
- the Excel layout.

---

## 13. Migration impact

- **Flags.**
  - `BC_ADDRESS_LAYER_ENABLED=False` keeps today's output byte for byte; a guard test enforces this.
  - `BC_PAYLOAD_GATE_ENABLED=False` keeps today's payload endpoint.
  - Rollback is turning both flags off. Rebalanced values contain the same text in the same order, so no data repair is needed.
- **Database.** One migration adds the nullable `vendors.address_review` JSON column; the downgrade drops it.
- **Existing records.**
  - `address_3/4` stay in the database. The gate never joins them; it proposes a re-layout (one click) or blocks.
  - Records without provenance are treated as human-authored, so only the length checks apply.
- **API.** All changes are additive:
  - `fields.*.provenance`;
  - optional keys on `needs_review` entries (`reviewFieldNames` in `api.js:229` reads only `.field`, so it is unaffected);
  - a 409 response from the payload endpoint, only when the gate flag is on.
- **`master` merge.**
  - Keep `ocr-testing`'s segmenter and resolver.
  - Drop `_BC_FIELD_MAX_LEN`, `_fit_to_bc_width`, `_truncated_fields` and the router's pop of them (R-01/R-02).
  - Replace the UI's "shortened" warning with gate findings.
  - Rewrite the truncation test.
- **Docs.** Rename the reason code and apply the corrections as part of the same change.

---

## 14. Regression risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | The flag-off path drifts | Guard test: flag off equals the current output for every corpus case and the saved `outputs/` runs |
| R2 | Clearing stale A2/A3/A4 blanks a genuine caption | The resolver runs only on combined lines (comment 382–396); check on the 20 vendor-line fixtures and on real runs |
| R3 | The bail path now reaches the BC layer and raises new BLOCKs | Shadow counts in P0 before the flag is enabled |
| R4 | Fewer reviews: the no-premise case no longer creates one | Intended. AUTO_FIX stays logged and visible. |
| R5 | More one-click reviews | Corpus rate is about 5 in 136 (M2); the real rate comes from the shadow run |
| R6 | The confirmation hash breaks on a harmless edit | Hash trimmed values; the UI says why re-confirmation is needed |
| R7 | Merge conflicts with `master` in `bc_mapper`, the router and tests | Merge in P2 following §13 |
| R8 | A rebalanced A1 shows locality text | Allowed, because BC gives the lines no meaning (C-ADR-01). The reviewer sees BEFORE/AFTER, and provenance keeps the role. |
| R9 | Newlines are flattened before step 1 | UNVERIFIED; add a multi-line caption fixture in P1 |
| R10 | Migrating the holdout corpus introduces expectation errors | Migrate by hand review, one line of rationale per case, and have a second person check it |

---

## 15. Exact implementation sequence

Each step is its own commit, with the full test and eval command set green after each one.

| # | Step | Verifies | Phase |
|---|---|---|---|
| 1 | Profile YAML, loader, flags (off), loader tests, grep test for limit literals | profile tests | P0 |
| 2 | `check_bc_metadata` CLI (reads a saved XML only) | fixture XML test | P0 |
| 3 | `bc_address_fit.py` (pure), unit tests, random-limit property tests | BC-01…06, BC-03 grep, minimal move, idempotence | P1 |
| 4 | `address_representation.py`: types, A1 fallback (both variants, exclusive), orchestrator, provenance; named cases on hand-built layouts | cases 2, 3, 3c, 5–10, 12, 15, 16; S-08, BC-08, BC-09 | P1 |
| 5 | Additive `SegmentedAddress` fields | segmenter suite unchanged and green | P1 |
| 6 | Resolver integration behind the flag, with the wrapper kept | R1 guard; cases 1, 3b, 4, 11, 13 end to end | P1 |
| 7 | `FieldResult.provenance`, `_flag` keys, `semantic_engine` write-back, country write-back rule, bail path | cases 13, 14, 17; BC-07, BC-12 | P1 |
| 8 | Add `bc_expect` blocks to the corpora; migrate the holdout file to 2 lines | eval commands, flag on and off | P1 |
| 9 | Shadow run and report; go/no-go on the flag | counts | P1 |
| 10 | Alembic migration, `address_review` in model, schema and CRUD | migration up/down, API test | P2 |
| 11 | Payload gate, router 409, confirm endpoint | BC-10, BC-11, case 18, T-GATE-01 | P2 |
| 12 | `bc_mapper`: remove the join, map the country code; migrate `test_business_central:80` | T-ADR-07, T-MD-01 | P2 |
| 13 | Frontend BEFORE/AFTER panel, Confirm / Edit, findings on the record page | manual walk-through of cases 7, 7b, 8 | P2 |
| 14 | Doc rename and corrections | review | P2 |
| 15 | `master` merge per §13 | T-GATE-02 | P2/P3 |
| 16 | (optional) Cross-document comparison (Appendix A) | T-XD-01…05 | P3 |
| 17 | Tenant items, `$metadata` check, Post Code read-back, UI character counters | T-BC-02, T-BC-05 | P4 |

**Effort** (developer days, excluding tenant waits):

| Phase | Days |
|---|---|
| P0 | 0.5–1 |
| P1 | 3.5–4.5 |
| P2 | 3.5–5 |
| P3 | 1.5–2 |
| P4 | 2–4 |
| **Total** | **≈ 11–16.5** |

---

## 16. Open questions that genuinely require a decision

**Tenant items (TENANT VERIFICATION REQUIRED):**
1. **Q4:** is the India Country/Region Code `IN` or `INDIA`? This blocks go-live of the country mapping.
2. **Q21:** how should County be shortened for the 40-character state name? This is a company decision. Until then, that state is blocked.
3. **Q6:** is BC's Post Code table populated with Indian PINs, and with which city spellings? This decides how often BC overwrites City/County.
4. **Q20 and `$metadata`:** which exact BC build is it, and does VendorCard expose `MaxLength`?
5. **Unicode:** does BC count characters or UTF-16 code units for non-ASCII text?

**Decisions with a default already chosen** (change them if you disagree):
- **D2:** `LOW_CONFIDENCE` review applies only to inferred boundaries where every fragment is `unknown`.
- **D3:** confirmations are stored in the new `address_review` column, not written into `raw_extraction`.
- **D4:** two new codes, `ADDRESS_OCR_REPAIRED` and `ADDRESS_INVARIANT_VIOLATION`, are added to the DESIGN §2 taxonomy.
- **D5:** `GEOGRAPHY_UNRESOLVED` applies only to source text with no comma and no line break. It is MANUAL_REVIEW (never BLOCK, never auto-fixed) and looks only at the last 1–3 words of the last fragment. A leaked fragment that exactly equals an extracted city/state is still a BC-07 BLOCK; `GEOGRAPHY_UNRESOLVED` is added beside it to explain why. Automatic trailing-word geography extraction is **not** part of this plan; a strict `CITY → STATE → PIN` suffix extraction is preserved as deferred future work in §18 (not implemented).
- **D6:** every finding closes only through the mechanism the §7 closure matrix names. Confirmation is limited to genuinely reviewable findings. `FIELD_NOT_FOUND` and `INVALID_COUNTRY` need a correction. `ADDRESS_INVARIANT_VIOLATION` stays a blocking system error.

---

## 17. Consistency review (done before finalising)

| Check | Finding | Resolution |
|---|---|---|
| Semantic classification changed because of BC limits | Not changed. Steps 5–7 move only the boundary; `semantic_role` is immutable (BC-09) | – |
| BC constraints treated as semantic rules | Docs call the rebalance an AUTO_FIX of the address "split" | Recategorised as a BC representation step; class MANUAL_REVIEW; renamed `ADDRESS_BC_LENGTH_REBALANCE` |
| Fallback inside the semantic function | The thoroughfare rule lives in `_split_by_role`, which contradicts "semantic A1 = initial A1 run" | Recorded as `semantic_boundary = 0` plus a fallback entry (user decision); the code stays put, so tests are unchanged |
| Two backfills in a row | Thoroughfare + generic backfill could both fire | They are mutually exclusive, and the thoroughfare variant stops |
| Backfill moving geography | Impossible by construction; guarded by BC-07 | Explicit tests (case 4) |
| Rebalance undoing the backfill (A1→A2→A1 oscillation) | The revision 2 algorithm allowed a left shift below the backfill boundary | Left shift is floored at the step-5 boundary; A1 over 100 after a backfill → OVERFLOW (case 16) |
| Boundary reopening by the rebalance | A1 stays a prefix; one direction; minimal move | Condition 12 plus S-04 |
| Arbitrary truncation / character splitting | None; grep test BC-03 | – |
| Duplicate / dropped / reordered fragments | Index-multiset checks | BC-04/05/06 |
| Repeated loops | Each step runs at most once; no loop in the orchestrator | §2 |
| Missing reason codes | The thoroughfare rule and OCR repair were previously silent | `ADDRESS_1_BACKFILLED` (rule `leading_thoroughfare`) and `ADDRESS_OCR_REPAIRED` |
| Missing review gate | Revision 1 let the `low` confidence of the no-premise case force review, contradicting AUTO_FIX | Removed; review comes only from the table in §7 |
| Missing confirmation re-check | A confirmed value could be edited afterwards | Hash-bound confirmation, and the gate re-validates at push |
| Hard-coded limits | `master` has literals; the plan uses constraint IDs | Grep test; profile loader with no defaults |
| Undocumented Microsoft claims | Every MICROSOFT_BC_CONSTRAINT row cites C-LEN/C-ADR/C-MD/C-TYP with sources S02/S04/S28. Unknowns are marked TENANT | – |
| Tests weakened | None. Conflicting expectations are migrated with a reason given (§11.3) | – |
| One situation, two reason codes | Stage-11 address length was `FIELD_TOO_LONG` while extraction used `ADDRESS_OVERFLOW` (29-case audit, 2026-10-03) | Address lines use only `ADDRESS_BC_LENGTH_REBALANCE` / `ADDRESS_OVERFLOW`; `FIELD_TOO_LONG` is for single-value fields only |
| Review findings with no closure | The gate enforced confirmation only for the rebalance, so `FIELD_NOT_FOUND` / `LOW_CONFIDENCE` could be pushed unreviewed (audit) | §7 closure matrix (D6); gate enforcement pending |
| Comma-less geography silently AUTO_PASS | Case 28: City/State empty, `GUWAHATI ASSAM` left in Address 2, no finding (audit) | `GEOGRAPHY_UNRESOLVED` → MANUAL_REVIEW (D5) |
| OCR repair silent | De-glue / inferred boundaries were only a segmenter note (audit case 18) | `ADDRESS_OCR_REPAIRED` provenance entry, AUTO_FIX |

---

## 18. DEFERRED / FUTURE ADDRESS SEGMENTATION WORK

> **STATUS: NOT IMPLEMENTED. Paused on 2026-10-03 by decision of the project owner.**
> Nothing in this section exists in code. No production code, test expectation, dataset or reason code was added for it.
> When address segmentation work resumes ("continue the deferred address segmentation work"), start here:
> 1. Re-read this section.
> 2. Re-check §18.1 against the code, because the code may have moved on.
> 3. Settle the open decisions in §18.6.
> 4. Only then change code.

### 18.1 Implementation state at the time of the pause

| Item | State |
|---|---|
| Two-layer pipeline, backfill, BC rebalance, payload gate, lossless mapper (§§1–9) | Implemented |
| `ADDRESS_OCR_REPAIRED` (OCR de-glue / inferred comma-less boundaries, AUTO_FIX, logged) | Implemented (`address_representation._ocr_repair_transforms`) |
| `LOW_CONFIDENCE` (inferred boundaries + every fragment unknown, MANUAL_REVIEW) | Implemented |
| `GEOGRAPHY_UNRESOLVED` (D5: comma-less, line-break-free text whose City/State are missing, or whose last fragment still ends in a known state/city) | Implemented as **report-only** MANUAL_REVIEW. Text is never peeled or moved (`address_representation._geography_unresolved`) |
| 29-case audit suite | Implemented: `backend/app/eval/address_audit29_cases.yaml`, `backend/tests/test_address_audit29.py` |
| Universal MANUAL_REVIEW closure matrix (§7, D6) | **Policy documented; gate enforcement NOT implemented.** The gate enforces only `ADDRESS_BC_LENGTH_REBALANCE` and gate-computed findings |
| Strict comma-less `CITY → STATE → PIN` suffix extraction (this section) | **NOT implemented** |

**What a comma-less address does today** (BC layer on). This is measured behaviour, not design:

| Input | City / State / PIN today | Address 2 today | Finding |
|---|---|---|---|
| `2ND FLOOR SILICON PLAZA RING ROAD ZOO ROAD GUWAHATI ASSAM` (audit case 28) | "" / "" / "" | `SILICON PLAZA, RING ROAD, ZOO ROAD, GUWAHATI ASSAM` | `GEOGRAPHY_UNRESOLVED` |
| `… ZOO ROAD GUWAHATI ASSAM 781005` | Kamrup Metro / Assam / 781005 (**derived from the PIN**) | `…, GUWAHATI ASSAM` | `GEOGRAPHY_UNRESOLVED` |
| `SHOP 12 MAIN BAZAR NAGPUR MAHARASHTRA 440010` | Nagpur / Maharashtra / 440010 | `MAIN BAZAR, NAGPUR MAHARASHTRA` | `GEOGRAPHY_UNRESOLVED` |
| `IT PARK PHASE 8 MOHALI PUNJAB 160059` | S.A.S Nagar / Punjab / 160059 | `MOHALI PUNJAB` | `GEOGRAPHY_UNRESOLVED` |

So, today, a comma-less address that has a PIN gets a **partial, PIN-derived** extraction. `_strip_pin` removes the PIN from wherever it sits, the state comes from the PIN, and the city is the PIN's district. Meanwhile the written place names stay in the address lines. `GEOGRAPHY_UNRESOLVED` makes this visible, but does not fix it.

### 18.2 Problem statement

OCR'd and hand-typed vendor addresses often arrive as one line with no commas. The geography peel (`_drop_trailing_country`, `_strip_pin`, `_match_state`, `_pick_city`) matches **whole comma segments**, so it cannot separate a city and state glued onto the end of the address text. The result:
- the city and state stay inside Address 2;
- City and State are empty, or derived from the PIN instead of from the text.

A reviewer has to fix every such record by hand, even when the address ends in a perfectly clear `NAGPUR MAHARASHTRA 440010`.

**Proposed enhancement:** treat a missing comma inside an otherwise valid, PIN-verified `CITY → STATE → PIN` suffix as recoverable OCR damage. Extract that suffix, and only that suffix, when every strict check passes. Otherwise change nothing and leave the record for review.

### 18.3 Scope

| Applies | Does **not** apply (existing behaviour must stay unchanged) |
|---|---|
| Vendor address path (`resolve_address_blob(multiline=True)`) with the BC address layer on | Customer path (`multiline=False`); BC layer off (must stay byte-identical, §14 R1) |
| Source text, after trimming, is **exactly one line**, contains **no comma** and **no line break** | Any address containing a comma, which keeps the existing comma-based extraction |
| The text **ends** with the suffix `CITY STATE PIN` | Multi-line addresses (a line break counts as a separator today: `_segments`) |
| | City/state words appearing anywhere other than the validated suffix (e.g. `NAGPUR ROAD`, `DELHI GATE`) |
| | City/state with no PIN, or a PIN that does not validate against **both** |

### 18.4 Strict validation rules (all must hold)

1. **PIN.** The final whitespace-separated token is exactly 6 digits matching `[1-9]\d{5}`, and the PIN exists in `pin_directory.csv`.
2. **State.** A span of 1–8 tokens (8 = the longest state name) ending immediately before the PIN is recognised by `canonical_state` (canonical names and the existing aliases) **and** equals the PIN's state.
3. **City.** A span of 1–4 tokens ending immediately before the state span is recognised by `canonical_city` / `is_known_city`, **and** its canonical name equals the PIN's **district**. The comparison ignores case, spaces and punctuation, the same way the existing `_pick_city` normalises.
4. **Order.** Exactly `CITY → STATE → PIN`, contiguous, at the very end. Anything else is a failure: `STATE CITY PIN`, a PIN that is not last, or a trailing country token.
5. **Uniqueness.** Enumerate every (city span, state span) combination. **Exactly one** must pass rules 1–4. Zero or several means a failure, and the code must never guess (see §18.8).
6. **Something remains.** After the suffix is removed, the remainder is non-empty.

### 18.5 Behaviour

**On success** (every rule in §18.4 holds):
1. Set City, State and PIN from the suffix. The City value uses the same canonical / title-casing as `_pick_city`. Country = "India" (config default; `country_source` stays `default`).
2. Remove **only** the suffix. The remainder is `original[:suffix_start].rstrip()`, so its text is preserved exactly.
3. Pass the remainder through the **existing** segmentation (`segment_leftover`, including comma-less boundary injection) and the existing representation layer, unchanged. The segmenter, classifier, keywords and `_split_by_role` are not modified.
4. Do **not** run `_strip_pin` / `_match_state` / `_pick_city` on the remainder. Otherwise a number such as `PLOT 411026` could be taken as a second PIN, or a word in the remainder taken as a state.
5. Keep the existing `GEOGRAPHY_UNRESOLVED` post-check. If the remainder still ends in a known place name (e.g. `… BHOSARI PUNE PUNE MAHARASHTRA 411026` leaves `… BHOSARI PUNE`), the record still goes to review.
6. Log the extraction in provenance. Design proposal, not decided: see §18.6 item 6.

**On failure** (any rule in §18.4 fails):
1. Do **not** partially extract City, State or PIN.
2. Keep the original text exactly.
3. Raise `GEOGRAPHY_UNRESOLVED` → MANUAL_REVIEW. Its detail names the failed check: no PIN / PIN not in directory / no state before the PIN / state ≠ PIN state / city not found / city ≠ PIN district / wrong order / more than one valid reading / nothing left over.
4. The case then follows the existing review flow, with no guessing.

Failure point 1 deliberately changes today's comma-less-with-PIN behaviour (§18.1: PIN-derived city/state with the place names left in the text). This was the recommended option and is recorded here as decided. The reviewer re-enters the PIN, and the PIN text stays in the address lines until then.

### 18.6 Decisions

**Decided (2026-10-03):**
1. **Scope** as in §18.3: single-line, comma-less vendor addresses only. Comma-based and multi-line behaviour is unchanged.
2. **Strict validation** as in §18.4: PIN final and correctly formatted, state = PIN state, city = PIN district under the currently available data. No partial extraction.
3. **Failure behaviour** as in §18.5: nothing extracted, text unchanged, `GEOGRAPHY_UNRESOLVED`, existing review flow.
4. **Ambiguity:** never guess (§18.8).

**Open (settle before implementing):**
5. **City → district data (known data limitation; do not solve until resumed).** `pin_directory.csv` maps each of its 19,586 PINs to exactly one (district, state). Cross-district collisions were "kept first" by `app.cli.build_address_lookups`, so a rare border PIN can fail and go to review, which is the safe direction. `cities.txt` is a flat list of 769 names with only 2 aliases. It has **no** city → district or city → state mapping. A city therefore validates only when it *is* the PIN's district. Legitimate addresses that fail strict validation today:
   - **Mohali** → district **S.A.S Nagar** (PIN 160059)
   - **Guwahati** → district **Kamrup Metro** (PIN 781005)
   - **Navi Mumbai** → districts **Thane / Raigad**
   - and likewise Bengaluru/Bangalore → Bengaluru Urban, Noida → Gautam Buddha Nagar, Gurgaon → Gurugram, Secunderabad → Hyderabad.

   These relationships are currently only **comments** in `build_address_lookups._COMMON_CITY_ALIASES`, not data. **Future requirement:** an authoritative city → district/state mapping (e.g. a new `backend/data/address/city_districts.txt`, allowing several districts per city, or an equivalent authoritative dataset), used **only** by this validation. It must **not** be added as `cities.txt` aliases, because `canonical_city` would then rewrite the City value the comma-based path produces today (e.g. Guwahati → Kamrup Metro). Investigate the source and its authority when this work resumes.
6. **Reason code for a successful extraction (DESIGN PROPOSAL, not decided).** Reuse the existing `ADDRESS_OCR_REPAIRED` (AUTO_FIX, provenance only), with `transformation: comma_less_geography_suffix` and a detail holding the suffix and the PIN checks, rather than adding a new code. Rationale: a missing comma before a PIN-verified suffix is OCR damage of the same kind as the existing comma-less boundary inference.
7. **City = state union territories** written once (`SECTOR 17 CHANDIGARH 160017`). The proposal says strict: a failure. `… CHANDIGARH CHANDIGARH 160017` passes.
8. **Trailing country after the PIN** (`… 440010 INDIA`). The proposal says strict: a failure.
9. **PIN separators** (`MAHARASHTRA-440010`, `MAHARASHTRA440010`, `PIN 440010`). The proposal says strict: a failure.
10. **State abbreviations** (`MH`, `UP`, `WB`, `NEW DELHI` → Delhi). The proposal accepts them, because the PIN must still confirm the state **and** the district.
11. **Flag gating.** The proposal runs this only when `BC_ADDRESS_LAYER_ENABLED` is on, so the flag-off output stays byte-identical.

### 18.7 Proposed implementation boundary (for when work resumes)

- One new pure function, `_split_trailing_geography(text) -> (remainder, city, state, pin) | failure_reason`, in `address_resolver.py`. It uses only the existing lookups (`pin_state_district`, `canonical_state`, `canonical_city`, `is_known_city`).
- It is called at the start of `resolve_address_blob` only under the §18.3 scope. On success, the remainder replaces the segment list and the normal geography peel is skipped. On failure, Decision 3 applies.
- **Unchanged:** the comma-based peel, `address_segmenter.py`, `address_representation.py` (apart from logging, per Decision 6), the payload gate, `cities.txt`, `pin_directory.csv`, and the reason-code taxonomy (unless Decision 6 changes).
- **Expected test churn:** four existing tests in `tests/test_address_bc_layer.py` (`TestGeographyUnresolved` / `TestOcrRepairProvenance`) use comma-less inputs that have a PIN but no validated city: `… ZOO ROAD 781005`, `… GUWAHATI ASSAM 781005`, `PLOT 45 … CHANDIGARH 160002`. Their expectations would change on purpose (no PIN-derived geography; the Chandigarh case moves from a BC-07 BLOCK to MANUAL_REVIEW), and each change must carry its reason.

### 18.8 Ambiguity handling

If more than one (city, state) reading passes every check, or the suffix cannot be read without assuming something the text does not say, the implementation must **not** pick one. The record stays unresolved (`GEOGRAPHY_UNRESOLVED`, detail "more than one valid reading") and goes to review. A city name shared by two states (Aurangabad, Maharashtra 431001 vs Bihar 824101) is **not** ambiguous, because the PIN decides it.

### 18.9 Invariants

- **Exact preservation:** `original_address == remaining_address + separator + extracted_geography_suffix`. Here `separator` is the original whitespace run between them, i.e. the remainder is `original[:suffix_start].rstrip()` and the suffix is `original[suffix_start:]`. No other normalisation is applied.
- On failure, every geography field produced by this rule is empty, and the address text is the original text.
- Source order and content are preserved; nothing is invented, reordered or deleted beyond the validated suffix.
- Flag off, comma-based input and multi-line input behave byte-for-byte as before.
- The 29-case audit suite stays green. Case 28 (no PIN) stays `GEOGRAPHY_UNRESOLVED`.

### 18.10 Proposed test categories

All PINs below were checked against `pin_directory.csv` on 2026-10-03.

| Category | Example input | Expected |
|---|---|---|
| Valid | `SHOP 12 MAIN BAZAR NAGPUR MAHARASHTRA 440010` | Nagpur / Maharashtra / 440010; remainder `SHOP 12 MAIN BAZAR`; no finding |
| Valid, multi-word city | `F 12 CONNAUGHT PLACE NEW DELHI DELHI 110001` | New Delhi / Delhi |
| Valid, multi-word state | `PLOT 9 HOWRAH WEST BENGAL 711302` | Howrah / West Bengal |
| Valid, city = district | `UNIT 7 SECTOR 12 GURUGRAM HARYANA 122001` | Gurugram / Haryana |
| Valid, UT written twice | `SCO 284 SECTOR 17 CHANDIGARH CHANDIGARH 160017` | Chandigarh / Chandigarh |
| Valid, same city name in two states | `GALI 4 AURANGABAD MAHARASHTRA 431001` | Aurangabad / Maharashtra (PIN decides) |
| Valid, state abbreviation | `SHOP 3 MAIN ROAD NAGPUR MH 440010` | Nagpur / Maharashtra (if Decision 10 holds) |
| Valid, remainder still ends in a place name | `… BHOSARI PUNE PUNE MAHARASHTRA 411026` | extracted, **and** `GEOGRAPHY_UNRESOLVED` from the post-check |
| Invalid PIN | `… NAGPUR MAHARASHTRA 999999` | failure: PIN not in directory |
| Missing PIN | `… NAGPUR MAHARASHTRA`; audit case 28 | failure: no PIN |
| City/PIN mismatch | `… PUNE MAHARASHTRA 440010` | failure: city ≠ PIN district |
| State/PIN mismatch | `… NAGPUR GUJARAT 440010` | failure: state ≠ PIN state |
| Ambiguous-looking city, wrong state | `… AURANGABAD MAHARASHTRA 824101` | failure: PIN is Aurangabad, Bihar |
| Wrong order | `… MAHARASHTRA NAGPUR 440010`; `… NAGPUR 440010 MAHARASHTRA` | failure: order |
| No city | `… MAIN BAZAR MAHARASHTRA 440010` | failure: city not found |
| Data limitation (§18.6 item 5) | `… GUWAHATI ASSAM 781005`; `IT PARK PHASE 8 MOHALI PUNJAB 160059` | failure: city ≠ PIN district (until the mapping exists) |
| UT written once | `SECTOR 17 CHANDIGARH 160017` | failure (Decision 7) |
| Trailing country / glued PIN | `… 440010 INDIA`; `… MAHARASHTRA-440010` | failure (Decisions 8, 9) |
| Nothing left | `NAGPUR MAHARASHTRA 440010` | failure: nothing left over |
| Multiple valid readings | built with stubbed lookup tables | failure: more than one valid reading |
| Comma-based (out of scope) | `SHOP 12, MAIN BAZAR, NAGPUR, MAHARASHTRA 440010` | identical to today |
| Multi-line (out of scope) | `SHOP 12 MAIN BAZAR\nNAGPUR MAHARASHTRA 440010` | identical to today |
| City word inside the text | `NAGPUR ROAD WARDHAMAN NAGAR …` | no suffix extracted from the middle |
| Flag off | any valid input above | byte-identical to today |
| Property | every row | §18.9 invariants hold |

---

## Appendix A. Cross-document address comparison (phase P3, optional)

**Today:** addresses are not compared across documents. `state` uses `fuzz.ratio ≥ 85`.

**Why fuzzy scoring is wrong here:**
- **For identifiers.** A GSTIN with 2 different characters still scores 86.7, and a PAN with 1 different character scores 90.0. Both pass the 85 threshold (M3). Identifiers must match exactly (C-XD-01).
- **For whole addresses.** A fuzzy score cannot say *which* token differs: `PLOT 45` vs `PLOT 46` scores high. The `token_set` and `partial` scores rated shifted boundaries 1.000 (ASR §7, §11).

**Proposed comparison, component by component:**
- PIN: exact.
- State and city: canonical equality.
- Numeric tokens: an exact multiset match.
- Word overlap: informational only.

The GST address is authoritative (C-XD-02).
- A PIN/state disagreement → MANUAL_REVIEW (C-XD-07).
- Other differences → warning only (C-XD-06).

---

## Summary for management

We are adding Business Central's field-size rules as a separate step in the address pipeline instead of treating them as an afterthought, while keeping the part that decides what each piece of an address *means* exactly as it is.

- If the address fits BC's fields, nothing changes and nobody has to look at it.
- If Address 1 comes out empty, the first one or two parts fill it automatically. This is logged, with no review.
- If Address 2 is too long for BC, the split point between the two lines moves by whole address parts. Nothing is cut, reordered or rewritten. A reviewer confirms the before/after with one click.
- If it still cannot fit, the push is blocked until someone edits the address. Text is never silently cut off.

Every automatic change is recorded for audit. Limits come from one configuration file, the country is sent as a BC code, and existing tests are kept or migrated with stated reasons.

The work is behind feature flags, in five phases, at about 11–16 developer days. Before go-live we need four answers about our BC environment: the country code, the Post Code table contents, the exact BC build, and a rule for one over-long state name.
