"""
Request/response shapes for the vendor extraction pipelines.

Both V1 and V2 converge on the same canonical vendor JSON (see README), so one
schema module covers both. Pydantic models here are for documentation/typing
of route responses -- validation of the underlying extraction is done by each
pipeline's own logic (V1's `validate()`, V2's YAML-driven validators).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class VendorData(BaseModel):
    vendor_name: Optional[str] = None
    address_1: Optional[str] = None
    address_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    pin_code: Optional[str] = None
    company_type: Optional[str] = None
    nature_of_business: Optional[str] = None
    pan: Optional[str] = None
    tan: Optional[str] = None
    gst_number: Optional[str] = None
    esic_number: Optional[str] = None
    udyam_number: Optional[str] = None
    bank_name: Optional[str] = None
    branch_address: Optional[str] = None
    ifsc: Optional[str] = None
    account_number: Optional[str] = None
    account_type: Optional[str] = None
    telephone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    needs_review: list[str] = []


class VerificationEntry(BaseModel):
    field: str
    sheet: Optional[str] = None
    cell: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    status: str  # "PASS" | "FAIL"


class VerificationSummary(BaseModel):
    total: int
    passed: int
    failed: int
    success_rate: int


class RunResult(BaseModel):
    """What a completed extraction run produces, regardless of pipeline."""

    run_id: str
    data: dict
    report: list[VerificationEntry]
    summary: VerificationSummary
    files: dict[str, str]
