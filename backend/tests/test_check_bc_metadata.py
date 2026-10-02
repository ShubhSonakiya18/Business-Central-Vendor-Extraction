"""Tests for app.cli.check_bc_metadata (docs/ADDRESS_SEGMENTATION_PLAN.md §9).

Uses a small fixture $metadata XML (not a real BC export) with a mix of
matching, mismatching, missing and MaxLength-less properties, to prove the
diff logic without requiring VPN/tenant access.
"""

from __future__ import annotations

import textwrap

import pytest

from app.cli.check_bc_metadata import (
    MATCH,
    MISMATCH,
    NOT_FOUND,
    UNVERIFIABLE,
    check,
    main,
)
from app.services.bc_target_profile import load_profile

_FIXTURE_METADATA = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="utf-8"?>
    <edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
      <edmx:DataServices>
        <Schema Namespace="NAV" xmlns="http://docs.oasis-open.org/odata/ns/edm">
          <EntityType Name="VendorCard">
            <Property Name="Address" Type="Edm.String" MaxLength="100"/>
            <Property Name="Address_2" Type="Edm.String" MaxLength="60"/>
            <Property Name="City" Type="Edm.String" MaxLength="30"/>
            <Property Name="County" Type="Edm.String"/>
            <Property Name="Post_Code" Type="Edm.String" MaxLength="20"/>
          </EntityType>
        </Schema>
      </edmx:DataServices>
    </edmx:Edmx>
    """
)


@pytest.fixture
def metadata_file(tmp_path):
    p = tmp_path / "vendorcard_metadata.xml"
    p.write_text(_FIXTURE_METADATA, encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _clear_profile_cache():
    load_profile.cache_clear()
    yield
    load_profile.cache_clear()


class TestCheck:
    def test_matching_fields_report_match(self, metadata_file):
        results = check(metadata_file, "bc22_in_vendorcard")
        by_id = {r["constraint_id"]: r for r in results}
        assert by_id["BC_ADDRESS_1_MAX_LENGTH"]["status"] == MATCH
        assert by_id["BC_CITY_MAX_LENGTH"]["status"] == MATCH
        assert by_id["BC_POST_CODE_MAX_LENGTH"]["status"] == MATCH

    def test_mismatched_field_reported(self, metadata_file):
        # fixture has Address_2 MaxLength=60, profile says 50
        results = check(metadata_file, "bc22_in_vendorcard")
        by_id = {r["constraint_id"]: r for r in results}
        r = by_id["BC_ADDRESS_2_MAX_LENGTH"]
        assert r["status"] == MISMATCH
        assert r["expected"] == 50
        assert r["found"] == 60

    def test_property_without_maxlength_is_unverifiable_not_pass(self, metadata_file):
        # fixture has County with no MaxLength attribute at all
        results = check(metadata_file, "bc22_in_vendorcard")
        by_id = {r["constraint_id"]: r for r in results}
        assert by_id["BC_COUNTY_MAX_LENGTH"]["status"] == UNVERIFIABLE

    def test_property_missing_from_metadata_is_not_found(self, metadata_file):
        # fixture has no Country_Region_Code property at all
        results = check(metadata_file, "bc22_in_vendorcard")
        by_id = {r["constraint_id"]: r for r in results}
        assert by_id["BC_COUNTRY_CODE_MAX_LENGTH"]["status"] == NOT_FOUND

    def test_constraints_without_bc_field_are_skipped(self, metadata_file):
        results = check(metadata_file, "bc22_in_vendorcard")
        ids = {r["constraint_id"] for r in results}
        assert "BC_NO_ADDRESS_3_4" not in ids  # no single bc_field


class TestMainExitCode:
    def test_exits_nonzero_on_mismatch(self, metadata_file, capsys):
        rc = main(["--metadata-file", str(metadata_file)])
        assert rc == 1
        out = capsys.readouterr().out
        assert "MISMATCH" in out

    def test_exits_2_on_missing_file(self, tmp_path):
        rc = main(["--metadata-file", str(tmp_path / "nope.xml")])
        assert rc == 2

    def test_exits_2_on_invalid_xml(self, tmp_path):
        bad = tmp_path / "bad.xml"
        bad.write_text("not xml at all <<<", encoding="utf-8")
        rc = main(["--metadata-file", str(bad)])
        assert rc == 2

    def test_all_matching_exits_zero(self, tmp_path):
        # A metadata file where every profile-checked field matches exactly.
        matching = textwrap.dedent(
            """\
            <?xml version="1.0" encoding="utf-8"?>
            <edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
              <edmx:DataServices>
                <Schema Namespace="NAV" xmlns="http://docs.oasis-open.org/odata/ns/edm">
                  <EntityType Name="VendorCard">
                    <Property Name="Address" MaxLength="100"/>
                    <Property Name="Address_2" MaxLength="50"/>
                    <Property Name="City" MaxLength="30"/>
                    <Property Name="County" MaxLength="30"/>
                    <Property Name="Post_Code" MaxLength="20"/>
                    <Property Name="Country_Region_Code" MaxLength="10"/>
                    <Property Name="Name" MaxLength="100"/>
                    <Property Name="Phone_No" MaxLength="30"/>
                    <Property Name="MobilePhoneNo" MaxLength="30"/>
                    <Property Name="E_Mail" MaxLength="80"/>
                    <Property Name="Home_Page" MaxLength="80"/>
                  </EntityType>
                </Schema>
              </edmx:DataServices>
            </edmx:Edmx>
            """
        )
        p = tmp_path / "all_match.xml"
        p.write_text(matching, encoding="utf-8")
        rc = main(["--metadata-file", str(p)])
        assert rc == 0
