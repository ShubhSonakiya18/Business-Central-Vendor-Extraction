"""PHASE 7 -- is cosine similarity (TF-IDF, the only embedding-family option
actually available in this stack -- no sentence-transformers/torch installed,
see requirements.txt) adding anything beyond token_jaccard / fuzzy / boundary
distance, which phase6 already measured on the SAME perturbation categories?

Method: fit ONE TF-IDF vectorizer over a large corpus of address_1 strings
(shared vocabulary -- this is what makes cosine similarity meaningful/fast;
phase6's per-pair-refit tfidf_cosine_pairwise() is NOT how TF-IDF cosine
would actually be deployed and is 100-1000x slower), then score the exact
same perturbation set phase6 used, for direct comparison.
"""
from __future__ import annotations

import json
import pathlib
import random

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from load_data import load_partition
import metrics as M

random.seed(13)
OUT = pathlib.Path(__file__).resolve().parent.parent / "output"

part = load_partition()
N = 20000
sample = part.sample(n=N, random_state=13).reset_index(drop=True)


def word_tokens(s):
    return M.normalize(s).split(" ")


def perturb_a1(a1, a2):
    a1w, a2w = word_tokens(a1), word_tokens(a2)
    out = {"clean": a1}
    if len(a1w) >= 1:
        out["boundary_shift_left1"] = " ".join(a1w[:-1])
    if len(a1w) >= 2:
        out["boundary_shift_left2"] = " ".join(a1w[:-2])
    if len(a2w) >= 1:
        out["boundary_shift_right1"] = " ".join(a1w + a2w[:1])
    if len(a2w) >= 2:
        out["boundary_shift_right2"] = " ".join(a1w + a2w[:2])
    if len(a1w) >= 1:
        idx = random.randrange(len(a1w))
        dup = a1w[: idx + 1] + [a1w[idx]] + a1w[idx + 1:]
        out["token_duplicate"] = " ".join(dup)
    out["case_change"] = a1.upper()
    return out


# Build the FULL corpus of texts to fit the vectorizer on: every clean
# address_1 in the sample, plus every perturbed variant -- this is the
# "shared vocabulary" a real deployment would have (fit once on production
# traffic, or on the training corpus).
records = []
for _, r in sample.iterrows():
    variants = perturb_a1(r["address_1"], r["address_2"])
    for ptype, cand in variants.items():
        records.append({"address_id": r["address_id"], "perturbation": ptype,
                         "gt_address_1": r["address_1"], "cand_address_1": cand})

pdf = pd.DataFrame(records)
corpus = pd.concat([pdf["gt_address_1"], pdf["cand_address_1"]]).unique().tolist()
vec = TfidfVectorizer(token_pattern=r"[A-Za-z0-9]+", lowercase=True)
vec.fit(corpus)
print(f"TF-IDF vocabulary size (fit over {len(corpus)} unique address_1 strings incl. perturbations): "
      f"{len(vec.vocabulary_)}")

gt_matrix = vec.transform(pdf["gt_address_1"])
cand_matrix = vec.transform(pdf["cand_address_1"])
# row-wise cosine similarity (not full pairwise matrix)
import numpy as np
cos = np.array((gt_matrix.multiply(cand_matrix)).sum(axis=1)).flatten()
gt_norm = np.sqrt(np.array(gt_matrix.multiply(gt_matrix).sum(axis=1)).flatten())
cand_norm = np.sqrt(np.array(cand_matrix.multiply(cand_matrix).sum(axis=1)).flatten())
denom = gt_norm * cand_norm
cos = np.divide(cos, denom, out=np.zeros_like(cos), where=denom != 0)
pdf["tfidf_cosine"] = cos

# also compute token_jaccard for direct side-by-side comparison
pdf["token_jaccard"] = [M.token_jaccard(a, b) for a, b in zip(pdf["gt_address_1"], pdf["cand_address_1"])]
pdf["fuzzy_ratio"] = [M.fuzzy_ratio(a, b) for a, b in zip(pdf["gt_address_1"], pdf["cand_address_1"])]

print("\nMean score by perturbation type -- tfidf_cosine vs token_jaccard vs fuzzy_ratio:")
summary = pdf.groupby("perturbation")[["tfidf_cosine", "token_jaccard", "fuzzy_ratio"]].mean()
print(summary.to_string())

print("\nCorrelation between tfidf_cosine and token_jaccard across ALL rows (are they measuring "
      "materially different things, or redundant?):")
corr = pdf[["tfidf_cosine", "token_jaccard", "fuzzy_ratio"]].corr()
print(corr.to_string())

print("\nRows where tfidf_cosine and token_jaccard DISAGREE by > 0.15 (where does TF-IDF actually diverge?):")
diverge = pdf[(pdf["tfidf_cosine"] - pdf["token_jaccard"]).abs() > 0.15]
print(f"count: {len(diverge)} / {len(pdf)} ({len(diverge)/len(pdf):.2%})")
print(diverge[["perturbation", "gt_address_1", "cand_address_1", "tfidf_cosine", "token_jaccard"]].head(10).to_string())

pdf.to_csv(OUT / "phase7_tfidf_vs_others.csv", index=False)

report = {
    "vocab_size": len(vec.vocabulary_),
    "n_scored": len(pdf),
    "mean_by_perturbation": summary.to_dict(orient="index"),
    "correlation_matrix": corr.to_dict(),
    "pct_rows_diverging_gt_0.15": len(diverge) / len(pdf),
}
with open(OUT / "phase7_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, default=str)
print("\nWrote", OUT / "phase7_report.json")
