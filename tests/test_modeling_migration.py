from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from packages.platform_core.database import Base
from packages.platform_core.models import User, Workspace
from packages.platform_core.settings import get_settings


def test_isolated_0015_upgrade_and_one_step_downgrade(tmp_path, monkeypatch):
    database = tmp_path / "isolated-modeling-migration.sqlite"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    try:
        engine = create_engine(url)
        try:
            Base.metadata.create_all(engine, tables=[User.__table__, Workspace.__table__])
        finally:
            engine.dispose()
        # Earlier migrations contain PostgreSQL-only ALTER operations. This
        # isolated test verifies 0015; full-chain upgrade requires PostgreSQL.
        command.stamp(config, "20260927_0014")
        command.upgrade(config, "head")
        engine = create_engine(url)
        try:
            names = inspect(engine).get_table_names()
            assert {
                "model_training_snapshots",
                "model_jobs",
                "registered_models",
                "model_versions",
            }.issubset(names)
        finally:
            engine.dispose()
        command.downgrade(config, "-1")
        engine = create_engine(url)
        try:
            names = inspect(engine).get_table_names()
            assert "model_jobs" not in names and "workspaces" in names
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()
