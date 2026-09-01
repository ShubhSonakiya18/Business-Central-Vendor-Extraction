"""Excel fill and read-back verification.

The read-back check is the most easily misread number the app reports. These
tests pin what it does prove -- that a value survived save, type coercion and
reopen, landing in the right cell -- and, explicitly, what it does not: it
compares the workbook against the same extracted JSON that filled it, so a
wrong value passes. Accuracy is eval/eval_extraction.py's job, not this one's.
"""

import openpyxl
import pytest
import yaml

from app.services.extraction_pipeline.excel.excel_mapper import ExcelMapper
from app.services.extraction_pipeline.excel.verifier import _normalize, summarize, verify_excel


@pytest.fixture
def mapper(tmp_path):
    mapping = {
        "sheet": "NSIND",
        "fields": {
            "vendor_name": "B37",
            "pan": "B53",
            "pin_code": "B45",
            "account_number": "B63",
        },
    }
    path = tmp_path / "test_mapping.yaml"
    path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
    return ExcelMapper.load(str(path))


@pytest.fixture
def template(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.active.title = "NSIND"
    path = tmp_path / "template.xlsx"
    workbook.save(path)
    return path


class TestNormalize:
    def test_none_becomes_empty(self):
        assert _normalize(None) == ""

    def test_comparison_is_case_insensitive(self):
        assert _normalize("ICICI Bank") == _normalize("icici bank")

    def test_surrounding_whitespace_ignored(self):
        assert _normalize("  700019  ") == _normalize("700019")

    def test_float_coercion_of_numeric_string_is_forgiven(self):
        """openpyxl reads a numeric cell back as a float, so a PIN code written
        as "700019" returns 700019.0. Without this the field would fail a
        comparison it should pass."""
        assert _normalize("700019") == _normalize(700019.0)
        assert _normalize("627851000539") == _normalize(627851000539.0)

    def test_genuine_decimal_is_not_truncated(self):
        assert _normalize("12.0") == "12"
        assert _normalize("12.5") == "12.5"


class TestRoundTrip:
    def test_written_values_read_back_as_pass(self, mapper, template, tmp_path):
        data = {
            "vendor_name": "M B CONTROL & SYSTEMS PVT LTD",
            "pan": "AABCM7980K",
            "pin_code": "700019",
            "account_number": "627851000539",
        }
        out = tmp_path / "filled.xlsx"
        mapper.fill(data, str(template), str(out), sheet_name="NSIND")

        report = verify_excel(data, str(out), mapper, sheet_name="NSIND", highlight=False)
        assert all(e["status"] == "PASS" for e in report), report
        assert summarize(report) == {
            "total": 4, "passed": 4, "failed": 0, "success_rate": 100
        }

    def test_missing_values_still_pass_when_cell_is_empty(self, mapper, template, tmp_path):
        """An absent field and an empty cell agree; that is a PASS, because the
        write did exactly what the data said."""
        out = tmp_path / "filled.xlsx"
        mapper.fill({"pan": "AABCM7980K"}, str(template), str(out), sheet_name="NSIND")

        report = verify_excel(
            {"pan": "AABCM7980K"}, str(out), mapper, sheet_name="NSIND", highlight=False
        )
        assert all(e["status"] == "PASS" for e in report), report

    def test_tampered_cell_is_reported_as_fail(self, mapper, template, tmp_path):
        """This is the class of bug the check exists for: the workbook no longer
        holds what the pipeline intended to write."""
        data = {"pan": "AABCM7980K", "pin_code": "700019"}
        out = tmp_path / "filled.xlsx"
        mapper.fill(data, str(template), str(out), sheet_name="NSIND")

        workbook = openpyxl.load_workbook(out)
        workbook["NSIND"]["B53"] = "TAMPERED"
        workbook.save(out)

        report = verify_excel(data, str(out), mapper, sheet_name="NSIND", highlight=False)
        failures = [e for e in report if e["status"] == "FAIL"]
        assert len(failures) == 1
        assert failures[0]["field"] == "pan"
        assert failures[0]["expected"] == "AABCM7980K"
        assert failures[0]["actual"] == "TAMPERED"

    def test_unknown_sheet_raises(self, mapper, template, tmp_path):
        data = {"pan": "AABCM7980K"}
        out = tmp_path / "filled.xlsx"
        mapper.fill(data, str(template), str(out), sheet_name="NSIND")
        with pytest.raises(ValueError, match="not found"):
            verify_excel(data, str(out), mapper, sheet_name="NOSUCHSHEET", highlight=False)


class TestWhatVerificationDoesNotProve:
    def test_a_wrong_value_still_scores_one_hundred_percent(
        self, mapper, template, tmp_path
    ):
        """The load-bearing caveat, asserted so it cannot quietly change.

        `expected` is the pipeline's own extracted value, not ground truth. A
        misread PAN is compared against itself and passes. 100% here means "the
        write worked", never "the extraction was right".
        """
        misread = {
            "vendor_name": "M B CONTROL & SYSTEMS PVT LTD",
            "pan": "AABCM798OK",       # OCR read 0 as O -- wrong, but consistent
            "pin_code": "700019",
            "account_number": "627851000539",
        }
        out = tmp_path / "filled.xlsx"
        mapper.fill(misread, str(template), str(out), sheet_name="NSIND")

        report = verify_excel(misread, str(out), mapper, sheet_name="NSIND", highlight=False)
        assert summarize(report)["success_rate"] == 100


class TestSummarize:
    def test_counts_and_rate(self):
        report = [
            {"status": "PASS"}, {"status": "PASS"},
            {"status": "FAIL"}, {"status": "PASS"},
        ]
        assert summarize(report) == {
            "total": 4, "passed": 3, "failed": 1, "success_rate": 75
        }

    def test_empty_report_does_not_divide_by_zero(self):
        assert summarize([]) == {
            "total": 0, "passed": 0, "failed": 0, "success_rate": 0
        }
