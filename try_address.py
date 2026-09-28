"""Interactive terminal tool: type a full Indian address, see it split into
Address 1 / Address 2 / City / State / Country / PIN.

Run with:
    .venv\\Scripts\\python.exe try_address.py

Type an address and press Enter. Type 'exit' or 'quit' to stop.
"""
import sys

sys.path.insert(0, "backend")
from app.services.extraction_pipeline.extract.address_resolver import resolve_address_blob


def main():
    print("Address Segmentation Tester -- type an address, press Enter.")
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

        r = resolve_address_blob(address, multiline=True)
        print()
        print(f"  Address 1 : {r.address_1}")
        print(f"  Address 2 : {r.address_2}")
        print(f"  City      : {r.city}")
        print(f"  State     : {r.state}")
        print(f"  Country   : {r.country}")
        print(f"  PIN       : {r.pin_code}")
        print(f"  Confidence: {r.confidence}")
        print()


if __name__ == "__main__":
    main()
