"""Persistence for completed runs.

A run's results are written under outputs/<run_id>/ already, so the state the
results page needs belongs there too rather than in a process-local dict: an
in-memory store grows without bound and, under more than one uvicorn worker,
strands a user on a worker that never saw their run.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from ..config.settings import OUTPUT_DIR

logger = logging.getLogger(__name__)

# The id format new_run_id() produces. run_id arrives from the URL and is then
# used as a path segment, so anything not matching this is refused rather than
# being allowed to walk out of the outputs directory.
_RUN_ID = re.compile(r"[0-9a-f]{10}")


def new_run_id() -> str:
    return uuid.uuid4().hex[:10]


def run_directory(run_id: str) -> Path:
    return OUTPUT_DIR / run_id


def _state_path(run_id: str) -> Path:
    return run_directory(run_id) / "run_state.json"


def save(run_id: str, state: dict) -> None:
    path = _state_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def load(run_id: str) -> Optional[dict]:
    """Return a persisted run, or None if the id is unknown or malformed."""
    if not _RUN_ID.fullmatch(run_id):
        return None
    path = _state_path(run_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Could not read run state for %s", run_id)
        return None
