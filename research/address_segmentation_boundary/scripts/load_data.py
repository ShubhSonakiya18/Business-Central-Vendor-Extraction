"""Load the two source Excel files into pandas, cache as parquet for fast
re-analysis (100k rows x 14 cols is slow to re-parse from .xlsx every run).

Source files (outside the repo, as provided):
  PARTITION_PATH = "Downloads/indian_address_partition_dataset_100000 (2).xlsx"
  PATTERNS_PATH  = "Downloads/indian_unique_address_patterns_100000 (1) (4).xlsx"

This script makes NO assumption about which file is "ground truth" -- that
is determined empirically in phase0_data_quality.py from actual column
contents, not from filenames.
"""
from __future__ import annotations

import pathlib

import pandas as pd

DOWNLOADS = pathlib.Path(r"C:\Users\shubh\Downloads")
PARTITION_PATH = DOWNLOADS / "indian_address_partition_dataset_100000 (2).xlsx"
PATTERNS_PATH = DOWNLOADS / "indian_unique_address_patterns_100000 (1) (4).xlsx"

CACHE_DIR = pathlib.Path(__file__).resolve().parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def load_partition(force: bool = False) -> pd.DataFrame:
    cache = CACHE_DIR / "partition.pkl"
    if cache.exists() and not force:
        return pd.read_pickle(cache)
    df = pd.read_excel(PARTITION_PATH, sheet_name="Address Partition Dataset", engine="openpyxl")
    df.to_pickle(cache)
    return df


def load_patterns(force: bool = False) -> pd.DataFrame:
    cache = CACHE_DIR / "patterns.pkl"
    if cache.exists() and not force:
        return pd.read_pickle(cache)
    df = pd.read_excel(PATTERNS_PATH, sheet_name="Indian Address Dataset", engine="openpyxl")
    df.to_pickle(cache)
    return df


if __name__ == "__main__":
    p1 = load_partition(force=True)
    p2 = load_patterns(force=True)
    print("partition dataset:", p1.shape, list(p1.columns))
    print("patterns dataset :", p2.shape, list(p2.columns))
