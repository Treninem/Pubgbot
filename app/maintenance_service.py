from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, update

from .config import get_settings
from .db import SessionLocal
from .models import Ad, TelegramUpdateLog

logger = logging.getLogger(__name__)
settings = get_settings()


async def run_maintenance() -> dict[str, int]:
    now = datetime.utcnow()
    async with SessionLocal() as db:
        expired = await db.execute(
            update(Ad)
            .where(Ad.status == "active", Ad.ends_at.is_not(None), Ad.ends_at <= now)
            .values(status="expired", updated_at=now)
        )
        old_updates = await db.execute(
            delete(TelegramUpdateLog).where(
                TelegramUpdateLog.status == "processed",
                TelegramUpdateLog.updated_at < now - timedelta(days=30),
            )
        )
        old_failed = await db.execute(
            delete(TelegramUpdateLog).where(
                TelegramUpdateLog.status == "failed",
                TelegramUpdateLog.updated_at < now - timedelta(days=90),
            )
        )
        await db.commit()
    result = {
        "expired_ads": int(expired.rowcount or 0),
        "deleted_processed_updates": int(old_updates.rowcount or 0),
        "deleted_failed_updates": int(old_failed.rowcount or 0),
    }
    if any(result.values()):
        logger.info("Плановое обслуживание: %s", result)
    return result


async def maintenance_loop(stop_event: asyncio.Event) -> None:
    interval = max(60, settings.maintenance_interval_seconds)
    while not stop_event.is_set():
        try:
            await run_maintenance()
        except Exception:
            logger.exception("Ошибка планового обслуживания")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue
