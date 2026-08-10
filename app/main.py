"""
FastAPI application entry point.

Two pipelines are served side by side:

  V1  "/"    Gemini multimodal extraction. Requires google-genai and a
             GEMINI_API_KEY, and sends documents to Google.
  V2  "/v2"  Fully local: PaddleOCR plus a YAML-driven semantic engine.
             No network calls, no API key.

V1's own modules are imported lazily so the app still starts in an offline
environment where google-genai is not installed -- the normal state of the
V2 virtualenv. In that case V1's routes are not registered and "/" redirects
to "/v2" instead.

Run with:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.logging import configure_logging

configure_logging()

settings.upload_dir.mkdir(exist_ok=True)
settings.output_dir.mkdir(exist_ok=True)

try:
    from app.routes import vendor_v1
    V1_AVAILABLE = True
    V1_IMPORT_ERROR = ""
except ImportError as exc:  # pragma: no cover - depends on the environment
    vendor_v1 = None
    V1_AVAILABLE = False
    V1_IMPORT_ERROR = str(exc)

from app.routes import vendor_v2

app = FastAPI(title=settings.app_title)
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

if V1_AVAILABLE:
    app.include_router(vendor_v1.router)
else:
    @app.get("/")
    def home_fallback():
        return RedirectResponse(url="/v2")

app.include_router(vendor_v2.router)

app.state.v1_available = V1_AVAILABLE
app.state.v1_import_error = V1_IMPORT_ERROR
