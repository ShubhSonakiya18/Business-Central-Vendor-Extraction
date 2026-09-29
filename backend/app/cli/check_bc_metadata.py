"""Diff a saved Business Central `$metadata` XML export against our BC target
profile's configured field-length limits.

The backend never calls BC directly (it is reachable only from the VPN --
see docs/ADDRESS_SEGMENTATION_PLAN.md §9 and §16). To confirm the profile's
limits actually match the tenant, an operator on the VPN saves the
VendorCard `$metadata` document:

    curl http://ntz-srv-bcdb:2248/BC220/ODataV4/$metadata -o vendorcard_metadata.xml

then runs this script against the saved file:

    python -m app.cli.check_bc_metadata --metadata-file vendorcard_metadata.xml

For each profile constraint with a `bc_field`, this looks for a matching
`<Property Name="...">` element in the metadata and compares its
`MaxLength` attribute (when present) to the profile's configured value.
Mismatches are printed and the script exits non-zero.

Whether VendorCard's OData metadata exposes `MaxLength` for page fields at
all is one of the plan's open TENANT VERIFICATION items (§16). If a
property is found but carries no `MaxLength`, this is reported as
UNVERIFIABLE, not as a pass -- see MATCH_STATUS below. In that case, use the
sandbox test path instead (plan TESTPLAN T-BC-02).

This script only READS a local XML file. It never makes a network call and
never writes `verified_against_metadata: true` for you -- that edit to the
profile YAML is a deliberate, separate step once you've reviewed the diff.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from app.services.bc_target_profile import BcProfileError, load_profile

MATCH = "MATCH"
MISMATCH = "MISMATCH"
NOT_FOUND = "PROPERTY_NOT_FOUND"
UNVERIFIABLE = "NO_MAXLENGTH_IN_METADATA"

# EDM/OData metadata XML is namespaced but the namespace URI varies by BC
# version; match on the local tag name only.
_PROPERTY_TAG_SUFFIX = "}Property"


def _iter_properties(metadata_path: Path):
    """Yield (name, max_length_or_None) for every <Property> element in the
    metadata document, regardless of namespace or which EntityType it sits
    under (VendorCard's own properties are looked up by name)."""
    tree = ET.parse(metadata_path)
    for elem in tree.getroot().iter():
        if not elem.tag.endswith(_PROPERTY_TAG_SUFFIX):
            continue
        name = elem.get("Name")
        if not name:
            continue
        max_len_attr = elem.get("MaxLength")
        max_len = int(max_len_attr) if max_len_attr and max_len_attr.isdigit() else None
        yield name, max_len


def check(metadata_path: Path, profile_name: str) -> list[dict]:
    """Returns one result dict per checked constraint:
    {constraint_id, bc_field, expected, found, status}."""
    profile = load_profile(profile_name)
    properties = dict(_iter_properties(metadata_path))

    results = []
    for constraint_id, c in profile.raw["constraints"].items():
        bc_field = c.get("bc_field")
        if not bc_field:
            continue  # e.g. BC_NO_ADDRESS_3_4 has no single BC field
        expected = c.get("value")
        if bc_field not in properties:
            results.append({
                "constraint_id": constraint_id, "bc_field": bc_field,
                "expected": expected, "found": None, "status": NOT_FOUND,
            })
            continue
        found = properties[bc_field]
        if found is None:
            status = UNVERIFIABLE
        elif found == expected:
            status = MATCH
        else:
            status = MISMATCH
        results.append({
            "constraint_id": constraint_id, "bc_field": bc_field,
            "expected": expected, "found": found, "status": status,
        })
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-file", required=True, type=Path,
                         help="Path to a saved $metadata XML export")
    parser.add_argument("--profile", default="bc22_in_vendorcard",
                         help="BC target profile name (default: bc22_in_vendorcard)")
    args = parser.parse_args(argv)

    if not args.metadata_file.is_file():
        print(f"ERROR: metadata file not found: {args.metadata_file}", file=sys.stderr)
        return 2

    try:
        results = check(args.metadata_file, args.profile)
    except BcProfileError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except ET.ParseError as exc:
        print(f"ERROR: {args.metadata_file} is not valid XML: {exc}", file=sys.stderr)
        return 2

    ok = True
    for r in results:
        line = (
            f"{r['status']:24s} {r['constraint_id']:28s} "
            f"bc_field={r['bc_field']:22s} expected={r['expected']!s:6s} found={r['found']!s}"
        )
        print(line)
        if r["status"] not in (MATCH, UNVERIFIABLE):
            ok = False

    print()
    if ok:
        print("All checkable constraints match (or could not be verified from metadata).")
        print("If everything relevant is MATCH, set verified_against_metadata: true "
              "in the profile YAML yourself after reviewing this output.")
    else:
        print("MISMATCH or PROPERTY_NOT_FOUND found -- do not mark the profile verified.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
