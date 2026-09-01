"""Test setup: isolate storage + DB into a temp dir *before* any `app.*`
module is imported anywhere in the test session (settings are read once, at
import time), then generate the synthetic fixture documents."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_STORAGE = Path(tempfile.mkdtemp(prefix="vendor_intake_test_"))
os.environ["STORAGE_DIR"] = str(_TEST_STORAGE)
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_STORAGE / 'test.db').as_posix()}"
os.environ["ENABLE_GOVERNMENT_VERIFICATION"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from tests.fixtures.make_fixtures import build_all  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def _bootstrap():
    init_db()
    build_all(FIXTURES_DIR)
    yield


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client():
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR
