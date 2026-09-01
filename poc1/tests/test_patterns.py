"""Regex / validation coverage for the structured Indian document formats."""
from app.patterns import (
    find_account_number, find_email, find_gstin, find_ifsc, find_mobile,
    find_pan, find_pin, find_udyam, is_valid_email, is_valid_gstin,
    is_valid_ifsc, is_valid_mobile, is_valid_pan, is_valid_pin, is_valid_udyam,
    pan_from_gstin,
)

GSTIN = "27AAACB1234C1Z5"
PAN = "AAACB1234C"
IFSC = "HDFC0001234"
UDYAM = "UDYAM-MH-03-1234567"


def test_gstin_matches_and_validates():
    assert find_gstin(f"GSTIN: {GSTIN}") == GSTIN
    assert is_valid_gstin(GSTIN)
    assert not is_valid_gstin("not-a-gstin")


def test_pan_embedded_in_gstin():
    assert pan_from_gstin(GSTIN) == PAN
    assert is_valid_pan(PAN)


def test_pan_found_standalone_and_excludes_gstin_embedded_copy():
    text = f"GSTIN {GSTIN} PAN {PAN}"
    # Should not just re-return the PAN embedded in the GSTIN when excluded.
    found = find_pan(text, exclude=GSTIN)
    assert found == PAN


def test_ifsc():
    assert find_ifsc(f"IFSC: {IFSC}") == IFSC
    assert is_valid_ifsc(IFSC)
    assert not is_valid_ifsc("HDFC1234567")  # 5th char must be '0'


def test_pin_code():
    assert find_pin("PIN Code: 400072") == "400072"
    assert is_valid_pin("400072")
    assert not is_valid_pin("40072")  # only 5 digits


def test_mobile():
    assert find_mobile("Mobile: 9876543210") == "9876543210"
    assert is_valid_mobile("9876543210")
    assert not is_valid_mobile("1876543210")  # must start 6-9
    assert not find_mobile("Mobile: 12345")


def test_email():
    assert find_email("Email: accounts@example.com") == "accounts@example.com"
    assert is_valid_email("accounts@example.com")
    assert not is_valid_email("not-an-email")


def test_udyam():
    assert find_udyam(f"Udyam No: {UDYAM}") == UDYAM
    assert is_valid_udyam(UDYAM)
    assert not is_valid_udyam("UDYAM-1234567")


def test_account_number_excludes_claimed_tokens():
    text = "MICR 400240002 A/C No 123456789012"
    found = find_account_number(text, exclude={"400240002"})
    assert found == "123456789012"
