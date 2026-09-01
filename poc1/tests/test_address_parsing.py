"""Label-anchored address parsing: split into Billing Address / City / State / Zip."""
from app.extraction.address import parse_address


GST_TEXT = """Form GST REG-06
Legal Name: Bharat Textiles Private Limited
Building No./Flat No.: Plot 14, MIDC Industrial Area
Road/Street: Andheri Kurla Road
City/Town/Village: Mumbai
District: Mumbai Suburban
State: Maharashtra
PIN Code: 400072
"""

UDYAM_TEXT = """UDYAM REGISTRATION CERTIFICATE
Official Address of Enterprise: Plot 14, MIDC Industrial Area, Andheri Kurla Road
City/Town/Village: Mumbai
State: Maharashtra
PIN Code: 400072
"""

UNLABELED_TEXT = """Some cover note.
Ship to our Mumbai warehouse, Maharashtra, PIN 400072, thanks.
"""


def test_gst_style_labeled_address_splits_correctly():
    parsed = parse_address(GST_TEXT)
    assert parsed.billing_address == "Plot 14, MIDC Industrial Area, Andheri Kurla Road"
    assert parsed.city == "Mumbai"
    assert parsed.state == "Maharashtra"
    assert parsed.zip_code == "400072"
    assert not parsed.used_generic_fallback


def test_udyam_style_generic_address_label_fallback():
    parsed = parse_address(UDYAM_TEXT)
    assert parsed.billing_address == "Plot 14, MIDC Industrial Area, Andheri Kurla Road"
    assert parsed.city == "Mumbai"
    assert parsed.state == "Maharashtra"
    assert parsed.zip_code == "400072"


def test_unlabeled_free_text_still_finds_state_and_zip():
    # State and Zip each have their own whole-text fallback (like a hard-
    # validatable regex/name-list field), independent of whether
    # Building/Road/City matched anything -- so `used_generic_fallback`
    # (which only covers the *last-resort* "nothing at all matched, fall
    # back to the generic Address label" path) is correctly False here even
    # though nothing was labeled.
    parsed = parse_address(UNLABELED_TEXT)
    assert parsed.state == "Maharashtra"
    assert parsed.zip_code == "400072"
    assert parsed.billing_address is None
    assert not parsed.used_generic_fallback


def test_state_is_normalized_against_known_list():
    text = "State: maharashtra\nPIN Code: 400072\n"
    parsed = parse_address(text)
    assert parsed.state == "Maharashtra"


def test_no_address_signal_returns_all_none():
    parsed = parse_address("Nothing relevant here at all.")
    assert parsed.billing_address is None
    assert parsed.city is None
    assert parsed.state is None
    assert parsed.zip_code is None
