"""Run the EXISTING production system (address_resolver.resolve_address_blob,
already built and tested in this repo -- keyword/tier-driven, deterministic,
no LLM) against this dataset's `address` column, and compare its output to
the dataset's ground truth on two SEPARATE axes:

  (a) city / state / pin_code extraction -- these ARE independently labeled
      in this dataset (city, state, postal_code columns) and ARE a fair,
      like-for-like test of the existing pipeline.
  (b) the address_1/address_2 TWO-WAY split -- NOT fully like-for-like (see
      note below), reported with that caveat front and center.

IMPORTANT ASYMMETRY, established BEFORE running this: resolve_address_blob
extracts city/state/pin_code into their OWN fields and does NOT include them
in address_1..address_4 -- which is the correct behaviour for a system
feeding typed Business Central fields. This dataset's ground-truth address_2
DELIBERATELY leaves city/state/pin embedded in the address_2 STRING (it is a
generic 2-way string partition, not a fielded extraction). So a raw
"production address_1 == GT address_1" comparison is expected to disagree
often for a structural reason that has nothing to do with either system being
"wrong" -- this script reports it anyway, decomposed, so the disagreement is
attributable rather than a single misleading number.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import pandas as pd

sys.path.insert(0, r"C:\Users\shubh\Downloads\vendor-extractor\backend")
from app.services.extraction_pipeline.extract.address_resolver import resolve_address_blob  # noqa: E402

from load_data import load_partition  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

part = load_partition()

N = 10000
sample = part.sample(n=N, random_state=7).reset_index(drop=True)

rows = []
t0 = time.time()
for i, r in sample.iterrows():
    res = resolve_address_blob(r["address"], multiline=True)
    rows.append({
        "address_id": r["address_id"],
        "gt_address_1": r["address_1"],
        "gt_address_2": r["address_2"],
        "gt_city": r["city"],
        "gt_state": r["state"],
        "gt_pin": str(r["postal_code"]),
        "pred_address_1": res.address_1,
        "pred_address_2": res.address_2,
        "pred_address_3": res.address_3,
        "pred_address_4": res.address_4,
        "pred_city": res.city,
        "pred_state": res.state,
        "pred_pin": res.pin_code,
        "pred_confidence": res.confidence,
        "pred_n_lines": sum(1 for x in (res.address_1, res.address_2, res.address_3, res.address_4) if x),
    })
elapsed = time.time() - t0
print(f"Processed {N} addresses through production resolve_address_blob in {elapsed:.2f}s "
      f"({elapsed/N*1000:.3f} ms/address)")

df = pd.DataFrame(rows)

print("\n=== (a) city / state / pin_code extraction accuracy (fair, fielded comparison) ===")
city_match = (df["pred_city"].str.strip().str.lower() == df["gt_city"].str.strip().str.lower())
state_match = (df["pred_state"].str.strip().str.lower() == df["gt_state"].str.strip().str.lower())
pin_match = (df["pred_pin"].str.strip() == df["gt_pin"].str.strip())
print(f"city  exact match : {city_match.sum()} / {N} ({city_match.mean():.2%})")
print(f"state exact match : {state_match.sum()} / {N} ({state_match.mean():.2%})")
print(f"pin   exact match : {pin_match.sum()} / {N} ({pin_match.mean():.2%})")

print("\ncity mismatch examples (production vs ground truth):")
print(df[~city_match][["gt_address_1", "gt_address_2", "gt_city", "pred_city", "pred_confidence"]].head(10).to_string())

print("\n=== (b) how many address LINES did production emit? ===")
print(df["pred_n_lines"].value_counts().sort_index())

print("\n=== (b) confidence distribution ===")
print(df["pred_confidence"].value_counts())

print("\n=== (b) naive address_1-vs-address_1 exact match (KNOWN to be an unfair comparison -- see module docstring) ===")
a1_exact = (df["pred_address_1"].str.strip().str.lower() == df["gt_address_1"].str.strip().str.lower())
print(f"{a1_exact.sum()} / {N} ({a1_exact.mean():.2%})")

print("\nExamples where they DISAGREE on address_1 (first 10):")
disagree = df[~a1_exact]
print(disagree[["gt_address_1", "gt_address_2", "pred_address_1", "pred_address_2", "pred_address_3", "pred_address_4"]].head(10).to_string())

df.to_csv(OUT / "phase9_production_vs_groundtruth_sample.csv", index=False)

report = {
    "n_sample": N,
    "ms_per_address": elapsed / N * 1000,
    "city_exact_match_pct": float(city_match.mean()),
    "state_exact_match_pct": float(state_match.mean()),
    "pin_exact_match_pct": float(pin_match.mean()),
    "pred_n_lines_distribution": df["pred_n_lines"].value_counts().sort_index().to_dict(),
    "pred_confidence_distribution": df["pred_confidence"].value_counts().to_dict(),
    "naive_address1_exact_match_pct": float(a1_exact.mean()),
}
with open(OUT / "phase9_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, default=str)
print("\nWrote", OUT / "phase9_report.json")
print("Wrote", OUT / "phase9_production_vs_groundtruth_sample.csv")
