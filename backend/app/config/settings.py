"""Paths and runtime settings for the web app.

Kept in one module so the directories are defined once rather than
recomputed relative to whichever file happens to need them. Every path is
anchored to this file's own location, so the app does not depend on the
directory uvicorn happens to be started from.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).resolve()
APP_DIR = _HERE.parents[1]          # backend/app
BACKEND_DIR = _HERE.parents[2]      # backend
PROJECT_ROOT = _HERE.parents[3]     # repository root
FRONTEND_DIR = PROJECT_ROOT / "frontend"

load_dotenv(BACKEND_DIR / ".env")

# Runtime data lives inside the app package; the templates and CSS it renders
# are the frontend's, so they are looked up outside the backend entirely.
UPLOAD_DIR = Path(os.environ.get("VENDOR_UPLOAD_DIR", APP_DIR / "uploads"))
OUTPUT_DIR = Path(os.environ.get("VENDOR_OUTPUT_DIR", APP_DIR / "outputs"))
LOG_DIR = APP_DIR / "logs"
STATIC_DIR = FRONTEND_DIR / "static"
TEMPLATE_DIR = FRONTEND_DIR / "templates"

APP_TITLE = os.environ.get("APP_TITLE", "Vendor Form Extractor")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

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
    LOG_DIR.mkdir(parents=True, exist_ok=True)
