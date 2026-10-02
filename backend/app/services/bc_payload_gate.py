"""Stage-11 pre-submission gate for a saved vendor (docs/ADDRESS_SEGMENTATION_PLAN.md
sections 5, 7 and 13).

Check-only: this module NEVER modifies a Vendor. It re-runs the BC address
representation layer on the STORED lines (which may have been edited by a
human since extraction) and checks the other BC address fields, returning
findings. A finding with class BLOCK_SUBMISSION, or an unconfirmed
MANUAL_REVIEW, stops the push (the router answers 409).

The one-click confirmation lives on `Vendor.address_review` and is written
only by `confirm_address()` below, which the confirm endpoint calls. A
confirmation is bound to a hash of the exact Address / Address 2 it
approved; once the lines change, it no longer counts.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models.model import Vendor
from app.services.bc_target_profile import BcTargetProfile
from app.services.extraction_pipeline.extract.address_representation import (
    BLOCK_SUBMISSION,
    MANUAL_REVIEW,
    REASON_ADDRESS_OVERFLOW,
    REASON_BC_LENGTH_REBALANCE,
    DecisionStatus,
    layout_from_stored,
    represent_address,
)

FIELD_TOO_LONG = "FIELD_TOO_LONG"
INVALID_COUNTRY = "INVALID_COUNTRY"
INVALID_PIN = "INVALID_PIN"

_PIN_RE = re.compile(r"^[1-9]\d{5}$")

# Vendor attributes owned by check_address (whole-fragment rebalance), never by
# the per-field length check.
_ADDRESS_LINE_ATTRS = frozenset({"address_1", "address_2", "address_3", "address_4"})


@dataclass
class GateFinding:
    field: str
    reason_code: str
    automation_class: str
    detail: str = ""
    constraint: str | None = None
    # before/after lines for the one-click review panel, when applicable
    before: dict | None = None
    proposal: dict | None = None
    confirmed: bool = False

    def to_dict(self) -> dict:
        # `proposal` is always present: null means "no safe automatic
        # re-layout exists -- edit by hand", which the review screen must be
        # able to tell apart from a finding that has one.
        d = {"field": self.field, "reason_code": self.reason_code,
             "automation_class": self.automation_class, "detail": self.detail,
             "confirmed": self.confirmed, "proposal": self.proposal}
        if self.constraint:
            d["constraint"] = self.constraint
        if self.before is not None:
            d["before"] = self.before
        return d


@dataclass
class GateResult:
    findings: list[GateFinding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        """True when the record may not be pushed: any BLOCK finding, or any
        MANUAL_REVIEW finding that has not been confirmed (DESIGN L151)."""
        return any(
            f.automation_class == BLOCK_SUBMISSION
            or (f.automation_class == MANUAL_REVIEW and not f.confirmed)
            for f in self.findings
        )

    def to_dict(self) -> dict:
        return {"blocked": self.blocked, "findings": [f.to_dict() for f in self.findings]}


def address_values_hash(address_1: str, address_2: str) -> str:
    """SHA-256 of the trimmed Address / Address 2 a confirmation approves."""
    payload = f"{(address_1 or '').strip()}\n{(address_2 or '').strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_confirmed(vendor: Vendor) -> bool:
    review = vendor.address_review or {}
    return bool(review) and review.get("values_sha256") == address_values_hash(
        vendor.address_1 or "", vendor.address_2 or ""
    )


def _extraction_rebalance(vendor: Vendor) -> dict | None:
    """The ADDRESS_BC_LENGTH_REBALANCE provenance entry recorded at
    extraction time, if the saved record carries one."""
    raw = vendor.raw_extraction or {}
    fields = raw.get("fields") if isinstance(raw, dict) else None
    a1 = fields.get("address_1") if isinstance(fields, dict) else None
    prov = a1.get("provenance") if isinstance(a1, dict) else None
    for entry in prov or []:
        if isinstance(entry, dict) and entry.get("reason_code") == REASON_BC_LENGTH_REBALANCE:
            return entry
    return None


def _lines(vendor: Vendor) -> tuple[str, str, str, str]:
    return tuple((getattr(vendor, k, "") or "").strip()
                 for k in ("address_1", "address_2", "address_3", "address_4"))  # type: ignore[return-value]


def check_address(vendor: Vendor, profile: BcTargetProfile) -> list[GateFinding]:
    """Address / Address 2 findings for the stored record."""
    a1, a2, a3, a4 = _lines(vendor)
    if not any((a1, a2, a3, a4)):
        return []
    limits = profile.address_limits()
    stored = {"address_1": a1, "address_2": a2}
    findings: list[GateFinding] = []
    legacy_3_4 = bool(a3 or a4)
    over_1 = len(a1) > limits.address_1_max
    over_2 = len(a2) > limits.address_2_max

    if legacy_3_4 or over_1 or over_2:
        # The stored lines cannot be pushed as they are. Propose the
        # representation layer's re-layout of the SAME text (legacy Address
        # 3/4 folded into Address 2, in order) -- as a proposal only.
        decision = represent_address(
            layout_from_stored(a1, a2, a3, a4), limits, profile_name=profile.name,
            geography={"city": vendor.city or "", "state": vendor.state or "",
                       "country": vendor.country or "", "pin_code": vendor.pin_code or ""},
            mode="check",
        )
        fits = decision.status in (DecisionStatus.AUTO_PASS, DecisionStatus.AUTO_FIX,
                                   DecisionStatus.MANUAL_REVIEW) and not any(
            f.reason_code != REASON_BC_LENGTH_REBALANCE for f in decision.findings)
        proposal = ({"address_1": decision.address_1, "address_2": decision.address_2}
                    if fits else None)
        if legacy_3_4:
            constraint = "BC_NO_ADDRESS_3_4"
            detail = "Address 3/4 have no Business Central field and are never joined into Address 2"
        elif over_2:
            constraint = "BC_ADDRESS_2_MAX_LENGTH"
            detail = f"Address 2 is {len(a2)} characters; the limit is {limits.address_2_max}"
        else:
            constraint = "BC_ADDRESS_1_MAX_LENGTH"
            detail = f"Address is {len(a1)} characters; the limit is {limits.address_1_max}"

        if proposal is not None:
            # A safe whole-fragment layout exists (plan section 6-7): one-click
            # review. The stored lines differ from the proposal, so it is
            # never pre-confirmed -- confirming applies the proposal.
            findings.append(GateFinding(
                field="address_1", reason_code=REASON_BC_LENGTH_REBALANCE,
                automation_class=MANUAL_REVIEW,
                detail=f"{detail}; confirm the proposed split (whole parts moved, no text cut)",
                constraint=constraint,
                before={**stored, "address_3": a3, "address_4": a4}, proposal=proposal,
            ))
        else:
            # No whole-fragment layout fits: BLOCK, stored text untouched.
            overflow = next((f.detail for f in decision.findings
                             if f.reason_code == REASON_ADDRESS_OVERFLOW), "")
            findings.append(GateFinding(
                field="address_1", reason_code=REASON_ADDRESS_OVERFLOW,
                automation_class=BLOCK_SUBMISSION,
                detail=(f"{detail}; no whole-fragment re-layout fits -- edit the address by hand"
                        + (f" ({overflow})" if overflow == "fragment_too_long" else "")),
                constraint=constraint,
                before={**stored, "address_3": a3, "address_4": a4}, proposal=None,
            ))
        return findings

    # Lines fit. If they are still the machine's extraction-time rebalance,
    # a reviewer must confirm it (one click) before the push.
    entry = _extraction_rebalance(vendor)
    if entry and (entry.get("final_address_1"), entry.get("final_address_2")) == (a1, a2):
        findings.append(GateFinding(
            field="address_1",
            reason_code=REASON_BC_LENGTH_REBALANCE,
            automation_class=MANUAL_REVIEW,
            detail=(f"Address line break moved to satisfy {entry.get('constraint')} "
                    f"({entry.get('constraint_value')} characters); confirm the new split"),
            constraint=entry.get("constraint"),
            before={"address_1": entry.get("original_address_1", ""),
                    "address_2": entry.get("original_address_2", "")},
            proposal=stored,
            confirmed=_is_confirmed(vendor),
        ))
    return findings


def check_other_fields(vendor: Vendor, profile: BcTargetProfile) -> list[GateFinding]:
    """Every non-address length constraint in the BC target profile (Name,
    City, County, Post Code, Phone, Mobile, E-Mail, Home Page, ...), plus PIN
    format and Country mapping (plan section 5). Over-limit -> FIELD_TOO_LONG,
    BLOCK. Never modifies a value and never shortens one: these fields do not
    take part in the address whole-fragment rebalance. The County
    abbreviation map, when configured, is offered as a PROPOSAL only."""
    findings: list[GateFinding] = []
    for constraint, spec in profile.raw["constraints"].items():
        attr = spec.get("portal")
        limit = spec.get("value")
        # Address / Address 2 are handled by check_address (whole-fragment
        # rebalance); Country is a code lookup (its width applies to the BC
        # code, not the stored name); Address 3/4 have no BC field.
        if (not isinstance(attr, str) or not isinstance(limit, int)
                or attr in _ADDRESS_LINE_ATTRS or attr == "country"):
            continue
        value = (getattr(vendor, attr, "") or "").strip()
        if len(value) > limit:
            proposal = None
            if attr == "state":
                abbr = profile.county_abbreviation(value)
                if abbr:
                    proposal = {"state": abbr}
            findings.append(GateFinding(
                field=attr, reason_code=FIELD_TOO_LONG, automation_class=BLOCK_SUBMISSION,
                detail=f"{len(value)} characters; the limit is {limit}",
                constraint=constraint, proposal=proposal,
            ))

    pin = (vendor.pin_code or "").strip()
    if pin and not _PIN_RE.match(pin):
        findings.append(GateFinding(field="pin_code", reason_code=INVALID_PIN,
                                    automation_class=BLOCK_SUBMISSION,
                                    detail="not a 6-digit Indian PIN"))

    country = (vendor.country or "").strip()
    if country and profile.country_code(country) is None:
        findings.append(GateFinding(
            field="country", reason_code=INVALID_COUNTRY, automation_class=MANUAL_REVIEW,
            detail=f"no Country/Region Code mapped for {country!r} in profile {profile.name}",
        ))
    return findings


def gate_vendor(vendor: Vendor, profile: BcTargetProfile) -> GateResult:
    return GateResult(findings=check_address(vendor, profile) + check_other_fields(vendor, profile))


class ConfirmationRejected(ValueError):
    """The lines a reviewer tried to confirm are not a safe re-layout of the
    stored address text."""


def _fragments(*lines: str) -> list[str]:
    return [p.strip() for line in lines for p in (line or "").split(",") if p.strip()]


def confirm_address(vendor: Vendor, address_1: str, address_2: str, user_id: int,
                    profile: BcTargetProfile) -> dict:
    """Record a reviewer's one-click confirmation (plan section 7).

    `address_1`/`address_2` are the lines the reviewer approved -- either the
    stored lines (acknowledging an extraction-time rebalance) or a gate
    proposal (a re-layout of stored text). Accepted only when they are a
    lossless, order-preserving re-layout of the stored text (same fragments,
    same order, legacy Address 3/4 included) AND fit the BC limits; this
    endpoint cannot be used to write arbitrary new text -- that is what the
    normal edit is for. On success the lines are written, Address 3/4 are
    cleared, and the hash-bound confirmation is stored on the vendor.
    """
    a1, a2 = (address_1 or "").strip(), (address_2 or "").strip()
    stored = _lines(vendor)
    if _fragments(a1, a2) != _fragments(*stored):
        raise ConfirmationRejected(
            "confirmed lines must contain exactly the stored address fragments, in the same order"
        )
    limits = profile.address_limits()
    if len(a1) > limits.address_1_max or len(a2) > limits.address_2_max:
        raise ConfirmationRejected(
            f"confirmed lines exceed the BC limits ({limits.address_1_max}/{limits.address_2_max})"
        )

    vendor.address_1, vendor.address_2 = a1, a2
    vendor.address_3 = vendor.address_4 = ""
    vendor.address_review = {
        "reason_code": REASON_BC_LENGTH_REBALANCE,
        "final_address_1": a1,
        "final_address_2": a2,
        "values_sha256": address_values_hash(a1, a2),
        "confirmed_by_user_id": user_id,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }
    return vendor.address_review
