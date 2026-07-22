from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, PreCheckoutQuery, WebAppInfo

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.payment_service import complete_successful_payment, validate_pre_checkout

settings = get_settings()
dp = Dispatcher()
logger = logging.getLogger(__name__)


@dp.message(CommandStart())
async def start(message: Message):
    url = settings.effective_public_base_url.rstrip("/") + "/"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть Squad Finder", web_app=WebAppInfo(url=url))
    ]])
    await message.answer("Подбор тимейтов PUBG Mobile.", reply_markup=keyboard)


@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, bot: Bot):
    async with SessionLocal() as db:
        ok, error = await validate_pre_checkout(
            db,
            invoice_payload=query.invoice_payload,
            payer_telegram_id=query.from_user.id,
            currency=query.currency,
            total_amount=query.total_amount,
            pre_checkout_query_id=query.id,
        )
    await bot.answer_pre_checkout_query(
        query.id,
        ok=ok,
        error_message=None if ok else error,
    )


@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payment_data = message.successful_payment
    if not payment_data:
        return
    try:
        async with SessionLocal() as db:
            payment = await complete_successful_payment(
                db,
                invoice_payload=payment_data.invoice_payload,
                payer_telegram_id=message.from_user.id,
                currency=payment_data.currency,
                total_amount=payment_data.total_amount,
                telegram_payment_charge_id=payment_data.telegram_payment_charge_id,
                provider_payment_charge_id=payment_data.provider_payment_charge_id,
            )
    except ValueError as exc:
        logger.exception("Не удалось зарегистрировать successful_payment: %s", exc)
        await message.answer(
            "Платёж получен Telegram, но возникла ошибка регистрации. "
            "Не создавайте повторный платёж — обратитесь в поддержку."
        )
        return
    await message.answer(
        f"Оплата {payment.amount} Stars подтверждена. Рекламная заявка отправлена на модерацию."
    )


async def main():
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан")
    await init_db()
    bot = Bot(settings.bot_token)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
