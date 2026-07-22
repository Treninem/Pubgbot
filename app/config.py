from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "PUBG Mobile Squad Finder"
    app_version: str = "1.3.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./data/squad_finder.db"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800
    db_startup_retries: int = 10
    db_startup_retry_seconds: float = 2.0

    bot_token: str = Field(
        default="",
        validation_alias=AliasChoices("BOT_TOKEN", "API_TOKEN", "TELEGRAM_BOT_TOKEN"),
    )
    public_base_url: str = ""
    domain: str = ""
    telegram_mode: str = "webhook"
    webhook_path: str = "/telegram/webhook"
    webhook_secret: str = ""
    webhook_max_connections: int = 20
    webhook_drop_pending_updates: bool = False
    webhook_auto_setup: bool = True

    owner_telegram_id: int = 0
    init_data_ttl_seconds: int = 86400
    allow_dev_auth: bool = False
    dev_telegram_id: int = 100001

    rate_limit_requests: int = 180
    rate_limit_window_seconds: int = 60
    request_body_limit_bytes: int = 1_048_576
    maintenance_interval_seconds: int = 300

    backup_enabled: bool = True
    backup_dir: str = "./data/backups"
    backup_interval_hours: int = 24
    backup_keep_count: int = 14
    backup_on_start: bool = False

    ad_default_price_stars: int = 50
    ad_default_duration_days: int = 7
    clan_creation_cooldown_hours: int = 24

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        value = str(value or "").strip()
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value[len("postgres://"):]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://"):]
        return value

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        value = str(value or "development").strip().lower()
        return value if value in {"development", "test", "production"} else "development"

    @field_validator("telegram_mode", mode="before")
    @classmethod
    def normalize_telegram_mode(cls, value: str) -> str:
        value = str(value or "webhook").strip().lower()
        if value not in {"webhook", "polling", "disabled"}:
            raise ValueError("TELEGRAM_MODE должен быть webhook, polling или disabled")
        return value

    @field_validator("webhook_path", mode="before")
    @classmethod
    def normalize_webhook_path(cls, value: str) -> str:
        value = "/" + str(value or "telegram/webhook").strip().strip("/")
        if value == "/":
            raise ValueError("WEBHOOK_PATH не может быть корнем сайта")
        return value

    @field_validator("webhook_secret", mode="before")
    @classmethod
    def validate_webhook_secret(cls, value: str) -> str:
        value = str(value or "").strip()
        if value and not _SECRET_RE.fullmatch(value):
            raise ValueError("WEBHOOK_SECRET: только A-Z, a-z, 0-9, _ и -, длина 1-256")
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        value = str(value or "INFO").strip().upper()
        return value if value in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else "INFO"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def effective_owner_telegram_id(self) -> int:
        if self.owner_telegram_id:
            return self.owner_telegram_id
        if self.allow_dev_auth and not self.is_production:
            return self.dev_telegram_id
        return 0

    @property
    def effective_public_base_url(self) -> str:
        value = self.public_base_url.strip().rstrip("/")
        if value and "YOUR_DOMAIN" not in value:
            return value
        domain = self.domain.strip().strip("/")
        if domain:
            if domain.startswith(("http://", "https://")):
                return domain.rstrip("/")
            return f"https://{domain}"
        return ""

    @property
    def webhook_url(self) -> str:
        base = self.effective_public_base_url
        return f"{base}{self.webhook_path}" if base else ""

    def production_errors(self) -> list[str]:
        if not self.is_production:
            return []
        errors: list[str] = []
        if self.allow_dev_auth:
            errors.append("ALLOW_DEV_AUTH должен быть false")
        if not self.owner_telegram_id:
            errors.append("OWNER_TELEGRAM_ID не задан")
        if self.telegram_mode != "disabled" and not self.bot_token:
            errors.append("BOT_TOKEN не задан")
        if self.telegram_mode == "webhook":
            if not self.webhook_secret:
                errors.append("WEBHOOK_SECRET не задан")
            parsed = urlparse(self.effective_public_base_url)
            if parsed.scheme != "https" or not parsed.netloc:
                errors.append("PUBLIC_BASE_URL/DOMAIN должен задавать публичный HTTPS-домен")
        if self.database_url.startswith("sqlite") and "/data/" not in self.database_url.replace("\\", "/"):
            errors.append("SQLite DATABASE_URL должен хранить базу в папке data")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
