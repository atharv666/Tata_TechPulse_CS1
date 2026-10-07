"""Alembic migration tests; live application is opt-in through DATABASE_TEST_URL."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import get_settings
from sqlalchemy import create_engine, inspect, text

from tests.test_database_schema import EXPECTED_TABLES


def test_initial_migration_declares_required_extensions_and_schema_creation() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "backend"
        / "alembic"
        / "versions"
        / "20260907_0001_mvp_schema.py"
    )
    migration = migration_path.read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in migration
    assert "Base.metadata.create_all" in migration


def test_chunk_extraction_state_migration_is_present() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "backend"
        / "alembic"
        / "versions"
        / "20260909_0006_chunk_extraction_state.py"
    )
    migration = migration_path.read_text(encoding="utf-8")

    assert 'revision = "20260909_0006"' in migration
    assert 'down_revision = "20260908_0005"' in migration
    assert 'add_column("chunks"' in migration


@pytest.mark.integration
def test_initial_migration_applies_to_postgresql_with_extensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip(
            "DATABASE_TEST_URL is required for PostgreSQL migration integration tests."
        )

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    alembic_config = Config(str(Path(__file__).parents[1] / "backend" / "alembic.ini"))
    command.upgrade(alembic_config, "head")

    engine = create_engine(database_url)
    try:
        assert EXPECTED_TABLES.issubset(set(inspect(engine).get_table_names()))
        extensions = set(
            engine.execute(text("SELECT extname FROM pg_extension")).scalars()
        )  # type: ignore[attr-defined]
        assert {"vector", "pg_trgm"}.issubset(extensions)
    finally:
        engine.dispose()
        get_settings.cache_clear()
