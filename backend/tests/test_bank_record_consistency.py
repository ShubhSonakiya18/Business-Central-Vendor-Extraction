"""Regression test for the P0 bug found 2026-08-28: bank_name, ifsc,
account_number and branch_address were resolved independently, per field, so
this vendor's cheque and Udyam certificate -- which list completely different
bank accounts -- could each win a different field. Production was emitting
ICICI's account number under Bank of India's name, with nothing flagging it.

Runs end to end (real OCR) against the one real document set this project has,
so it is slow; that is the honest cost of testing this class of bug for real
rather than mocking the pipeline into agreeing with itself.
"""
import pytest

from app.services.extraction_pipeline.ingest.document_loader import load_documents
from app.services.extraction_pipeline.ingest.ocr_engine import OCREngine
from app.services.extraction_pipeline.pipeline import collect_inputs, extract_from_document_set

DOCS = "app/uploads/09e0ff7aca"

BANK_FIELDS = ("bank_name", "ifsc", "account_number", "branch_address")


@pytest.mark.slow
@pytest.mark.parametrize("backend", ["paddleocr", "rapidocr"])
def test_bank_fields_all_come_from_the_same_document(backend):
    files = collect_inputs([DOCS])
    engine = OCREngine(backend=backend)
    doc_set = load_documents(files, engine=engine, force_ocr=False)
    result = extract_from_document_set(doc_set)

    sources = {
        key: result.fields[key].source_document
        for key in BANK_FIELDS
        if result.fields[key].value
    }

    # Every bank field that has a value must come from the same document --
    # otherwise the record combines one bank's account with another's name,
    # which is not a real account and would misroute a payment.
    assert len(set(sources.values())) <= 1, (
        f"[{backend}] bank fields came from different documents: {sources}"
    )


@pytest.mark.slow
@pytest.mark.parametrize("backend", ["paddleocr", "rapidocr"])
def test_bank_name_matches_the_cheques_actual_bank(backend):
    """Ground truth: the vendor's cheque is ICICI; the Udyam certificate lists
    an unrelated Bank of India account. bank_name must reflect the cheque."""
    files = collect_inputs([DOCS])
    engine = OCREngine(backend=backend)
    doc_set = load_documents(files, engine=engine, force_ocr=False)
    result = extract_from_document_set(doc_set)

    assert result.fields["bank_name"].value == "ICICI Bank"
    assert result.fields["ifsc"].value == "ICIC0006278"
    assert result.fields["account_number"].value == "627851000539"
