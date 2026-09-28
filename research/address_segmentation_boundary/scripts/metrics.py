"""Reusable metric implementations under evaluation. Every metric takes two
strings (or two token lists, for the token-level ones) and returns a score.
No metric here is assumed correct -- phase6/phase11 scripts test what each
one actually does.
"""
from __future__ import annotations

import difflib
import re

from rapidfuzz import fuzz

_WS = re.compile(r"\s+")
_TOK = re.compile(r"[A-Za-z0-9]+")


def normalize(s: str) -> str:
    if s is None:
        return ""
    return _WS.sub(" ", str(s)).strip()


def tokens(s: str) -> list[str]:
    return _TOK.findall(normalize(s).lower())


# ---------------------------------------------------------------------------
# 1. exact / normalized exact
def exact_match(a: str, b: str) -> int:
    return int(normalize(a) == normalize(b))


def normalized_exact_match(a: str, b: str) -> int:
    return int(normalize(a).lower() == normalize(b).lower())


# ---------------------------------------------------------------------------
# 2. character-level similarity (SequenceMatcher ratio, char-based)
def char_sequence_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize(a).lower(), normalize(b).lower()).ratio()


# ---------------------------------------------------------------------------
# 3/4. token Jaccard / containment
def token_jaccard(a: str, b: str) -> float:
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def token_containment(a: str, b: str) -> float:
    """What fraction of a's tokens are present in b -- order-insensitive,
    ignores extra tokens in b."""
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta:
        return 1.0 if not tb else 0.0
    return len(ta & tb) / len(ta)


# ---------------------------------------------------------------------------
# 5. Levenshtein (via rapidfuzz, which implements it in C)
def levenshtein_similarity(a: str, b: str) -> float:
    """Normalized: 1 - (edit_distance / max_len)."""
    return fuzz.ratio(normalize(a), normalize(b)) / 100.0  # rapidfuzz.ratio IS Indel-based normalized Levenshtein-like


# ---------------------------------------------------------------------------
# 6. RapidFuzz family
def fuzzy_ratio(a: str, b: str) -> float:
    return fuzz.ratio(normalize(a), normalize(b)) / 100.0


def fuzzy_partial_ratio(a: str, b: str) -> float:
    return fuzz.partial_ratio(normalize(a), normalize(b)) / 100.0


def fuzzy_token_sort_ratio(a: str, b: str) -> float:
    return fuzz.token_sort_ratio(normalize(a), normalize(b)) / 100.0


def fuzzy_token_set_ratio(a: str, b: str) -> float:
    return fuzz.token_set_ratio(normalize(a), normalize(b)) / 100.0


# ---------------------------------------------------------------------------
# 7. SequenceMatcher token-level (order-sensitive)
def token_sequence_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, tokens(a), tokens(b)).ratio()


# ---------------------------------------------------------------------------
# 8. TF-IDF cosine (fit per-pair on a shared micro-corpus -- see phase6 for
# how this is actually used at corpus scale with a shared vectorizer)
def tfidf_cosine_pairwise(a: str, b: str) -> float:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    docs = [normalize(a), normalize(b)]
    if not any(docs):
        return 1.0
    try:
        vec = TfidfVectorizer(token_pattern=r"[A-Za-z0-9]+").fit(docs)
        m = vec.transform(docs)
        return float(cosine_similarity(m[0], m[1])[0, 0])
    except ValueError:
        return 0.0


ALL_METRICS = {
    "exact_match": exact_match,
    "normalized_exact_match": normalized_exact_match,
    "char_sequence_ratio": char_sequence_ratio,
    "token_jaccard": token_jaccard,
    "token_containment": token_containment,
    "fuzzy_ratio": fuzzy_ratio,
    "fuzzy_partial_ratio": fuzzy_partial_ratio,
    "fuzzy_token_sort_ratio": fuzzy_token_sort_ratio,
    "fuzzy_token_set_ratio": fuzzy_token_set_ratio,
    "token_sequence_ratio": token_sequence_ratio,
}


# ---------------------------------------------------------------------------
# BOUNDARY metrics -- operate on the ORIGINAL full address + two candidate
# splits, not on address_1/address_2 strings in isolation.
def boundary_token_index(full_address: str, address_1: str) -> int | None:
    """Given the full address and a candidate address_1, return the TOKEN
    INDEX (0-based, count of tokens) where the split falls, measured against
    the full address's own tokenization. None if address_1's tokens are not
    a prefix of full_address's tokens (candidate doesn't even preserve
    order/content at the start)."""
    full_toks = tokens(full_address)
    a1_toks = tokens(address_1)
    if full_toks[: len(a1_toks)] == a1_toks:
        return len(a1_toks)
    return None


def boundary_char_index(full_address: str, address_1: str) -> int | None:
    norm_full = normalize(full_address)
    norm_a1 = normalize(address_1)
    if norm_full.lower().startswith(norm_a1.lower()):
        return len(norm_a1)
    return None


def boundary_token_distance(full_address: str, gt_address_1: str, cand_address_1: str) -> int | None:
    """Absolute difference, in TOKENS, between where the ground truth cut
    and where the candidate cut -- the single most direct "did we choose the
    right boundary" measurement. None if either boundary can't be located as
    a clean prefix (see boundary_token_index)."""
    gt_idx = boundary_token_index(full_address, gt_address_1)
    cand_idx = boundary_token_index(full_address, cand_address_1)
    if gt_idx is None or cand_idx is None:
        return None
    return abs(gt_idx - cand_idx)


# ---------------------------------------------------------------------------
# RECONSTRUCTION check
def reconstruction_ok(full_address: str, address_1: str, address_2: str, sep: str = ", ") -> bool:
    return normalize(f"{normalize(address_1)}{sep}{normalize(address_2)}") == normalize(full_address)


def reconstruction_diff(full_address: str, address_1: str, address_2: str, sep: str = ", ") -> dict:
    """Classify HOW reconstruction failed, at token-multiset level:
    missing / extra / duplicated tokens (order-blind; order issues are a
    separate check)."""
    from collections import Counter

    full_toks = tokens(full_address)
    joined_toks = tokens(address_1) + tokens(address_2)
    c_full, c_joined = Counter(full_toks), Counter(joined_toks)
    missing = c_full - c_joined
    extra = c_joined - c_full
    return {
        "ok": (c_full == c_joined),
        "missing_tokens": dict(missing),
        "extra_tokens": dict(extra),
        "order_preserved": (full_toks == joined_toks) if (c_full == c_joined) else None,
    }
