"""Stage 1 (unsupervised): learns a segment-word -> tag-type vocabulary from
Sheet 1 (indian_unique_address_patterns), which has `address` and
`component_sequence` but NO address_1/address_2 split labels.

There is nothing to learn a split boundary from in Sheet 1 (no label exists),
so this stage does not train a classifier. What it DOES learn, genuinely from
Sheet 1's 100k addresses, is: which words tend to open a segment of which
component type (SHOP, FLAT, HOUSE, CITY, STATE, PIN, ...), and how common
each type is overall. That is real signal a fitted table can capture and a
hand-written numeric feature (length/digit-ratio) cannot -- e.g. "Shop"
almost always opens a SHOP-type segment, "Uttar Pradesh" almost always closes
a STATE-type segment.

`build_segment_vocab()` returns a dict: first-word (casefolded) -> Counter of
component types it was seen labelled as, across every segment of every
address in Sheet 1. `SegmentVocab.type_scores(segment)` turns that into a
per-segment feature vector (Stage 2 uses it as extra columns alongside the
existing numeric surface features) -- a fitted representation trained on the
full 100k-address corpus, not just whatever appears in Sheet 2.

Usage (library, not a script):
    from app.eval.segment_vocab import SegmentVocab
    vocab = SegmentVocab.fit(sheet1_df)
    vocab.save("segment_vocab.joblib")
    vocab = SegmentVocab.load("segment_vocab.joblib")
    vocab.type_scores("Shop 23")   # -> {"SHOP": 0.98, "HOUSE": 0.01, ...}
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

import joblib
import pandas as pd


def _segments(address: str) -> list[str]:
    return [s.strip() for s in str(address).split(",") if s.strip()]


def _first_word(segment: str) -> str:
    words = segment.split()
    return words[0].casefold() if words else ""


@dataclass
class SegmentVocab:
    # first-word -> {component_type: count}
    word_type_counts: dict[str, Counter] = field(default_factory=dict)
    # overall frequency of each component type, for the fallback/unknown case
    type_totals: Counter = field(default_factory=Counter)
    all_types: tuple[str, ...] = ()

    @classmethod
    def fit(cls, sheet1_df: pd.DataFrame) -> "SegmentVocab":
        required = {"address", "component_sequence"}
        missing = required - set(sheet1_df.columns)
        if missing:
            raise ValueError(f"sheet1 missing columns: {sorted(missing)}")

        word_type_counts: dict[str, Counter] = defaultdict(Counter)
        type_totals: Counter = Counter()
        type_set: set[str] = set()

        for row in sheet1_df.itertuples(index=False):
            segs = _segments(row.address)
            tags = str(row.component_sequence).split("|")
            if len(segs) != len(tags):
                continue  # malformed row -- skip rather than misalign labels
            for seg, tag in zip(segs, tags):
                w = _first_word(seg)
                if not w:
                    continue
                word_type_counts[w][tag] += 1
                type_totals[tag] += 1
                type_set.add(tag)

        return cls(
            word_type_counts=dict(word_type_counts),
            type_totals=type_totals,
            all_types=tuple(sorted(type_set)),
        )

    def type_scores(self, segment: str) -> dict[str, float]:
        """P(component_type | first word of this segment), smoothed with the
        overall type prior when the word was never seen in Sheet 1 (e.g. a
        proper noun / city name not in the fitted vocabulary)."""
        w = _first_word(segment)
        counts = self.word_type_counts.get(w)
        if counts:
            total = sum(counts.values())
            return {t: counts.get(t, 0) / total for t in self.all_types}
        total_all = sum(self.type_totals.values()) or 1
        return {t: self.type_totals.get(t, 0) / total_all for t in self.all_types}

    def is_known_word(self, segment: str) -> bool:
        return _first_word(segment) in self.word_type_counts

    def save(self, path: str) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: str) -> "SegmentVocab":
        return joblib.load(path)
