"""Reshapes a V2 ExtractionResult onto the fixed customer-onboarding schema.

The shared extraction pipeline (extraction_pipeline/*) already does the real
work here -- OCR, PDF rasterization, document classification, label-proximity
field matching, GSTIN/PAN/IFSC/PIN validation, cross-document merging -- it
just returns its own canonical JSON shape (the keys in
config/field_dictionary.yaml, e.g. `vendor_name` for the business's legal
name -- that pipeline was originally built for a different, vendor-facing
use case). This module is the one place that translates that result into the
customer-onboarding form's own keys, so the shared engine and its config stay
untouched.

Two onboarding keys have no source anywhere in field_dictionary.yaml
(`contact_name`, `email_id_cc`) and are always returned as "" rather than
guessed -- there is nothing in a cheque/GST/Udyam/PAN document set that could
fill them.
"""

from __future__ import annotations

import re
from typing import Any

from .extraction_pipeline.models import ExtractionResult

# Address lines are positional in field_dictionary.yaml (address_1 = building/
# flat/road, address_2 = locality, address_3/4 = template overflow rows that
# are almost never populated) -- concatenating them is exactly the "Building +
# Road/Street" join the onboarding form's billing_address expects.
_ADDRESS_FIELDS = ["address_1", "address_2", "address_3", "address_4"]

# onboarding key -> canonical field_dictionary.yaml key. One-to-one only;
# billing_address (see _ADDRESS_FIELDS) and the bank sub-object are handled
# separately below.
_SIMPLE_FIELDS = {
    "company_name": "vendor_name",
    "city": "city",
    "state": "state",
    "country": "country",
    "email_id_to": "email",
    "phone_number": "telephone",
}

_BANK_FIELDS = {
    "bank_name": "bank_name",
    "account_number": "account_number",
    "branch": "branch_address",
}

# Friendly labels for source_documents[].document_type. Anything not listed
# here (a profile added later to document_profiles.yaml, or the "other"
# bucket) falls back to a titlecased version of the profile key, so a new
# document type never comes back blank.
_DOC_TYPE_LABELS = {
    "gst_certificate": "GST Certificate",
    "udyam_certificate": "Udyam Certificate",
    "cancelled_cheque": "Cancelled Cheque",
    "pan_card": "PAN Card",
    "bank_statement": "Bank Statement",
    "other": "Other",
}

# A GSTIN embeds its holder's PAN at characters 3-12 (0-indexed 2:12) -- this
# mirrors the `gstin_contains_pan` cross-check already in validation_rules.yaml,
# just used here as a fallback fill instead of a consistency check.
_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

# Reverse map: canonical field key -> the onboarding field name it feeds, used
# only to translate needs_review entries so a flag on "gst_number" is reported
# to the caller as "gst_registration_number" -- the name they actually asked
# for, not the internal one.
_REVIEW_TARGET: dict[str, str] = {"vendor_name": "company_name", "pin_code": "zip_code",
                                  "gst_number": "gst_registration_number", "pan": "pan_number"}
for _onboarding_key, _canonical_key in _SIMPLE_FIELDS.items():
    _REVIEW_TARGET.setdefault(_canonical_key, _onboarding_key)
for _onboarding_key, _canonical_key in _BANK_FIELDS.items():
    _REVIEW_TARGET.setdefault(_canonical_key, f"bank_details.{_onboarding_key}")
_REVIEW_TARGET.setdefault("ifsc", "bank_details.ifsc_code")
for _addr_key in _ADDRESS_FIELDS:
    _REVIEW_TARGET.setdefault(_addr_key, "billing_address")


def _value(result: ExtractionResult, key: str) -> str:
    field = result.fields.get(key)
    return (field.value or "") if field else ""


def _valid_value(result: ExtractionResult, key: str) -> str:
    """Like `_value`, but a value the engine already marked format-invalid
    (failed its regex validator) comes back as "" instead of as-is.

    Scoped to the identifiers the onboarding form calls out by name --
    GSTIN, PAN, IFSC, PIN -- because a confidently-wrong 15-character string
    sitting in `gst_registration_number` is worse than an empty field: a
    human reviewing `fields_needing_review` needs to know to go re-check the
    source document, not be handed a value that merely looks plausible.
    """
    field = result.fields.get(key)
    if field is None or field.validation_status == "invalid":
        return ""
    return field.value or ""


def _billing_address(result: ExtractionResult) -> str:
    parts = [_value(result, key) for key in _ADDRESS_FIELDS]
    return ", ".join(p for p in parts if p)


def _doc_type_label(doc_type: str) -> str:
    return _DOC_TYPE_LABELS.get(doc_type, doc_type.replace("_", " ").title())


def _source_documents(result: ExtractionResult) -> list[dict[str, Any]]:
    out = []
    for doc in result.documents:
        # classification_score is keyword-weighted (content_weight=2.0 per
        # content keyword hit, see document_profiles.yaml) with no fixed
        # ceiling, so several strong hits can exceed 1.0 -- capped here since
        # "confidence" in this schema is documented as a 0-1 value.
        confidence = min(1.0, round(float(doc.get("classification_score", 0.0)), 2))
        out.append({
            "file_name": doc.get("document", ""),
            "document_type": _doc_type_label(doc.get("doc_type", "other")),
            "confidence": confidence,
        })
    return out


def _fields_needing_review(result: ExtractionResult) -> list[str]:
    """Translate the engine's needs_review entries into onboarding field
    names, deduplicated and in first-seen order.

    Only entries whose canonical field actually feeds this schema are kept --
    the underlying engine also tracks fields (company_type, tan, website, ...)
    that have no place in the onboarding form and would be noise here.
    """
    out: list[str] = []
    for item in result.needs_review:
        target = _REVIEW_TARGET.get(item.get("field", ""))
        if target and target not in out:
            out.append(target)
    return out


def to_onboarding_schema(result: ExtractionResult) -> dict[str, Any]:
    """Reshape a pipeline ExtractionResult into the onboarding form's fixed
    JSON schema. Never invents a value: every field either comes from an
    extracted/validated candidate, a documented derivation (PAN-from-GSTIN),
    or is left as "" when nothing in the uploaded documents supports it.
    """
    gst = _valid_value(result, "gst_number")
    pan = _valid_value(result, "pan")
    review = _fields_needing_review(result)

    if not pan and gst:
        derived = gst[2:12]
        if _PAN_RE.match(derived):
            pan = derived
            # Computed, not read off a page -- flag it like the engine's own
            # derive_from fields do (see semantic_engine.py), so a human can
            # see this PAN was inferred from the GSTIN rather than printed on
            # a PAN card.
            if "pan_number" not in review:
                review.append("pan_number")

    return {
        "company_name": _value(result, "vendor_name"),
        "contact_name": "",
        "billing_address": _billing_address(result),
        "city": _value(result, "city"),
        "state": _value(result, "state"),
        "zip_code": _valid_value(result, "pin_code"),
        "country": _value(result, "country"),
        "gst_registration_number": gst,
        "pan_number": pan,
        "email_id_to": _value(result, "email"),
        "email_id_cc": "",
        "phone_number": _value(result, "telephone"),
        # Business fields that no uploaded document contains -- returned as
        # empty (type defaults to "Services") so the schema matches the
        # customer form's 17 fields. The reviewer fills these in on-screen.
        "payment_terms": "",
        "salesperson": "",
        "region": "",
        "customer_agreement": "",
        "type": "Services",
        "bank_details": {
            "bank_name": _value(result, "bank_name"),
            "account_number": _value(result, "account_number"),
            "ifsc_code": _valid_value(result, "ifsc"),
            "branch": _value(result, "branch_address"),
        },
        "source_documents": _source_documents(result),
        "fields_needing_review": review,
    }
