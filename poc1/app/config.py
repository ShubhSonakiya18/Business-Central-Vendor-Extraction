"""Application settings.

Everything here can be overridden via environment variables (see README).
The whole point of this service is that it runs fully local / CPU-only and
never phones home -- ENABLE_GOVERNMENT_VERIFICATION guards the one capability
(GST portal lookup etc.) that would talk to an external service, and it is
OFF by default.
"""
from __future__ import annotations

import os
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    # --- Storage ---
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    STORAGE_DIR: Path = Path(os.environ.get("STORAGE_DIR", BASE_DIR / "storage"))
    UPLOAD_DIR: Path = STORAGE_DIR / "uploads"
    EXCEL_DIR: Path = STORAGE_DIR / "excel"

    # --- Database ---
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL", f"sqlite:///{(STORAGE_DIR / 'vendor_intake.db').as_posix()}"
    )

    # --- OCR ---
    # Small PP-OCRv6 variant for speed, CPU inference only. Note: PP-OCRv6's
    # naming convention is "small" (not "mobile" -- that was PP-OCRv3/v4/v5's
    # naming; PaddleX's model registry only recognizes
    # PP-OCRv6_{tiny,small,medium}_{det,rec}).
    OCR_DET_MODEL: str = os.environ.get("OCR_DET_MODEL", "PP-OCRv6_small_det")
    OCR_REC_MODEL: str = os.environ.get("OCR_REC_MODEL", "PP-OCRv6_small_rec")
    OCR_LANG: str = os.environ.get("OCR_LANG", "en")
    OCR_USE_GPU: bool = False  # hard-pinned: this pipeline is CPU-only, always.
    PDF_RASTER_DPI: int = int(os.environ.get("PDF_RASTER_DPI", "300"))
    # If the native PDF text layer has fewer than this many characters, we
    # treat the page as "scanned" and fall back to OCR rasterization.
    MIN_TEXT_LAYER_CHARS: int = int(os.environ.get("MIN_TEXT_LAYER_CHARS", "40"))

    # --- External verification (disabled by default, this build never calls it) ---
    ENABLE_GOVERNMENT_VERIFICATION: bool = _bool_env(
        "ENABLE_GOVERNMENT_VERIFICATION", False
    )

    # --- Misc ---
    MAX_UPLOAD_MB: int = int(os.environ.get("MAX_UPLOAD_MB", "25"))
    ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


settings = Settings()
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.EXCEL_DIR.mkdir(parents=True, exist_ok=True)
