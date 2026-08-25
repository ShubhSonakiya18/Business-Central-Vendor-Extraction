"""
Step 4 harness: validate the field dictionary and prove it against real data.

    python -m cli.check_config

Two checks, each of which can fail the run:

1. The YAML loads and every internal reference resolves.
2. Configured patterns actually match the real values OCR'd out of the sample
   documents in Step 3 -- a regex that looks right but rejects the genuine
   GSTIN is worse than no regex at all.
"""

from __future__ import annotations

import sys

from vendor_extractor.config_loader import ConfigError, load_config

# Real values read off the sample documents during the Step 3 OCR run, plus
# values that must NOT match. The negatives matter: the cheque's MICR band
# yields digit runs that a loose account-number pattern would happily accept.
PATTERN_CASES: dict[str, tuple[list[str], list[str]]] = {
    #                 should match                        should NOT match
    "gst_number": (["19AABCM7980K1ZU", "27AABCU9603R1ZM"], ["AABCM7980K", "19AABCM7980K"]),
    "pan": (["AABCM7980K", "AABCU9603R"], ["19AABCM7980K1ZU", "AABCM798OK"]),
    "udyam_number": (["UDYAM-WB-10-0003543"], ["UDYAM-WB-10-000354", "UDYAM100003543"]),
    "ifsc": (["ICIC0006278", "SBIN0011223", "HDFC0001234"], ["ICIC1006278", "ICIC000627"]),
    "account_number": (["627851000539", "38291047561"], ["12345678", "1234567890123456789"]),
    "pin_code": (["700029", "110001"], ["70002", "023456"]),
    "email": (["accounts@acme-eng.in"], ["accounts@acme", "acme-eng.in"]),
    "telephone": (["9876543210", "+919876543210"], ["1234567890", "98765432"]),
}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    failures: list[str] = []

    # -- 1. load ------------------------------------------------------------
    print("=" * 74)
    print("1. LOADING CONFIG")
    print("=" * 74)
    try:
        dictionary, rules = load_config()
    except ConfigError as exc:
        print(f"  FAIL  {exc}")
        return 1
    print(f"  OK  {len(dictionary)} fields, {len(rules.validators)} validators")
    print(f"      required fields   : {', '.join(dictionary.required_fields)}")
    print(f"      fields w/ patterns: {len(dictionary.with_patterns())}")
    print(f"      cross-doc checks  : {sum(1 for f in dictionary if f.cross_document_consistency)}")

    # -- 2. field table -----------------------------------------------------
    print()
    print("=" * 74)
    print("2. FIELD DICTIONARY")
    print("=" * 74)
    print(f"  {'field':<20} {'pri':>3} {'lbls':>4} {'pat':>3}  {'req':<3} validators")
    print(f"  {'-'*20} {'-'*3} {'-'*4} {'-'*3}  {'-'*3} {'-'*22}")
    for spec in dictionary.by_priority():
        print(
            f"  {spec.key:<20} {spec.priority:>3} {len(spec.labels):>4} "
            f"{len(spec.patterns):>3}  {'yes' if spec.required else '-':<3} "
            f"{','.join(spec.validators) or '-'}"
        )

    # -- 3. patterns vs real values ----------------------------------------
    print()
    print("=" * 74)
    print("3. PATTERNS vs REAL EXTRACTED VALUES")
    print("=" * 74)
    for key, (positives, negatives) in PATTERN_CASES.items():
        spec = dictionary.get(key)
        if spec is None:
            failures.append(f"pattern test references unknown field {key!r}")
            print(f"  FAIL  {key}: not in dictionary")
            continue

        bad_pos = [v for v in positives if not spec.matches_pattern(v)]
        bad_neg = [v for v in negatives if spec.matches_pattern(v)]
        if bad_pos or bad_neg:
            if bad_pos:
                failures.append(f"{key}: pattern rejected real value(s) {bad_pos}")
            if bad_neg:
                failures.append(f"{key}: pattern wrongly accepted {bad_neg}")
            print(f"  FAIL  {key:<16} rejected={bad_pos} wrongly-accepted={bad_neg}")
        else:
            print(f"  OK    {key:<16} {len(positives)} accepted, {len(negatives)} rejected")

    # -- summary ------------------------------------------------------------
    print()
    print("=" * 74)
    if failures:
        print(f"RESULT: {len(failures)} PROBLEM(S)")
        print("=" * 74)
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
