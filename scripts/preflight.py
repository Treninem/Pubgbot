from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
import json

from app.config import get_settings
from app.db import check_db, init_db_with_retry, close_db


async def main() -> int:
    settings = get_settings()
    errors = settings.production_errors()
    result = {
        "version": settings.app_version,
        "environment": settings.environment,
        "telegram_mode": settings.telegram_mode,
        "public_base_url": settings.effective_public_base_url,
        "webhook_url": settings.webhook_url,
        "database_backend": settings.database_url.split(":", 1)[0],
        "configuration_errors": errors,
        "database": False,
    }
    if not errors:
        try:
            await init_db_with_retry()
            result["database"] = await check_db()
        finally:
            await close_db()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors and result["database"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
