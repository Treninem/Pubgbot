from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def _prepare_sqlite_directory(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return
    database_path = Path(url.database)
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path
    database_path.parent.mkdir(parents=True, exist_ok=True)


_prepare_sqlite_directory(settings.database_url)
engine_options: dict = {
    "echo": settings.debug,
    "pool_pre_ping": True,
}
if settings.database_url.startswith("postgresql"):
    engine_options.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle_seconds,
    )
engine = create_async_engine(settings.database_url, **engine_options)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as session:
        yield session


async def check_db() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Проверка соединения с базой данных не пройдена")
        return False


async def close_db() -> None:
    await engine.dispose()


def _add_missing_columns(sync_conn, table: str, additions: dict[str, str]) -> None:
    inspector = inspect(sync_conn)
    if table not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns(table)}
    for column, ddl in additions.items():
        if column not in existing:
            sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def _migrate_legacy_schema(sync_conn) -> None:
    """Add missing v0.9-v1.2 columns without deleting existing data."""
    _add_missing_columns(sync_conn, "clans", {
        "modes": "VARCHAR(240) NOT NULL DEFAULT 'Классика'",
        "maps": "VARCHAR(240) NOT NULL DEFAULT ''",
        "logo_url": "VARCHAR(300) NOT NULL DEFAULT ''",
        "max_members": "INTEGER NOT NULL DEFAULT 30",
        "join_policy": "VARCHAR(20) NOT NULL DEFAULT 'approval'",
        "rating_points": "INTEGER NOT NULL DEFAULT 0",
        "blocked_reason": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TIMESTAMP NULL",
    })
    _add_missing_columns(sync_conn, "clan_members", {"updated_at": "TIMESTAMP NULL"})
    _add_missing_columns(sync_conn, "users", {
        "is_muted": "BOOLEAN NOT NULL DEFAULT FALSE",
        "mute_until": "TIMESTAMP NULL",
        "ads_blocked": "BOOLEAN NOT NULL DEFAULT FALSE",
        "ban_reason": "TEXT NOT NULL DEFAULT ''",
        "moderation_note": "TEXT NOT NULL DEFAULT ''",
        "last_seen_at": "TIMESTAMP NULL",
    })
    _add_missing_columns(sync_conn, "rooms", {
        "moderation_reason": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TIMESTAMP NULL",
    })
    _add_missing_columns(sync_conn, "ads", {
        "tariff_id": "INTEGER NULL",
        "placement": "VARCHAR(30) NOT NULL DEFAULT 'standard'",
        "priority": "INTEGER NOT NULL DEFAULT 0",
        "is_pinned": "BOOLEAN NOT NULL DEFAULT FALSE",
        "paid_at": "TIMESTAMP NULL",
        "refunded_at": "TIMESTAMP NULL",
        "updated_at": "TIMESTAMP NULL",
    })


async def _seed_default_tariffs() -> None:
    from .models import AdTariff

    async with SessionLocal() as db:
        total = int((await db.execute(select(func.count()).select_from(AdTariff))).scalar_one())
        if total:
            return
        db.add_all([
            AdTariff(name="Старт", description="Обычное размещение на 3 дня.", price_stars=25,
                     duration_days=3, placement="standard", priority=0, is_pinned=False),
            AdTariff(name="Премиум", description="Приоритетное размещение на 7 дней.", price_stars=60,
                     duration_days=7, placement="premium", priority=20, is_pinned=False),
            AdTariff(name="ТОП", description="Закрепление выше остальных объявлений на 14 дней.",
                     price_stars=120, duration_days=14, placement="top", priority=100, is_pinned=True),
        ])
        await db.commit()


async def init_db() -> None:
    from . import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_legacy_schema)
    await _seed_default_tariffs()


async def init_db_with_retry() -> None:
    attempts = max(1, settings.db_startup_retries)
    for attempt in range(1, attempts + 1):
        try:
            await init_db()
            logger.info("База данных готова")
            return
        except Exception:
            if attempt >= attempts:
                logger.exception("База данных недоступна после %s попыток", attempts)
                raise
            logger.warning("База данных недоступна, попытка %s/%s", attempt, attempts, exc_info=True)
            await asyncio.sleep(max(0.1, settings.db_startup_retry_seconds))
