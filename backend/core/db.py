"""The api's database: SQLite in the data directory, migrated at startup. Requests get an
AsyncSession through the `db` dependency."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from alembic import command
from alembic.config import Config
from fastapi import Request
from pydantic import AfterValidator
from sqlalchemy import MetaData, event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parent.parent


def db_path(data_dir: Path) -> Path:
    return data_dir / "echo.db"


def migrate(data_dir: Path) -> None:
    # Alembic is synchronous, so the caller runs this in a thread. It uses the stdlib sqlite3 driver.
    config = Config(BACKEND_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path(data_dir)}")
    command.upgrade(config, "head")


def create_engine(data_dir: Path) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path(data_dir)}")

    # SQLite ignores foreign keys unless each connection turns them on.
    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


async def db(request: Request) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(request.app.state.db_engine, expire_on_commit=False)() as session:
        yield session


# Table definitions the repositories query. The migrations, not this, create and change the schema.
metadata = MetaData()


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# SQLite keeps no time zone, so stored times come back naive. They were written in UTC, and API
# responses must say so, or a browser reads them as its own local time.
UtcDateTime = Annotated[datetime, AfterValidator(_as_utc)]
