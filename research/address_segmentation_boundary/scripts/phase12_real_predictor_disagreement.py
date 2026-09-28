"""Analyze address_split_manual_review.xlsx -- a genuine (prediction, ground
truth) pair on 5,000 rows of the 100k-row corpus (address_id 1..5000).

Unlike every negative example used elsewhere in this research (phase6's
191,602-row perturbation study), this file's `pred_address_1/pred_address_2/
predicted_split_index` are a REAL second opinion, disagreeing with this
corpus's own (already-known-flawed, see phase2/§4/§12) ground truth on
4,113 / 5,000 rows (82.3%). This is the first real predictor-disagreement
data available to this research -- it directly addresses the §18/§23.1
limitation that threshold calibration had only synthetic perturbations to
work with.

IMPORTANT CAVEAT, established before drawing conclusions: this predictor's
behaviour (see section 1 below) looks like a naive rule -- it only ever
predicts split_index 1 or 4 on 5-component rows, which is the naive
premise/admin boundary (Rule B, already REJECTED in phase2/§14 -- matches
GT only 22.7% of the time). This file is NOT evidence about what a real LLM
would do; it is evidence about how the EXISTING validation engine behaves
when fed a real, systematically-biased predictor's output. Both things are
reported, not conflated.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pandas as pd

sys.path.insert(0, r"C:\Users\shubh\Downloads\vendor-extractor\backend")

import metrics as M  # noqa: E402
from validation_engine import validate  # noqa: E402

DOWNLOADS = pathlib.Path(r"C:\Users\shubh\Downloads")
SRC = DOWNLOADS / "address_split_manual_review.xlsx"
OUT = pathlib.Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

df = pd.read_excel(SRC)
N = len(df)
print(f"Loaded {SRC.name}: {df.shape}")

# ---------------------------------------------------------------------------
# 1. Predictor behaviour: split_index distribution, relation to Rule B
# ---------------------------------------------------------------------------
print("\n=== 1. predicted_split_index vs gt_split_index distributions ===")
pred_dist = df["predicted_split_index"].value_counts(normalize=True).sort_index()
gt_dist = df["gt_split_index"].value_counts(normalize=True).sort_index()
print("predicted:\n", pred_dist)
print("ground truth:\n", gt_dist)

only_1_or_4 = df["predicted_split_index"].isin([1, 4]).mean()
print(f"\npredictor emits ONLY split_index in {{1,4}}: {only_1_or_4:.4%} of rows")

# Confirm split_match is exactly index equality (not a fuzzy criterion)
implied_match = df["predicted_split_index"] == df["gt_split_index"]
match_consistency = (implied_match == df["split_match"]).mean()
print(f"split_match == (predicted_split_index == gt_split_index) for {match_consistency:.4%} of rows")

n_match = int(df["split_match"].sum())
print(f"\nsplit_match: {n_match} / {N} ({n_match / N:.2%}) -- predictor agrees with this corpus's GT")

# ---------------------------------------------------------------------------
# 2. Metric behaviour on REAL disagreement vs the synthetic perturbation study
# ---------------------------------------------------------------------------
print("\n=== 2. token_sequence_ratio / char_sequence_ratio / boundary_token_distance on real pred-vs-gt ===")
df["token_sequence_ratio"] = df.apply(
    lambda r: M.token_sequence_ratio(r["pred_address_1"], r["gt_address_1"]), axis=1
)
df["char_sequence_ratio"] = df.apply(
    lambda r: M.char_sequence_ratio(r["pred_address_1"], r["gt_address_1"]), axis=1
)
df["boundary_token_distance"] = df.apply(
    lambda r: M.boundary_token_distance(r["address"], r["gt_address_1"], r["pred_address_1"]), axis=1
)

# Does the phase18-calibrated 0.96 threshold on token_sequence_ratio still
# separate "split_match True" from "split_match False" on this REAL data?
tsr_ge_096 = df["token_sequence_ratio"] >= 0.96
confusion = pd.crosstab(df["split_match"], tsr_ge_096, rownames=["split_match"], colnames=["tsr>=0.96"])
print("\nConfusion matrix: split_match (rows) vs token_sequence_ratio>=0.96 (cols)")
print(confusion)

tp = int(((df["split_match"]) & (tsr_ge_096)).sum())
fp = int(((~df["split_match"]) & (tsr_ge_096)).sum())
fn = int(((df["split_match"]) & (~tsr_ge_096)).sum())
tn = int(((~df["split_match"]) & (~tsr_ge_096)).sum())
precision = tp / (tp + fp) if (tp + fp) else float("nan")
recall = tp / (tp + fn) if (tp + fn) else float("nan")
f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else float("nan")
print(f"Treating split_match as label, tsr>=0.96 as prediction: precision={precision:.4f} recall={recall:.4f} f1={f1:.4f}")

print("\nMean scores by split_match:")
print(df.groupby("split_match")[["token_sequence_ratio", "char_sequence_ratio", "fuzzy_ratio"]].mean())

# Does fuzzy_ratio (already in the file) show the same "misleadingly high on
# disagreement" pattern phase6 found for fuzzy_partial/token_set?
print("\nfuzzy_ratio distribution when split_match=False (mismatches):")
print(df.loc[~df["split_match"], "fuzzy_ratio"].describe())
high_fuzzy_mismatch = ((~df["split_match"]) & (df["fuzzy_ratio"] >= 90)).sum()
print(f"Mismatched rows (split_match=False) with fuzzy_ratio>=90: {high_fuzzy_mismatch} "
      f"({high_fuzzy_mismatch / (~df['split_match']).sum():.2%} of mismatches)")

boundary_dist_defined = df["boundary_token_distance"].notna().mean()
print(f"\nboundary_token_distance defined (candidate is a clean prefix) for {boundary_dist_defined:.2%} of rows")
print("boundary_token_distance distribution (defined rows only):")
print(df["boundary_token_distance"].value_counts(dropna=True).sort_index())

# ---------------------------------------------------------------------------
# 3. Run the EXISTING validation engine: pred as candidate, gt as reference
# ---------------------------------------------------------------------------
print("\n=== 3. validation_engine.validate() -- pred_address_1/2 as candidate, gt_address_1 as reference ===")
verdicts = []
for _, r in df.iterrows():
    res = validate(
        full_address=r["address"],
        candidate_address_1=r["pred_address_1"],
        candidate_address_2=r["pred_address_2"],
        candidate_source="real_predictor_manual_review",
        reference_address_1=r["gt_address_1"],
    )
    verdicts.append({
        "address_id": r["address_id"],
        "split_match": r["split_match"],
        "verdict": res.verdict,
        "deciding_stage": res.deciding_stage,
        "hard_fail_reason": res.hard_fail_reason,
        "structural_plausibility": res.structural_plausibility,
        "review_reason": res.review_reason,
    })
vdf = pd.DataFrame(verdicts)

verdict_counts = vdf["verdict"].value_counts().to_dict()
print("Verdict counts:", verdict_counts)

print("\nVerdict breakdown by split_match (does the validator's verdict track real correctness?):")
cross = pd.crosstab(vdf["split_match"], vdf["verdict"])
print(cross)

# False-accept: validator says ACCEPT but split_match is False (predictor
# actually picked a different index than GT). False-reject/review: validator
# flags REVIEW/REJECT but split_match is True.
false_accept = int(((vdf["verdict"] == "ACCEPT") & (~vdf["split_match"])).sum())
false_flag = int(((vdf["verdict"] != "ACCEPT") & (vdf["split_match"])).sum())
n_mismatch = int((~vdf["split_match"]).sum())
n_match_rows = int(vdf["split_match"].sum())
print(f"\nFalse-accept rate (validator ACCEPTs a split_index disagreement): "
      f"{false_accept} / {n_mismatch} ({false_accept / n_mismatch:.2%} of mismatches)")
print(f"False-flag rate (validator REVIEW/REJECTs an index MATCH): "
      f"{false_flag} / {n_match_rows} ({false_flag / n_match_rows:.2%} of matches)")

print("\nHard-fail reasons (Stage 2):")
print(vdf["hard_fail_reason"].value_counts(dropna=True))
print("\nReview reasons (when verdict=REVIEW):")
print(vdf.loc[vdf["verdict"] == "REVIEW", "review_reason"].value_counts())

# ---------------------------------------------------------------------------
# Write report
# ---------------------------------------------------------------------------
report = {
    "n_rows": N,
    "predicted_split_index_distribution": pred_dist.to_dict(),
    "gt_split_index_distribution": gt_dist.to_dict(),
    "predictor_only_emits_1_or_4_pct": float(only_1_or_4),
    "split_match_consistency_with_index_equality": float(match_consistency),
    "split_match_rate": n_match / N,
    "tsr_0_96_threshold_confusion": {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
    },
    "mean_scores_by_split_match": df.groupby("split_match")[
        ["token_sequence_ratio", "char_sequence_ratio", "fuzzy_ratio"]
    ].mean().to_dict(),
    "high_fuzzy_ratio_on_mismatch_pct": float(high_fuzzy_mismatch / (~df["split_match"]).sum()),
    "boundary_token_distance_defined_pct": float(boundary_dist_defined),
    "boundary_token_distance_distribution": {
        str(k): int(v) for k, v in df["boundary_token_distance"].value_counts(dropna=True).sort_index().items()
    },
    "validation_engine_verdict_counts": verdict_counts,
    "validation_engine_false_accept_rate_on_mismatches": false_accept / n_mismatch,
    "validation_engine_false_flag_rate_on_matches": false_flag / n_match_rows,
    "validation_engine_hard_fail_reasons": vdf["hard_fail_reason"].value_counts(dropna=True).to_dict(),
}
with open(OUT / "phase12_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, default=str)
print("\nWrote", OUT / "phase12_report.json")

# Save flagged examples: rows where the predictor and GT disagree, for manual
# inspection (mirrors phase0/phase9's "examples" CSVs).
flagged = df.loc[~df["split_match"], [
    "address_id", "address", "gt_address_1", "pred_address_1", "gt_split_index",
    "predicted_split_index", "token_sequence_ratio", "fuzzy_ratio",
]].merge(vdf[["address_id", "verdict", "review_reason"]], on="address_id", how="left")
flagged.to_csv(OUT / "phase12_disagreement_examples.csv", index=False)
print("Wrote", OUT / "phase12_disagreement_examples.csv")

# ---------------------------------------------------------------------------
# Full-dataset validated export: every one of the 5,000 rows, with the
# validation engine's verdict attached, not just the disagreement subset
# above. This is the file to open in Excel to review/filter the FULL run.
# ---------------------------------------------------------------------------
full_export = df[[
    "address_id", "address", "gt_address_1", "gt_address_2", "gt_split_index",
    "pred_address_1", "pred_address_2", "predicted_split_index", "confidence",
    "split_match", "fuzzy_ratio", "token_sequence_ratio", "char_sequence_ratio",
    "boundary_token_distance",
]].merge(
    vdf[["address_id", "verdict", "deciding_stage", "hard_fail_reason",
         "structural_plausibility", "review_reason"]],
    on="address_id", how="left",
)
full_export = full_export.sort_values("address_id").reset_index(drop=True)
full_export.to_excel(OUT / "phase12_full_validation_result.xlsx", index=False, engine="openpyxl")
print("Wrote", OUT / "phase12_full_validation_result.xlsx",
      f"({len(full_export)} rows -- every row of address_split_manual_review.xlsx, "
      "with the validation engine's verdict per row)")
