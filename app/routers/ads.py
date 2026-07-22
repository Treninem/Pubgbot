from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import auth_user, require_ads_allowed
from ..config import get_settings
from ..db import get_db
from ..models import Ad, AdTariff, Payment, User
from ..payment_service import complete_successful_payment
from ..schemas import AdIn

router = APIRouter(prefix="/ads", tags=["ads"])
ALLOWED = {
    "Набор в клан", "Постоянный состав", "Игровая группа", "Турнир",
    "Скрим", "Тренировка", "Помощь новичкам", "Игровой канал",
}


def model_dict(value) -> dict:
    return {column.name: getattr(value, column.name) for column in value.__table__.columns}


async def expire_finished_ads(db: AsyncSession) -> None:
    now = datetime.utcnow()
    result = await db.execute(
        update(Ad)
        .where(Ad.status == "active", Ad.ends_at.is_not(None), Ad.ends_at <= now)
        .values(status="expired")
    )
    if result.rowcount:
        await db.commit()


@router.get("/tariffs")
async def tariffs(db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    rows = (
        await db.execute(
            select(AdTariff).where(AdTariff.is_active.is_(True)).order_by(
                AdTariff.price_stars.asc(), AdTariff.id.asc()
            )
        )
    ).scalars().all()
    return [model_dict(item) for item in rows]


@router.get("/mine")
async def my_ads(db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    await expire_finished_ads(db)
    rows = (
        await db.execute(
            select(Ad, AdTariff)
            .outerjoin(AdTariff, AdTariff.id == Ad.tariff_id)
            .where(Ad.user_id == user.id)
            .order_by(Ad.id.desc())
        )
    ).all()
    result = []
    for ad, tariff in rows:
        payment = (
            await db.execute(
                select(Payment).where(Payment.ad_id == ad.id).order_by(Payment.id.desc()).limit(1)
            )
        ).scalar_one_or_none()
        result.append({
            **model_dict(ad),
            "tariff": model_dict(tariff) if tariff else None,
            "payment": model_dict(payment) if payment else None,
        })
    return result


@router.get("")
async def active_ads(db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    await expire_finished_ads(db)
    rows = (
        await db.execute(
            select(Ad, AdTariff)
            .outerjoin(AdTariff, AdTariff.id == Ad.tariff_id)
            .where(Ad.status == "active")
            .order_by(Ad.is_pinned.desc(), Ad.priority.desc(), Ad.id.desc())
            .limit(100)
        )
    ).all()
    return [{**model_dict(ad), "tariff": model_dict(tariff) if tariff else None} for ad, tariff in rows]


@router.post("")
async def create(payload: AdIn, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    require_ads_allowed(user)
    if payload.category not in ALLOWED:
        raise HTTPException(400, "Категория не разрешена")
    if not payload.url.startswith("https://t.me/"):
        raise HTTPException(400, "Разрешены только безопасные Telegram-ссылки")
    tariff = await db.get(AdTariff, payload.tariff_id)
    if not tariff or not tariff.is_active:
        raise HTTPException(400, "Тариф недоступен")
    data = payload.model_dump(exclude={"tariff_id"})
    ad = Ad(
        user_id=user.id,
        tariff_id=tariff.id,
        **data,
        price_stars=tariff.price_stars,
        duration_days=tariff.duration_days,
        placement=tariff.placement,
        priority=tariff.priority,
        is_pinned=tariff.is_pinned,
        status="draft",
    )
    db.add(ad)
    await db.commit()
    await db.refresh(ad)
    return {**model_dict(ad), "tariff": model_dict(tariff)}


@router.post("/{ad_id}/invoice")
async def create_invoice(ad_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    require_ads_allowed(user)
    ad = await db.get(Ad, ad_id)
    if not ad or ad.user_id != user.id:
        raise HTTPException(404, "Рекламная заявка не найдена")
    if ad.status not in {"draft", "awaiting_payment"}:
        raise HTTPException(409, "Для этой заявки нельзя создать новый счёт")
    tariff = await db.get(AdTariff, ad.tariff_id) if ad.tariff_id else None
    if not tariff:
        raise HTTPException(409, "Тариф заявки больше не существует")

    old_rows = (
        await db.execute(
            select(Payment).where(
                Payment.ad_id == ad.id,
                Payment.status.in_(["created", "invoice_sent"]),
            )
        )
    ).scalars().all()
    for old in old_rows:
        old.status = "cancelled"
        old.failure_reason = "Создан новый счёт"

    payload = f"ad:{ad.id}:{secrets.token_urlsafe(18)}"
    payment = Payment(
        user_id=user.id,
        ad_id=ad.id,
        tariff_id=tariff.id,
        invoice_payload=payload,
        currency="XTR",
        amount=ad.price_stars,
        status="created",
    )
    db.add(payment)
    ad.status = "awaiting_payment"
    await db.commit()
    await db.refresh(payment)

    settings = get_settings()
    if not settings.bot_token:
        if settings.allow_dev_auth:
            return {
                "payment_id": payment.id,
                "invoice_link": None,
                "dev_mode": True,
                "amount": payment.amount,
                "currency": "XTR",
            }
        raise HTTPException(503, "BOT_TOKEN не настроен")

    from aiogram import Bot
    from aiogram.types import LabeledPrice

    bot = Bot(settings.bot_token)
    try:
        link = await bot.create_invoice_link(
            title=f"Реклама: {ad.title}"[:32],
            description=f"{tariff.name}: размещение на {ad.duration_days} дн."[:255],
            payload=payment.invoice_payload,
            currency="XTR",
            prices=[LabeledPrice(label=tariff.name[:32], amount=payment.amount)],
        )
    except Exception as exc:
        payment.status = "failed"
        payment.failure_reason = str(exc)[:1000]
        ad.status = "draft"
        await db.commit()
        raise HTTPException(502, "Telegram не создал счёт. Проверьте BOT_TOKEN") from exc
    finally:
        await bot.session.close()

    payment.status = "invoice_sent"
    await db.commit()
    return {
        "payment_id": payment.id,
        "invoice_link": link,
        "dev_mode": False,
        "amount": payment.amount,
        "currency": "XTR",
    }


@router.post("/payments/{payment_id}/simulate")
async def simulate_payment(payment_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    settings = get_settings()
    if not settings.allow_dev_auth:
        raise HTTPException(404, "Раздел не найден")
    payment = await db.get(Payment, payment_id)
    if not payment or payment.user_id != user.id:
        raise HTTPException(404, "Платёж не найден")
    try:
        payment = await complete_successful_payment(
            db,
            invoice_payload=payment.invoice_payload,
            payer_telegram_id=user.telegram_id,
            currency="XTR",
            total_amount=payment.amount,
            telegram_payment_charge_id=f"DEV-{payment.id}-{secrets.token_hex(8)}",
            provider_payment_charge_id="",
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"payment_id": payment.id, "status": payment.status}


@router.post("/{ad_id}/impression")
async def impression(ad_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    result = await db.execute(
        update(Ad).where(Ad.id == ad_id, Ad.status == "active").values(impressions=Ad.impressions + 1)
    )
    await db.commit()
    return {"counted": bool(result.rowcount)}


@router.post("/{ad_id}/click")
async def click(ad_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    ad = await db.get(Ad, ad_id)
    if not ad or ad.status != "active":
        raise HTTPException(404, "Объявление недоступно")
    ad.clicks += 1
    await db.commit()
    return {"url": ad.url, "clicks": ad.clicks}
