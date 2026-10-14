"""Shared test configuration.

Two guarantees that every test run relies on:

1. **Hermetic providers.** Tests never talk to a real LLM/embedding/OCR service and never see API
   keys, regardless of what a developer's ``.env`` contains.
2. **Throwaway database.** Integration tests run against a brand-new PostgreSQL database that is
   created for the pytest session and dropped afterwards. The developer's real database named in
   ``DATABASE_URL`` is only used to *connect* (to issue ``CREATE DATABASE``); no test ever writes to it.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
BACKEND_DIRECTORY = ROOT_DIRECTORY / "backend"
sys.path.insert(0, str(BACKEND_DIRECTORY))
sys.path.insert(0, str(ROOT_DIRECTORY))

# Must happen before any ``app`` module is imported: settings are read lazily but the ORM reads the
# embedding dimension at import time.
os.environ.update(
    {
        "LLM_PROVIDER": "fake",
        "EMBEDDING_PROVIDER": "fake",
        "EMBEDDING_MODEL": "fake-embedding",
        "EMBEDDING_DIMENSIONS": "768",
        "OCR_PROVIDER": "none",
        "LLM_API_KEY": "",
        "EMBEDDING_API_KEY": "",
        "GROQ_API_KEY": "",
        "GEMINI_API_KEY": "",
        "AUTH_MODE": "development",
    }
)
# Uploaded sources go to a temp directory, never into the repository's data/ folder.
_SOURCE_DIR = tempfile.mkdtemp(prefix="autosar_test_sources_")
os.environ["DOCUMENT_SOURCE_DIR"] = _SOURCE_DIR

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

_STATE: dict[str, object] = {
    "database": None,
    "admin_url": None,
    "unavailable": "not initialised",
}


def _discover_base_url() -> str | None:
    """Find a PostgreSQL URL that is only used to issue CREATE/DROP DATABASE."""
    explicit = os.environ.get("TEST_DATABASE_ADMIN_URL") or os.environ.get(
        "DATABASE_URL"
    )
    if explicit:
        return explicit
    from app.core.config import Settings

    return Settings().database_url


def _libpq(url: str) -> str:
    parsed = make_url(url)
    return parsed.set(drivername="postgresql").render_as_string(hide_password=False)


def pytest_configure(config: pytest.Config) -> None:
    base_url = _discover_base_url()
    # Whatever happens, tests must not inherit the developer's real database URL.
    os.environ["DATABASE_URL"] = (
        "postgresql://unavailable:unavailable@127.0.0.1:1/unavailable"
    )
    if not base_url:
        _STATE["unavailable"] = "DATABASE_URL is not configured"
        return
    name = f"autosar_pytest_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    try:
        admin = make_url(base_url).set(database="postgres")
        with psycopg.connect(
            _libpq(admin.render_as_string(hide_password=False)), autocommit=True
        ) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
    except Exception as error:  # server down, wrong credentials, no CREATEDB privilege
        _STATE["unavailable"] = (
            f"PostgreSQL is not available for integration tests: {type(error).__name__}"
        )
        return
    test_url = (
        make_url(base_url).set(database=name).render_as_string(hide_password=False)
    )
    os.environ["DATABASE_URL"] = test_url
    _STATE.update(
        {
            "database": name,
            "admin_url": admin.render_as_string(hide_password=False),
            "unavailable": None,
        }
    )


def pytest_unconfigure(config: pytest.Config) -> None:
    shutil.rmtree(_SOURCE_DIR, ignore_errors=True)
    name = _STATE.get("database")
    admin_url = _STATE.get("admin_url")
    if not name or not admin_url:
        return
    try:
        from app.db.session import get_engine, get_session_factory

        get_session_factory.cache_clear()
        get_engine().dispose()
        get_engine.cache_clear()
    except Exception:
        pass
    try:
        with psycopg.connect(_libpq(str(admin_url)), autocommit=True) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (name,),
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
    except Exception:
        pass


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if os.environ.get("RUN_LIVE_TESTS") == "1":
        return
    skip_live = pytest.mark.skip(reason="live provider tests need RUN_LIVE_TESTS=1")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(scope="session")
def migrated_database() -> str:
    """Create the schema exactly as production does: by running every Alembic migration."""
    reason = _STATE["unavailable"]
    if reason:
        pytest.skip(str(reason))
    from alembic import command
    from alembic.config import Config
    from app.core.config import get_settings
    from app.db.session import get_engine, get_session_factory

    get_settings.cache_clear()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    config = Config(str(BACKEND_DIRECTORY / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIRECTORY / "alembic"))
    command.upgrade(config, "head")
    return os.environ["DATABASE_URL"]


@pytest.fixture
def clean_database(migrated_database: str) -> Iterator[None]:
    """Empty every application table before a test (fast: the schema is tiny)."""
    from app.db.session import get_engine
    from app.models.base import Base

    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with get_engine().begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def db_session(clean_database: None) -> Iterator[object]:
    """A session built by the *production* factory (same autoflush/commit semantics as the app)."""
    from app.db.session import get_session_factory

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
