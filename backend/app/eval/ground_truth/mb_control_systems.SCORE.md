# Ground-truth score record — mb_control_systems

`mb_control_systems.yaml` is git-ignored (contains real GSTIN, PAN, phone,
email, bank account number, and address for a real vendor — see
`.gitignore`). That correctly keeps PII out of history, but it also means a
reviewer with only this repo checked out cannot verify any accuracy claim
made about it. This file is the redacted record: field-level PASS/WRONG
status and the run command, with no field values.

## Verification method

Both engines were first run against the ground-truth candidate with
`--allow-unverified`. Every field where PaddleOCR and RapidOCR agreed with
each other but disagreed with the candidate (`nature_of_business`,
`branch_address`, `website`) was checked by a human against the source PDFs
and the candidate corrected. Fields where the candidate and both engines
already agreed were treated as verified by that unanimous agreement rather
than re-checked individually. `verified: true`, `verified_by`,
`verified_on: 2026-09-01` are set in the (untracked) ground-truth file.

## Score, both engines, identical (2026-09-01)

Run with `OCR_BACKEND=rapidocr` then `OCR_BACKEND=paddleocr`:

```
python -m app.eval.eval_extraction \
  --ground-truth app/eval/ground_truth/mb_control_systems.yaml \
  --documents app/uploads/09e0ff7aca
```

| correct | wrong | missed | hallucinated | correctly absent | recall | precision | accuracy |
|---|---|---|---|---|---|---|---|
| 19 | 1 | 0 | 0 | 4 | 95.0% | 95.0% | 95.8% |

**Identical result for both `rapidocr` and `paddleocr`** — this is the evidence
cited in `ocr_engine.py`'s `OCR_BACKEND` comment for switching the default:
RapidOCR is not worse than PaddleOCR on this vendor's documents, not that
either is fully correct.

## Per-field result (24 fields, no values shown)

| Field | Result | Notes |
|---|---|---|
| vendor_name | CORRECT | |
| company_type | CORRECT | |
| nature_of_business | **WRONG** (both engines) | See "Known open bug" below |
| gst_number | CORRECT | native PDF text layer |
| pan | CORRECT | |
| udyam_number | CORRECT | |
| tan | correctly absent | not printed on any document |
| esic_number | correctly absent | not printed on any document |
| address_1 | CORRECT | |
| address_2 | CORRECT | |
| address_3 | correctly absent | |
| address_4 | correctly absent | |
| city | CORRECT | |
| state | CORRECT | |
| country | CORRECT | inferred, config default |
| pin_code | CORRECT | |
| telephone | CORRECT | |
| email | CORRECT | |
| website | CORRECT | see conflict note below |
| bank_name | CORRECT | see conflict note below |
| branch_address | CORRECT | |
| ifsc | CORRECT | |
| account_number | CORRECT | |
| account_type | CORRECT | |

## Known open bug: `nature_of_business`

Root-caused 2026-09-01. The source document prints the field's value in full
on page 1, but that occurrence sits just past the field matcher's default
spatial search radius (`max_distance: 12.0`, in label-height units) from its
label, so it was invisible to matching entirely. A second, genuine
occurrence of the same field exists on page 3, much closer to its own
label, whose OCR read is truncated. Both engines independently pick the
closer-but-truncated page-3 match.

**Fix applied** (`field_dictionary.yaml`): widened `nature_of_business`'s
`search.max_distance` to 14.0, which makes the correct page-1 candidate
visible in the field's `alternatives` for manual review.

**Deliberately not fixed further**: the wrong match still wins on score,
because it is legitimately closer to its label — forcing the farther,
correct one to win would mean loosening or special-casing the general
"closer wins" tie-break every other field and vendor relies on. See
`plan.md`'s 2026-09-01 entry for the full writeup and the options considered.

## Documented conflicts in the ground truth (not bugs, business calls)

- **bank_name / ifsc / account_number**: the Udyam certificate and the
  cancelled cheque list different bank accounts for this vendor. Ground
  truth takes the cheque's account, on the basis that a vendor-creation form
  is collecting the account to pay into and the cheque is the
  proof-of-ownership artefact; a Udyam bank block can be years out of date.
  Confirm this matches your process before trusting this field's score for
  a different use case.
- **vendor_name**: three spellings appear across the three documents; ground
  truth uses the GST certificate's Legal Name as the statutory source of
  record.
