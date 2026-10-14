"""Alembic migrations are the schema contract: they must build the ORM schema from an empty database."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from tests.test_database_schema import EXPECTED_TABLES

VERSIONS = Path(__file__).parents[1] / "backend" / "alembic" / "versions"


def test_initial_migration_is_frozen_ddl_not_create_all() -> None:
    migration = (VERSIONS / "20260907_0001_mvp_schema.py").read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in migration
    # create_all would build today's models inside yesterday's revision and break later migrations.
    assert "create_all" not in migration.replace("``Base.metadata.create_all``", "")
    assert "op.create_table(" in migration


def test_migration_chain_is_linear_and_has_one_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(VERSIONS.parent))
    script = ScriptDirectory.from_config(config)
    assert len(script.get_heads()) == 1


@pytest.mark.integration
def test_empty_database_upgrades_to_head_with_all_tables_and_extensions(
    migrated_database: str,
) -> None:
    from app.db.session import get_engine

    engine = get_engine()
    assert EXPECTED_TABLES.issubset(set(inspect(engine).get_table_names()))
    with engine.connect() as connection:
        extensions = {
            row[0]
            for row in connection.exec_driver_sql("SELECT extname FROM pg_extension")
        }
    assert {"vector", "pg_trgm"}.issubset(extensions)


@pytest.mark.integration
def test_migrated_schema_matches_orm_models(migrated_database: str) -> None:
    """Fail when a model changes without a migration (or the other way round)."""
    from app.db.session import get_engine
    from app.models import Base

    def include_object(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        # Index definitions are compared by name only; operator classes/HNSW options are DDL details.
        return True

    with get_engine().connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": False,
                "include_object": include_object,
            },
        )
        differences = compare_metadata(context, Base.metadata)

    def describe(item: object) -> str:
        return repr(item)

    # ``alembic_version`` is not part of the model metadata and is never reported.
    assert not differences, "Models and migrations disagree:\n" + "\n".join(
        map(describe, differences)
    )
