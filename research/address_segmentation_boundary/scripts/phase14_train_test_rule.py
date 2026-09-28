"""Learn an explainable, rule-based address-split heuristic from a TRAINING
portion of indian_address_partition_dataset_100000 (address + address_1 +
address_2 + split_index), then apply it to the CORRESPONDING held-out
addresses as supplied by indian_unique_address_patterns_100000 (address-only
-- no split columns), and validate the predictions against the partition
file's split_index for those same held-out rows.

This directly implements the user's requested framing:
  - indian_unique_address_patterns_100000  = the address-ONLY input side
  - indian_address_partition_dataset_100000 = the supervised (address, split)
    signal used to LEARN the rule

IMPORTANT, established earlier in this research and re-confirmed here: the
`address` and `component_sequence` columns are BYTE-IDENTICAL between the two
files for all 100,000 matching address_id (phase0/phase2). So reading the
held-out addresses from the patterns file rather than the partition file
changes nothing about WHAT text is read -- what makes this a fair,
non-circular exercise is the TRAIN/TEST SPLIT of address_id itself: the rule
is derived using ONLY training-row address_1/address_2/split_index, and is
then scored ONLY against held-out rows it never saw labels for. The held-out
rows' address_1/address_2/split_index are read from the partition file
exactly once, at the very end, purely to SCORE the rule's predictions -- the
rule-derivation code path never touches them.

Rule form (explainable, not ML, per explicit user request):
  1. Rule A (already established, re-confirmed on the TRAINING split only):
     the last component of component_sequence is always ADMIN-type
     (STATE/CITY/DISTRICT/PIN) -- used as the universal fallback.
  2. A majority-vote lookup table, keyed by component_sequence (the exact
     structural "shape" of the address, e.g. "FLAT|HOUSE|FLAT|HOUSE|STATE"),
     mapping shape -> the most common split_index for that shape IN THE
     TRAINING SPLIT ONLY. A shape only gets a trusted (non-fallback) entry if
     it appears at least MIN_SUPPORT times in training.
  3. For a held-out address whose shape was seen with sufficient support in
     training, predict the majority split_index for that shape. For a shape
     that's absent, or seen too rarely to trust, fall back to Rule A alone:
     cut immediately before the trailing admin-type run (split_index =
     component_count - 1) -- the one fully evidenced structural rule.
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Users\shubh\Downloads\vendor-extractor\backend")

import metrics as M  # noqa: E402
from load_data import load_partition, load_patterns  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

RANDOM_STATE = 42
TEST_FRACTION = 0.20
MIN_SUPPORT = 5  # minimum training occurrences of a shape to trust its majority vote

ADMIN_TYPES = {"STATE", "CITY", "DISTRICT", "PIN"}


def section(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


partition = load_partition()
patterns = load_patterns()

# ---------------------------------------------------------------------------
section("0. Leakage check -- is a plain random row-level split safe here?")
n_unique_shapes = partition["component_sequence"].nunique()
n_rows = len(partition)
print(f"component_sequence unique values: {n_unique_shapes} / {n_rows} rows")
if n_unique_shapes == n_rows:
    print("Every row has a UNIQUE shape -- a plain random address_id split cannot leak a "
          "repeated shape across train/test, because no shape repeats at all. Proceeding "
          "with a plain random split.")
else:
    dup = n_rows - n_unique_shapes
    print(f"WARNING: {dup} rows share a component_sequence shape with at least one other row. "
          "A plain random split COULD place instances of the same shape on both sides. "
          "Proceeding anyway since shape-level majority voting (not per-row memorization) is "
          "the mechanism being tested, but this is noted for the report.")

# ---------------------------------------------------------------------------
section("1. Train/test split of address_id")
rng = np.random.RandomState(RANDOM_STATE)
all_ids = partition["address_id"].to_numpy().copy()
rng.shuffle(all_ids)
n_test = int(len(all_ids) * TEST_FRACTION)
test_ids = set(all_ids[:n_test])
train_ids = set(all_ids[n_test:])
print(f"train: {len(train_ids)} rows, test (held-out): {len(test_ids)} rows")

train_df = partition[partition["address_id"].isin(train_ids)].copy()
test_partition_df = partition[partition["address_id"].isin(test_ids)].copy()  # labels only, used at the end
test_patterns_df = patterns[patterns["address_id"].isin(test_ids)].copy()  # address-only input

assert set(train_df["address_id"]) & set(test_partition_df["address_id"]) == set(), "train/test overlap!"
assert len(test_partition_df) == len(test_patterns_df) == n_test

# ---------------------------------------------------------------------------
section("2. Derive the rule from TRAINING data ONLY")

# 2a. Confirm Rule A on the training split alone (not assumed from the full corpus).
train_seqs = train_df["component_sequence"].str.split("|")
last_types_train = train_seqs.map(lambda s: s[-1])
rule_a_holds = last_types_train.isin(ADMIN_TYPES).mean()
print(f"Rule A on TRAINING split: last component is ADMIN-type for {rule_a_holds:.4%} of training rows")

# 2b. Majority-vote lookup table: component_sequence shape -> majority split_index,
# computed using ONLY train_df. This is the entire "model" -- a lookup table, no
# black-box weights.
shape_votes = (
    train_df.groupby("component_sequence")["split_index"]
    .agg(lambda s: s.value_counts().idxmax())
)
shape_support = train_df.groupby("component_sequence")["split_index"].count()
shape_majority_frac = (
    train_df.groupby("component_sequence")["split_index"]
    .agg(lambda s: s.value_counts(normalize=True).iloc[0])
)

trusted_shapes = shape_support[shape_support >= MIN_SUPPORT].index
lookup = shape_votes[shape_votes.index.isin(trusted_shapes)].to_dict()
print(f"Distinct shapes in training: {len(shape_votes)}")
print(f"Shapes with >= {MIN_SUPPORT} training occurrences (trusted lookup entries): {len(lookup)}")
coverage = train_df["component_sequence"].isin(trusted_shapes).mean()
print(f"Fraction of TRAINING rows covered by a trusted lookup entry: {coverage:.4%}")

# In-training accuracy of the resulting rule (optimistic upper bound -- reported as such).
def rule_a_split_index(component_sequence: str) -> int:
    n = len(component_sequence.split("|"))
    return n - 1  # cut immediately before the trailing admin-type run


def predict_split_index(component_sequence: str) -> tuple[int, str]:
    """Returns (predicted_split_index, source) where source is
    'lookup' (trusted shape) or 'fallback_rule_a' (unseen/low-support shape)."""
    if component_sequence in lookup:
        return int(lookup[component_sequence]), "lookup"
    return rule_a_split_index(component_sequence), "fallback_rule_a"


train_df["pred_split_index"], train_df["pred_source"] = zip(
    *train_df["component_sequence"].map(predict_split_index)
)
in_train_acc = (train_df["pred_split_index"] == train_df["split_index"]).mean()
print(f"\nIN-TRAINING accuracy (optimistic upper bound, NOT a held-out test): {in_train_acc:.4%}")
print("In-training accuracy by prediction source:")
print(train_df.groupby("pred_source").apply(
    lambda g: (g["pred_split_index"] == g["split_index"]).mean(), include_groups=False
))

# ---------------------------------------------------------------------------
section("3. Apply the rule to the PATTERNS file's held-out addresses (never seen labels)")
# Use test_patterns_df's component_sequence -- the address-ONLY file, per the
# user's framing. (Confirmed identical to the partition file's own copy, but
# this is the file that models "what a real pipeline would actually have".)
test_patterns_df["pred_split_index"], test_patterns_df["pred_source"] = zip(
    *test_patterns_df["component_sequence"].map(predict_split_index)
)


def split_address(address: str, split_index: int) -> tuple[str, str]:
    parts = [p.strip() for p in address.split(",")]
    a1 = ", ".join(parts[:split_index])
    a2 = ", ".join(parts[split_index:])
    return a1, a2


pred_lines = test_patterns_df["address"].combine(
    test_patterns_df["pred_split_index"], split_address
)
test_patterns_df["pred_address_1"] = [x[0] for x in pred_lines]
test_patterns_df["pred_address_2"] = [x[1] for x in pred_lines]

# ---------------------------------------------------------------------------
section("4. Validate against the PARTITION file's split_index for the SAME held-out rows")
# Labels read here, for the FIRST time in this script, purely to score.
eval_df = test_patterns_df[["address_id", "address", "pred_split_index", "pred_source",
                             "pred_address_1", "pred_address_2"]].merge(
    test_partition_df[["address_id", "address_1", "address_2", "split_index", "component_sequence"]],
    on="address_id",
)
eval_df = eval_df.rename(columns={"address_1": "gt_address_1", "address_2": "gt_address_2",
                                   "split_index": "gt_split_index"})

held_out_acc = (eval_df["pred_split_index"] == eval_df["gt_split_index"]).mean()
print(f"HELD-OUT (real, non-circular) accuracy: {held_out_acc:.4%}  (n={len(eval_df)})")

print("\nHeld-out accuracy BY prediction source (this is the honest breakdown):")
by_source = eval_df.groupby("pred_source").apply(
    lambda g: pd.Series({
        "n": len(g),
        "accuracy": (g["pred_split_index"] == g["gt_split_index"]).mean(),
    }), include_groups=False
)
print(by_source)

# Secondary signals: reconstruction + token_sequence_ratio, consistent with
# the rest of this research's evaluation vocabulary (§7/§18/§25).
eval_df["reconstruction_ok"] = eval_df.apply(
    lambda r: M.reconstruction_ok(r["address"], r["pred_address_1"], r["pred_address_2"]), axis=1
)
eval_df["token_sequence_ratio"] = eval_df.apply(
    lambda r: M.token_sequence_ratio(r["pred_address_1"], r["gt_address_1"]), axis=1
)
tsr_agree = (eval_df["token_sequence_ratio"] >= 0.96).mean()
print(f"\nreconstruction_ok rate: {eval_df['reconstruction_ok'].mean():.4%}")
print(f"token_sequence_ratio >= 0.96 (agrees with GT per §18/§25 calibration): {tsr_agree:.4%}")

# ---------------------------------------------------------------------------
section("5. Mode-baseline comparison, on the SAME held-out rows (the fair §13 comparison)")
# Content-blind baseline: predict the most common split_index for a row's
# component_count, using ONLY training data to compute that mode (never the
# held-out labels), exactly mirroring §13's methodology but actually run here.
mode_by_count = train_df.groupby("component_count")["split_index"].agg(lambda s: s.value_counts().idxmax())
print("Mode split_index by component_count (from TRAINING data):")
print(mode_by_count)

eval_df["component_count"] = eval_df["component_sequence"].str.count(r"\|") + 1
eval_df["mode_baseline_pred"] = eval_df["component_count"].map(mode_by_count)
mode_baseline_acc = (eval_df["mode_baseline_pred"] == eval_df["gt_split_index"]).mean()
print(f"\nMode-baseline (content-blind) accuracy on held-out set: {mode_baseline_acc:.4%}")
print(f"Rule-based lookup accuracy on held-out set:              {held_out_acc:.4%}")
print(f"Improvement over content-blind mode-baseline:            {held_out_acc - mode_baseline_acc:+.4%}")

# ---------------------------------------------------------------------------
report = {
    "random_state": RANDOM_STATE,
    "test_fraction": TEST_FRACTION,
    "min_support": MIN_SUPPORT,
    "n_train": len(train_df),
    "n_test": len(eval_df),
    "component_sequence_unique_pct": n_unique_shapes / n_rows,
    "rule_a_holds_on_training_pct": float(rule_a_holds),
    "n_distinct_shapes_in_training": int(len(shape_votes)),
    "n_trusted_lookup_entries": int(len(lookup)),
    "training_coverage_by_trusted_lookup_pct": float(coverage),
    "in_training_accuracy_upper_bound": float(in_train_acc),
    "held_out_accuracy": float(held_out_acc),
    "held_out_accuracy_by_source": by_source.to_dict(),
    "held_out_reconstruction_ok_pct": float(eval_df["reconstruction_ok"].mean()),
    "held_out_token_sequence_ratio_agree_pct": float(tsr_agree),
    "mode_baseline_accuracy_held_out": float(mode_baseline_acc),
    "improvement_over_mode_baseline": float(held_out_acc - mode_baseline_acc),
}
with open(OUT / "phase14_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, default=str)
print("\nWrote", OUT / "phase14_report.json")

# Export the lookup table itself -- this IS the "business logic" artifact.
# (May legitimately be empty -- see §27: every shape in this corpus is unique,
# so MIN_SUPPORT>=5 trusted entries may not exist at all. An empty table is
# itself the finding, not a bug to hide.)
if lookup:
    lookup_export = pd.DataFrame([
        {"component_sequence": shape, "majority_split_index": int(idx),
         "training_support": int(shape_support[shape]),
         "training_majority_fraction": float(shape_majority_frac[shape])}
        for shape, idx in lookup.items()
    ]).sort_values("training_support", ascending=False)
else:
    lookup_export = pd.DataFrame(columns=["component_sequence", "majority_split_index",
                                           "training_support", "training_majority_fraction"])
lookup_export.to_csv(OUT / "phase14_learned_lookup_table.csv", index=False)
print("Wrote", OUT / "phase14_learned_lookup_table.csv", f"({len(lookup_export)} trusted shape entries)")

# Export held-out predictions for spot-checking.
eval_df.to_csv(OUT / "phase14_held_out_predictions.csv", index=False)
print("Wrote", OUT / "phase14_held_out_predictions.csv")
