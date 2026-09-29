"""Layer 2: Business Central representation constraints for an address.

See docs/ADDRESS_SEGMENTATION_PLAN.md §§5-6 for the full design. This module
knows NOTHING about address semantics (fragment tiers, roles, "premise" vs
"locality") -- it only ever sees an ordered list of opaque text fragments
and a boundary index, and answers exactly one question: "does the text at
this boundary fit Business Central's field limits, and if not, can the
boundary move (whole fragments only) to make it fit?"

This is deliberately separate from `address_representation.py` (Layer 1 +
the presentation fallback), which is the only caller that knows what a
fragment MEANS. Keeping the two apart is the plan's core requirement: a BC
length limit must never be the reason a fragment is classified as Address 1
or Address 2 (plan §1, "SEMANTIC ROLE != FINAL BC FIELD").

No BC field-length literal appears in this file -- every limit comes from
`bc_target_profile.AddressLimits`, passed in by the caller. See
tests/test_bc_target_profile.py's grep test and
tests/test_bc_address_fit.py, which enforces the same rule on this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.services.bc_target_profile import AddressLimits

FRAGMENT_TOO_LONG = "fragment_too_long"


class FitStatus(str, Enum):
    FIT = "FIT"                    # boundary unchanged, both lines within limits
    REBALANCED = "REBALANCED"      # boundary moved; both lines now within limits
    OVERFLOW = "OVERFLOW"          # no whole-fragment boundary fits; values unchanged


@dataclass(frozen=True)
class FitResult:
    boundary: int                  # the (possibly new) boundary
    status: FitStatus
    detail: str = ""               # set to FRAGMENT_TOO_LONG on that specific overflow cause


def _joined_len(fragments: list[str], i: int, j: int, sep: str) -> int:
    return len(sep.join(fragments[i:j]))


def check_constraints(a1_text: str, a2_text: str, limits: AddressLimits) -> list[str]:
    """Violated constraint IDs for the given joined A1/A2 text, or [] if both
    fit. Pure length check -- no fragment knowledge, no mutation."""
    violated = []
    if len(a1_text) > limits.address_1_max:
        violated.append("BC_ADDRESS_1_MAX_LENGTH")
    if len(a2_text) > limits.address_2_max:
        violated.append("BC_ADDRESS_2_MAX_LENGTH")
    return violated


def rebalance(
    fragments: list[str],
    boundary: int,
    limits: AddressLimits,
    floor: int = 0,
) -> FitResult:
    """Attempt a deterministic, order-preserving, whole-fragment boundary
    shift so that `sep.join(fragments[:b])` fits `address_1_max` and
    `sep.join(fragments[b:])` fits `address_2_max`.

    `floor` is the minimum boundary this call may return -- it exists so a
    caller that already ran the step-5 A1-empty fallback can prevent this
    function from shifting left past that fallback's own boundary (plan §6
    condition 12: "never reverses a step-5 move"; plan §2: no A1<->A2
    oscillation). Callers that did not run a fallback pass floor=0.

    Never truncates, never drops/reorders/duplicates a fragment, never moves
    part of a fragment -- the unit of movement is always one complete
    fragment (plan §6). If no whole-fragment boundary satisfies both limits,
    returns OVERFLOW with the ORIGINAL boundary and fragments untouched.
    """
    sep = limits.separator
    n = len(fragments)

    if n == 0:
        return FitResult(boundary=boundary, status=FitStatus.FIT)

    a1_len = _joined_len(fragments, 0, boundary, sep)
    a2_len = _joined_len(fragments, boundary, n, sep)
    if a1_len <= limits.address_1_max and a2_len <= limits.address_2_max:
        return FitResult(boundary=boundary, status=FitStatus.FIT)

    # A2 too long (A1, if anything, is already within its own limit): shift
    # RIGHT only, one fragment at a time, stopping at the first boundary
    # where A2 fits -- the smallest possible move (plan §6 condition 12).
    if a2_len > limits.address_2_max and a1_len <= limits.address_1_max:
        for nb in range(boundary + 1, n + 1):
            if _joined_len(fragments, 0, nb, sep) > limits.address_1_max:
                break  # A1 would itself overflow by absorbing this fragment
            if _joined_len(fragments, nb, n, sep) <= limits.address_2_max:
                return FitResult(boundary=nb, status=FitStatus.REBALANCED)

    # A1 too long (A2 already fits): shift LEFT only, down to `floor` (never
    # below it -- never undoes a step-5 backfill, never empties A1 below
    # what the fallback already guaranteed).
    elif a1_len > limits.address_1_max and a2_len <= limits.address_2_max:
        for nb in range(boundary - 1, floor - 1, -1):
            if _joined_len(fragments, nb, n, sep) > limits.address_2_max:
                break
            if _joined_len(fragments, 0, nb, sep) <= limits.address_1_max:
                return FitResult(boundary=nb, status=FitStatus.REBALANCED)

    # Both too long, or no whole-fragment boundary satisfies both limits
    # (granularity overflow, or a single fragment exceeds a limit on its
    # own -- see whether any individual fragment is unplaceable, for the
    # more specific `detail`).
    for frag in fragments:
        if len(frag) > limits.address_1_max:
            return FitResult(boundary=boundary, status=FitStatus.OVERFLOW, detail=FRAGMENT_TOO_LONG)
    return FitResult(boundary=boundary, status=FitStatus.OVERFLOW)


def validate_final(fragments: list[str], boundary: int, limits: AddressLimits) -> list[str]:
    """Length/boundary validation (plan §8, invariants BC-01/BC-02/BC-06).
    Returns a list of violated invariant IDs (empty = all pass).

    This module only ever moves a boundary index over the SAME fragment
    list it was given -- it never reorders, drops, duplicates or invents a
    fragment (there is no code path here that could). So BC-04/BC-05
    (no loss/no duplication) and BC-03 (no truncation) are structural
    guarantees of this module's design, not something to re-check at
    runtime here. What a caller CAN get wrong is passing an out-of-range or
    otherwise inconsistent boundary, which is what BC-06 catches.

    Geography (BC-07) and provenance/semantic-role preservation (BC-08/09)
    require information this module deliberately does not have (fragment
    text alone carries no semantic role or geography tag) -- those are
    checked in `address_representation.py`, which holds that information.
    """
    violations: list[str] = []
    n = len(fragments)
    sep = limits.separator

    if not (0 <= boundary <= n):
        violations.append("BC-06")
        return violations

    a1_text = sep.join(fragments[:boundary])
    a2_text = sep.join(fragments[boundary:])

    if len(a1_text) > limits.address_1_max:
        violations.append("BC-01")
    if len(a2_text) > limits.address_2_max:
        violations.append("BC-02")

    return violations
