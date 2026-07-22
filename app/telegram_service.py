from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import Update
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from bot import dp

from .config import get_settings
from .db import SessionLocal
from .models import TelegramUpdateLog
from .runtime import runtime_state, track_task

logger = logging.getLogger(__name__)
settings = get_settings()


async def setup_webhook(bot: Bot) -> bool:
    if settings.telegram_mode != "webhook" or not settings.webhook_auto_setup:
        return settings.telegram_mode != "webhook"
    if not settings.webhook_url:
        runtime_state.last_webhook_error = "Публичный URL webhook не задан"
        logger.error(runtime_state.last_webhook_error)
        return False
    try:
        await bot.set_webhook(
            url=settings.webhook_url,
            secret_token=settings.webhook_secret or None,
            max_connections=max(1, min(100, settings.webhook_max_connections)),
            drop_pending_updates=settings.webhook_drop_pending_updates,
            allowed_updates=dp.resolve_used_update_types(),
        )
        info = await bot.get_webhook_info()
        runtime_state.webhook_url = info.url or settings.webhook_url
        runtime_state.webhook_ready = info.url == settings.webhook_url
        runtime_state.last_webhook_error = info.last_error_message or ""
        logger.info("Telegram webhook установлен: %s", runtime_state.webhook_url)
        return runtime_state.webhook_ready
    except Exception as exc:
        runtime_state.webhook_ready = False
        runtime_state.last_webhook_error = str(exc)
        logger.exception("Не удалось установить Telegram webhook")
        return False


async def _claim_update(update_id: int) -> bool:
    stale_before = datetime.utcnow() - timedelta(minutes=2)
    async with SessionLocal() as db:
        row = (
            await db.execute(select(TelegramUpdateLog).where(TelegramUpdateLog.update_id == update_id))
        ).scalar_one_or_none()
        if row:
            if row.status == "processed":
                return False
            if row.status == "processing" and row.updated_at and row.updated_at > stale_before:
                return False
            row.status = "processing"
            row.attempts += 1
            row.error = ""
            row.updated_at = datetime.utcnow()
            await db.commit()
            return True
        db.add(TelegramUpdateLog(update_id=update_id, status="processing", attempts=1))
        try:
            await db.commit()
            return True
        except IntegrityError:
            await db.rollback()
            return False


async def _finish_update(update_id: int, *, error: str = "") -> None:
    async with SessionLocal() as db:
        row = (
            await db.execute(select(TelegramUpdateLog).where(TelegramUpdateLog.update_id == update_id))
        ).scalar_one_or_none()
        if not row:
            return
        row.status = "failed" if error else "processed"
        row.error = error[:4000]
        row.updated_at = datetime.utcnow()
        await db.commit()


async def _process_update(bot: Bot, update: Update) -> None:
    try:
        await dp.feed_update(bot, update)
    except Exception as exc:
        await _finish_update(update.update_id, error=str(exc))
        logger.exception("Ошибка обработки Telegram update_id=%s", update.update_id)
        return
    await _finish_update(update.update_id)


async def telegram_webhook(request: Request) -> dict:
    bot: Bot | None = getattr(request.app.state, "telegram_bot", None)
    if bot is None or settings.telegram_mode != "webhook":
        raise HTTPException(status_code=503, detail="Telegram webhook отключён")
    if settings.webhook_secret:
        received = request.headers.get("x-telegram-bot-api-secret-token", "")
        if received != settings.webhook_secret:
            raise HTTPException(status_code=403, detail="Некорректный секрет webhook")
    try:
        payload = await request.json()
        update = Update.model_validate(payload, context={"bot": bot})
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Некорректный Telegram update") from exc

    if not await _claim_update(update.update_id):
        return {"ok": True, "duplicate": True}
    task = asyncio.create_task(_process_update(bot, update), name=f"telegram-update-{update.update_id}")
    track_task(task, label=f"telegram update {update.update_id}")
    return {"ok": True}
