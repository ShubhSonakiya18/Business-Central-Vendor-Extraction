"""
Application configuration.

Loads environment variables (from .env in development, real env vars in
deployment) into one typed object so the rest of the app never touches
os.environ directly. This is also the single place that knows how to route
between the V1 (Gemini) and V2 (local) pipelines based on what is configured.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os

APP_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = APP_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    # -- V1 (Gemini) ----------------------------------------------------
    gemini_api_key: str | None
    gemini_model: str

    # -- Routing ----------------------------------------------------------
    # "v1", "v2", or "auto" (use V1 if a key is configured, else fall back
    # to V2). This is what lets the same app.py serve both pipelines and
    # switch between them without code changes.
    default_pipeline: str

    # -- Paths --------------------------------------------------------------
    upload_dir: Path
    output_dir: Path
    templates_dir: Path
    static_dir: Path
    config_dir: Path

    # -- App ------------------------------------------------------------
    app_title: str
    debug: bool


def get_settings() -> Settings:
    return Settings(
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest"),
        default_pipeline=os.environ.get("DEFAULT_PIPELINE", "auto"),
        upload_dir=Path(os.environ.get("UPLOAD_DIR", PROJECT_ROOT / "uploads")),
        output_dir=Path(os.environ.get("OUTPUT_DIR", PROJECT_ROOT / "outputs")),
        templates_dir=APP_DIR / "templates",
        static_dir=APP_DIR / "static",
        config_dir=APP_DIR / "config",
        app_title=os.environ.get("APP_TITLE", "Vendor Form Extractor"),
        debug=os.environ.get("DEBUG", "false").lower() in ("1", "true", "yes"),
    )


settings = get_settings()
