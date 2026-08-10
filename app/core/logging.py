"""
Application-wide logging setup.

V2's modules (document_loader, ocr_engine, pipeline, etc.) already call
logging.getLogger(__name__) but nothing configures the root logger when
running under uvicorn -- only the standalone CLI scripts call basicConfig.
configure_logging() is called once from app/main.py so those logger calls
end up on stdout with a consistent format instead of being silently dropped
below WARNING level.
"""

from __future__ import annotations

import logging

from app.core.config import settings


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
