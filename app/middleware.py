from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RequestGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    @staticmethod
    def _client_key(request: Request) -> str:
        init_data = request.headers.get("x-telegram-init-data", "")
        if init_data:
            digest = hashlib.sha256(init_data.encode("utf-8", errors="ignore")).hexdigest()[:24]
            return f"tg:{digest}"
        forwarded = request.headers.get("x-forwarded-for", "")
        ip = forwarded.split(",", 1)[0].strip() if forwarded else ""
        if not ip and request.client:
            ip = request.client.host
        return f"ip:{ip or 'unknown'}"

    async def _limited(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - max(1, settings.rate_limit_window_seconds)
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= max(1, settings.rate_limit_requests):
                return True
            events.append(now)
            if len(self._events) > 10_000:
                stale = [name for name, q in self._events.items() if not q or q[-1] <= cutoff]
                for name in stale[:2000]:
                    self._events.pop(name, None)
            return False

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.monotonic()

        if request.url.path.startswith("/api/"):
            key = f"{self._client_key(request)}:{request.url.path.split('/', 3)[2]}"
            if await self._limited(key):
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Слишком много запросов. Повторите немного позже."},
                    headers={"Retry-After": str(settings.rate_limit_window_seconds)},
                )
                response.headers["X-Request-ID"] = request_id
                return response

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.request_body_limit_bytes:
                    return JSONResponse(status_code=413, content={"detail": "Запрос слишком большой"})
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Некорректный Content-Length"})

        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Необработанная ошибка request_id=%s path=%s", request_id, request.url.path)
            raise

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=(), payment=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
        if request.url.path.startswith("/static/assets/"):
            response.headers.setdefault("Cache-Control", "public, max-age=604800, immutable")
        elif request.url.path in {"/", "/static/app.js", "/static/styles.css"}:
            response.headers.setdefault("Cache-Control", "no-cache")

        elapsed_ms = int((time.monotonic() - started) * 1000)
        if elapsed_ms >= 1500:
            logger.warning(
                "Медленный запрос request_id=%s method=%s path=%s status=%s duration_ms=%s",
                request_id, request.method, request.url.path, response.status_code, elapsed_ms,
            )
        return response
