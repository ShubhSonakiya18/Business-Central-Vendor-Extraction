"""Address segmentation accuracy check.

Feeds each raw address string in `address_cases.yaml` through the current
splitting logic and scores the fields it pulls out against the hand-made
expected values. Prints a per-case, per-field table and an aggregate.

    python -m app.eval.eval_address                # score current code
    python -m app.eval.eval_address --verbose      # also show every field
    python -m app.eval.eval_address --multiline --bc-layer --cases address_vendor_lines.yaml

Exit code is non-zero when any field is `wrong` or `missed`, so this can gate
a change: run it before a phase to record the baseline, run it after to prove
the phase did not regress.

Which splitter is scored is decided by `_split(address)` below -- it currently
calls onboarding_mapper._split_trailing_location. When address_resolver lands,
point it there instead and the same cases measure the new module.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_CASES_FILE = Path(__file__).with_name("address_cases.yaml")

# Fields we score, in display order. --multiline extends this with
# address_3/address_4 (see main()).
_FIELDS = ("address_1", "address_2", "city", "state", "pin_code")
_MULTILINE_FIELDS = ("address_1", "address_2", "address_3", "address_4", "city", "state", "pin_code")


def _split(address: str, multiline: bool = False, bc_layer: bool = False) -> dict[str, str]:
    """Run the address through the current segmentation path and return
    {address_1, address_2, [address_3, address_4,] city, state, pin_code,
    _confidence}.

    Points at extraction_pipeline.extract.address_resolver (Phase 2). The
    pre-Phase-2 baseline pointed at onboarding_mapper._split_trailing_location;
    the 37/55 number recorded then is what every change here must not drop
    below. `_confidence` is reported but not scored -- the case files carry no
    expected confidence, it is shown so a `correct`-but-`low` row is visible.

    `multiline=True` (opt-in, matching `resolve_address_blob`'s own default)
    routes the premises/locality remainder through address_segmenter.py's
    Address 1/Address 2 role-based split instead of joining everything into
    address_1 as one string (the "interpretation B" convention this file's
    own `expect` blocks are written under). address_3/address_4 are ALWAYS ""
    under the current Address 1/Address 2 redesign -- correctly_absent on
    every case, in every mode -- so a `--multiline` FAIL on address_1/
    address_2 here is EXPECTED wherever a case's locality content should now
    move to Address 2 under the new business rule (e.g. "14 EXAMPLE ROAD,
    KORAMANGALA" -> address_1="14 EXAMPLE ROAD", address_2="KORAMANGALA"
    rather than both joined into address_1). This file's cases were never
    rewritten to the new convention because that is `address_line_cases.
    yaml`'s job (scored by test_address_segmenter.py, 74/74 passing) --
    `--multiline` here remains a smoke check that address_3/address_4 never
    get populated and that city/state/pin_code stay correct, not a claim
    that address_1/address_2 match this file's single-line convention.
    """
    from app.services.extraction_pipeline.extract.address_resolver import (
        resolve_address_blob,
    )

    r = resolve_address_blob(address, multiline=multiline, bc_layer=bc_layer)
    a1, a2 = r.address_1, r.address_2
    if bc_layer and r.representation is not None:
        # Score `expect` against the layout AFTER the step-5 backfill but
        # BEFORE any BC rebalance -- i.e. the semantic expectation. The BC
        # result is scored separately against `bc_expect` (see main()).
        a1, a2 = _pre_bc_lines(r.representation)
    out = {
        "address_1": a1.strip(", ").strip(),
        "address_2": a2,
        "city": r.city,
        "state": r.state,
        "pin_code": r.pin_code,
        "_confidence": r.confidence,
    }
    if multiline:
        out["address_3"] = r.address_3
        out["address_4"] = r.address_4
    if bc_layer and r.representation is not None:
        out["_bc"] = {
            "address_1": r.address_1,
            "address_2": r.address_2,
            "status": r.representation["status"],
            "reason_codes": [f["reason_code"] for f in r.findings],
        }
    return out


def _pre_bc_lines(representation: dict) -> tuple[str, str]:
    """A1/A2 after the presentation fallback, before any BC rebalance."""
    lines = (representation["semantic"]["semantic_address_1"],
             representation["semantic"]["semantic_address_2"])
    for t in representation["transforms"]:
        if t["layer"] == "presentation_fallback":
            lines = (t["final_address_1"], t["final_address_2"])
    return lines


def _score_bc(got: dict, case: dict) -> list[str]:
    """Problems with the BC representation of one case. With a `bc_expect`
    block the final A1/A2, status and review/block reason codes must match
    it; without one, the BC layer must have changed nothing (final A1/A2 ==
    the case's semantic `expect`) and raised no review/block finding."""
    want = case.get("bc_expect")
    problems = []
    if want is None:
        exp = case["expect"]
        for f in ("address_1", "address_2"):
            if _norm(got[f]) != _norm(exp.get(f, "")):
                problems.append(f"bc {f}: got={got[f]!r} want={exp.get(f, '')!r} (no bc_expect: must be unchanged)")
        if got["reason_codes"]:
            problems.append(f"bc findings {got['reason_codes']} but no bc_expect")
        return problems
    for f in ("address_1", "address_2"):
        if _norm(got[f]) != _norm(want[f]):
            problems.append(f"bc {f}: got={got[f]!r} want={want[f]!r}")
    if got["status"] != want["status"]:
        problems.append(f"bc status: got={got['status']} want={want['status']}")
    if sorted(got["reason_codes"]) != sorted(want.get("reason_codes", [])):
        problems.append(f"bc reason_codes: got={got['reason_codes']} want={want.get('reason_codes', [])}")
    return problems


def _norm(s: str) -> str:
    """Comparison-normalise a string: collapse whitespace, drop a trailing
    comma, casefold. Address strings vary in spacing and comma style without
    being wrong."""
    return " ".join((s or "").replace(",", " , ").split()).strip(" ,").casefold()


def _score_field(got: str, want: str) -> str:
    got, want = (got or "").strip(), (want or "").strip()
    if want == "":
        return "correctly_absent" if got == "" else "hallucinated"
    if got == "":
        return "missed"
    return "correct" if _norm(got) == _norm(want) else "wrong"


def main() -> int:
    ap = argparse.ArgumentParser(description="Score address segmentation against address_cases.yaml")
    ap.add_argument("--verbose", action="store_true", help="show every field, not just failures")
    ap.add_argument(
        "--multiline", action="store_true",
        help="score resolve_address_blob(multiline=True) instead of the legacy "
             "single-address_1 path -- adds address_3/address_4 to the scored "
             "fields (expected '' on every existing address_cases.yaml case "
             "unless noted otherwise).",
    )
    ap.add_argument(
        "--cases",
        help="path to an alternative case file (default: address_cases.yaml). "
             "Use with --multiline to score a corpus written under the 4-line "
             "convention, e.g. address_vendor_lines.yaml. Keeping those in a "
             "separate file leaves the legacy baseline comparable.",
    )
    ap.add_argument(
        "--bc-layer", action="store_true",
        help="with --multiline: run the BC address representation layer "
             "(docs/ADDRESS_SEGMENTATION_PLAN.md). `expect` is scored against "
             "the pre-rebalance layout; each case's final BC A1/A2, status and "
             "reason codes are checked against its `bc_expect` block, or must "
             "be unchanged when it has none.",
    )
    args = ap.parse_args()
    if args.bc_layer and not args.multiline:
        print("--bc-layer requires --multiline", file=sys.stderr)
        return 2

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    fields = _MULTILINE_FIELDS if args.multiline else _FIELDS

    cases_file = Path(args.cases) if args.cases else _CASES_FILE
    if not cases_file.is_absolute() and args.cases:
        # Allow either a path relative to the working directory or a bare
        # filename sitting next to the default case file.
        beside = _CASES_FILE.with_name(cases_file.name)
        if not cases_file.exists() and beside.exists():
            cases_file = beside
    if not cases_file.exists():
        print(f"case file not found: {cases_file}", file=sys.stderr)
        return 2

    doc = yaml.safe_load(cases_file.read_text(encoding="utf-8"))
    cases = doc["cases"]

    tally = {"correct": 0, "wrong": 0, "missed": 0, "hallucinated": 0, "correctly_absent": 0}
    conf_tally: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    failing_cases: list[str] = []
    bc_failing: list[str] = []
    bc_counts: dict[str, int] = {}
    # cases the resolver got fully right but flagged low-confidence, and the
    # reverse -- a wrong/missed field the resolver reported as high. Both are
    # calibration problems worth seeing even though neither changes the score.
    miscalibrated: list[str] = []

    print("=" * 78)
    mode = (" [--multiline]" if args.multiline else "") + (" [--bc-layer]" if args.bc_layer else "")
    print(f"ADDRESS SEGMENTATION{mode}  --  {len(cases)} cases, {len(fields)} fields each")
    print(f"cases: {cases_file.name}")
    print("=" * 78)

    for case in cases:
        cid = case["id"]
        got = _split(case["address"], multiline=args.multiline, bc_layer=args.bc_layer)
        want = case["expect"]

        results = {f: _score_field(got.get(f, ""), want.get(f, "")) for f in fields}
        for r in results.values():
            tally[r] += 1
        bad = [f for f, r in results.items() if r in ("wrong", "missed", "hallucinated")]
        if bad:
            failing_cases.append(cid)

        conf = got.get("_confidence", "low")
        conf_tally[conf] = conf_tally.get(conf, 0) + 1
        # `low` is the right call when the case genuinely has nothing to find
        # (no city/state/pin expected), so only flag a low-confidence case that
        # actually resolved something, and any wrong/missed case reported high.
        resolved_something = any(want.get(f) for f in ("city", "state", "pin_code"))
        if not bad and conf == "low" and resolved_something:
            miscalibrated.append(f"{cid} (correct but low)")
        elif bad and conf == "high":
            miscalibrated.append(f"{cid} (wrong but high)")

        bc_problems: list[str] = []
        if args.bc_layer and "_bc" in got:
            bc_counts[got["_bc"]["status"]] = bc_counts.get(got["_bc"]["status"], 0) + 1
            bc_problems = _score_bc(got["_bc"], case)
            if bc_problems:
                bc_failing.append(cid)

        status = "OK  " if not bad and not bc_problems else "FAIL"
        print(f"\n[{status}] {cid}   confidence={conf}")
        for p in bc_problems:
            print(f"   ** {p}")
        if args.verbose or bad:
            for f in fields:
                r = results[f]
                mark = "  " if r in ("correct", "correctly_absent") else "**"
                print(f"   {mark} {f:11} {r:16} got={got.get(f, '')!r}")
                if r in ("wrong", "missed"):
                    print(f"      {'':11} {'':16} want={want.get(f, '')!r}")

    total = sum(tally.values())
    print("\n" + "=" * 78)
    print("AGGREGATE")
    print("=" * 78)
    for k in ("correct", "wrong", "missed", "hallucinated", "correctly_absent"):
        print(f"  {k:18} {tally[k]:3}")
    good = tally["correct"] + tally["correctly_absent"]
    print(f"  {'-'*18}")
    print(f"  {'good / total':18} {good:3} / {total}   ({100*good/total:.1f}%)")
    print(f"  {'-'*18}")
    print(f"  {'confidence':18} high={conf_tally['high']}  "
          f"medium={conf_tally['medium']}  low={conf_tally['low']}   (reported, not scored)")
    if miscalibrated:
        print(f"  {'miscalibrated':18} {', '.join(miscalibrated)}")
    if args.bc_layer:
        summary = "  ".join(f"{k}={v}" for k, v in sorted(bc_counts.items()))
        print(f"  {'bc status':18} {summary}")
        print(f"  {'bc checks':18} {len(cases) - len(bc_failing)} / {len(cases)} cases match bc_expect / unchanged")
    if failing_cases:
        print(f"\n  failing cases: {', '.join(failing_cases)}")
    if bc_failing:
        print(f"  bc failing cases: {', '.join(bc_failing)}")
    print("=" * 78)

    return 1 if (tally["wrong"] or tally["missed"] or tally["hallucinated"] or bc_failing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
