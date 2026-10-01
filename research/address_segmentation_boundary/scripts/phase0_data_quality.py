"""PHASE 0 -- locate/characterize the data. No assumptions from filenames.

Answers, with numbers:
  - are the two files actually a (input, ground-truth) pair, or something else?
  - row counts, columns, dtypes
  - 1:1 correspondence by address_id?
  - duplicates
  - missing values
  - malformed rows
  - does address_1 + sep + address_2 reconstruct address?
  - whitespace/punctuation differences
  - is ordering (address_id) contiguous/sorted?
"""
from __future__ import annotations

import json
import re

import pandas as pd
from load_data import load_partition, load_patterns

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)

OUT = __import__("pathlib").Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

report = {}


def section(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# ---------------------------------------------------------------------------
part = load_partition()
patt = load_patterns()

section("0. Raw shapes")
print("partition file:", part.shape)
print("patterns  file:", patt.shape)
report["shapes"] = {"partition": list(part.shape), "patterns": list(patt.shape)}

section("1. dtypes")
print("--- partition ---")
print(part.dtypes)
print("--- patterns ---")
print(patt.dtypes)

section("2. Are the two files the SAME addresses (by address_id), just one has a partition?")
merged_ids = part[["address_id", "address"]].merge(
    patt[["address_id", "address"]], on="address_id", suffixes=("_part", "_patt")
)
print("rows where address_id exists in both files:", len(merged_ids), "/", len(part))
mismatch = merged_ids[merged_ids["address_part"] != merged_ids["address_patt"]]
print("rows where the 'address' text DIFFERS between the two files for the same address_id:", len(mismatch))
if len(mismatch):
    print(mismatch.head(10).to_string())
report["same_address_text_across_files"] = {
    "ids_in_both": int(len(merged_ids)),
    "text_mismatches": int(len(mismatch)),
}

section("3. address_id uniqueness / contiguity / sort order")
for name, df in [("partition", part), ("patterns", patt)]:
    ids = df["address_id"]
    print(f"--- {name} ---")
    print("  n rows:", len(ids))
    print("  n unique address_id:", ids.nunique())
    print("  min/max:", ids.min(), ids.max())
    print("  is exactly range(1, N+1) in file order:", list(ids) == list(range(1, len(ids) + 1)))
    dup_ids = ids[ids.duplicated(keep=False)]
    print("  duplicated address_id rows:", len(dup_ids))

section("4. Duplicate ADDRESS TEXT (not just id) -- template leakage signal")
for name, df in [("partition", part), ("patterns", patt)]:
    n_dup = df["address"].duplicated(keep=False).sum()
    n_unique_addr = df["address"].nunique()
    print(f"--- {name} --- total rows={len(df)}  unique address strings={n_unique_addr}  "
          f"rows sharing an address string with >=1 other row={n_dup}")
report["duplicate_address_text"] = {}
for name, df in [("partition", part), ("patterns", patt)]:
    report["duplicate_address_text"][name] = {
        "unique_addresses": int(df["address"].nunique()),
        "rows_with_a_duplicate": int(df["address"].duplicated(keep=False).sum()),
    }

section("5. Missing values")
print("--- partition ---")
print(part.isna().sum())
print("--- patterns ---")
print(patt.isna().sum())

section("6. partition_valid column -- is it always True?")
vc = part["partition_valid"].value_counts(dropna=False)
print(vc)
report["partition_valid_counts"] = {str(k): int(v) for k, v in vc.items()}

section("7. Malformed rows -- address_1 or address_2 blank/whitespace-only")
blank_a1 = part["address_1"].fillna("").str.strip().eq("")
blank_a2 = part["address_2"].fillna("").str.strip().eq("")
print("address_1 blank:", blank_a1.sum())
print("address_2 blank:", blank_a2.sum())
report["blank_fields"] = {"address_1": int(blank_a1.sum()), "address_2": int(blank_a2.sum())}

section("8. RECONSTRUCTION TEST: does address_1 + sep + address_2 == address (after normalizing)?")


def normalize(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def try_join_seps(a1: str, a2: str) -> list[str]:
    """Every join we should plausibly try before declaring reconstruction failed."""
    a1n, a2n = normalize(a1), normalize(a2)
    return [
        f"{a1n}, {a2n}",
        f"{a1n} {a2n}",
        f"{a1n}{a2n}",
        f"{a1n},{a2n}",
    ]


sample_n = len(part)  # full dataset -- 100k rows, cheap with vectorized-ish loop
recon_exact_comma_space = 0
recon_any_join = 0
recon_fail_examples = []

addr_norm = part["address"].map(normalize)
a1_norm = part["address_1"].map(normalize)
a2_norm = part["address_2"].map(normalize)
joined_comma_space = a1_norm + ", " + a2_norm

exact_mask = joined_comma_space == addr_norm
recon_exact_comma_space = int(exact_mask.sum())

# Try the other separators only for the ones that failed comma-space, to save time
fail_idx = part.index[~exact_mask]
any_join_ok = exact_mask.copy()
for i in fail_idx[: min(len(fail_idx), 100000)]:
    a1, a2, orig = part.at[i, "address_1"], part.at[i, "address_2"], part.at[i, "address"]
    ok = orig is not None and any(j == normalize(orig) for j in try_join_seps(a1, a2))
    any_join_ok.at[i] = ok

recon_any_join = int(any_join_ok.sum())

print(f"Exact reconstruction with 'address_1, address_2' == address: {recon_exact_comma_space} / {sample_n} "
      f"({recon_exact_comma_space/sample_n:.4%})")
print(f"Reconstruction succeeds with ANY of the tried separators:    {recon_any_join} / {sample_n} "
      f"({recon_any_join/sample_n:.4%})")

report["reconstruction"] = {
    "exact_comma_space": recon_exact_comma_space,
    "any_separator": recon_any_join,
    "total": int(sample_n),
}

fail_mask = ~any_join_ok
fail_df = part.loc[fail_mask, ["address_id", "address", "address_1", "address_2"]]
print(f"\nRows that reconstruct under NO tried separator: {len(fail_df)}")
if len(fail_df):
    print(fail_df.head(15).to_string())
fail_df.head(200).to_csv(OUT / "phase0_reconstruction_failures_sample.csv", index=False)

section("9. Separator actually used, for rows that DID reconstruct exactly")
# infer separator char(s) between address_1 and address_2 within `address`
sep_counter = {}
ok_idx = part.index[exact_mask]
for i in ok_idx[: 5000]:
    a1n = a1_norm.at[i]
    orig = addr_norm.at[i]
    if orig.startswith(a1n):
        rest = orig[len(a1n):]
        # take up to first alnum char as the "separator"
        m = re.match(r"^([^A-Za-z0-9]*)", rest)
        sep = m.group(1) if m else ""
        sep_counter[sep] = sep_counter.get(sep, 0) + 1
print("Separator strings observed (sampled 5000 exact-reconstruction rows):")
for sep, cnt in sorted(sep_counter.items(), key=lambda x: -x[1]):
    print(f"  {sep!r}: {cnt}")
report["separator_sample"] = sep_counter

section("10. split_index / split_component_boundary sanity")
print(part["split_index"].describe())
print()
print(part["component_count"].describe())
print()
# does split_index always fall within [1, component_count-1]?
bad_split = part[(part["split_index"] < 1) | (part["split_index"] >= part["component_count"])]
print("rows where split_index is NOT in [1, component_count-1]:", len(bad_split))
report["split_index_out_of_range"] = int(len(bad_split))

section("11. postal_code dtype / format consistency")
print("partition postal_code dtype:", part["postal_code"].dtype)
print("patterns  postal_code dtype:", patt["postal_code"].dtype)
print("partition postal_code sample:", part["postal_code"].head(5).tolist())
print("patterns  postal_code sample:", patt["postal_code"].head(5).tolist())
bad_pin = part[~part["postal_code"].astype(str).str.match(r"^\d{6}$")]
print("partition rows where postal_code is not exactly 6 digits:", len(bad_pin))

section("12. structural_pattern / component_sequence cardinality")
print("unique structural_pattern values (partition):", part["structural_pattern"].nunique())
print("unique component_sequence values (partition):", part["component_sequence"].nunique())
print("\nTop 20 component_sequence by frequency:")
print(part["component_sequence"].value_counts().head(20))

section("13. component_count distribution")
print(part["component_count"].value_counts().sort_index())

section("14. generation_method values")
print(part["generation_method"].value_counts())
print(patt["generation_method"].value_counts())

with open(OUT / "phase0_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, default=str)

print("\n\nWrote", OUT / "phase0_report.json")
