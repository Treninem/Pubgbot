from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .backup_service import backup_loop
from .config import get_settings
from .db import SessionLocal, close_db, init_db_with_retry
from .middleware import RequestGuardMiddleware
from .maintenance_service import maintenance_loop
from .routers import ads, clans, common, owner, profiles, rooms, social
from .runtime import runtime_state

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    errors = settings.production_errors()
    if errors:
        raise RuntimeError("Небезопасная production-конфигурация: " + "; ".join(errors))

    await init_db_with_retry()
    runtime_state.database_ready = True
    stop_event = asyncio.Event()
    backup_task = asyncio.create_task(backup_loop(stop_event), name="database-backup-loop")
    maintenance_task = asyncio.create_task(maintenance_loop(stop_event), name="maintenance-loop")

    telegram_bot = None
    polling_task: asyncio.Task | None = None
    if settings.telegram_mode != "disabled" and settings.bot_token:
        from aiogram import Bot
        from bot import dp

        telegram_bot = Bot(settings.bot_token)
        app.state.telegram_bot = telegram_bot
        runtime_state.bot_ready = True
        if settings.telegram_mode == "webhook":
            from .telegram_service import setup_webhook
            await setup_webhook(telegram_bot)
        elif settings.telegram_mode == "polling":
            await telegram_bot.delete_webhook(drop_pending_updates=False)
            polling_task = asyncio.create_task(dp.start_polling(telegram_bot), name="telegram-polling")
            runtime_state.webhook_ready = False
            logger.warning("Telegram запущен в polling-режиме; для Bothost используйте webhook")
    else:
        app.state.telegram_bot = None
        logger.warning("Telegram-бот отключён или BOT_TOKEN не задан")

    try:
        yield
    finally:
        stop_event.set()
        if polling_task:
            polling_task.cancel()
            await asyncio.gather(polling_task, return_exceptions=True)
        backup_task.cancel()
        maintenance_task.cancel()
        await asyncio.gather(backup_task, maintenance_task, return_exceptions=True)
        if telegram_bot:
            await telegram_bot.session.close()
        runtime_state.bot_ready = False
        runtime_state.webhook_ready = False
        runtime_state.database_ready = False
        await close_db()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.debug and not settings.is_production else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.debug and not settings.is_production else None,
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(RequestGuardMiddleware)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.include_router(common.router, prefix="/api")
app.include_router(profiles.router, prefix="/api")
app.include_router(rooms.router, prefix="/api")
app.include_router(clans.router, prefix="/api")
app.include_router(social.router, prefix="/api")
app.include_router(ads.router, prefix="/api")
app.include_router(owner.router, prefix="/api")
async def _telegram_webhook_endpoint(request: Request):
    if settings.telegram_mode != "webhook":
        raise HTTPException(status_code=503, detail="Telegram webhook отключён")
    from .telegram_service import telegram_webhook
    return await telegram_webhook(request)


app.add_api_route(
    settings.webhook_path,
    _telegram_webhook_endpoint,
    methods=["POST"],
    include_in_schema=False,
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
    }


@app.get("/ready")
async def ready():
    database_ok = False
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        logger.exception("Readiness: база данных недоступна")
    runtime_state.database_ready = database_ok

    bot_required = settings.telegram_mode != "disabled"
    webhook_required = settings.telegram_mode == "webhook"
    is_ready = database_ok and (not bot_required or runtime_state.bot_ready) and (
        not webhook_required or runtime_state.webhook_ready
    )
    payload = {
        "status": "ready" if is_ready else "degraded",
        "version": settings.app_version,
        "database": database_ok,
        "bot": runtime_state.bot_ready,
        "webhook": runtime_state.webhook_ready,
    }
    return JSONResponse(status_code=200 if is_ready else 503, content=payload)


@app.get("/")
async def index():
    return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})
