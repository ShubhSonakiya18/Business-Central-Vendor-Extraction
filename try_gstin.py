"""Interactive terminal tool: type a GSTIN, get the registered vendor's full
address AND its Business Central Address 1 / Address 2 split.

Two steps chained together:
  1. verify_gstin(gstin)       -- looks up the GSTIN in the live GST registry
                                   (gstinapi.in), returns legal name + address.
  2. resolve_address_blob(...) -- splits that address into Address 1/Address 2/
                                   City/State/Country/PIN (the same logic
                                   try_address.py exercises directly).

Requires GSTIN_API_ENABLED=true and a valid GSTIN_API_KEY in backend/.env --
the free tier is capped at 50 requests total, so don't loop this in a script.

Run with:
    .venv\\Scripts\\python.exe try_gstin.py

Type a GSTIN and press Enter. Type 'exit' or 'quit' to stop.
"""
import sys

sys.path.insert(0, "backend")
from app.services.gstin_verification import verify_gstin
from app.services.extraction_pipeline.extract.address_resolver import resolve_address_blob


def main():
    print("GSTIN -> Address Tester -- type a 15-character GSTIN, press Enter.")
    print("Type 'exit' or 'quit' to stop.\n")
    while True:
        try:
            gstin = input("GSTIN: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not gstin:
            continue
        if gstin.lower() in ("exit", "quit"):
            break

        result = verify_gstin(gstin)
        print()
        if not result.checked:
            print(f"  Could not verify: {result.error}")
            print()
            continue

        print(f"  Legal name : {result.legal_name}")
        if result.trade_name and result.trade_name != result.legal_name:
            print(f"  Trade name : {result.trade_name}")
        print(f"  Status     : {result.status} ({'active' if result.active else 'NOT active'})")
        print(f"  Full address (from registry): {result.address}")
        print()

        if not result.address:
            print("  No address returned by the registry -- nothing to segment.")
            print()
            continue

        # The registry often returns `address`, `city`, and `pincode` as
        # SEPARATE fields, with the address text itself carrying none of
        # them (no PIN, sometimes no city either). resolve_address_blob's
        # state/city resolution leans on finding a PIN code IN THE TEXT to
        # trigger its PIN-directory fallback -- so if the PIN/city aren't
        # already present in `result.address`, append them before
        # segmenting. Without this, a text-only address with no PIN/state/
        # city words at all comes back with State/City empty even though
        # the registry told us both separately.
        to_segment = result.address
        if result.pincode and result.pincode not in to_segment:
            to_segment = f"{to_segment}, {result.pincode}"
        if result.city and result.city.casefold() not in to_segment.casefold():
            to_segment = f"{to_segment}, {result.city}"

        r = resolve_address_blob(to_segment, multiline=True)
        print("  --- segmented ---")
        print(f"  Address 1 : {r.address_1}")
        print(f"  Address 2 : {r.address_2}")
        print(f"  City      : {r.city or result.city}")
        print(f"  State     : {r.state}")
        print(f"  Country   : {r.country}")
        print(f"  PIN       : {r.pin_code or result.pincode}")
        print(f"  Confidence: {r.confidence}")
        print()


if __name__ == "__main__":
    main()
