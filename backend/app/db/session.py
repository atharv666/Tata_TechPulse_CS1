"""SQLAlchemy engine, transactions, and FastAPI dependency boundaries."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


class DatabaseConfigurationError(RuntimeError):
    """Raised when an operation requires DATABASE_URL but none is configured."""


@lru_cache
def get_engine() -> Engine:
    """Create the PostgreSQL engine lazily so importing the API never contacts a database."""
    database_url = get_settings().database_url
    if database_url is None:
        raise DatabaseConfigurationError("DATABASE_URL must be configured for database operations.")
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    settings = get_settings()
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Return a typed, non-autocommitting session factory."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    """Provide one transaction-scoped SQLAlchemy session to an API request."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> None:
    """Verify connectivity and required PostgreSQL extensions without changing schema state."""
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
        extensions = (
            connection.execute(
                text("SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm')")
            )
            .scalars()
            .all()
        )
    missing = {"vector", "pg_trgm"}.difference(extensions)
    if missing:
        raise RuntimeError(
            f"Required PostgreSQL extensions are unavailable: {', '.join(sorted(missing))}"
        )
