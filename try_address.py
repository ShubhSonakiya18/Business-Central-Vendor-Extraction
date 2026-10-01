"""Interactive terminal tool: type a full Indian address, see it split into
Address 1 / Address 2 / City / State / Country / PIN.

Run with:
    .venv\\Scripts\\python.exe try_address.py
    .venv\\Scripts\\python.exe try_address.py --bc

--bc also runs the Business Central representation layer
(docs/ADDRESS_SEGMENTATION_PLAN.md) and shows the semantic split, every
automatic transformation with its reason code, and the final BC lines with
their lengths against the configured limits.

Type an address and press Enter. Type 'exit' or 'quit' to stop.
"""
import sys

sys.path.insert(0, "backend")
from app.services.extraction_pipeline.extract.address_resolver import resolve_address_blob


def _print_bc(r):
    rep = r.representation
    if rep is None:
        print("  (BC layer: nothing to represent -- no address lines left after geography)")
        return
    from app.config.config import settings
    from app.services.bc_target_profile import load_profile

    limits = load_profile(settings.BC_TARGET_PROFILE).address_limits()
    sem = rep["semantic"]
    print("  -- semantic split (Layer 1) --")
    for f in sem["fragments"]:
        print(f"     [{f['index']}] {f['text']!r:42} tier={f['tier']:14} semantic_role={f['semantic_role']}")
    print(f"     semantic Address 1 : {sem['semantic_address_1']!r}")
    print(f"     semantic Address 2 : {sem['semantic_address_2']!r}")
    for t in rep["transforms"]:
        print(f"  -- {t['layer']}: {t['transformation']} --")
        print(f"     reason {t['reason_code']}  class {t['automation_class']}"
              + (f"  constraint {t['constraint']}={t['constraint_value']}" if t.get("constraint") else ""))
        print(f"     moved fragments {t['moved_fragment_indices']}")
    print(f"  -- Business Central (status {rep['status']}) --")
    a1, a2 = rep["final_address_1"], rep["final_address_2"]
    print(f"     Address   ({len(a1):3}/{limits.address_1_max}) : {a1}")
    print(f"     Address 2 ({len(a2):3}/{limits.address_2_max}) : {a2}")
    for f in r.findings:
        print(f"     FINDING {f['reason_code']} ({f['automation_class']}): {f['detail']}")


def main():
    bc = "--bc" in sys.argv[1:]
    print("Address Segmentation Tester -- type an address, press Enter."
          + (" [BC layer on]" if bc else ""))
    print("Type 'exit' or 'quit' to stop.\n")
    while True:
        try:
            address = input("Full address: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not address:
            continue
        if address.lower() in ("exit", "quit"):
            break

        r = resolve_address_blob(address, multiline=True, bc_layer=bc)
        print()
        print(f"  Address 1 : {r.address_1}")
        print(f"  Address 2 : {r.address_2}")
        print(f"  City      : {r.city}")
        print(f"  State     : {r.state}")
        print(f"  Country   : {r.country}")
        print(f"  PIN       : {r.pin_code}")
        print(f"  Confidence: {r.confidence}")
        if bc:
            print()
            _print_bc(r)
        print()


if __name__ == "__main__":
    main()
