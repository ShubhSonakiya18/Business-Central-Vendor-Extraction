"""Stage 2 (rule-based, NO fitting on Sheet 2): decides the address_1 /
address_2 split using ONLY the Stage-1 vocabulary fitted on Sheet 1
(segment_vocab.py) -- Sheet 2 is never used to train or tune anything here,
only to score this rule's output afterwards. This satisfies the constraint
that training and validation must not share a file.

Rule: classify each comma-segment's most likely component type via the
Stage-1 vocab (word -> type learned from Sheet 1's 100k addresses), bucket
each type as PREMISES-tier (FLAT, HOUSE, SHOP, OFFICE, PLOT, UNIT, FLOOR,
TOWER, BLOCK, WING, PHASE, BUILDING, SOCIETY, CAMPUS, MARKET, BUSINESS_PARK,
INDUSTRIAL_AREA, ROAD, STREET, LANDMARK, NEAR, OPPOSITE, DIRECTION) or
GEOGRAPHY-tier (CITY, DISTRICT, PIN, STATE, TEHSIL, VILLAGE, LOCALITY,
MOHALLA, SECTOR, POST, GALI). Split right before the FIRST geography-tier
segment; everything before it is address_1, everything from it onward is
address_2. This mirrors the premises-vs-geography tier split already used in
this codebase's production segmenter (segmentation_keywords.yaml /
address_segmenter.py's _PREMISES_BAND_MAX), applied here to Stage-1's
learned vocabulary instead of a hand-written keyword list.

Confidence for a row = the Stage-1 vocab's own type-probability for the
segment the cut was based on (how sure the vocab is that segment is really
geography-tier), or a low fallback confidence when no geography-tier segment
was found in the address at all (cut defaults to "no split" -- everything in
address_1).
"""

from __future__ import annotations

from app.eval.segment_vocab import SegmentVocab
from app.eval.train_split_classifier import _segments

# Bucketed from the 34 component types actually present in Sheet 1's
# component_sequence column (see conversation record) -- a data-derived list,
# not exhaustive of every possible Indian-address tag, but exhaustive of this
# dataset's vocabulary.
GEOGRAPHY_TIER = frozenset({
    "CITY", "DISTRICT", "PIN", "STATE", "TEHSIL", "VILLAGE",
    "LOCALITY", "MOHALLA", "SECTOR", "POST", "GALI",
})
PREMISES_TIER = frozenset({
    "FLAT", "HOUSE", "SHOP", "OFFICE", "PLOT", "UNIT", "FLOOR", "TOWER",
    "BLOCK", "WING", "PHASE", "BUILDING", "SOCIETY", "CAMPUS", "MARKET",
    "BUSINESS_PARK", "INDUSTRIAL_AREA", "ROAD", "STREET", "LANDMARK",
    "NEAR", "OPPOSITE", "DIRECTION",
})


def _most_likely_type(segment: str, vocab: SegmentVocab) -> tuple[str, float]:
    scores = vocab.type_scores(segment)
    if not scores:
        return "", 0.0
    best_type = max(scores, key=scores.get)
    return best_type, scores[best_type]


def predict_split(address: str, vocab: SegmentVocab) -> tuple[str, str, int, float]:
    """Returns (address_1, address_2, cut, confidence). `cut` is 1-indexed
    (number of leading segments in address_1), matching split_index's
    convention in the ground-truth sheet, so eval_address_partition.py's
    scoring is directly comparable."""
    segs = _segments(address)
    total = len(segs)
    if total < 2:
        return address, "", total, 1.0

    for i, seg in enumerate(segs):
        best_type, prob = _most_likely_type(seg, vocab)
        if best_type in GEOGRAPHY_TIER and i > 0:
            # split right BEFORE this segment -> address_1 = segs[:i]
            address_1 = ", ".join(segs[:i])
            address_2 = ", ".join(segs[i:])
            return address_1, address_2, i, prob

    # no geography-tier segment found anywhere after the first position --
    # low-confidence fallback: everything stays in address_1.
    return ", ".join(segs), "", total, 0.2
