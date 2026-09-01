"""Document classifier: decide which of the known document types a file is,
before running the relevant field parser on it.

Runs on already-extracted raw text (text-layer or OCR output, see
app/ocr/text_extraction.py) -- purely rule-based, no ML classifier, so it's
fast, deterministic, and fully explainable (each decision records *why*).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.enums import DocumentType
from app.patterns import GSTIN_RE, IFSC_RE, PAN_RE, UDYAM_RE


@dataclass
class ClassificationResult:
    document_type: DocumentType
    subtype: str | None
    confidence: float
    reasons: list[str]
    extra_flags: dict


def _has_any(text: str, needles: list[str]) -> list[str]:
    upper = text.upper()
    return [n for n in needles if n.upper() in upper]


def classify_document(text: str) -> ClassificationResult:
    text = text or ""

    gstin_hits = GSTIN_RE.findall(text.upper())
    udyam_hits = UDYAM_RE.findall(text.upper())
    ifsc_hits = IFSC_RE.findall(text.upper())
    pan_hits = PAN_RE.findall(text.upper())

    # --- GST Certificate ---
    gst_keywords = _has_any(text, ["Form GST REG-06", "GST REG-06", "Registration Certificate", "GSTIN"])
    if gstin_hits or gst_keywords:
        score = 0.0
        reasons = []
        if any("REG-06" in k.upper() for k in gst_keywords):
            score += 0.5
            reasons.append("matched 'Form GST REG-06'")
        if any("REGISTRATION CERTIFICATE" in k.upper() for k in gst_keywords):
            score += 0.2
            reasons.append("matched 'Registration Certificate'")
        if gstin_hits:
            score += 0.4
            reasons.append(f"GSTIN pattern matched ({gstin_hits[0]})")
        if score >= 0.4:
            return ClassificationResult(
                document_type=DocumentType.GST_CERTIFICATE,
                subtype="gst_reg06",
                confidence=min(score, 0.99),
                reasons=reasons,
                extra_flags={},
            )

    # --- Udyam Registration Certificate ---
    udyam_keywords = _has_any(text, ["UDYAM REGISTRATION CERTIFICATE", "UDYAM REGISTRATION NUMBER", "UDYAM-"])
    if udyam_hits or udyam_keywords:
        score = 0.0
        reasons = []
        if any("UDYAM REGISTRATION CERTIFICATE" in k.upper() for k in udyam_keywords):
            score += 0.6
            reasons.append("matched 'UDYAM REGISTRATION CERTIFICATE'")
        if udyam_hits:
            score += 0.4
            reasons.append(f"UDYAM registration number pattern matched ({udyam_hits[0]})")
        if score >= 0.4:
            return ClassificationResult(
                document_type=DocumentType.UDYAM_CERTIFICATE,
                subtype="udyam",
                confidence=min(score, 0.99),
                reasons=reasons,
                extra_flags={},
            )

    # --- PAN Card ---
    pan_keywords = _has_any(text, ["INCOME TAX DEPARTMENT", "Permanent Account Number", "GOVT. OF INDIA"])
    if pan_hits and not gstin_hits:
        score = 0.0
        reasons = []
        if pan_keywords:
            score += 0.5
            reasons.append(f"matched card keyword(s): {pan_keywords}")
        if pan_hits:
            score += 0.3
            reasons.append(f"PAN pattern matched ({pan_hits[0]})")
        # PAN cards are short documents -- little other text is a good signal.
        if len(text.strip()) < 600:
            score += 0.15
            reasons.append("short document (consistent with a PAN card, not a full certificate)")
        if score >= 0.4:
            return ClassificationResult(
                document_type=DocumentType.PAN_CARD,
                subtype="pan",
                confidence=min(score, 0.99),
                reasons=reasons,
                extra_flags={},
            )

    # --- Cancelled Cheque ---
    cheque_keywords = _has_any(text, ["A/C NO", "ACCOUNT NO", "PAYEE", "IFSC", "MICR", "CANCELLED"])
    if ifsc_hits and not gstin_hits and not udyam_hits:
        score = 0.3
        reasons = [f"IFSC pattern matched ({ifsc_hits[0]})"]
        if any(k in ("A/C NO", "ACCOUNT NO") for k in cheque_keywords):
            score += 0.25
            reasons.append("matched account-number label")
        if "MICR" in cheque_keywords:
            score += 0.15
            reasons.append("matched 'MICR'")
        is_cancelled = "CANCELLED" in text.upper()
        if score >= 0.4:
            return ClassificationResult(
                document_type=DocumentType.CANCELLED_CHEQUE,
                subtype="cancelled_cheque",
                confidence=min(score, 0.95),
                reasons=reasons,
                # Handwritten "CANCELLED" scrawl detection is unreliable via OCR --
                # surfaced as a low-confidence flag, never something the pipeline
                # depends on.
                extra_flags={"is_cancelled": is_cancelled, "is_cancelled_confidence": "low"},
            )

    return ClassificationResult(
        document_type=DocumentType.OTHER,
        subtype=None,
        confidence=0.0,
        reasons=["no known document signature matched"],
        extra_flags={},
    )
