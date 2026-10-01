"""PHASE 1 + 2 + 4 + 8 (combined, data-driven) -- what does the ground-truth
split_index actually encode? Is it a semantic premise/locality boundary, or
something closer to an arbitrary cut point within the component run?

Method: decompose component_sequence (pipe-delimited component TYPE labels,
e.g. "FLAT|HOUSE|FLAT|HOUSE|STATE") into per-row component types, classify
each type as PREMISE-ish or ADMIN/LOCALITY-ish using the same two-tier idea
the production address_segmenter.py already uses (premises/structural vs
locality/admin), then compare the row's actual split_index against the
"naive" boundary a premise-vs-locality rule would produce.
"""
from __future__ import annotations

import json
import pathlib
from collections import Counter

import pandas as pd
from load_data import load_partition

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)

OUT = pathlib.Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

part = load_partition()

# ---------------------------------------------------------------------------
def section(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


section("1. What component TYPES exist, and how often does each appear at each position?")
seqs = part["component_sequence"].str.split("|")
all_types = Counter()
pos_type_counter: dict[int, Counter] = {}
for seq in seqs:
    for i, t in enumerate(seq):
        all_types[t] += 1
        pos_type_counter.setdefault(i, Counter())[t] += 1

print("All component types observed, with total occurrence count:")
for t, c in all_types.most_common():
    print(f"  {t:12} {c:7}")

print("\nPer-position type distribution (position 0 = first component):")
max_len = max(pos_type_counter.keys()) + 1
for i in range(max_len):
    ctr = pos_type_counter.get(i, Counter())
    total = sum(ctr.values())
    top = ctr.most_common(6)
    print(f"  pos {i}: n={total:6}  top types: " + ", ".join(f"{t}={c}" for t, c in top))

# ---------------------------------------------------------------------------
section("2. Classify each type as PREMISE-ish vs ADMIN/LOCALITY-ish")
# Candidate admin/terminal types, inferred from position-0..N frequency table
# above (whichever types cluster at the LAST position only).
ADMIN_TYPES = {"STATE", "CITY", "DISTRICT", "PIN"}
last_pos_types = pos_type_counter[max_len - 1]
print("Types seen at the LAST position of the sequence:", dict(last_pos_types))
non_last_admin = {t for t in ADMIN_TYPES if any(pos_type_counter[i].get(t, 0) for i in range(max_len - 1))}
print("Do any ADMIN_TYPES ever appear at a NON-LAST position?", non_last_admin or "no")

PREMISE_TYPES = all_types.keys() - ADMIN_TYPES
print("\nPREMISE_TYPES:", sorted(PREMISE_TYPES))
print("ADMIN_TYPES  :", sorted(ADMIN_TYPES))

# ---------------------------------------------------------------------------
section("3. How many ADMIN-type components does a row have, and where?")
n_admin_per_row = seqs.map(lambda s: sum(1 for t in s if t in ADMIN_TYPES))
print(n_admin_per_row.value_counts())

admin_positions = seqs.map(lambda s: [i for i, t in enumerate(s) if t in ADMIN_TYPES])
always_last = admin_positions.map(lambda pos: pos == [len(pos_type_counter) - 1] or (len(pos) == 1))
# more precise: admin position(s) relative to sequence length
rel = []
for s, pos in zip(seqs, admin_positions):
    n = len(s)
    rel.append(tuple(p - (n - 1) for p in pos))  # 0 = last position, negative = earlier
rel_counter = Counter(rel)
print("\nAdmin-component position(s) relative to end of sequence (0 = last token):")
for k, v in rel_counter.most_common(10):
    print(f"  {k}: {v}")

# ---------------------------------------------------------------------------
section("4. THE KEY TEST: does split_index match the 'naive' premise/admin boundary?")
# naive boundary: address_1 = all PREMISE-type components (a contiguous prefix,
# given finding above that admin types only ever appear at the end),
# address_2 = all ADMIN-type components.
# naive_split_index (1-based, meaning "split after component N") =
#   component_count - (number of admin-type components in this row)


def naive_boundary(row):
    types = row["component_sequence"].split("|")
    n_admin = sum(1 for t in types if t in ADMIN_TYPES)
    return len(types) - n_admin


part["naive_split_index"] = part.apply(naive_boundary, axis=1)
part["boundary_delta"] = part["split_index"] - part["naive_split_index"]

print("split_index vs naive premise|admin boundary -- delta distribution "
      "(0 = ground truth matches the naive semantic boundary exactly):")
print(part["boundary_delta"].value_counts().sort_index())

n_match = int((part["boundary_delta"] == 0).sum())
n_total = len(part)
print(f"\nRows where ground-truth split EXACTLY matches naive premise/admin boundary: "
      f"{n_match} / {n_total} ({n_match/n_total:.2%})")

print("\nRows where ground truth split is BEFORE the naive boundary (admin content leaks into address_1):")
before = part[part["boundary_delta"] < 0]
print(f"  count: {len(before)} ({len(before)/n_total:.2%})")
print(before[["address", "address_1", "address_2", "component_sequence", "split_index", "naive_split_index"]].head(8).to_string())

print("\nRows where ground truth split is AFTER the naive boundary (premise content leaks into address_2):")
after = part[part["boundary_delta"] > 0]
print(f"  count: {len(after)} ({len(after)/n_total:.2%})")
print(after[["address", "address_1", "address_2", "component_sequence", "split_index", "naive_split_index"]].head(8).to_string())

# ---------------------------------------------------------------------------
section("5. Distribution of split_index as a FRACTION of component_count")
part["split_fraction"] = part["split_index"] / part["component_count"]
print(part["split_fraction"].describe())
print("\nHistogram (10 buckets):")
print(pd.cut(part["split_fraction"], bins=10).value_counts().sort_index())

# ---------------------------------------------------------------------------
section("6. Lexical realism check -- does the ADDRESS TEXT carry a recognizable "
        "keyword for each component type, or is it a bare number?")
import re

KEYWORD_RE = re.compile(r"[A-Za-z]{3,}")


def component_texts(row):
    """Best-effort: split `address` on ', ' the same number of times as
    component_count, to see the raw text realized for each component type."""
    parts = [p.strip() for p in row["address"].split(",")]
    types = row["component_sequence"].split("|")
    return list(zip(types, parts)) if len(parts) == len(types) else None


sample = part.sample(n=3000, random_state=42)
type_has_keyword = Counter()
type_total = Counter()
examples_by_type: dict[str, list[str]] = {}
for _, row in sample.iterrows():
    pairs = component_texts(row)
    if pairs is None:
        continue
    for typ, text in pairs:
        type_total[typ] += 1
        if KEYWORD_RE.search(text):
            type_has_keyword[typ] += 1
        examples_by_type.setdefault(typ, [])
        if len(examples_by_type[typ]) < 5:
            examples_by_type[typ].append(text)

print("Fraction of realizations that contain a recognizable A-Za-z keyword (>=3 letters), by component type:")
for typ in sorted(type_total, key=lambda t: -type_total[t]):
    frac = type_has_keyword[typ] / type_total[typ]
    print(f"  {typ:12} keyword-present={frac:6.1%}   n={type_total[typ]:5}   examples={examples_by_type[typ]}")

report = {
    "admin_types": sorted(ADMIN_TYPES),
    "premise_types": sorted(PREMISE_TYPES),
    "admin_component_position_relative_to_end": {str(k): v for k, v in rel_counter.items()},
    "naive_boundary_exact_match_pct": n_match / n_total,
    "split_before_naive_boundary_pct": len(before) / n_total,
    "split_after_naive_boundary_pct": len(after) / n_total,
    "split_fraction_describe": part["split_fraction"].describe().to_dict(),
    "keyword_presence_by_type": {t: type_has_keyword[t] / type_total[t] for t in type_total},
}
with open(OUT / "phase2_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, default=str)
print("\nWrote", OUT / "phase2_report.json")

part.to_pickle(pathlib.Path(__file__).resolve().parent.parent / "cache" / "partition_enriched.pkl")
