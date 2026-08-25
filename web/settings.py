"""Paths and runtime settings for the web app.

Kept in one module so the directories are defined once rather than
recomputed relative to whichever file happens to need them.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path(os.environ.get("VENDOR_UPLOAD_DIR", BASE_DIR / "uploads"))
OUTPUT_DIR = Path(os.environ.get("VENDOR_OUTPUT_DIR", BASE_DIR / "outputs"))
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"

# The OCR model size the upload form defaults to. `small` is ~9x faster than
# `medium` for a marginal confidence cost; see ocr_engine for the measurements.
DEFAULT_OCR_MODELS = "small"
DEFAULT_MAPPING = "vendor_creation_v1"

LOG_LEVEL = os.environ.get("VENDOR_LOG_LEVEL", "INFO").upper()


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def ensure_directories() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
