from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_db
from .models import User


def validate_init_data(init_data: str, bot_token: str, ttl: int) -> dict:
    if not init_data or not bot_token:
        raise ValueError("Telegram initData недоступны")
    pairs = dict(parse_qsl(init_data, strict_parsing=True))
    received_hash = pairs.pop("hash", "")
    auth_date = int(pairs.get("auth_date", "0"))
    if not received_hash or not auth_date:
        raise ValueError("Некорректные initData")
    if int(time.time()) - auth_date > ttl:
        raise ValueError("initData устарели")
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_hash, expected_hash):
        raise ValueError("Подпись initData не прошла проверку")
    raw_user = pairs.get("user")
    if not raw_user:
        raise ValueError("В initData нет пользователя")
    return json.loads(raw_user)


def is_exact_owner(user: User) -> bool:
    settings = get_settings()
    owner_id = settings.effective_owner_telegram_id
    return bool(owner_id and user.telegram_id == owner_id and user.role == "owner")


async def get_current_user(
    db: AsyncSession,
    x_telegram_init_data: str | None,
    x_dev_telegram_id: int | None,
) -> User:
    settings = get_settings()
    user_data: dict
    if x_telegram_init_data:
        try:
            user_data = validate_init_data(
                x_telegram_init_data, settings.bot_token, settings.init_data_ttl_seconds
            )
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
    elif settings.allow_dev_auth:
        telegram_id = x_dev_telegram_id or settings.dev_telegram_id
        user_data = {
            "id": telegram_id,
            "username": "dev_user",
            "first_name": "Тестовый игрок",
        }
    else:
        raise HTTPException(status_code=401, detail="Откройте Mini App через Telegram")

    telegram_id = int(user_data["id"])
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    should_be_owner = bool(settings.effective_owner_telegram_id and telegram_id == settings.effective_owner_telegram_id)
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=user_data.get("username"),
            display_name=" ".join(
                x for x in [user_data.get("first_name"), user_data.get("last_name")] if x
            ) or "Игрок",
            role="owner" if should_be_owner else "user",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    elif should_be_owner and user.role != "owner":
        user.role = "owner"
        await db.commit()
    elif not should_be_owner and user.role == "owner":
        # Роль владельца нельзя получить изменением записи в БД.
        user.role = "user"
        await db.commit()

    if user.is_banned:
        message = "Доступ ограничен владельцем"
        if user.ban_reason:
            message += f": {user.ban_reason}"
        raise HTTPException(status_code=403, detail=message)

    now = datetime.utcnow()
    changed = False
    if user.is_muted and user.mute_until and user.mute_until <= now:
        user.is_muted = False
        user.mute_until = None
        changed = True
    if not user.last_seen_at or user.last_seen_at <= now - timedelta(minutes=5):
        user.last_seen_at = now
        changed = True
    if changed:
        await db.commit()
    return user


async def auth_user(
    db: AsyncSession = Depends(get_db),
    x_telegram_init_data: str | None = Header(default=None),
    x_dev_telegram_id: int | None = Header(default=None),
) -> User:
    return await get_current_user(db, x_telegram_init_data, x_dev_telegram_id)


async def owner_only(user: User = Depends(auth_user)) -> User:
    if not is_exact_owner(user):
        raise HTTPException(status_code=404, detail="Раздел не найден")
    return user


def require_roles(user: User, *roles: str) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="Недостаточно прав")


def require_not_muted(user: User) -> None:
    if not user.is_muted:
        return
    until = f" до {user.mute_until:%d.%m.%Y %H:%M} UTC" if user.mute_until else ""
    raise HTTPException(status_code=403, detail=f"Отправка и создание материалов временно ограничены{until}")


def require_ads_allowed(user: User) -> None:
    if user.ads_blocked:
        raise HTTPException(status_code=403, detail="Размещение рекламы запрещено владельцем")
    require_not_muted(user)
