"""Entrypoint for the vendor extraction web app.

The application itself lives in web/; this module exists so the documented
`uvicorn app:app` command keeps working. `uvicorn web.main:app` is equivalent.
"""

from web.main import app

__all__ = ["app"]
