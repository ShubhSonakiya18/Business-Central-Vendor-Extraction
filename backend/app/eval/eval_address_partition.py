"""Scores a predicted address_1/address_2 split against the synthetic
partition ground truth (Shashwat's dataset: address, address_1, address_2,
split_index, ...). Two-way split ONLY -- no address_3/address_4, matching the
agreed dataset scope (the segmenter's 4-line capability is a separate,
deferred concern; see CLAUDE.md / conversation history).

Three metrics, deliberately not blended into one similarity number:

  1. split_match   -- exact: does the predicted cut land at the same
                       component boundary as ground truth (address_1 and
                       address_2 both normalise-equal). This is the headline
                       metric -- the dataset's ground truth IS a split index,
                       so this is the real target, not an approximation.
  2. fuzzy_ratio    -- rapidfuzz token_sort_ratio per field, averaged. Partial
                       credit for near-misses (formatting/comma/casing
                       differences, or a boundary off by one short token) so
                       "close" isn't scored the same as "unrelated".
  3. jaccard_union  -- token-set Jaccard between the FULL predicted output
                       (address_1+address_2 combined) and the full ground
                       truth combined. Deliberately computed on the union, not
                       per-field: catches dropped/hallucinated components
                       (a real defect) while staying blind to which side of
                       the split a component landed on (a different, already-
                       covered-by-split_match defect). Never used as the
                       primary score -- see conversation notes on why plain
                       per-field Jaccard/cosine are the wrong tool for a
                       boundary-placement problem.

Usage:
    python -m app.eval.eval_address_partition \\
        --ground-truth "path/to/indian_address_partition_dataset_100000.xlsx" \\
        --predictions "path/to/model_predictions.xlsx"

`--predictions` is optional: if omitted, the script runs the CURRENT
`address_resolver.split_trailing_location` against the ground truth's
`address` column and scores that as a baseline.

IMPORTANT: this ground truth encodes a NEW, purely positional splitting
target that is meant to REPLACE `address_resolver`'s semantic (city/state/
PIN-aware) leftover logic, not describe it. A low/zero split_match score for
the current resolver is therefore an EXPECTED baseline reading -- the two
were never designed to agree -- not a defect in either the resolver or this
scorer. The number that matters going forward is how a NEW splitter (model
or rewritten deterministic logic) trained/tuned against this ground truth
scores here over time.

Predictions file must have at least: address_id (or address), address_1,
address_2. Extra columns are ignored.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz


def _norm(s) -> str:
    """Comparison-normalise: collapse whitespace, drop trailing comma/space,
    casefold. Mirrors eval_address.py's convention so the two evals agree on
    what counts as "the same string"."""
    s = "" if s is None or (isinstance(s, float) and s != s) else str(s)
    return " ".join(s.replace(",", " , ").split()).strip(" ,").casefold()


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(_norm(a).split()), set(_norm(b).split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _predict_with_current_code(address: str) -> tuple[str, str]:
    from app.services.extraction_pipeline.extract.address_resolver import (
        resolve_address_blob,
    )

    r = resolve_address_blob(address, multiline=False)
    # legacy path packs everything into address_1; address_2 is "" unless a
    # genuine second field is provided by that path (kept in step with
    # eval_address.py's own handling of this same resolver call).
    return r.address_1.strip(", ").strip(), r.address_2


def load_ground_truth(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    required = {"address", "address_1", "address_2"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"ground truth file missing columns: {sorted(missing)}")
    if "address_id" not in df.columns:
        df = df.reset_index().rename(columns={"index": "address_id"})
    return df


def load_predictions(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    required = {"address_1", "address_2"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"predictions file missing columns: {sorted(missing)}")
    if "address_id" not in df.columns and "address" not in df.columns:
        raise SystemExit("predictions file needs address_id or address to join on")
    return df


def score(gt: pd.DataFrame, pred: pd.DataFrame | None) -> pd.DataFrame:
    if pred is not None:
        key = "address_id" if "address_id" in pred.columns else "address"
        merged = gt.merge(
            pred[[key, "address_1", "address_2"]],
            on=key,
            how="left",
            suffixes=("_gt", "_pred"),
        )
    else:
        preds = [_predict_with_current_code(a) for a in gt["address"]]
        merged = gt.rename(columns={"address_1": "address_1_gt", "address_2": "address_2_gt"})
        merged["address_1_pred"] = [p[0] for p in preds]
        merged["address_2_pred"] = [p[1] for p in preds]

    rows = []
    for _, row in merged.iterrows():
        a1_gt, a2_gt = row["address_1_gt"], row["address_2_gt"]
        a1_pred, a2_pred = row.get("address_1_pred"), row.get("address_2_pred")

        split_match = _norm(a1_gt) == _norm(a1_pred) and _norm(a2_gt) == _norm(a2_pred)
        fuzzy = (
            fuzz.token_sort_ratio(_norm(a1_gt), _norm(a1_pred))
            + fuzz.token_sort_ratio(_norm(a2_gt), _norm(a2_pred))
        ) / 2.0
        gt_union = f"{a1_gt} {a2_gt}"
        pred_union = f"{a1_pred} {a2_pred}"
        jac = _jaccard(gt_union, pred_union)

        rows.append(
            {
                "address_id": row.get("address_id"),
                "address": row.get("address"),
                "split_match": split_match,
                "fuzzy_ratio": round(fuzzy, 2),
                "jaccard_union": round(jac, 3),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ground-truth", required=True, help="path to the partition ground-truth xlsx")
    ap.add_argument("--predictions", help="path to a predictions xlsx (address_id/address, address_1, address_2). Omit to score the current deterministic resolver as baseline.")
    ap.add_argument("--out", help="optional path to write the per-row score table as xlsx/csv")
    ap.add_argument("--limit", type=int, help="only score the first N rows (useful for a quick smoke run before the full 100k)")
    args = ap.parse_args()

    gt = load_ground_truth(args.ground_truth)
    if args.limit:
        gt = gt.head(args.limit)
    pred = load_predictions(args.predictions) if args.predictions else None

    results = score(gt, pred)

    n = len(results)
    split_acc = results["split_match"].mean() if n else 0.0
    avg_fuzzy = results["fuzzy_ratio"].mean() if n else 0.0
    avg_jac = results["jaccard_union"].mean() if n else 0.0

    mode = "predictions file" if pred is not None else "current deterministic resolver (pre-replacement baseline, not expected to match)"
    print(f"Scored {n} rows against: {mode}")
    print(f"  split_match accuracy (headline): {split_acc:.4f}")
    print(f"  avg fuzzy_ratio (partial credit): {avg_fuzzy:.2f}")
    print(f"  avg jaccard_union (completeness): {avg_jac:.4f}")

    if args.out:
        out_path = Path(args.out)
        if out_path.suffix.lower() == ".csv":
            results.to_csv(out_path, index=False)
        else:
            results.to_excel(out_path, index=False)
        print(f"Per-row scores written to {out_path}")

    return 0 if split_acc == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
