"""
One-off test for "Hoka" -- the Hokashoes GPT deployment on Azure's
OpenAI-compatible /openai/v1 endpoint. NOT part of the extraction pipeline --
imports nothing from extraction_pipeline/, ocr_engine.py, or document_loader.py.

    # text only
    python -m app.cli.check_azure_gpt

    # send a real vendor document and see what it reads back
    python -m app.cli.check_azure_gpt --image path/to/gst_certificate.png
    python -m app.cli.check_azure_gpt --image cheque.png --prompt "Extract the IFSC and account number"

Requires AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY and AZURE_OPENAI_MODEL in
backend/.env -- see .env.example. Auth is the plain API key (the /openai/v1
endpoint accepts it directly as a bearer token), not Entra ID -- so no
`az login` and no browser sign-in needed.
"""

from __future__ import annotations

import argparse
import base64
import io
import mimetypes
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DEFAULT_IMAGE_PROMPT = (
    "Read this vendor document and extract every field you can identify as a "
    "key/value pair -- for example vendor name, address, GSTIN, PAN, IFSC, "
    "bank account number, PIN code. Return them as JSON. If a value is not "
    "present, omit it rather than guessing."
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the Hoka Azure GPT deployment")
    parser.add_argument("--image", help="Optional image or PDF to send (vendor doc, cheque, etc.)")
    parser.add_argument("--page", type=int, default=1, help="Page to render if --image is a PDF")
    parser.add_argument("--prompt", help="Prompt text (defaults depend on --image)")
    args = parser.parse_args()

    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    key = os.environ.get("AZURE_OPENAI_KEY")
    model = os.environ.get("AZURE_OPENAI_MODEL")
    missing = [
        name
        for name, value in [
            ("AZURE_OPENAI_ENDPOINT", endpoint),
            ("AZURE_OPENAI_KEY", key),
            ("AZURE_OPENAI_MODEL", model),
        ]
        if not value
    ]
    if missing:
        raise SystemExit(
            f"Missing from backend/.env: {', '.join(missing)}. See .env.example."
        )

    prompt = args.prompt or (DEFAULT_IMAGE_PROMPT if args.image else "What is the capital of France?")

    try:
        from openai import APIStatusError, AuthenticationError, OpenAI, OpenAIError
    except ImportError:
        raise SystemExit(
            "openai is not installed. pip install -r requirements-dev.txt "
            "(it lives there, not in requirements.txt, since this is a one-off "
            "developer test, not something the running app needs)."
        )

    # Build the request payload. Text-only takes a plain string; an image needs
    # the Responses API's structured content form.
    if args.image:
        image_path = Path(args.image)
        if not image_path.is_file():
            raise SystemExit(f"No such file: {image_path}")

        if image_path.suffix.lower() == ".pdf":
            # The vendor documents are all PDFs, so render a page rather than
            # making the caller convert by hand. pypdfium2 is already a runtime
            # dependency; this deliberately does not import the pipeline's
            # document_loader, to keep this script standalone.
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(image_path))
            if args.page < 1 or args.page > len(pdf):
                raise SystemExit(
                    f"--page {args.page} out of range: {image_path.name} has {len(pdf)} page(s)"
                )
            # 200 DPI matches the pipeline's RENDER_DPI, so what the model sees
            # is comparable to what PaddleOCR sees.
            bitmap = pdf[args.page - 1].render(scale=200 / 72)
            buffer = io.BytesIO()
            bitmap.to_pil().save(buffer, format="PNG")
            raw, mime = buffer.getvalue(), "image/png"
            print(f"(rendered page {args.page} of {len(pdf)} at 200 DPI)")
        else:
            mime, _ = mimetypes.guess_type(image_path.name)
            if mime is None or not mime.startswith("image/"):
                raise SystemExit(f"Not a recognized image or PDF: {image_path.name}")
            raw = image_path.read_bytes()

        b64 = base64.b64encode(raw).decode("ascii")
        payload = [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"},
                ],
            }
        ]
    else:
        payload = prompt

    print(f"Endpoint : {endpoint}")
    print(f"Model    : {model}")
    if args.image:
        print(f"Image    : {args.image}")
    print(f"Prompt   : {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    print()

    client = OpenAI(base_url=endpoint, api_key=key)

    t0 = time.perf_counter()
    try:
        response = client.responses.create(model=model, input=payload)
    except AuthenticationError as exc:
        raise SystemExit(f"Authentication failed -- check AZURE_OPENAI_KEY. ({exc})")
    except APIStatusError as exc:
        raise SystemExit(
            f"Azure returned HTTP {exc.status_code}: {exc.message}\n"
            "404 usually means AZURE_OPENAI_MODEL is not the exact deployment name, "
            "or AZURE_OPENAI_ENDPOINT is missing the /openai/v1 suffix."
        )
    except OpenAIError as exc:
        raise SystemExit(f"Request failed: {exc}")
    except Exception as exc:
        raise SystemExit(f"Request failed ({type(exc).__name__}): {exc}")
    elapsed = time.perf_counter() - t0

    print("=" * 78)
    print("RESPONSE")
    print("=" * 78)
    print(response.output_text)
    print()
    print(f"Latency : {elapsed:.2f}s")
    usage = getattr(response, "usage", None)
    if usage:
        print(f"Tokens  : input={usage.input_tokens} output={usage.output_tokens}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    main()
