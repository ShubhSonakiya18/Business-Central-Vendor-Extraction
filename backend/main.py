"""FastAPI application factory.

Run from this directory with:
    uvicorn main:app --reload

The `app` name below is rebound from the package to the FastAPI instance once
the imports above have resolved, so import names out of `app.*` rather than
importing the package itself.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config.settings import (
    APP_TITLE,
    STATIC_DIR,
    configure_logging,
    ensure_directories,
)
from app.routers.extraction import router
from app.routers.onboarding import router as onboarding_router
from app.database.db import get_db, Base, engine
from app.routers.auth import router as auth_router

Base.metadata.create_all(bind=engine)

def create_app() -> FastAPI:
    configure_logging()
    ensure_directories()

    app = FastAPI(title=APP_TITLE)

    # Allow the React dev server (and any production origin) to call the API
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_origin_regex=r"https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)
    app.include_router(onboarding_router)
    app.include_router(auth_router)
    return app


app = create_app()
