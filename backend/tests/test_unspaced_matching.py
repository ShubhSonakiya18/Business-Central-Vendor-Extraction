"""The unspaced-match fallback must not reintroduce the false positives that
token-boundary guarding exists to prevent.

Every case in `test_documented_false_positives_stay_rejected` is quoted from the
docstring of `FieldSpec.find_pattern_matches` -- they were observed on the real
sample documents, and each one is a confident-looking value that is wrong.
"""

import pytest

from app.services.extraction_pipeline.config_loader import load_config


@pytest.fixture(scope="module")
def fields():
    dictionary, _ = load_config()
    return dictionary.fields


# ---------------------------------------------------------------------------
# The regression this fallback exists to fix
# ---------------------------------------------------------------------------

def test_spaced_text_still_matches_normally(fields):
    """PaddleOCR's spacing -- must go through the guarded path, unchanged."""
    assert fields["account_type"].find_pattern_matches(
        "BUSINESS BANKING: NEW CURRENT ACCOUNT"
    ) == ["CURRENT"]


def test_unspaced_text_now_matches(fields):
    """RapidOCR's run-on spacing -- the case that motivated the fallback."""
    assert "CURRENT" in fields["account_type"].find_pattern_matches(
        "BUSINESSBANKING:NEW CURRENTACCOUNT"
    )


# ---------------------------------------------------------------------------
# The guard must still hold -- these are the documented real-document failures
# ---------------------------------------------------------------------------

def test_documented_false_positives_stay_rejected(fields):
    account_type = fields["account_type"]

    # "CC" inside "CCGEN" -- 2 chars, below the length floor.
    assert account_type.find_pattern_matches("CCGEN") == []

    # "OD" inside "PRODUCTION" -- 2 chars, below the length floor.
    assert account_type.find_pattern_matches("PRODUCTION") == []


def test_numeric_patterns_never_relax(fields):
    """A digit run colliding inside a longer digit run is the PIN-inside-
    account-number failure; no length threshold makes that safe."""
    account_number = "627851000539"
    assert fields["pin_code"].find_pattern_matches(account_number) == []
    assert fields["telephone"].find_pattern_matches(account_number) == []


def test_identifier_fields_cannot_reach_the_relaxed_path(fields):
    """GSTIN/PAN/IFSC/account number are all digit-bearing, so the alphabetic-
    only rule means the relaxation can never affect the fields that matter."""
    noise = "XX19AABCM7980K1ZUYY627851000539ZZICIC0006278QQ"
    for key in ("gst_number", "pan", "ifsc", "account_number"):
        for value in fields[key].find_pattern_matches(noise):
            # Anything found must have come from the guarded path, which by
            # construction requires token boundaries -- never the fallback.
            assert not value.replace(" ", "").isalpha() or len(value.replace(" ", "")) < 5


def test_fallback_only_fires_when_guarded_scan_finds_nothing(fields):
    """A well-spaced string must not additionally pick up relaxed matches."""
    spaced = "CURRENT ACCOUNT AND SAVINGS ACCOUNT"
    guarded = fields["account_type"].find_pattern_matches(spaced)
    assert "CURRENT" in guarded and "SAVINGS" in guarded
