"""Business Central target profile: the constraint registry for the address
representation layer (docs/ADDRESS_SEGMENTATION_PLAN.md §9).

Every BC field-length limit used by the address representation / BC fit code
(`extraction_pipeline/extract/bc_address_fit.py`,
`extraction_pipeline/extract/address_representation.py`, `services/bc_mapper.py`)
comes from here, never from a literal in that code -- see
`tests/test_bc_target_profile.py`'s grep test. This is deliberate: BC's
limits are per-product-version/tenant, and the plan's whole point is that
changing them is a config edit, not a code change.

Unlike `address_lookups.segmentation_keywords()` (which degrades gracefully
when its data file is missing, because address segmentation still has a
usable fallback), a missing or incomplete BC profile is a HARD FAILURE: there
is no safe default field-length limit to fall back to, and silently using one
is exactly the "afterthought" bug this plan exists to fix. `load_profile()`
raises rather than returning partial/empty data.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve()
_BC_TARGETS_DIR = _HERE.parents[2] / "config" / "bc_targets"

# Every constraint ID the address representation / BC layer relies on. A
# profile YAML missing any of these fails to load -- see load_profile().
_REQUIRED_CONSTRAINT_IDS = frozenset({
    "BC_ADDRESS_1_MAX_LENGTH",
    "BC_ADDRESS_2_MAX_LENGTH",
    "BC_CITY_MAX_LENGTH",
    "BC_COUNTY_MAX_LENGTH",
    "BC_POST_CODE_MAX_LENGTH",
    "BC_COUNTRY_CODE_MAX_LENGTH",
    "BC_NO_ADDRESS_3_4",
})


class BcProfileError(RuntimeError):
    """A BC target profile is missing, malformed, or missing a required
    constraint ID. Raised rather than degrading to a default, because there
    is no safe default BC field-length limit (see module docstring)."""


@dataclass(frozen=True)
class AddressLimits:
    """The two limits `bc_address_fit.py` checks/rebalances against, plus the
    separator used to join fragments back into one line."""

    address_1_max: int
    address_2_max: int
    separator: str


@dataclass(frozen=True)
class BcTargetProfile:
    name: str
    raw: dict

    def limit(self, constraint_id: str) -> int:
        """The `value` of one length constraint (characters). Raises
        BcProfileError for an unknown ID or a non-length constraint (use
        `.constraint()` for those) -- callers should never silently get 0."""
        c = self.raw["constraints"].get(constraint_id)
        if c is None:
            raise BcProfileError(
                f"profile {self.name!r} has no constraint {constraint_id!r}"
            )
        value = c.get("value")
        if not isinstance(value, int):
            raise BcProfileError(
                f"constraint {constraint_id!r} in profile {self.name!r} "
                f"has no numeric length value (got {value!r})"
            )
        return value

    def constraint(self, constraint_id: str) -> dict:
        """The full constraint record ({bc_field, portal, value, category,
        registry, ...}), for constraints without a simple numeric length
        (e.g. BC_NO_ADDRESS_3_4)."""
        c = self.raw["constraints"].get(constraint_id)
        if c is None:
            raise BcProfileError(
                f"profile {self.name!r} has no constraint {constraint_id!r}"
            )
        return c

    def address_limits(self, separator: str | None = None) -> AddressLimits:
        return AddressLimits(
            address_1_max=self.limit("BC_ADDRESS_1_MAX_LENGTH"),
            address_2_max=self.limit("BC_ADDRESS_2_MAX_LENGTH"),
            separator=separator if separator is not None else self.raw.get("separator", ", "),
        )

    def country_code(self, country_name: str) -> str | None:
        """BC Country/Region Code for a country name (e.g. "India" -> "IN"),
        or None if the name has no mapping in this profile (caller should
        raise/flag INVALID_COUNTRY, never guess)."""
        codes = self.raw.get("country_codes") or {}
        return codes.get(country_name)

    def county_abbreviation(self, state_name: str) -> str | None:
        """A configured shorter County value for a state name that exceeds
        BC_COUNTY_MAX_LENGTH, or None if none is configured (plan §16, Q21)."""
        abbrevs = self.raw.get("county_abbreviations") or {}
        return abbrevs.get(state_name)


@lru_cache(maxsize=8)
def load_profile(name: str) -> BcTargetProfile:
    """Load and validate `backend/config/bc_targets/<name>.yaml`.

    Raises BcProfileError if the file is missing, is not a mapping, has no
    `constraints` section, or is missing any of `_REQUIRED_CONSTRAINT_IDS`.
    Cached per process -- call `load_profile.cache_clear()` in tests that
    swap the file on disk.
    """
    path = _BC_TARGETS_DIR / f"{name}.yaml"
    if not path.is_file():
        raise BcProfileError(f"BC target profile file not found: {path}")

    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise BcProfileError(f"BC target profile {path} is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise BcProfileError(f"BC target profile {path} did not parse to a mapping")

    constraints = data.get("constraints")
    if not isinstance(constraints, dict):
        raise BcProfileError(f"BC target profile {path} has no 'constraints' mapping")

    missing = _REQUIRED_CONSTRAINT_IDS - constraints.keys()
    if missing:
        raise BcProfileError(
            f"BC target profile {path} is missing required constraints: {sorted(missing)}"
        )

    return BcTargetProfile(name=name, raw=data)
