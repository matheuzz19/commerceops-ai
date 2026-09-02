"""Synchronous SQLAlchemy session factory used by repositories and services."""

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from commerceops.config import settings


def build_engine(database_url: str) -> Engine:
    """Create an engine without binding application code to one database vendor."""
    return create_engine(database_url, pool_pre_ping=True)


engine = build_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    """Yield a transaction boundary for FastAPI dependencies and scripts."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
