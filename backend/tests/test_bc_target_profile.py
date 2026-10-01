"""Tests for the BC target profile loader (docs/ADDRESS_SEGMENTATION_PLAN.md §9).

Covers: the shipped profile loads and validates; a missing/incomplete/
malformed profile fails loudly rather than degrading; and the "no BC
field-length literal outside the profile YAML" grep test (plan §9, §10 BC-03
note, §17 "hard-coded limits").
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest

from app.services.bc_target_profile import (
    BcProfileError,
    load_profile,
)

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_BC_LAYER_MODULES = [
    _BACKEND_DIR / "app" / "services" / "extraction_pipeline" / "extract" / "bc_address_fit.py",
    _BACKEND_DIR / "app" / "services" / "extraction_pipeline" / "extract" / "address_representation.py",
]


class TestShippedProfile:
    def setup_method(self):
        load_profile.cache_clear()

    def test_loads_without_error(self):
        profile = load_profile("bc22_in_vendorcard")
        assert profile.name == "bc22_in_vendorcard"

    def test_address_limits(self):
        limits = load_profile("bc22_in_vendorcard").address_limits()
        assert limits.address_1_max == 100
        assert limits.address_2_max == 50
        assert limits.separator == ", "

    def test_all_required_constraints_present(self):
        profile = load_profile("bc22_in_vendorcard")
        for cid in (
            "BC_ADDRESS_1_MAX_LENGTH", "BC_ADDRESS_2_MAX_LENGTH",
            "BC_CITY_MAX_LENGTH", "BC_COUNTY_MAX_LENGTH",
            "BC_POST_CODE_MAX_LENGTH", "BC_COUNTRY_CODE_MAX_LENGTH",
        ):
            assert isinstance(profile.limit(cid), int)
        assert profile.constraint("BC_NO_ADDRESS_3_4")["value"] == "empty"

    def test_city_county_post_code_country_limits(self):
        profile = load_profile("bc22_in_vendorcard")
        assert profile.limit("BC_CITY_MAX_LENGTH") == 30
        assert profile.limit("BC_COUNTY_MAX_LENGTH") == 30
        assert profile.limit("BC_POST_CODE_MAX_LENGTH") == 20
        assert profile.limit("BC_COUNTRY_CODE_MAX_LENGTH") == 10

    def test_country_code_lookup(self):
        profile = load_profile("bc22_in_vendorcard")
        assert profile.country_code("India") == "IN"
        assert profile.country_code("Narnia") is None

    def test_county_abbreviation_absent_by_default(self):
        profile = load_profile("bc22_in_vendorcard")
        assert profile.county_abbreviation("Dadra and Nagar Haveli and Daman and Diu") is None

    def test_unknown_constraint_id_raises(self):
        profile = load_profile("bc22_in_vendorcard")
        with pytest.raises(BcProfileError):
            profile.limit("BC_DOES_NOT_EXIST")

    def test_cached_by_name(self):
        assert load_profile("bc22_in_vendorcard") is load_profile("bc22_in_vendorcard")


class TestFailsLoudly:
    """A missing/incomplete/malformed profile must raise, never silently
    degrade to a default limit (module docstring: no safe default exists)."""

    def setup_method(self):
        load_profile.cache_clear()

    def teardown_method(self):
        load_profile.cache_clear()

    def test_missing_file_raises(self):
        with pytest.raises(BcProfileError):
            load_profile("does_not_exist_anywhere")

    def test_missing_constraint_raises(self, tmp_path, monkeypatch):
        import app.services.bc_target_profile as mod

        bad_dir = tmp_path / "bc_targets"
        bad_dir.mkdir()
        (bad_dir / "incomplete.yaml").write_text(
            textwrap.dedent(
                """
                separator: ", "
                constraints:
                  BC_ADDRESS_1_MAX_LENGTH: {value: 100}
                """
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "_BC_TARGETS_DIR", bad_dir)
        with pytest.raises(BcProfileError, match="missing required constraints"):
            load_profile("incomplete")

    def test_not_a_mapping_raises(self, tmp_path, monkeypatch):
        import app.services.bc_target_profile as mod

        bad_dir = tmp_path / "bc_targets"
        bad_dir.mkdir()
        (bad_dir / "listy.yaml").write_text("- 1\n- 2\n", encoding="utf-8")
        monkeypatch.setattr(mod, "_BC_TARGETS_DIR", bad_dir)
        with pytest.raises(BcProfileError, match="mapping"):
            load_profile("listy")

    def test_malformed_yaml_raises(self, tmp_path, monkeypatch):
        import app.services.bc_target_profile as mod

        bad_dir = tmp_path / "bc_targets"
        bad_dir.mkdir()
        (bad_dir / "broken.yaml").write_text("constraints: [unclosed\n", encoding="utf-8")
        monkeypatch.setattr(mod, "_BC_TARGETS_DIR", bad_dir)
        with pytest.raises(BcProfileError):
            load_profile("broken")

    def test_no_constraints_section_raises(self, tmp_path, monkeypatch):
        import app.services.bc_target_profile as mod

        bad_dir = tmp_path / "bc_targets"
        bad_dir.mkdir()
        (bad_dir / "nokeys.yaml").write_text("target: {product: BC}\n", encoding="utf-8")
        monkeypatch.setattr(mod, "_BC_TARGETS_DIR", bad_dir)
        with pytest.raises(BcProfileError, match="constraints"):
            load_profile("nokeys")


class TestNoHardcodedLimitsInBcLayerCode:
    """Grep guard: BC address-line length literals (100, 50, and the combined
    152) must never appear as executable-code literals in the BC
    representation layer modules -- they come from the profile only (plan
    §9, §17). Lines inside a docstring/comment, or explicitly marked
    `# literal-ok`, are exempt (they document the *current* profile value,
    they don't hard-code it)."""

    _LITERAL_RE = re.compile(r"(?<![\w.])(100|50|152)(?![\w.])")

    def _code_lines(self, text: str) -> list[tuple[int, str]]:
        """Executable-code lines only: strips triple-quoted docstrings and
        single-line comments. Coarse but sufficient for this guard -- these
        are small, hand-written modules."""
        out: list[tuple[int, str]] = []
        in_docstring = False
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if '"""' in stripped or "'''" in stripped:
                # toggle for every triple-quote marker on the line; a line
                # that both opens and closes a docstring contributes 0 net
                # toggles, matching how Python itself parses it.
                marker = '"""' if '"""' in stripped else "'''"
                in_docstring = (in_docstring != (stripped.count(marker) % 2 == 1))
                continue
            if in_docstring:
                continue
            code = stripped.split("#", 1)[0].strip()
            if code and "# literal-ok" not in line:
                out.append((lineno, code))
        return out

    def test_no_length_literals_in_bc_layer_modules(self):
        violations = []
        for path in _BC_LAYER_MODULES:
            if not path.is_file():
                continue  # module not created yet; enforced once it exists
            for lineno, code in self._code_lines(path.read_text(encoding="utf-8")):
                if self._LITERAL_RE.search(code):
                    violations.append(f"{path.name}:{lineno}: {code}")
        assert not violations, (
            "BC address-line length literals found outside the profile YAML "
            "(use profile.limit(...) / AddressLimits instead):\n" + "\n".join(violations)
        )
