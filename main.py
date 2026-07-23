from __future__ import annotations

import logging
import os

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "3000")),
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=not settings.is_production or settings.debug,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
