"""Database engine and session factory."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from kryptoskatt.config import settings

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine)


def get_session() -> Session:
    """Create and return a new database session."""
    return SessionLocal()
