from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    listen_host: str = "0.0.0.0"
    listen_port: int = 8000

    zone_config_path: str = "configs/zones.yaml"
    db_path: str = "data/alert_relay.db"
    retention_days: int = Field(default=30, ge=1)
    cleanup_interval_events: int = Field(default=200, ge=1)

    default_timezone: str = "America/Sao_Paulo"

    whatsapp_enabled: bool = True
    whatsapp_webhook_url: str | None = None
    whatsapp_timeout_sec: float = Field(default=5.0, ge=1.0)
    whatsapp_bearer_token: str | None = None

    email_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    smtp_from: str = "ez-watch@localhost"
    email_to_csv: str = ""

    camera_health_enabled: bool = True
    camera_offline_threshold_sec: int = Field(default=180, ge=30)
    camera_health_check_interval_sec: int = Field(default=60, ge=15)
    camera_offline_alert_cooldown_sec: int = Field(default=900, ge=60)

    @property
    def email_recipients(self) -> list[str]:
        recipients = [item.strip() for item in self.email_to_csv.split(",")]
        return [item for item in recipients if item]

    @property
    def db_file(self) -> Path:
        return Path(self.db_path)


settings = Settings()
