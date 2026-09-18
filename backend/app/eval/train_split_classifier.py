"""Trains a CPU-only, feature-based classifier that learns, from the
ground-truth partition sheet (address, address_1, address_2), where an
address splits -- so that when it sees an address it was trained on again,
it reproduces the same address_1 / address_2 split, with a confidence score.

Two-stage design (per team decision):

  Stage 1 (unsupervised, segment_vocab.py) -- fit a first-word -> component-
  type vocabulary from Sheet 1 (indian_unique_address_patterns), which has
  100k addresses' worth of structural_pattern/component_sequence but NO
  address_1/address_2 split labels. This teaches the feature space what
  "Shop", "Tower", "Uttar Pradesh", etc. typically ARE (segment type),
  grounded in the full 100k-address vocabulary rather than only whatever
  words happen to appear in Sheet 2.

  Stage 2 (supervised, this file) -- train the actual split classifier on
  Sheet 2 (the ground-truth partition sheet), which DOES have address_1/
  address_2 labels. Each candidate cut point's feature vector is the numeric
  surface features (length, digit ratio, word count, ...) PLUS the Stage-1
  vocabulary's type-probability scores for the segments on either side of
  the cut. No component_sequence/structural_pattern tags from Sheet 2 itself
  are used directly as features (real messy addresses won't have them) --
  only the Stage-1-derived word->type probabilities, which are a property of
  the WORD, not a label leaked from this row's own answer.

Model: address_1 is always a prefix of `address`'s comma-segments (verified
against the ground truth), so "predict address_1/address_2" reduces to
"predict how many of the leading comma-segments belong to address_1" --
a multiclass classification over segment count. A RandomForestClassifier
(scikit-learn, CPU-only) is trained over per-cut-point feature vectors, one
training example per possible cut point per address, labelled 1 at the true
cut and 0 elsewhere. predict_proba at inference gives the confidence score.

Usage:
    python -m app.eval.train_split_classifier \\
        --sheet1 "path/to/indian_unique_address_patterns_100000.xlsx" \\
        --ground-truth "path/to/indian_address_partition_dataset_100000.xlsx" \\
        --model-out split_classifier.joblib \\
        [--limit N]

`--sheet1` is optional: omit it to fall back to the numeric-features-only
model (no Stage 1 vocabulary), e.g. for a quick smoke test.

Then score it with eval_address_partition.py by first running
predict_split_classifier.py to produce a --predictions file.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

from app.eval.segment_vocab import SegmentVocab

_DIGIT_RE = re.compile(r"\d")
_ALPHA_RE = re.compile(r"[a-zA-Z]")


def _segments(address: str) -> list[str]:
    return [s.strip() for s in str(address).split(",") if s.strip()]


def _segment_features(seg: str) -> list[float]:
    n = len(seg) or 1
    n_digits = len(_DIGIT_RE.findall(seg))
    n_alpha = len(_ALPHA_RE.findall(seg))
    words = seg.split()
    return [
        len(seg),
        len(words),
        n_digits / n,
        n_alpha / n,
        1.0 if seg[:1].isdigit() else 0.0,
        1.0 if any(ch.isdigit() for ch in seg) else 0.0,
        1.0 if seg.isupper() else 0.0,
    ]


def _vocab_features(segment: str, vocab: SegmentVocab | None) -> list[float]:
    """Stage-1-derived features for one segment: P(component_type | first
    word), for every type the vocabulary learned from Sheet 1, plus whether
    the word was seen at all. Empty list when no vocab was fitted (numeric-
    features-only fallback mode)."""
    if vocab is None:
        return []
    scores = vocab.type_scores(segment) if segment else {t: 0.0 for t in vocab.all_types}
    return [scores.get(t, 0.0) for t in vocab.all_types] + [
        1.0 if segment and vocab.is_known_word(segment) else 0.0
    ]


def _cut_point_features(
    segments: list[str], cut: int, vocab: SegmentVocab | None = None
) -> list[float]:
    """Features describing the candidate boundary AFTER `cut` segments
    (1-indexed, i.e. cut=3 means address_1 = segments[:3]).
    Uses only the two segments adjacent to the candidate boundary plus
    whole-address shape -- no tag/label information from THIS row. When
    `vocab` is given (Stage 1, fitted on Sheet 1), also includes each side's
    learned component-type probabilities."""
    total = len(segments)
    left = segments[cut - 1]
    right = segments[cut] if cut < total else ""
    feats = [
        cut,
        total,
        cut / total,
        total - cut,
    ]
    feats += _segment_features(left)
    feats += _segment_features(right) if right else [0.0] * 7
    feats += _vocab_features(left, vocab)
    feats += _vocab_features(right, vocab)
    return feats


def feature_names(vocab: SegmentVocab | None = None) -> tuple[str, ...]:
    base = (
        "cut", "total", "cut_ratio", "remaining",
        "left_len", "left_words", "left_digit_ratio", "left_alpha_ratio", "left_starts_digit", "left_has_digit", "left_isupper",
        "right_len", "right_words", "right_digit_ratio", "right_alpha_ratio", "right_starts_digit", "right_has_digit", "right_isupper",
    )
    if vocab is None:
        return base
    vocab_names = tuple(f"left_type_{t}" for t in vocab.all_types) + ("left_word_known",)
    vocab_names += tuple(f"right_type_{t}" for t in vocab.all_types) + ("right_word_known",)
    return base + vocab_names


# kept for any external caller still importing the old constant name
_FEATURE_NAMES = feature_names()


def build_training_table(
    df: pd.DataFrame, vocab: SegmentVocab | None = None
) -> tuple[np.ndarray, np.ndarray, list]:
    """One row per (address, candidate cut point): label 1 at the ground
    truth split_index, 0 for every other candidate cut in that address.
    Returns (X, y, group_ids) -- group_ids lets a caller reconstruct which
    rows belong to the same source address (for argmax-based prediction)."""
    X, y, groups = [], [], []
    for gid, row in enumerate(df.itertuples(index=False)):
        segs = _segments(row.address)
        total = len(segs)
        if total < 2:
            continue
        true_cut = int(row.split_index) if hasattr(row, "split_index") else None
        if true_cut is None:
            # derive from address_1 when split_index isn't provided
            a1_segs = _segments(row.address_1)
            true_cut = len(a1_segs)
        for cut in range(1, total):
            X.append(_cut_point_features(segs, cut, vocab))
            y.append(1 if cut == true_cut else 0)
            groups.append(gid)
    return np.array(X, dtype=float), np.array(y, dtype=int), groups


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ground-truth", required=True)
    ap.add_argument("--sheet1", help="Sheet 1 (indian_unique_address_patterns) for Stage-1 vocabulary fitting; omit for numeric-features-only mode")
    ap.add_argument("--model-out", default="split_classifier.joblib")
    ap.add_argument("--vocab-out", default=None, help="where to save the fitted Stage-1 vocab (default: alongside model-out); ignored if --sheet1 omitted")
    ap.add_argument("--limit", type=int, help="only use the first N rows (for a quick run)")
    ap.add_argument("--test-size", type=float, default=0.1)
    args = ap.parse_args()

    df = pd.read_excel(args.ground_truth)
    required = {"address", "address_1", "address_2"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"ground truth missing columns: {sorted(missing)}")
    if args.limit:
        df = df.head(args.limit)

    vocab: SegmentVocab | None = None
    if args.sheet1:
        print(f"Stage 1: fitting segment vocabulary from {args.sheet1} ...")
        sheet1_df = pd.read_excel(args.sheet1)
        vocab = SegmentVocab.fit(sheet1_df)
        print(f"  learned {len(vocab.word_type_counts)} distinct first-words across {len(vocab.all_types)} component types")
        vocab_path = args.vocab_out or (str(Path(args.model_out).with_suffix("")) + "_vocab.joblib")
        vocab.save(vocab_path)
        print(f"  vocab saved to {vocab_path}")
    else:
        print("No --sheet1 given: training with numeric surface features only (no Stage-1 vocabulary).")

    print(f"Stage 2: building per-cut-point training table from {len(df)} addresses (ground truth)...")
    X, y, groups = build_training_table(df, vocab)
    print(f"  {X.shape[0]} candidate-cut rows, {y.sum()} positive (true splits), {X.shape[1]} features")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=args.test_size, random_state=42, stratify=y
    )

    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=None,
        n_jobs=-1,
        random_state=42,
        class_weight="balanced",
    )
    print("Training RandomForestClassifier (CPU)...")
    clf.fit(X_train, y_train)

    train_acc = clf.score(X_train, y_train)
    test_acc = clf.score(X_test, y_test)
    print(f"  per-cut-point accuracy -- train: {train_acc:.4f}  held-out: {test_acc:.4f}")
    print("  (this is candidate-cut classification accuracy, not whole-address")
    print("   split accuracy -- run eval_address_partition.py via predict_split_classifier.py")
    print("   for the real, whole-address split_match metric.)")

    vocab_path = (
        (args.vocab_out or (str(Path(args.model_out).with_suffix("")) + "_vocab.joblib"))
        if args.sheet1 else None
    )
    joblib.dump(
        {"model": clf, "feature_names": feature_names(vocab), "vocab_path": vocab_path},
        args.model_out,
    )
    print(f"Model written to {args.model_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
