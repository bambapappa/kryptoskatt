"""Database engine and session factory."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kryptoskatt.config import settings


def normalize_db_url(url: str) -> str:
    """Route plain postgresql:// URLs to the psycopg (v3) driver.

    SQLAlchemy interprets a bare ``postgresql://`` scheme as psycopg2;
    this project uses psycopg 3. Explicit drivers (``postgresql+X://``)
    and non-PostgreSQL URLs are left untouched.
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


engine = create_engine(normalize_db_url(settings.database_url))
SessionLocal = sessionmaker(bind=engine)


def get_session() -> Session:
    """Create and return a new database session."""
    return SessionLocal()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yield a session and always close it."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()
