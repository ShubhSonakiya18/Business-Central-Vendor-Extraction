"""Runs a model trained by train_split_classifier.py over a sheet of
addresses and writes predicted address_1 / address_2 plus a confidence
score, in the format eval_address_partition.py's --predictions expects.

For each address, every candidate cut point is scored by the classifier's
predict_proba; the cut with the highest predicted probability of being the
true split is chosen, and that probability (normalised across candidates) is
reported as the confidence score for that row -- directly answering "when we
use the same address, does it give the same split as ground truth, and how
confident is it."

Usage:
    python -m app.eval.predict_split_classifier \\
        --model split_classifier.joblib \\
        --addresses "path/to/indian_address_partition_dataset_100000.xlsx" \\
        --out predictions.xlsx
"""

from __future__ import annotations

import argparse
import sys

import joblib
import numpy as np
import pandas as pd

from app.eval.segment_vocab import SegmentVocab
from app.eval.train_split_classifier import _cut_point_features, _segments


def predict_one(clf, address: str, vocab: SegmentVocab | None = None) -> tuple[str, str, int, float]:
    segs = _segments(address)
    if len(segs) < 2:
        return address, "", len(segs), 1.0

    feats = np.array(
        [_cut_point_features(segs, cut, vocab) for cut in range(1, len(segs))],
        dtype=float,
    )
    proba = clf.predict_proba(feats)[:, 1]
    total = proba.sum()
    conf_dist = proba / total if total > 0 else np.full(len(proba), 1.0 / len(proba))

    best_i = int(np.argmax(proba))
    best_cut = best_i + 1
    confidence = float(conf_dist[best_i])

    address_1 = ", ".join(segs[:best_cut])
    address_2 = ", ".join(segs[best_cut:])
    return address_1, address_2, best_cut, confidence


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--addresses", required=True, help="xlsx with an 'address' column (and optionally address_id)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    bundle = joblib.load(args.model)
    clf = bundle["model"]
    vocab = None
    vocab_path = bundle.get("vocab_path")
    if vocab_path:
        vocab = SegmentVocab.load(vocab_path)
        print(f"Loaded Stage-1 vocabulary from {vocab_path}")

    df = pd.read_excel(args.addresses)
    if "address" not in df.columns:
        raise SystemExit("--addresses file needs an 'address' column")
    if args.limit:
        df = df.head(args.limit)
    if "address_id" not in df.columns:
        df = df.reset_index().rename(columns={"index": "address_id"})

    print(f"Predicting splits for {len(df)} addresses...")
    results = []
    for _, row in df.iterrows():
        a1, a2, cut, conf = predict_one(clf, row["address"], vocab)
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
