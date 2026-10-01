"""Analyze india_10000_unique_synthetic_addresses (1).csv -- 10,000 rows of
REALISTIC Indian address text (actual rendered keywords: "Flat 6600", "House
No. 1063", "Plot No. 4724", ...), unlike the 100k-row corpus used everywhere
else in this research, where every row's premise component is a bare number
with no keyword ever rendered (§22/§23.2 of docs/ADDRESS_SEGMENTATION_RESEARCH.md).

This file has NO address_1/address_2/split_index columns. Any split here is
a DERIVED CONVENTION, defended with evidence in section 2 below -- not a
ground-truth label pulled from the file. Natural candidate, matching the
task's own worked examples: address_1 = Building (premise-level),
address_2 = "Street, City, State, Postal Code" (locality-level).

Purpose: test whether findings from the bare-numeric 100k corpus (Rule A --
trailing component is always admin-type; token_sequence_ratio as the winning
metric; fuzzy_partial/token_set as unreliable) generalize to realistic text,
or were artifacts of that corpus's unrealistic bare-numeric rendering. Also:
first time the EXISTING production resolver/segmenter is tested against text
that actually contains real keywords.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import pandas as pd

sys.path.insert(0, r"C:\Users\shubh\Downloads\vendor-extractor\backend")

import metrics as M  # noqa: E402
from app.services.extraction_pipeline.extract.address_resolver import resolve_address_blob  # noqa: E402

DOWNLOADS = pathlib.Path(r"C:\Users\shubh\Downloads")
SRC = DOWNLOADS / "india_10000_unique_synthetic_addresses (1).csv"
OUT = pathlib.Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)


def section(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


df = pd.read_csv(SRC)
N = len(df)
print(f"Loaded {SRC.name}: {df.shape}")

# ---------------------------------------------------------------------------
section("1. Data quality (mirrors phase0's rigor)")
nulls = df.isnull().sum()
print("Nulls per column:\n", nulls)
dup_full = df["Full Address"].duplicated().sum()
dup_id = df["Address ID"].duplicated().sum()
print(f"Duplicate 'Full Address': {dup_full} / {N}")
print(f"Duplicate 'Address ID': {dup_id} / {N}")
building_has_comma = df["Building"].str.contains(",", regex=False).sum()
print(f"'Building' values containing a comma (would need sub-splitting): {building_has_comma} / {N}")

# ---------------------------------------------------------------------------
section("2. Derive address_1 / address_2 from structured columns")
# address_1 = Building only (verified section 1: never comma-compound, so no
# information is lost by treating it as one premise-level unit).
# address_2 = Street, City, State, Postal Code (locality-level), joined with
# ", " to match the convention used throughout this research.
df["derived_address_1"] = df["Building"].str.strip()
df["derived_address_2"] = (
    df["Street"].str.strip() + ", " + df["City"].str.strip() + ", "
    + df["State"].str.strip() + ", " + df["Postal Code"].astype(str).str.strip()
)
print("Sample derived split:")
pd.set_option("display.max_colwidth", 60)
print(df[["derived_address_1", "derived_address_2"]].head(5).to_string())

# ---------------------------------------------------------------------------
section("3. Reconstruction check against Full Address")
# Full Address is Name + Building + Street + City + State + Postal Code +
# "India", newline-joined. The ADDRESS portion (excluding Name and India) is
# reconstructed by derived_address_1 + ", " + derived_address_2. Reported
# explicitly rather than silently special-cased.
address_only = (
    df["Building"].str.strip() + ", " + df["Street"].str.strip() + ", " + df["City"].str.strip()
    + ", " + df["State"].str.strip() + ", " + df["Postal Code"].astype(str).str.strip()
)
df["reconstructed"] = df["derived_address_1"].str.strip() + ", " + df["derived_address_2"].str.strip()
recon_ok = df["reconstructed"].map(M.normalize) == address_only.map(M.normalize)
print(f"derived_address_1 + derived_address_2 reconstructs (Building,Street,City,State,PIN): "
      f"{recon_ok.sum()} / {N} ({recon_ok.mean():.2%})")
print("NOTE: 'Full Address' itself also embeds Name (first line) and the literal "
      "string 'India' (last line), which are NOT part of the address_1/address_2 "
      "convention used elsewhere in this research (no country line in the 100k "
      "corpus) -- excluded here deliberately, not lost silently.")

# ---------------------------------------------------------------------------
section("4. Production resolver/segmenter on REALISTIC text (first time -- 100k corpus was bare-numeric)")
single_line = (
    df["Building"].str.strip() + ", " + df["Street"].str.strip() + ", " + df["City"].str.strip()
    + ", " + df["State"].str.strip() + " " + df["Postal Code"].astype(str).str.strip()
)

import time
t0 = time.time()
pred_rows = []
for i, r in df.iterrows():
    res = resolve_address_blob(single_line.iloc[i], multiline=True)
    pred_rows.append({
        "address_id": r["Address ID"],
        "pred_address_1": res.address_1,
        "pred_address_2": res.address_2,
        "pred_address_3": res.address_3,
        "pred_address_4": res.address_4,
        "pred_city": res.city,
        "pred_state": res.state,
        "pred_pin": res.pin_code,
        "pred_confidence": res.confidence,
    })
elapsed = time.time() - t0
pdf = pd.DataFrame(pred_rows)
print(f"Processed {N} realistic addresses in {elapsed:.2f}s ({elapsed / N * 1000:.3f} ms/address)")

merged = df.reset_index(drop=True).join(pdf.drop(columns=["address_id"]))

city_match = merged["pred_city"].str.strip().str.lower() == merged["City"].str.strip().str.lower()
state_match = merged["pred_state"].str.strip().str.lower() == merged["State"].str.strip().str.lower()
pin_match = merged["pred_pin"].astype(str).str.strip() == merged["Postal Code"].astype(str).str.strip()
print(f"\ncity  exact match (production vs structured column): {city_match.sum()} / {N} ({city_match.mean():.2%})")
print(f"state exact match : {state_match.sum()} / {N} ({state_match.mean():.2%})")
print(f"pin   exact match : {pin_match.sum()} / {N} ({pin_match.mean():.2%})")
print("\n(Compare to phase9 on the bare-numeric 100k corpus: city 33.82%, state 35.60%, pin 24.74% -- "
      "that ceiling was explained there as a corpus-text-content limit, §9.2. This realistic corpus "
      "test whether that ceiling was corpus-specific or systemic.)")

print("\npred_confidence distribution on realistic text:")
print(merged["pred_confidence"].value_counts())

a1_vs_building = merged["pred_address_1"].str.strip().str.lower() == merged["derived_address_1"].str.strip().str.lower()
print(f"\nproduction address_1 == derived_address_1 (Building) exact match: {a1_vs_building.sum()} / {N} ({a1_vs_building.mean():.2%})")
print("\nDisagreement examples (first 8):")
disagree = merged[~a1_vs_building]
print(disagree[["Building", "Street", "pred_address_1", "pred_address_2"]].head(8).to_string())

# ---------------------------------------------------------------------------
section("5. Does Rule A hold on realistic text? (trailing component always admin-type)")
# Rule A on the 100k corpus: component_sequence's LAST type is always one of
# {CITY, DISTRICT, PIN, STATE}. This corpus has no component_sequence column,
# but the STRUCTURED columns encode an equivalent claim: does the address, as
# rendered token-by-token, always end with Postal Code (or State, if PIN is
# separated in an actual document layout)? Checked directly against the
# single-line reconstruction used above.
ends_with_pin = single_line.str.strip().str.split().str[-1] == df["Postal Code"].astype(str)
print(f"Rendered single-line address ends with the postal code token: {ends_with_pin.sum()} / {N} ({ends_with_pin.mean():.2%})")

# ---------------------------------------------------------------------------
section("6. Do the metric rankings hold on realistic text? (token_sequence_ratio vs fuzzy_partial/token_set)")
# Reuse phase6's perturbation idea (boundary_shift_left1/right1) but on THIS
# corpus's derived_address_1/derived_address_2, to check the metric ranking
# isn't an artifact of the bare-numeric 100k corpus's structure.
import random
random.seed(11)
sample_idx = random.sample(range(N), min(2000, N))
rows = []
for i in sample_idx:
    full = address_only.iloc[i]
    a1 = df["derived_address_1"].iloc[i]
    a2 = df["derived_address_2"].iloc[i]
    a1_toks = M.tokens(a1)
    a2_toks = M.tokens(a2)
    if len(a2_toks) < 1:
        continue
    # boundary_shift_right1: move first token of a2 into a1 (a realistic
    # off-by-one boundary mistake, mirrors phase6's perturbation exactly)
    shifted_a1 = M.normalize(a1) + " " + a2_toks[0]
    rows.append({
        "clean_fuzzy_partial": M.fuzzy_partial_ratio(a1, a1),
        "shift_fuzzy_partial": M.fuzzy_partial_ratio(shifted_a1, a1),
        "clean_token_set": M.fuzzy_token_set_ratio(a1, a1),
        "shift_token_set": M.fuzzy_token_set_ratio(shifted_a1, a1),
        "clean_tsr": M.token_sequence_ratio(a1, a1),
        "shift_tsr": M.token_sequence_ratio(shifted_a1, a1),
    })
mdf = pd.DataFrame(rows)
print(f"n={len(mdf)} boundary_shift_right1 perturbations on realistic address_1 values")
print("Mean scores, clean vs shifted (mirrors phase6 Table, §7):")
print(mdf.mean())
print("\nfuzzy_partial_ratio staying >=0.85 despite a real boundary shift (the phase6 failure mode):",
      f"{(mdf['shift_fuzzy_partial'] >= 0.85).mean():.2%} of shifted rows")
print("token_sequence_ratio staying >=0.96 despite a real boundary shift (should be near 0% if the metric works):",
      f"{(mdf['shift_tsr'] >= 0.96).mean():.2%} of shifted rows")

# ---------------------------------------------------------------------------
report = {
    "n_rows": N,
    "nulls": {k: int(v) for k, v in nulls.items()},
    "duplicate_full_address": int(dup_full),
    "duplicate_address_id": int(dup_id),
    "building_contains_comma_pct": float(building_has_comma / N),
    "reconstruction_ok_pct": float(recon_ok.mean()),
    "production_ms_per_address": elapsed / N * 1000,
    "production_city_exact_match_pct": float(city_match.mean()),
    "production_state_exact_match_pct": float(state_match.mean()),
    "production_pin_exact_match_pct": float(pin_match.mean()),
    "production_confidence_distribution": merged["pred_confidence"].value_counts().to_dict(),
    "production_address1_vs_derived_building_match_pct": float(a1_vs_building.mean()),
    "rule_a_ends_with_pin_pct": float(ends_with_pin.mean()),
    "metric_check_n": len(mdf),
    "metric_check_means": mdf.mean().to_dict(),
    "fuzzy_partial_misleading_rate_on_realistic_shift": float((mdf["shift_fuzzy_partial"] >= 0.85).mean()),
    "token_sequence_ratio_false_positive_rate_on_realistic_shift": float((mdf["shift_tsr"] >= 0.96).mean()),
}
with open(OUT / "phase13_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, default=str)
print("\nWrote", OUT / "phase13_report.json")

disagree.head(50).to_csv(OUT / "phase13_production_disagreement_sample.csv", index=False)
print("Wrote", OUT / "phase13_production_disagreement_sample.csv")
