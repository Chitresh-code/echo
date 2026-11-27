import sqlite3

from fastapi.testclient import TestClient

from core.config import get_settings
from core.db import db_path


def tables(path):
    with sqlite3.connect(path) as conn:
        return {row[0] for row in conn.execute("select name from sqlite_master where type = 'table'")}


def test_startup_migrates_a_fresh_database_and_again_is_a_no_op(app, fake_runner):
    path = db_path(get_settings().data_dir)
    with TestClient(app):
        pass
    assert {"users", "sessions", "agents", "credentials", "alembic_version"} <= tables(path)
    with sqlite3.connect(path) as conn:
        conn.execute("insert into users values ('u', 't', 'o', null, null, '2026-01-01', '2026-01-01')")
    # A second start finds the schema current and leaves the data alone.
    with TestClient(app):
        pass
    with sqlite3.connect(path) as conn:
        assert conn.execute("select count(*) from users").fetchone() == (1,)
        assert conn.execute("select version_num from alembic_version").fetchone() == ("0005",)


def test_requests_get_a_session_with_foreign_keys_on(app, fake_runner):
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    with TestClient(app):
        async def insert_orphan():
            async with app.state.db_engine.begin() as conn:
                await conn.execute(text("insert into sessions values ('h', 'nobody', '2026-01-01', '2026-01-02')"))

        try:
            asyncio.run(insert_orphan())
            raise AssertionError("a session for a missing user was accepted")
        except IntegrityError:
            pass


def test_migration_keeps_workspaces_made_before_agents(app, fake_runner):
    from alembic import command
    from alembic.config import Config

    from core.db import BACKEND_DIR

    path = db_path(get_settings().data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    config = Config(BACKEND_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "0001")
    with sqlite3.connect(path) as conn:
        conn.execute("insert into users values ('u', 't', 'o', null, null, '2026-01-01', '2026-01-01')")
        conn.execute("insert into workspaces values ('w', 'u', '2026-01-01')")
    with TestClient(app):
        pass
    with sqlite3.connect(path) as conn:
        assert conn.execute("select id, owner_id, name, job, last_used_at from agents").fetchall() == [("w", "u", "Untitled agent", "", None)]


def test_stored_times_reach_the_api_as_utc():
    from datetime import datetime

    from apps.credentials.models.credential import Credential

    naive = Credential(id="c", provider="openai", label="l", base_url=None, key_hint="", created_at=datetime(2026, 1, 1, 12))
    assert '"created_at":"2026-01-01T12:00:00Z"' in naive.model_dump_json()
