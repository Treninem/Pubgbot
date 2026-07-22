from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class RuntimeState:
    started_at: datetime = field(default_factory=datetime.utcnow)
    database_ready: bool = False
    bot_ready: bool = False
    webhook_ready: bool = False
    webhook_url: str = ""
    last_webhook_error: str = ""
    last_backup_at: datetime | None = None
    last_backup_error: str = ""

    def public_dict(self) -> dict:
        data = asdict(self)
        for key in ("started_at", "last_backup_at"):
            if data[key] is not None:
                data[key] = data[key].isoformat() + "Z"
        return data


runtime_state = RuntimeState()


def track_task(task: asyncio.Task, *, label: str) -> None:
    def done_callback(done: asyncio.Task) -> None:
        try:
            done.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Фоновая задача завершилась с ошибкой: %s", label)

    task.add_done_callback(done_callback)
