"""Enumerations shared across models, schemas and pipeline code."""
from __future__ import annotations

import enum


class VendorStatus(str, enum.Enum):
    DRAFT = "draft"
    PROCESSING = "processing"
    REVIEW = "review"
    APPROVED = "approved"


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class DocumentType(str, enum.Enum):
    GST_CERTIFICATE = "gst_certificate"
    PAN_CARD = "pan_card"
    UDYAM_CERTIFICATE = "udyam_certificate"
    CANCELLED_CHEQUE = "cancelled_cheque"
    OTHER = "other"


class ExtractionMethod(str, enum.Enum):
    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    REGEX = "regex"
    RULE = "rule"
    MANUAL = "manual"


class FieldName(str, enum.Enum):
    """The 17 target columns of the vendor onboarding Excel sheet, in the
    exact order they must appear in the output workbook, plus 5 bonus
    bank-detail fields extracted from the cancelled cheque (kept out of the
    literal Excel layout but exposed via the extraction API)."""

    COMPANY_NAME = "company_name"
    CONTACT_NAME = "contact_name"
    BILLING_ADDRESS = "billing_address"
    CITY = "city"
    STATE = "state"
    ZIP_CODE = "zip_code"
    COUNTRY = "country"
    GST_REGISTRATION_CERTIFICATE = "gst_registration_certificate"
    PAN_CARD = "pan_card"
    EMAIL_ID_TO = "email_id_to"
    EMAIL_ID_CC = "email_id_cc"
    PHONE_NUMBER = "phone_number"
    PAYMENT_TERMS = "payment_terms"
    SALESPERSON = "salesperson"
    REGION = "region"
    CUSTOMER_AGREEMENT = "customer_agreement"
    TYPE = "type"

    # Bonus bank-detail fields (from cancelled cheque) -- not in the Excel layout.
    BANK_NAME = "bank_name"
    BANK_BRANCH = "bank_branch"
    BANK_IFSC_CODE = "bank_ifsc_code"
    BANK_ACCOUNT_NUMBER = "bank_account_number"
    BANK_ACCOUNT_HOLDER_NAME = "bank_account_holder_name"


# Fields that are never sourced from a document -- always blank until a human fills them in.
MANUAL_ONLY_FIELDS = {
    FieldName.EMAIL_ID_CC,
    FieldName.PAYMENT_TERMS,
    FieldName.SALESPERSON,
    FieldName.CUSTOMER_AGREEMENT,
    FieldName.TYPE,
}

# The exact row order of the Excel output (the 17 literal columns only).
EXCEL_FIELD_ORDER = [
    FieldName.COMPANY_NAME,
    FieldName.CONTACT_NAME,
    FieldName.BILLING_ADDRESS,
    FieldName.CITY,
    FieldName.STATE,
    FieldName.ZIP_CODE,
    FieldName.COUNTRY,
    FieldName.GST_REGISTRATION_CERTIFICATE,
    FieldName.PAN_CARD,
    FieldName.EMAIL_ID_TO,
    FieldName.EMAIL_ID_CC,
    FieldName.PHONE_NUMBER,
    FieldName.PAYMENT_TERMS,
    FieldName.SALESPERSON,
    FieldName.REGION,
    FieldName.CUSTOMER_AGREEMENT,
    FieldName.TYPE,
]

EXCEL_FIELD_LABELS = {
    FieldName.COMPANY_NAME: "Company Name",
    FieldName.CONTACT_NAME: "Contact Name",
    FieldName.BILLING_ADDRESS: "Billing Address",
    FieldName.CITY: "City",
    FieldName.STATE: "State",
    FieldName.ZIP_CODE: "Zip code/Pin code",
    FieldName.COUNTRY: "Country",
    FieldName.GST_REGISTRATION_CERTIFICATE: "GST(ABN,TRN) Registration Certificate",
    FieldName.PAN_CARD: "PAN Card (Company/Individual)",
    FieldName.EMAIL_ID_TO: "Email ID TO",
    FieldName.EMAIL_ID_CC: "Email ID CC",
    FieldName.PHONE_NUMBER: "Phone Number",
    FieldName.PAYMENT_TERMS: "Payment Terms",
    FieldName.SALESPERSON: "SALESPERSON",
    FieldName.REGION: "REGION",
    FieldName.CUSTOMER_AGREEMENT: "Customer Agreement / Contract/Purchase Order/Sale Order",
    FieldName.TYPE: "Type",
}

BANK_FIELD_ORDER = [
    FieldName.BANK_NAME,
    FieldName.BANK_BRANCH,
    FieldName.BANK_IFSC_CODE,
    FieldName.BANK_ACCOUNT_NUMBER,
    FieldName.BANK_ACCOUNT_HOLDER_NAME,
]

BANK_FIELD_LABELS = {
    FieldName.BANK_NAME: "Bank Name",
    FieldName.BANK_BRANCH: "Branch",
    FieldName.BANK_IFSC_CODE: "IFSC Code",
    FieldName.BANK_ACCOUNT_NUMBER: "Account Number",
    FieldName.BANK_ACCOUNT_HOLDER_NAME: "Account Holder Name",
}
