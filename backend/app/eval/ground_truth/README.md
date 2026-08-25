# Ground truth datasets

A ground truth file records **what a human read off the source documents**, so
extraction accuracy can be measured against reality rather than against the
extractor's own output.

## Why this exists

The verification report produced during a normal run (`verifier.py` /
`vendor_v1_verify.py`) reopens the saved Excel and compares each cell against
the extracted JSON. That proves the *write* round-tripped correctly. It cannot
prove the extraction was *right* — both sides of that comparison come from the
same extraction call, so a misread GSTIN sails through as a confident PASS.

Ground truth is the missing independent reference.

## Hard rule: never generate ground truth from the pipeline

If you populate these files by running the extractor and saving its output, the
evaluation becomes circular and will report ~100% accuracy no matter how wrong
the extractor is. Every value must be read off the document by a person.

The OCR dump is a legitimate *aid* for this — `python -m
app.pipelines.v2.dump_ocr <docs> --out outputs/inspect` shows the text on each
page, which is faster to scan than opening the PDFs — but a human still has to
decide what the correct value is, especially when documents disagree (see
`conflicts` below).

## PII warning

Real vendor documents contain real GSTINs, PANs and bank account numbers.
`ground_truth/*.yaml` is gitignored for that reason; only
`example_synthetic.yaml` (fabricated values) is committed. Keep real ground
truth local, or store it wherever your organisation keeps vendor PII — not in
the repo.

## Creating one

1. Dump the document text:
   ```bash
   python -m app.pipelines.v2.dump_ocr path/to/vendor/docs --out outputs/inspect
   ```
2. Copy `example_synthetic.yaml` to `<vendor_slug>.yaml`.
3. Fill in every field by reading the documents. For each field set:
   - `value`   — exactly as printed (or the business-correct value; see below)
   - `source`  — which document you read it from
   - `absent: true` instead of a value when the field is **not printed on any
     supplied document**. This is not the same as "the extractor missed it" —
     `absent` means a correct extractor should return null, and producing a
     value is a hallucination.
4. Set `verified: true` at the top only once you have checked every field.
   The harness refuses to score an unverified file without `--allow-unverified`.

## Fields where documents disagree

Real vendor packets contradict themselves. The sample set in this repo has a
vendor whose Udyam registration lists one bank and whose cancelled cheque shows
another. Ground truth has to take a position, and the position is a *business*
decision, not a transcription one — record it under `conflicts` with the
reasoning so the next person doesn't silently reverse it.

For bank details the cancelled cheque wins: it is the account the vendor is
asking to be paid into, and the cheque is the proof-of-ownership artefact the
form is collecting. A Udyam certificate's bank block can be years stale.

## Scoring outcomes

| Outcome | Meaning |
|---|---|
| `correct` | Extracted value matches ground truth |
| `wrong` | Ground truth has a value, extractor produced a *different* one |
| `missed` | Ground truth has a value, extractor produced nothing |
| `hallucinated` | Ground truth says `absent`, extractor produced a value |
| `correctly_absent` | Ground truth says `absent`, extractor produced nothing |

`wrong` and `hallucinated` are the dangerous ones: they put a confident,
well-formed, incorrect value onto a form a human is likely to sign off.
