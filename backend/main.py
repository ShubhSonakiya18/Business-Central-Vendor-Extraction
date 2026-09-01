"""FastAPI application factory.

Run from this directory with:
    uvicorn main:app --reload

The `app` name below is rebound from the package to the FastAPI instance once
the imports above have resolved, so import names out of `app.*` rather than
importing the package itself.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config.settings import (
    APP_TITLE,
    STATIC_DIR,
    configure_logging,
    ensure_directories,
)
from app.routers.extraction import router


def create_app() -> FastAPI:
    configure_logging()
    ensure_directories()

    app = FastAPI(title=APP_TITLE)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)
    return app


app = create_app()
