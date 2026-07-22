from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import Update
from fastapi import HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from bot import dp

from .config import get_settings
from .db import SessionLocal
from .models import TelegramUpdateLog
from .runtime import runtime_state

logger = logging.getLogger(__name__)
settings = get_settings()


async def _sync_bot_identity(bot_id: int) -> None:
    """Сбрасывает дедупликацию update только при смене Telegram-бота.

    update_id уникален только внутри одного бота. Постоянная база может пережить
    redeploy и содержать номера update другого или тестового бота. Без фиксации
    bot_id новая команда /start могла ошибочно считаться старым дублем.
    """
    async with SessionLocal() as db:
        await db.execute(text(
            "CREATE TABLE IF NOT EXISTS app_runtime_meta ("
            "meta_key VARCHAR(100) PRIMARY KEY, "
            "meta_value TEXT NOT NULL, "
            "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))
        result = await db.execute(
            text("SELECT meta_value FROM app_runtime_meta WHERE meta_key = :key"),
            {"key": "telegram_bot_id"},
        )
        previous = result.scalar_one_or_none()
        current = str(bot_id)
        if previous == current:
            await db.commit()
            return

        await db.execute(text("DELETE FROM telegram_update_log"))
        if previous is None:
            await db.execute(
                text(
                    "INSERT INTO app_runtime_meta (meta_key, meta_value, updated_at) "
                    "VALUES (:key, :value, CURRENT_TIMESTAMP)"
                ),
                {"key": "telegram_bot_id", "value": current},
            )
        else:
            await db.execute(
                text(
                    "UPDATE app_runtime_meta "
                    "SET meta_value = :value, updated_at = CURRENT_TIMESTAMP "
                    "WHERE meta_key = :key"
                ),
                {"key": "telegram_bot_id", "value": current},
            )
        await db.commit()
        logger.warning(
            "Сброшен журнал Telegram update после смены/первой фиксации бота: old_bot_id=%s new_bot_id=%s",
            previous or "not-set",
            current,
        )


async def setup_webhook(bot: Bot) -> bool:
    if settings.telegram_mode != "webhook" or not settings.webhook_auto_setup:
        return settings.telegram_mode != "webhook"
    if not settings.webhook_url:
        runtime_state.last_webhook_error = "Публичный URL webhook не задан"
        logger.error(runtime_state.last_webhook_error)
        return False
    try:
        me = await bot.get_me()
        logger.info("Telegram-бот подключён: id=%s username=@%s", me.id, me.username or "без_username")
        await _sync_bot_identity(me.id)
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
        logger.info(
            "Telegram webhook установлен: url=%s pending_updates=%s allowed_updates=%s",
            runtime_state.webhook_url,
            info.pending_update_count,
            dp.resolve_used_update_types(),
        )
        if info.last_error_message:
            logger.warning(
                "Telegram сообщает об ошибке webhook: %s",
                info.last_error_message,
            )
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
        handled = await dp.feed_update(bot, update)
    except Exception as exc:
        await _finish_update(update.update_id, error=str(exc))
        logger.exception("Ошибка обработки Telegram update_id=%s", update.update_id)
        raise
    await _finish_update(update.update_id)
    logger.info(
        "Telegram update обработан: update_id=%s type=%s handled=%s",
        update.update_id,
        update.event_type,
        handled is not None,
    )


async def telegram_webhook(request: Request) -> dict:
    bot: Bot | None = getattr(request.app.state, "telegram_bot", None)
    if bot is None or settings.telegram_mode != "webhook":
        raise HTTPException(status_code=503, detail="Telegram webhook отключён")
    if settings.webhook_secret:
        received = request.headers.get("x-telegram-bot-api-secret-token", "")
        if received != settings.webhook_secret:
            logger.warning(
                "Отклонён Telegram webhook: отсутствует или не совпадает секрет, ip=%s",
                request.client.host if request.client else "unknown",
            )
            raise HTTPException(status_code=403, detail="Некорректный секрет webhook")
    try:
        payload = await request.json()
        update = Update.model_validate(payload, context={"bot": bot})
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Некорректный Telegram update") from exc

    user_id = None
    if update.message and update.message.from_user:
        user_id = update.message.from_user.id
    elif update.callback_query and update.callback_query.from_user:
        user_id = update.callback_query.from_user.id
    elif update.pre_checkout_query and update.pre_checkout_query.from_user:
        user_id = update.pre_checkout_query.from_user.id

    logger.info(
        "Получен Telegram update: update_id=%s type=%s user_id=%s",
        update.update_id,
        update.event_type,
        user_id,
    )

    if not await _claim_update(update.update_id):
        logger.info("Telegram update пропущен как дубль: update_id=%s", update.update_id)
        return {"ok": True, "duplicate": True}

    # Обрабатываем update до возврата HTTP 200. Это важно для небольших
    # команд вроде /start: исключает потерю фоновой задачи на хостинге и
    # позволяет Telegram повторить доставку при временной ошибке.
    try:
        await _process_update(bot, update)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Ошибка обработки Telegram update") from exc
    return {"ok": True}
