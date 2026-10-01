"""Orchestrates the presentation fallback (step 5) and the BC representation
layer (steps 6-9) on top of an already-segmented address.

See docs/ADDRESS_SEGMENTATION_PLAN.md §§1-4, 6-8. This module is the ONE
place semantic information (fragment tier/role) and BC representation
(length limits, rebalancing) meet -- and even here they are kept apart:

  * `SemanticLayout` / `LayoutFragment` carry `semantic_role`, set once from
    `address_segmenter`'s output and NEVER rewritten (plan §1: "SEMANTIC
    ROLE != FINAL BC FIELD").
  * All BC-length knowledge is delegated to `bc_address_fit` (Layer 2),
    which never sees a semantic role -- only fragment text and a boundary
    index.
  * This module's own job is bookkeeping: applying the step-5 fallback
    exactly once, calling Layer 2, and recording what happened in
    `AddressTransform` provenance entries so nothing here is a silent edit.

No BC field-length literal appears in this file either -- see
tests/test_bc_target_profile.py's grep test (extended to this module).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum

from app.services.bc_target_profile import AddressLimits

from .bc_address_fit import FitStatus, rebalance, validate_final

ADDRESS_1 = "ADDRESS_1"
ADDRESS_2 = "ADDRESS_2"

# Reason codes (plan §7's decision table; DESIGN §2 taxonomy extended per
# plan §16 D4). These are the only reason codes this module emits.
REASON_ADDRESS_1_BACKFILLED = "ADDRESS_1_BACKFILLED"
REASON_BC_LENGTH_REBALANCE = "ADDRESS_BC_LENGTH_REBALANCE"
REASON_ADDRESS_OVERFLOW = "ADDRESS_OVERFLOW"
REASON_ADDRESS_INVARIANT_VIOLATION = "ADDRESS_INVARIANT_VIOLATION"

AUTO_FIX = "AUTO_FIX"
MANUAL_REVIEW = "MANUAL_REVIEW"
BLOCK_SUBMISSION = "BLOCK_SUBMISSION"
AUTO_PASS = "AUTO_PASS"

# Backfill variant names (plan §4).
RULE_LEADING_THOROUGHFARE = "leading_thoroughfare"
RULE_FIRST_1_2_FRAGMENTS = "first_1_2_fragments"


class DecisionStatus(str, Enum):
    AUTO_PASS = AUTO_PASS
    AUTO_FIX = AUTO_FIX
    MANUAL_REVIEW = MANUAL_REVIEW
    BLOCK = BLOCK_SUBMISSION


@dataclass(frozen=True)
class LayoutFragment:
    """One address fragment, carrying both what it MEANS (semantic_role, set
    once, plan §1) and where it currently sits (final_bc_field, moved_by --
    updated as steps 5/7 run). `index` is this fragment's position in the
    ORIGINAL source order and is never reassigned."""

    index: int
    text: str
    tier: str
    # The semantic LINE this fragment belongs to after step 4 (the initial
    # contiguous ADDRESS_1-role run, never reopened): ADDRESS_1 iff
    # index < semantic_boundary. Immutable after creation.
    semantic_role: str
    final_bc_field: str         # ADDRESS_1 or ADDRESS_2 -- may change
    moved_by: str | None = None  # reason_code of the transform that last moved it, if any
    # The role this fragment's tier maps to IN ISOLATION (_address_role).
    # Differs from semantic_role when the boundary rule overrides it, e.g.
    # "Block C" after "Sunrise Apartments": tier_role ADDRESS_1, semantic_role
    # ADDRESS_2. Audit-only; never used to move a fragment.
    tier_role: str = ""


@dataclass(frozen=True)
class SemanticLayout:
    """Layer 1's finished, immutable output: fragments with their semantic
    roles, and the semantic boundary (plan §2 stage 4). Built once by
    `layout_from_segmented()` / `layout_from_stored()` and never mutated --
    every later step reads it but produces its own new `AddressLayout`."""

    fragments: tuple[LayoutFragment, ...]
    semantic_boundary: int          # length of the initial contiguous ADDRESS_1-role run
    thoroughfare_fallback_applied: bool = False  # _split_by_role's own leading_thoroughfare fallback

    @property
    def semantic_address_1(self) -> str:
        return ", ".join(f.text for f in self.fragments[: self.semantic_boundary])

    @property
    def semantic_address_2(self) -> str:
        return ", ".join(f.text for f in self.fragments[self.semantic_boundary :])


@dataclass(frozen=True)
class AddressTransform:
    """One provenance entry (plan §8). `layer` is "semantic" (recorded
    once, boundary_before==boundary_after), "presentation_fallback", or
    "bc_representation"."""

    layer: str
    transformation: str
    reason_code: str | None
    automation_class: str
    boundary_before: int
    boundary_after: int
    moved_fragment_indices: tuple[int, ...]
    original_address_1: str
    original_address_2: str
    final_address_1: str
    final_address_2: str
    manual_review_required: bool
    constraint: str | None = None
    constraint_value: int | None = None
    profile: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict:
        d = {
            "layer": self.layer,
            "transformation": self.transformation,
            "reason_code": self.reason_code,
            "automation_class": self.automation_class,
            "boundary_before": self.boundary_before,
            "boundary_after": self.boundary_after,
            "moved_fragment_indices": list(self.moved_fragment_indices),
            "original_address_1": self.original_address_1,
            "original_address_2": self.original_address_2,
            "final_address_1": self.final_address_1,
            "final_address_2": self.final_address_2,
            "manual_review_required": self.manual_review_required,
            "review": None,
        }
        if self.constraint is not None:
            d["constraint"] = self.constraint
        if self.constraint_value is not None:
            d["constraint_value"] = self.constraint_value
        if self.profile is not None:
            d["profile"] = self.profile
        if self.detail:
            d["detail"] = self.detail
        return d


@dataclass(frozen=True)
class AddressFinding:
    """One review-worthy or blocking fact about the address, ready to feed
    into semantic_engine._flag / the payload gate (plan §7, §8)."""

    reason_code: str
    automation_class: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {"reason_code": self.reason_code, "automation_class": self.automation_class,
                "detail": self.detail}


@dataclass(frozen=True)
class AddressLayout:
    fragments: tuple[LayoutFragment, ...]
    boundary: int

    @property
    def address_1(self) -> str:
        return ", ".join(f.text for f in self.fragments[: self.boundary])

    @property
    def address_2(self) -> str:
        return ", ".join(f.text for f in self.fragments[self.boundary :])


@dataclass(frozen=True)
class AddressDecision:
    semantic: SemanticLayout
    final: AddressLayout
    transforms: tuple[AddressTransform, ...]
    findings: tuple[AddressFinding, ...]
    status: DecisionStatus

    @property
    def address_1(self) -> str:
        return self.final.address_1

    @property
    def address_2(self) -> str:
        return self.final.address_2


# ---------------------------------------------------------------------------
# building a SemanticLayout
# ---------------------------------------------------------------------------

def layout_from_segmented(seg_result) -> SemanticLayout:
    """Build a SemanticLayout from an `address_segmenter.SegmentedAddress`.
    Reads `seg_result.fragments` (flat, source order) and the additive
    `semantic_boundary` / `fallback_applied` fields -- does not re-derive
    role assignment (that stays entirely inside address_segmenter)."""
    from .address_segmenter import _address_role  # tier -> role, pure (plan §3: unchanged)

    b = seg_result.semantic_boundary
    layout_fragments = tuple(
        LayoutFragment(
            index=f.index, text=f.text, tier=f.tier,
            semantic_role=ADDRESS_1 if pos < b else ADDRESS_2,
            final_bc_field=ADDRESS_1 if pos < b else ADDRESS_2,
            tier_role=_address_role(f.tier, f.evidence),
        )
        for pos, f in enumerate(seg_result.fragments)
    )
    return SemanticLayout(
        fragments=layout_fragments,
        semantic_boundary=seg_result.semantic_boundary,
        thoroughfare_fallback_applied=seg_result.fallback_applied,
    )


def layout_from_stored(a1: str, a2: str, a3: str = "", a4: str = "") -> SemanticLayout:
    """Recover a SemanticLayout from STORED text (plan §6 "Gate mode"; §2
    "Fragment recovery from stored text"). Used by the stage-11 payload gate
    on human-edited or legacy values. Fragments are recovered by splitting
    on "," -- this round-trips exactly because fragments never contain
    commas (segmenter never injects one into fragment text).

    Legacy `address_3`/`address_4` content (plan T-ADR-07) is folded into
    the recovered Address-2 fragment list, in order, after address_2's own
    fragments -- so a rebalance proposal can consider ALL of the address's
    original text, never silently dropping the 3/4 lines.

    Recovered fragments carry no real tier/semantic_role -- there is no
    classifier re-run here (plan §4: "do not run semantic classification
    again"). They are tagged tier="unknown_recovered" and semantic_role is
    set to whichever side of the stored boundary they came from, so
    `AddressLayout.address_1`/`.address_2` still reflect the STORED split
    when nothing needs to move.
    """
    a1_frags = [s.strip() for s in a1.split(",") if s.strip()]
    a2_frags = [s.strip() for s in a2.split(",") if s.strip()]
    a3_frags = [s.strip() for s in a3.split(",") if s.strip()]
    a4_frags = [s.strip() for s in a4.split(",") if s.strip()]

    all_texts = a1_frags + a2_frags + a3_frags + a4_frags
    boundary = len(a1_frags)
    layout_fragments = tuple(
        LayoutFragment(
            index=i, text=t, tier="unknown_recovered",
            semantic_role=ADDRESS_1 if i < boundary else ADDRESS_2,
            final_bc_field=ADDRESS_1 if i < boundary else ADDRESS_2,
        )
        for i, t in enumerate(all_texts)
    )
    return SemanticLayout(fragments=layout_fragments, semantic_boundary=boundary)


# ---------------------------------------------------------------------------
# step 5: A1-empty presentation fallback
# ---------------------------------------------------------------------------

def apply_a1_fallback(sem: SemanticLayout) -> tuple[AddressLayout, AddressTransform | None]:
    """Step 5 (plan §4). Returns (layout_after_step_5, transform_or_None).

    Exactly one variant fires, and only when semantic_boundary == 0 and at
    least one fragment exists:

      * leading_thoroughfare: `sem.thoroughfare_fallback_applied` is True
        (address_segmenter's OWN fallback already promoted fragment 0 for
        exactly this reason -- see its docstring). This function does not
        re-derive that decision; it only RECORDS it as a fallback transform
        with boundary 0 -> 1, and then STOPS: first_1_2_fragments never
        also runs (plan decision, user-confirmed).
      * first_1_2_fragments: otherwise, boundary 0 -> (1 if n<=2 else 2).

    If semantic_boundary > 0 (a real premise run exists) this is a no-op:
    (AddressLayout matching the semantic layout unchanged, None).
    """
    n = len(sem.fragments)
    semantic_layout = AddressLayout(fragments=sem.fragments, boundary=sem.semantic_boundary)

    if sem.semantic_boundary != 0 or n == 0:
        return semantic_layout, None

    if sem.thoroughfare_fallback_applied:
        new_boundary = 1
        rule = RULE_LEADING_THOROUGHFARE
    else:
        new_boundary = 1 if n <= 2 else 2
        rule = RULE_FIRST_1_2_FRAGMENTS

    moved_indices = tuple(f.index for f in sem.fragments[:new_boundary])
    new_fragments = _move(sem.fragments, moved_indices, ADDRESS_1, REASON_ADDRESS_1_BACKFILLED)
    new_layout = AddressLayout(fragments=new_fragments, boundary=new_boundary)

    transform = AddressTransform(
        layer="presentation_fallback",
        transformation=rule,
        reason_code=REASON_ADDRESS_1_BACKFILLED,
        automation_class=AUTO_FIX,
        boundary_before=0,
        boundary_after=new_boundary,
        moved_fragment_indices=moved_indices,
        original_address_1=semantic_layout.address_1,
        original_address_2=semantic_layout.address_2,
        final_address_1=new_layout.address_1,
        final_address_2=new_layout.address_2,
        manual_review_required=False,
    )
    return new_layout, transform


# ---------------------------------------------------------------------------
# steps 6-9: BC constraint validation, rebalance, final validation, decision
# ---------------------------------------------------------------------------

def represent_address(
    sem: SemanticLayout,
    limits: AddressLimits,
    *,
    profile_name: str = "",
    geography: Mapping[str, str] | None = None,
    mode: str = "apply",
) -> AddressDecision:
    """Runs steps 5-9 (plan §2) and returns the full decision.

    `mode="apply"` (the normal extraction-time path) actually applies the
    step-5 fallback and the step-7 rebalance to produce final text.
    `mode="check"` (the stage-11 payload gate) runs the identical logic but
    is intended to be called on a SemanticLayout built by
    `layout_from_stored()`, whose "semantic_boundary" is really the STORED
    boundary -- the gate treats any resulting rebalance as a PROPOSAL, never
    applying it to the stored record itself (the gate's caller is
    responsible for not persisting `decision.final` when mode="check").

    `geography` is the extracted {city, state, country, pin_code} -- used
    only for the BC-07 guard in step 8; never mutated, never consulted to
    move a fragment (plan §4 "Geography safety").
    """
    transforms: list[AddressTransform] = []
    findings: list[AddressFinding] = []

    # step 5
    after_fallback, fallback_transform = apply_a1_fallback(sem)
    floor = after_fallback.boundary if fallback_transform is not None else 0
    if fallback_transform is not None:
        transforms.append(fallback_transform)

    fragment_texts = [f.text for f in after_fallback.fragments]

    # steps 6-7
    fit = rebalance(fragment_texts, after_fallback.boundary, limits, floor=floor)

    if fit.status == FitStatus.FIT:
        final_layout = after_fallback
    elif fit.status == FitStatus.REBALANCED:
        shift_right = fit.boundary > after_fallback.boundary
        if shift_right:
            # A2 too long: fragments cross from A2 into A1
            moved = after_fallback.fragments[after_fallback.boundary : fit.boundary]
            to_field, constraint_id = ADDRESS_1, "BC_ADDRESS_2_MAX_LENGTH"
            constraint_value = limits.address_2_max
        else:
            # A1 too long: fragments cross from A1 into A2
            moved = after_fallback.fragments[fit.boundary : after_fallback.boundary]
            to_field, constraint_id = ADDRESS_2, "BC_ADDRESS_1_MAX_LENGTH"
            constraint_value = limits.address_1_max
        moved_indices = tuple(f.index for f in moved)
        new_fragments = _move(after_fallback.fragments, moved_indices, to_field,
                              REASON_BC_LENGTH_REBALANCE)
        final_layout = AddressLayout(fragments=new_fragments, boundary=fit.boundary)
        rebalance_transform = AddressTransform(
            layer="bc_representation",
            transformation="bc_boundary_shift_right" if shift_right else "bc_boundary_shift_left",
            reason_code=REASON_BC_LENGTH_REBALANCE,
            automation_class=MANUAL_REVIEW,
            constraint=constraint_id,
            constraint_value=constraint_value,
            profile=profile_name or None,
            boundary_before=after_fallback.boundary,
            boundary_after=fit.boundary,
            moved_fragment_indices=moved_indices,
            original_address_1=after_fallback.address_1,
            original_address_2=after_fallback.address_2,
            final_address_1=final_layout.address_1,
            final_address_2=final_layout.address_2,
            manual_review_required=True,
        )
        transforms.append(rebalance_transform)
        findings.append(AddressFinding(
            reason_code=REASON_BC_LENGTH_REBALANCE, automation_class=MANUAL_REVIEW,
            detail=f"boundary moved {after_fallback.boundary}->{fit.boundary} to satisfy {constraint_id}",
        ))
    else:  # OVERFLOW -- values unchanged, never truncated
        # "MANUAL_REVIEW / BLOCK" in the plan's decision table means
        # BLOCK_SUBMISSION, resolved by a human edit on the review screen
        # (plan §0 "Rule categories"). The edited values re-enter at step 6.
        final_layout = after_fallback
        findings.append(AddressFinding(
            reason_code=REASON_ADDRESS_OVERFLOW, automation_class=BLOCK_SUBMISSION,
            detail=fit.detail or "no whole-fragment boundary satisfies both BC limits",
        ))

    # step 8: final validation. Length invariants (BC-01/BC-02) are only
    # meaningful when step 7 claimed success (FIT/REBALANCED); an OVERFLOW
    # already carries its own BLOCK finding and is expected to exceed the
    # limits, so re-flagging it as an invariant violation would double-report.
    invariant_violations: list[str] = []
    if fit.status != FitStatus.OVERFLOW:
        invariant_violations += validate_final(fragment_texts, final_layout.boundary, limits)
    invariant_violations += _check_geography_leak(final_layout, geography or {})
    invariant_violations += _check_semantic_role_preserved(sem, final_layout)
    if invariant_violations:
        findings.append(AddressFinding(
            reason_code=REASON_ADDRESS_INVARIANT_VIOLATION, automation_class=BLOCK_SUBMISSION,
            detail=f"violated: {', '.join(invariant_violations)}",
        ))

    # step 9: decision
    if any(f.automation_class == BLOCK_SUBMISSION for f in findings):
        status = DecisionStatus.BLOCK
    elif any(f.automation_class == MANUAL_REVIEW for f in findings):
        status = DecisionStatus.MANUAL_REVIEW
    elif fallback_transform is not None:
        status = DecisionStatus.AUTO_FIX
    else:
        status = DecisionStatus.AUTO_PASS

    return AddressDecision(
        semantic=sem, final=final_layout,
        transforms=tuple(transforms), findings=tuple(findings), status=status,
    )


def _move(
    fragments: tuple[LayoutFragment, ...],
    indices: tuple[int, ...],
    to_field: str,
    reason_code: str,
) -> tuple[LayoutFragment, ...]:
    """Copy of `fragments` with the given indices re-tagged to `to_field`.
    Only final_bc_field/moved_by change -- text, order, semantic_role and
    tier_role are carried over untouched (BC-09)."""
    moving = set(indices)
    return tuple(
        replace(f, final_bc_field=to_field, moved_by=reason_code) if f.index in moving else f
        for f in fragments
    )


def _check_geography_leak(layout: AddressLayout, geography: Mapping[str, str]) -> list[str]:
    """BC-07 (plan §4/§10): no A1/A2 fragment may equal an EXTRACTED
    geography value (city / state / country / pin_code) or an alias of one.

    Structural prevention already makes this nearly impossible (fragments
    come from the post-geography-peel list); this is defence in depth. It
    deliberately compares against the values the resolver actually
    extracted, not against every gazetteer name: a district that was NOT
    chosen as the city (e.g. "Tikamgarh" when the city is "Niwari") is a
    legitimate address fragment. Aliases are matched through the same
    canonical_city/canonical_state lookups the resolver uses, so
    "Sahibzada Ajit Singh Nagar" counts as the city "S.A.S Nagar"."""
    from .address_lookups import canonical_city, canonical_state

    city = (geography.get("city") or "").strip()
    state = (geography.get("state") or "").strip()
    plain = {v.strip().casefold() for v in geography.values() if v and v.strip()}
    if not plain:
        return []
    for f in layout.fragments:
        text = f.text.strip()
        if text.casefold() in plain:
            return ["BC-07"]
        if city and (canonical_city(text) or "").casefold() == city.casefold():
            return ["BC-07"]
        if state and (canonical_state(text) or "").casefold() == state.casefold():
            return ["BC-07"]
    return []


def _check_semantic_role_preserved(sem: SemanticLayout, final: AddressLayout) -> list[str]:
    """BC-09: semantic_role must be identical, per fragment index, between
    the semantic layout and the final layout -- only final_bc_field may
    differ. Also re-checks BC-04/BC-05 (no loss/duplication) and BC-06
    (order preserved) at the whole-pipeline level, since `after_fallback`
    and the rebalance step each construct a fresh fragment tuple."""
    sem_by_index = {f.index: f.semantic_role for f in sem.fragments}
    final_indices = [f.index for f in final.fragments]

    if sorted(final_indices) != sorted(sem_by_index.keys()) or len(final_indices) != len(set(final_indices)):
        return ["BC-04"]  # loss or duplication
    if final_indices != sorted(final_indices):
        return ["BC-06"]  # order not preserved
    for f in final.fragments:
        if f.semantic_role != sem_by_index[f.index]:
            return ["BC-09"]
    return []
