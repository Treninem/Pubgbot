from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from .config import get_settings
from .runtime import runtime_state

logger = logging.getLogger(__name__)
settings = get_settings()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_manifest(backup_path: Path, backend: str) -> None:
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "app_version": settings.app_version,
        "backend": backend,
        "file": backup_path.name,
        "size_bytes": backup_path.stat().st_size,
        "sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest(),
    }
    backup_path.with_suffix(backup_path.suffix + ".json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _sqlite_backup(database_path: Path, target: Path) -> None:
    source = sqlite3.connect(str(database_path), timeout=30)
    try:
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()


def _postgres_backup(database_url: str, target: Path) -> None:
    executable = shutil.which("pg_dump")
    if not executable:
        raise RuntimeError("pg_dump не установлен; используйте Dockerfile из архива или резервные копии провайдера PostgreSQL")
    url = make_url(database_url)
    command = [executable, "--format=custom", "--no-owner", "--no-acl", "--file", str(target)]
    if url.host:
        command.extend(["--host", url.host])
    if url.port:
        command.extend(["--port", str(url.port)])
    if url.username:
        command.extend(["--username", url.username])
    if url.database:
        command.append(url.database)
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "pg_dump завершился с ошибкой")


def _cleanup(directory: Path) -> None:
    keep = max(1, settings.backup_keep_count)
    backups = sorted(
        [path for path in directory.glob("squad_finder_*") if path.suffix in {".db", ".dump"}],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old in backups[keep:]:
        old.unlink(missing_ok=True)
        old.with_suffix(old.suffix + ".json").unlink(missing_ok=True)


async def create_backup() -> Path:
    directory = Path(settings.backup_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    url = make_url(settings.database_url)
    if url.drivername.startswith("sqlite"):
        if not url.database or url.database == ":memory:":
            raise RuntimeError("Нельзя сохранить резервную копию временной SQLite")
        source = Path(url.database)
        if not source.is_absolute():
            source = Path.cwd() / source
        if not source.exists():
            raise RuntimeError(f"Файл базы не найден: {source}")
        target = directory / f"squad_finder_{_timestamp()}.db"
        await asyncio.to_thread(_sqlite_backup, source, target)
        backend = "sqlite"
    elif url.drivername.startswith("postgresql"):
        target = directory / f"squad_finder_{_timestamp()}.dump"
        await asyncio.to_thread(_postgres_backup, settings.database_url, target)
        backend = "postgresql"
    else:
        raise RuntimeError(f"Резервное копирование не поддерживает {url.drivername}")

    await asyncio.to_thread(_write_manifest, target, backend)
    await asyncio.to_thread(_cleanup, directory)
    runtime_state.last_backup_at = datetime.utcnow()
    runtime_state.last_backup_error = ""
    logger.info("Резервная копия создана: %s", target)
    return target


async def backup_loop(stop_event: asyncio.Event) -> None:
    if not settings.backup_enabled:
        return
    if settings.backup_on_start:
        try:
            await create_backup()
        except Exception as exc:
            runtime_state.last_backup_error = str(exc)
            logger.exception("Стартовая резервная копия не создана")
    interval = max(1, settings.backup_interval_hours) * 3600
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            try:
                await create_backup()
            except Exception as exc:
                runtime_state.last_backup_error = str(exc)
                logger.exception("Плановая резервная копия не создана")
