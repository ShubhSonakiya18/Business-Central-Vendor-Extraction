"""
One-off connectivity test for an Azure AI Foundry vision-language deployment
(e.g. Qwen3-VL). NOT part of the extraction pipeline -- imports nothing from
extraction_pipeline/, ocr_engine.py, or document_loader.py. Run by hand:

    python -m app.cli.check_azure_vlm path/to/image.png
    python -m app.cli.check_azure_vlm path/to/image.png --prompt "List every field label you see"

Requires AZURE_AI_ENDPOINT, AZURE_AI_KEY, AZURE_AI_MODEL in backend/.env --
see .env.example. The endpoint must be the model's inference URL
(https://<resource-name>.services.ai.azure.com/models), not the Foundry
project/portal URL; both the endpoint and the model/deployment name are shown
together on the deployment's details page in the Foundry portal.
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test an Azure AI Foundry VLM deployment")
    parser.add_argument("image", help="Path to an image file to send")
    parser.add_argument(
        "--prompt",
        default="Read all the text in this image, verbatim.",
        help="Instruction sent alongside the image",
    )
    args = parser.parse_args()

    endpoint = os.environ.get("AZURE_AI_ENDPOINT")
    key = os.environ.get("AZURE_AI_KEY")
    model = os.environ.get("AZURE_AI_MODEL")
    missing = [
        name
        for name, value in [
            ("AZURE_AI_ENDPOINT", endpoint),
            ("AZURE_AI_KEY", key),
            ("AZURE_AI_MODEL", model),
        ]
        if not value
    ]
    if missing:
        raise SystemExit(
            f"Missing from backend/.env: {', '.join(missing)}. "
            "See .env.example and the Foundry deployment's details page."
        )

    image_path = Path(args.image)
    if not image_path.is_file():
        raise SystemExit(f"No such file: {image_path}")

    mime, _ = mimetypes.guess_type(image_path.name)
    if mime is None or not mime.startswith("image/"):
        raise SystemExit(f"Not a recognized image type: {image_path.name}")
    data_url = f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"

    try:
        from azure.ai.inference import ChatCompletionsClient
        from azure.ai.inference.models import (
            ImageContentItem,
            ImageUrl,
            TextContentItem,
            UserMessage,
        )
        from azure.core.credentials import AzureKeyCredential
        from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
    except ImportError:
        raise SystemExit(
            "azure-ai-inference is not installed. "
            "pip install -r requirements-dev.txt (it lives there, not in requirements.txt, "
            "since this is a one-off developer test, not something the running app needs)."
        )

    client = ChatCompletionsClient(endpoint=endpoint, credential=AzureKeyCredential(key))

    print(f"Endpoint : {endpoint}")
    print(f"Model    : {model}")
    print(f"Image    : {image_path}  ({mime})")
    print(f"Prompt   : {args.prompt}")
    print()

    t0 = time.perf_counter()
    try:
        response = client.complete(
            model=model,
            messages=[
                UserMessage(
                    content=[
                        TextContentItem(text=args.prompt),
                        ImageContentItem(image_url=ImageUrl(url=data_url)),
                    ]
                )
            ],
        )
    except ClientAuthenticationError as exc:
        raise SystemExit(f"Authentication failed -- check AZURE_AI_KEY. ({exc})")
    except HttpResponseError as exc:
        raise SystemExit(
            f"Azure returned an error (status {exc.status_code}): {exc.message}\n"
            "If this is a 404, AZURE_AI_ENDPOINT is likely the Foundry project URL "
            "rather than the model's inference endpoint -- check the deployment's "
            "details page for the exact endpoint and model name."
        )
    except Exception as exc:
        raise SystemExit(f"Request failed ({type(exc).__name__}): {exc}")
    elapsed = time.perf_counter() - t0

    choice = response.choices[0]
    print("=" * 78)
    print("RESPONSE")
    print("=" * 78)
    print(choice.message.content)
    print()
    print(f"Latency : {elapsed:.2f}s")
    usage = getattr(response, "usage", None)
    if usage:
        print(f"Tokens  : prompt={usage.prompt_tokens} completion={usage.completion_tokens}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    main()
