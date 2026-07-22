from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Ad, AuditLog, Notification, Payment, User


async def validate_pre_checkout(
    db: AsyncSession,
    *,
    invoice_payload: str,
    payer_telegram_id: int,
    currency: str,
    total_amount: int,
    pre_checkout_query_id: str,
) -> tuple[bool, str]:
    payment = (
        await db.execute(select(Payment).where(Payment.invoice_payload == invoice_payload))
    ).scalar_one_or_none()
    if not payment:
        return False, "Счёт не найден"
    payer = await db.get(User, payment.user_id)
    if not payer or payer.telegram_id != payer_telegram_id:
        return False, "Этот счёт создан для другого пользователя"
    if payment.status not in {"created", "invoice_sent"}:
        return False, "Счёт уже обработан или отменён"
    if currency != "XTR" or payment.currency != "XTR":
        return False, "Некорректная валюта платежа"
    if total_amount != payment.amount:
        return False, "Сумма счёта изменилась. Создайте новый счёт"
    payment.pre_checkout_query_id = pre_checkout_query_id
    payment.status = "invoice_sent"
    await db.commit()
    return True, ""


async def complete_successful_payment(
    db: AsyncSession,
    *,
    invoice_payload: str,
    payer_telegram_id: int,
    currency: str,
    total_amount: int,
    telegram_payment_charge_id: str,
    provider_payment_charge_id: str | None,
) -> Payment:
    payment = (
        await db.execute(select(Payment).where(Payment.invoice_payload == invoice_payload))
    ).scalar_one_or_none()
    if not payment:
        raise ValueError("Платёж не найден")
    payer = await db.get(User, payment.user_id)
    if not payer or payer.telegram_id != payer_telegram_id:
        raise ValueError("Плательщик не совпадает с владельцем счёта")
    if currency != "XTR" or payment.currency != "XTR":
        raise ValueError("Ожидалась оплата Telegram Stars")
    if total_amount != payment.amount:
        raise ValueError("Получена неверная сумма")
    if payment.status == "paid":
        if payment.telegram_payment_charge_id == telegram_payment_charge_id:
            return payment
        raise ValueError("Счёт уже оплачен другим платежом")
    if payment.status in {"refunded", "cancelled", "failed"}:
        raise ValueError("Этот счёт больше не активен")

    duplicate = (
        await db.execute(
            select(Payment).where(
                Payment.telegram_payment_charge_id == telegram_payment_charge_id,
                Payment.id != payment.id,
            )
        )
    ).scalar_one_or_none()
    if duplicate:
        raise ValueError("Платёж уже зарегистрирован")

    ad = await db.get(Ad, payment.ad_id)
    if not ad or ad.user_id != payment.user_id:
        raise ValueError("Рекламная заявка не найдена")

    paid_at = datetime.utcnow()
    payment.status = "paid"
    payment.telegram_payment_charge_id = telegram_payment_charge_id
    payment.provider_payment_charge_id = provider_payment_charge_id or None
    payment.paid_at = paid_at

    ad.status = "pending_moderation"
    ad.telegram_payment_charge_id = telegram_payment_charge_id
    ad.provider_payment_charge_id = provider_payment_charge_id or ""
    ad.paid_at = paid_at
    ad.refunded_at = None
    ad.rejection_reason = ""

    db.add(Notification(
        user_id=payment.user_id,
        kind="payment",
        title="Оплата Telegram Stars получена",
        text=f"Объявление «{ad.title}» оплачено: {payment.amount} Stars. Заявка отправлена на модерацию.",
    ))
    db.add(AuditLog(
        actor_id=payment.user_id,
        action="payment.success",
        object_kind="payment",
        object_id=payment.id,
        details=f"ad_id={ad.id};amount={payment.amount};currency=XTR",
    ))
    await db.commit()
    await db.refresh(payment)
    return payment
