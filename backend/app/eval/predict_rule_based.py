"""Runs rule_based_split.py (Stage 1 vocab from Sheet 1 + geography-boundary
rule, NO fitting on Sheet 2) over a sheet of addresses and writes predicted
address_1/address_2 + confidence, in the format eval_address_partition.py's
--predictions expects.

Usage:
    python -m app.eval.predict_rule_based \\
        --sheet1 "path/to/indian_unique_address_patterns_100000.xlsx" \\
        --addresses "path/to/indian_address_partition_dataset_100000.xlsx" \\
        --out predictions.xlsx
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from app.eval.rule_based_split import predict_split
from app.eval.segment_vocab import SegmentVocab


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sheet1", required=True, help="Sheet 1 (indian_unique_address_patterns) to fit the Stage-1 vocab from")
    ap.add_argument("--addresses", required=True, help="xlsx with an 'address' column to predict splits for")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    print(f"Fitting Stage-1 vocabulary from {args.sheet1} ...")
    sheet1_df = pd.read_excel(args.sheet1)
    vocab = SegmentVocab.fit(sheet1_df)
    print(f"  learned {len(vocab.word_type_counts)} distinct first-words across {len(vocab.all_types)} component types")

    df = pd.read_excel(args.addresses)
    if "address" not in df.columns:
        raise SystemExit("--addresses file needs an 'address' column")
    if args.limit:
        df = df.head(args.limit)
    if "address_id" not in df.columns:
        df = df.reset_index().rename(columns={"index": "address_id"})

    print(f"Predicting splits for {len(df)} addresses (rule-based, zero fitting on this file)...")
    results = []
    for _, row in df.iterrows():
        a1, a2, cut, conf = predict_split(row["address"], vocab)
        results.append(
            {
                "address_id": row["address_id"],
                "address": row["address"],
                "address_1": a1,
                "address_2": a2,
                "predicted_split_index": cut,
                "confidence": round(conf, 4),
            }
        )

    out_df = pd.DataFrame(results)
    out_df.to_excel(args.out, index=False)
    print(f"Predictions written to {args.out}")
    print(f"  avg confidence: {out_df['confidence'].mean():.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
