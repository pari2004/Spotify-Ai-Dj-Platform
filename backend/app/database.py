"""SQLAlchemy engine + session management.

Scope decision (PRD §13.2): default persistence is SQLite for zero-config, single-machine
runnability. The code only uses portable SQLAlchemy Core/ORM so the same models run on
PostgreSQL by changing DATABASE_URL — no query rewrites needed.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

settings = get_settings()

# check_same_thread is a SQLite-only flag; harmless/ignored on Postgres.
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a scoped DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Called on startup and by tests."""
    from . import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)
