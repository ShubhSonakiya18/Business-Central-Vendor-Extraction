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

# Render DPI for RapidOCR, the active default engine as of 2026-09-01
# (OCR_BACKEND=rapidocr). The preserved PaddleOCR fallback stays at
# extraction_pipeline.models.RENDER_DPI (200) -- this is deliberately
# separate rather than raising that shared constant, because RENDER_DPI also
# sizes the synthetic DOCX coordinate space (document_loader.py: DOCX_PAGE_W/H,
# margins, line height), and a global bump would rescale that for a backend
# it was never asked for. document_loader._default_dpi_for() picks the right
# one automatically based on which engine is actually active.
#
# SUPERSEDED 2026-09-01: 125 DPI (set 2026-08-31) was chosen from a sweep
# that only ever tested threads=4, so it could not see a thread x DPI
# interaction. A later 12-rep, 16-config (threads x DPI) isolated sweep
# -- full latency stats (median/P90/stdev/CV) plus per-config identifier
# self-consistency AND agreement with a PaddleOCR reference, not median
# speed alone -- found threads=8 at DPI=125 is the least stable config in
# the whole grid (CV=0.40, spiked to 70s vs a 26s median), while threads=8
# at DPI=100 is both the fastest AND most stable config measured overall:
# 19.72s median, P90 19.90s, CV=0.01, zero identifier mismatches across 12
# reps. This DPI change is paired with intra_op_num_threads=8 (see
# ocr_engine.RapidOCRTuning) -- the two were not validated independently at
# any other combination, so do not change one without re-checking the other
# against the sweep data (see plan.md).
#
# All prior finding retained: RapidOCR's max_side_len (3508 by default, see
# RapidOCRTuning) is only a ceiling, so it stays safely unheeded at 100 DPI.
# If this is later raised past ~300 DPI on an A4 page, max_side_len needs
# raising in lockstep (>= ceil(11.69 * dpi)) or the extra resolution is
# silently downscaled straight back off before detection ever sees it --
# set OCR_RAPID_MAX_SIDE_LEN accordingly, or pass --ocr-tune
# max_side_len=... on the CLI.
RAPID_RENDER_DPI = int(os.environ.get("VENDOR_RAPID_RENDER_DPI", "100"))

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
