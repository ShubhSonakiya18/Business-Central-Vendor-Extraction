"""PHASE 3 + 6 + 7 + 11 (combined, evidence-based).

The provided files contain NO (LLM output, ground truth) pairs -- see
phase0/phase2 findings (both files are the same generator's own output; there
is only ever ONE address_1/address_2 per row). To test metric behaviour under
KNOWN, CATEGORIZED error types (as Phase 11 explicitly sanctions when real
negative data doesn't exist), this script takes the dataset's own
address_1/address_2 as a base and applies CONTROLLED, LABELED perturbations:

  clean                 -- unperturbed (address_1, address_2) pair
  boundary_shift_left1   -- move 1 token from address_1 to address_2
  boundary_shift_left2   -- move 2 tokens
  boundary_shift_right1  -- move 1 token from address_2 to address_1
  boundary_shift_right2  -- move 2 tokens
  token_drop             -- delete one token from address_2 entirely (content loss)
  token_duplicate        -- duplicate one token within address_1
  token_reorder          -- swap two adjacent tokens within address_2
  whitespace_punct       -- pure formatting noise (extra spaces, comma style),
                            no content change -- should score ~perfect on
                            every metric that claims to be format-tolerant
  case_change            -- uppercase/lowercase change only

For every (row, perturbation_type) we compute every metric in metrics.py on
BOTH address_1 and address_2 vs the clean ground truth, plus boundary_token_
distance and reconstruction_ok. We then ask, with real numbers:
  - does each metric actually DROP when the boundary moves?
  - does each metric stay near-perfect on pure formatting noise?
  - can a metric distinguish "boundary shift" from "token drop" from
    "duplicate"? (these are very different failure severities)
  - what threshold on each metric would separate "boundary unchanged"
    (clean + whitespace_punct + case_change) from "boundary changed"
    (all shift/drop/duplicate/reorder types), with real precision/recall?
"""
from __future__ import annotations

import json
import pathlib
import random

import pandas as pd
from load_data import load_partition

import metrics as M

random.seed(13)

OUT = pathlib.Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

part = load_partition()
N = 20000
sample = part.sample(n=N, random_state=13).reset_index(drop=True)


def word_tokens(s: str) -> list[str]:
    """Whitespace-level tokens (keeps commas attached), for perturbation --
    distinct from metrics.tokens() which is alnum-only for scoring."""
    return M.normalize(s).split(" ")


def perturb(a1: str, a2: str) -> dict[str, tuple[str, str]]:
    a1w, a2w = word_tokens(a1), word_tokens(a2)
    out = {"clean": (a1, a2)}

    # boundary shifts: move token(s) across the boundary
    if len(a1w) >= 1:
        out["boundary_shift_left1"] = (" ".join(a1w[:-1]), " ".join(a1w[-1:] + a2w))
    if len(a1w) >= 2:
        out["boundary_shift_left2"] = (" ".join(a1w[:-2]), " ".join(a1w[-2:] + a2w))
    if len(a2w) >= 1:
        out["boundary_shift_right1"] = (" ".join(a1w + a2w[:1]), " ".join(a2w[1:]))
    if len(a2w) >= 2:
        out["boundary_shift_right2"] = (" ".join(a1w + a2w[:2]), " ".join(a2w[2:]))

    # token drop -- delete one token from address_2 (content LOSS, not a boundary move)
    if len(a2w) >= 2:
        idx = random.randrange(len(a2w))
        dropped = a2w[:idx] + a2w[idx + 1:]
        out["token_drop"] = (a1, " ".join(dropped))

    # duplicate a token within address_1
    if len(a1w) >= 1:
        idx = random.randrange(len(a1w))
        dup = a1w[: idx + 1] + [a1w[idx]] + a1w[idx + 1:]
        out["token_duplicate"] = (" ".join(dup), a2)

    # reorder -- swap two adjacent tokens within address_2
    if len(a2w) >= 2:
        idx = random.randrange(len(a2w) - 1)
        reordered = a2w[:]
        reordered[idx], reordered[idx + 1] = reordered[idx + 1], reordered[idx]
        out["token_reorder"] = (a1, " ".join(reordered))

    # pure formatting noise -- no content change
    out["whitespace_punct"] = (a1.replace(",", " ,").replace("  ", " ") + "  ", " " + a2)
    out["case_change"] = (a1.upper(), a2.lower())

    return out


rows = []
for _, r in sample.iterrows():
    full = r["address"]
    gt_a1, gt_a2 = r["address_1"], r["address_2"]
    variants = perturb(gt_a1, gt_a2)
    for ptype, (cand_a1, cand_a2) in variants.items():
        bdist = M.boundary_token_distance(full, gt_a1, cand_a1)
        recon = M.reconstruction_ok(full, cand_a1, cand_a2)
        row = {
            "address_id": r["address_id"],
            "perturbation": ptype,
            "boundary_token_distance": bdist,
            "reconstruction_ok": recon,
        }
        for mname, mfn in M.ALL_METRICS.items():
            row[f"a1_{mname}"] = mfn(gt_a1, cand_a1)
            row[f"a2_{mname}"] = mfn(gt_a2, cand_a2)
        rows.append(row)

df = pd.DataFrame(rows)
df.to_csv(OUT / "phase6_perturbation_scores.csv", index=False)
print(f"Scored {len(df)} (row x perturbation) combinations across {N} base addresses.")

# ---------------------------------------------------------------------------
print("\n" + "=" * 90)
print("MEAN METRIC SCORE BY PERTURBATION TYPE (address_1 side)")
print("=" * 90)
metric_cols_a1 = [c for c in df.columns if c.startswith("a1_")]
summary_a1 = df.groupby("perturbation")[metric_cols_a1].mean()
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
pd.set_option("display.float_format", lambda x: f"{x:.3f}")
print(summary_a1.to_string())
summary_a1.to_csv(OUT / "phase6_mean_scores_by_perturbation_address1.csv")

print("\n" + "=" * 90)
print("MEAN METRIC SCORE BY PERTURBATION TYPE (address_2 side)")
print("=" * 90)
metric_cols_a2 = [c for c in df.columns if c.startswith("a2_")]
summary_a2 = df.groupby("perturbation")[metric_cols_a2].mean()
print(summary_a2.to_string())
summary_a2.to_csv(OUT / "phase6_mean_scores_by_perturbation_address2.csv")

print("\n" + "=" * 90)
print("boundary_token_distance BY PERTURBATION TYPE")
print("=" * 90)
print(df.groupby("perturbation")["boundary_token_distance"].describe())

print("\n" + "=" * 90)
print("reconstruction_ok BY PERTURBATION TYPE")
print("=" * 90)
print(df.groupby("perturbation")["reconstruction_ok"].mean())

# ---------------------------------------------------------------------------
print("\n" + "=" * 90)
print("THE KEY FAILURE-MODE TEST: does a HIGH similarity score coexist with a")
print("MOVED boundary? (boundary_token_distance >= 1, i.e. genuinely wrong split)")
print("=" * 90)
moved = df[df["boundary_token_distance"].fillna(0) >= 1]
unmoved = df[df["boundary_token_distance"].fillna(0) == 0]
print(f"\n'Moved boundary' rows: {len(moved)}   'Unmoved boundary' rows: {len(unmoved)}")

for mname in M.ALL_METRICS:
    col = f"a1_{mname}"
    thresholds_to_check = [0.80, 0.85, 0.90, 0.95]
    print(f"\n--- {mname} (address_1 side) ---")
    print(f"  mean score | moved boundary:   {moved[col].mean():.3f}")
    print(f"  mean score | unmoved boundary: {unmoved[col].mean():.3f}")
    for th in thresholds_to_check:
        false_accept = (moved[col] >= th).mean()  # a WRONG boundary that still scores >= threshold
        print(f"  at threshold >= {th}: {false_accept:.2%} of MOVED-boundary cases would be WRONGLY ACCEPTED "
              f"(false positive rate for 'boundary is fine')")

# ---------------------------------------------------------------------------
print("\n" + "=" * 90)
print("THRESHOLD CALIBRATION: precision/recall/F1 for detecting 'boundary changed'")
print("(label = boundary_token_distance >= 1, i.e. a REAL known-by-construction shift)")
print("=" * 90)


def prf(y_true_changed: pd.Series, score: pd.Series, threshold: float, lower_is_flag: bool = True):
    """Predict 'changed' when score < threshold (since a similarity metric
    should be LOW when the boundary changed)."""
    pred_changed = score < threshold
    tp = int((pred_changed & y_true_changed).sum())
    fp = int((pred_changed & ~y_true_changed).sum())
    fn = int((~pred_changed & y_true_changed).sum())
    tn = int((~pred_changed & ~y_true_changed).sum())
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = 2 * precision * recall / (precision + recall) if (precision and recall) else float("nan")
    return {"threshold": threshold, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": f1}


calib_rows = []
label = (df["boundary_token_distance"].fillna(999) >= 1)  # 999 = boundary wasn't even a clean prefix -> definitely "changed"
for mname in M.ALL_METRICS:
    col = f"a1_{mname}"
    best = None
    for th in [round(x * 0.01, 2) for x in range(50, 100)]:
        r = prf(label, df[col], th)
        r["metric"] = mname
        calib_rows.append(r)
        if r["f1"] == r["f1"] and (best is None or r["f1"] > best["f1"]):
            best = r
    if best:
        print(f"{mname:26} BEST threshold={best['threshold']:.2f}  "
              f"precision={best['precision']:.3f}  recall={best['recall']:.3f}  f1={best['f1']:.3f}")

calib_df = pd.DataFrame(calib_rows)
calib_df.to_csv(OUT / "phase11_threshold_calibration_full.csv", index=False)

best_per_metric = calib_df.loc[calib_df.groupby("metric")["f1"].idxmax()]
best_per_metric.to_csv(OUT / "phase11_best_threshold_per_metric.csv", index=False)
print("\nWrote", OUT / "phase11_best_threshold_per_metric.csv")

report = {
    "n_base_addresses": N,
    "n_perturbation_rows": len(df),
    "mean_scores_address1_by_perturbation": summary_a1.to_dict(orient="index"),
    "best_threshold_per_metric": best_per_metric.set_index("metric")[["threshold", "precision", "recall", "f1"]].to_dict(orient="index"),
}
with open(OUT / "phase6_11_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, default=str)
print("Wrote", OUT / "phase6_11_report.json")
