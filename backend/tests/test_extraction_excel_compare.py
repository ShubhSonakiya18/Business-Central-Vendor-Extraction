"""routers/extraction.py's _run_as_json(): the excel_value / excel_mismatch /
excel_uploaded fields it adds to each entry in `fields`, which drive the
vendor compare screen's "Excel / Template Value" column.

Uses app.services.run_state directly to persist a fake run, then calls the
real serializer -- no HTTP layer needed, this logic has nothing to do with
routing.
"""

from __future__ import annotations

import pytest

from app.routers.extraction import _run_as_json
from app.services import run_state


def _persist(run_id: str, *, excel_uploaded: bool, fields: dict, original_excel_values: dict):
    run_state.save(run_id, {
        "fields": fields,
        "needs_review": [],
        "documents": [],
        "summary": {},
        "report": [],
        "verification": None,
        "excel_uploaded": excel_uploaded,
        "original_excel_values": original_excel_values,
        "files": {},
        "timings": {},
    })


@pytest.fixture
def run_id(tmp_path, monkeypatch):
    # run_state writes under OUTPUT_DIR/<run_id>/run_state.json -- point it
    # at a scratch dir so this test never touches real run data.
    monkeypatch.setattr(run_state, "OUTPUT_DIR", tmp_path)
    return run_state.new_run_id()  # real generator, so it matches _RUN_ID's shape


class TestNoExcelUploaded:
    def test_excel_uploaded_false_and_no_excel_fields_added(self, run_id):
        _persist(run_id, excel_uploaded=False,
                fields={"vendor_name": {"field": "vendor_name", "value": "Acme Ltd"}},
                original_excel_values={})
        body = _run_as_json(run_id)
        assert body["excel_uploaded"] is False
        assert "excel_value" not in body["fields"]["vendor_name"]
        assert "excel_mismatch" not in body["fields"]["vendor_name"]


class TestExcelUploadedAgreement:
    def test_matching_values_no_mismatch(self, run_id):
        _persist(run_id, excel_uploaded=True,
                fields={"vendor_name": {"field": "vendor_name", "value": "Acme Traders Pvt Ltd"}},
                original_excel_values={"vendor_name": "Acme Traders Pvt Ltd"})
        body = _run_as_json(run_id)
        f = body["fields"]["vendor_name"]
        assert f["excel_value"] == "Acme Traders Pvt Ltd"
        assert f["excel_mismatch"] is False

    def test_matching_values_case_and_whitespace_insensitive(self, run_id):
        """Same normalisation the write-integrity verifier uses -- a real
        agreement should not be flagged just because of casing/spacing."""
        _persist(run_id, excel_uploaded=True,
                fields={"vendor_name": {"field": "vendor_name", "value": "  ACME traders pvt ltd  "}},
                original_excel_values={"vendor_name": "Acme Traders Pvt Ltd"})
        body = _run_as_json(run_id)
        assert body["fields"]["vendor_name"]["excel_mismatch"] is False


class TestExcelUploadedMismatch:
    def test_genuinely_different_values_flagged(self, run_id):
        _persist(run_id, excel_uploaded=True,
                fields={"vendor_name": {"field": "vendor_name", "value": "Acme Traders Pvt Ltd"}},
                original_excel_values={"vendor_name": "Beta Industries Pvt Ltd"})
        body = _run_as_json(run_id)
        f = body["fields"]["vendor_name"]
        assert f["excel_value"] == "Beta Industries Pvt Ltd"
        assert f["excel_mismatch"] is True

    def test_pin_code_numeric_float_tail_does_not_falsely_mismatch(self, run_id):
        """700019 vs '700019.0' (openpyxl's float round-trip) must compare
        equal -- covered upstream by read_values' own normalisation, but this
        confirms the two normalisations actually agree end to end."""
        _persist(run_id, excel_uploaded=True,
                fields={"pin_code": {"field": "pin_code", "value": "700019"}},
                original_excel_values={"pin_code": "700019"})
        body = _run_as_json(run_id)
        assert body["fields"]["pin_code"]["excel_mismatch"] is False


class TestOneSidedValues:
    """A field present on only one side is a gap, not a disagreement -- never
    flagged as a mismatch."""

    def test_never_printed_on_pdf_not_a_mismatch(self, run_id):
        _persist(run_id, excel_uploaded=True,
                fields={"website": {"field": "website", "value": None}},
                original_excel_values={"website": "www.acme.example"})
        body = _run_as_json(run_id)
        f = body["fields"]["website"]
        assert f["excel_value"] == "www.acme.example"
        assert f["excel_mismatch"] is False

    def test_left_blank_in_excel_not_a_mismatch(self, run_id):
        _persist(run_id, excel_uploaded=True,
                fields={"website": {"field": "website", "value": "www.acme.example"}},
                original_excel_values={})
        body = _run_as_json(run_id)
        f = body["fields"]["website"]
        assert f["excel_value"] is None
        assert f["excel_mismatch"] is False

    def test_absent_on_both_sides_not_a_mismatch(self, run_id):
        _persist(run_id, excel_uploaded=True,
                fields={"website": {"field": "website", "value": None}},
                original_excel_values={})
        body = _run_as_json(run_id)
        assert body["fields"]["website"]["excel_mismatch"] is False


class TestValuesMapUnaffected:
    def test_values_still_reflect_extracted_not_excel(self, run_id):
        """The flattened `values` map is documented as the extracted value --
        adding excel_value to `fields` must not change what `values` reports."""
        _persist(run_id, excel_uploaded=True,
                fields={"vendor_name": {"field": "vendor_name", "value": "Acme Ltd"}},
                original_excel_values={"vendor_name": "Different Name Ltd"})
        body = _run_as_json(run_id)
        assert body["values"]["vendor_name"] == "Acme Ltd"
