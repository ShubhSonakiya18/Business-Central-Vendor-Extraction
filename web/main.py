"""FastAPI application factory.

Run with:
    uvicorn app:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import router
from .settings import STATIC_DIR, configure_logging, ensure_directories


def create_app() -> FastAPI:
    configure_logging()
    ensure_directories()

    app = FastAPI(title="Vendor Form Extractor")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)
    return app


app = create_app()
