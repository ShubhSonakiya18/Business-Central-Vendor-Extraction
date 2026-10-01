"""ExcelMapper.read_values() and the fill_and_verify() ordering it exists for.

Covers the bug this was written to fix: the "Excel / Template Value" column
on the vendor compare screen was always a duplicate of the extracted value,
because the vendor's own entries in an uploaded Excel form were overwritten
by ExcelMapper.fill() before anything read them. read_values() must capture
those original entries first, read-only, leaving the file untouched.
"""

from __future__ import annotations

import openpyxl
import pytest

from app.services.extraction_pipeline.excel.excel_mapper import ExcelMapper


@pytest.fixture
def mapper():
    return ExcelMapper.load("vendor_creation_v1")


def _make_workbook(path, sheet_name, cell_values: dict[str, str]):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for cell, value in cell_values.items():
        ws[cell] = value
    wb.save(path)
    return path


class TestReadValues:
    def test_reads_vendor_filled_cells(self, mapper, tmp_path):
        path = tmp_path / "vendor_form.xlsx"
        _make_workbook(path, "Sheet1", {
            "B37": "Acme Traders Pvt Ltd",   # vendor_name
            "B38": "12 MG Road",              # address_1
        })
        values = mapper.read_values(str(path), sheet_name="Sheet1")
        assert values["vendor_name"] == "Acme Traders Pvt Ltd"
        assert values["address_1"] == "12 MG Road"

    def test_empty_cell_is_absent_not_empty_string(self, mapper, tmp_path):
        """A blank cell must not appear as excel_value="" -- that would look
        like a genuine empty value on the vendor's form rather than 'nothing
        was ever filled in here', and would wrongly compare as a mismatch
        against any real extracted value."""
        path = tmp_path / "vendor_form.xlsx"
        _make_workbook(path, "Sheet1", {"B37": "Acme Traders"})
        values = mapper.read_values(str(path), sheet_name="Sheet1")
        assert "vendor_name" in values
        assert "address_1" not in values  # B38 was never set

    def test_numeric_pin_reads_back_as_clean_string(self, mapper, tmp_path):
        """openpyxl round-trips a numeric-looking cell as a float; PIN codes
        must not come back as '700019.0' -- same normalisation the verifier
        already applies when comparing our own written output."""
        path = tmp_path / "vendor_form.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws["B45"] = 700019  # pin_code cell, written as a real number
        wb.save(path)
        values = mapper.read_values(str(path), sheet_name="Sheet1")
        assert values.get("pin_code") == "700019"

    def test_does_not_write_anything_to_the_file(self, mapper, tmp_path):
        """Read-only: this is the whole point -- it must run BEFORE fill()
        without disturbing the workbook fill() is about to overwrite."""
        path = tmp_path / "vendor_form.xlsx"
        _make_workbook(path, "Sheet1", {"B37": "Acme Traders"})
        before = path.read_bytes()
        mapper.read_values(str(path), sheet_name="Sheet1")
        after = path.read_bytes()
        assert before == after

    def test_read_before_fill_captures_original_before_overwrite(self, mapper, tmp_path):
        """The actual bug scenario: read_values() must be called BEFORE
        fill(), because fill() unconditionally overwrites every mapped cell
        (excel_mapper.py ExcelMapper.fill) -- calling read_values() after
        fill() would just read back our own extracted values, reproducing
        the original bug."""
        template = tmp_path / "vendor_form.xlsx"
        output = tmp_path / "vendor_filled.xlsx"
        _make_workbook(template, "Sheet1", {"B37": "Vendor's Own Name Ltd"})

        original = mapper.read_values(str(template), sheet_name="Sheet1")
        assert original["vendor_name"] == "Vendor's Own Name Ltd"

        mapper.fill({"vendor_name": "OCR Extracted Name Ltd"}, str(template), str(output),
                    sheet_name="Sheet1")

        # The original capture is unaffected by the later fill() call.
        assert original["vendor_name"] == "Vendor's Own Name Ltd"
        # And fill() really did overwrite it in the output, confirming the
        # vendor's value would have been lost had it been read afterwards.
        wb = openpyxl.load_workbook(output)
        assert wb["Sheet1"]["B37"].value == "OCR Extracted Name Ltd"

    def test_missing_sheet_is_skipped_not_an_error(self, mapper, tmp_path):
        path = tmp_path / "vendor_form.xlsx"
        _make_workbook(path, "OnlySheet", {"B37": "Acme Traders"})
        values = mapper.read_values(str(path), sheet_name="DoesNotExist")
        assert values == {}
