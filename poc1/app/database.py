"""SQLAlchemy engine/session setup + simple create_all() bootstrap.

v1 targets SQLite (file-based, zero-config, fine for single-tenant local use).
The models use plain SQLAlchemy Core-compatible types so swapping
DATABASE_URL to Postgres later is a drop-in change -- no SQLite-specific
column types are used anywhere in app/models.py.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Bootstrap the schema. Import models first so they register on Base.metadata."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
