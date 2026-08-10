"""Shared helper for saving FastAPI UploadFile objects to disk per-run."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import UploadFile


def save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    dest = dest_dir / upload.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest
