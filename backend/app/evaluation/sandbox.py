"""A throwaway PostgreSQL database for evaluation runs, so they never touch real project data."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url


def _libpq(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


@contextmanager
def temporary_database(base_url: str, keep: bool = False) -> Iterator[str]:
    """Create ``autosar_eval_<id>``, apply every migration, yield its URL, then drop it.

    ``base_url`` is only used to connect and issue CREATE/DROP DATABASE; its own database is
    never touched.
    The process environment is pointed at the new database for the duration (settings and engines
    are reset so the application code picks it up).
    """
    from alembic.config import Config

    from alembic import command
    from app.core.config import get_settings
    from app.db.session import get_engine, get_session_factory

    name = f"autosar_eval_{uuid.uuid4().hex[:10]}"
    admin = make_url(base_url).set(database="postgres").render_as_string(hide_password=False)
    with psycopg.connect(_libpq(admin), autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}"')
    url = make_url(base_url).set(database=name).render_as_string(hide_password=False)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url

    def reset() -> None:
        get_settings.cache_clear()
        try:
            get_session_factory.cache_clear()
            get_engine().dispose()
        except Exception:
            pass
        get_engine.cache_clear()

    try:
        reset()
        backend = Path(__file__).resolve().parents[2]
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "head")
        yield url
    finally:
        reset()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        reset()
        if not keep:
            with psycopg.connect(_libpq(admin), autocommit=True) as connection:
                connection.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                    (name,),
                )
                connection.execute(f'DROP DATABASE IF EXISTS "{name}"')
