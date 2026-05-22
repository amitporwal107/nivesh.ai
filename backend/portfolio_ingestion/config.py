"""Runtime configuration for the portfolio_ingestion service.

Uses ``os.environ`` directly instead of ``pydantic-settings`` so the package
ships with no dependency the host repo isn't already shipping.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


@dataclass(frozen=True)
class Settings:
    service_name: str
    version: str
    app_env: str
    log_level: str
    postgres_url: str | None
    mongo_url: str | None
    redis_url: str | None
    nidp_daas_base_url: str | None
    pan_encryption_key: str | None

    @classmethod
    def load(cls) -> "Settings":
        from . import __service_name__, __version__

        return cls(
            service_name=__service_name__,
            version=__version__,
            app_env=_env("APP_ENV", "dev") or "dev",
            log_level=_env("LOG_LEVEL", "INFO") or "INFO",
            postgres_url=_env("PI_POSTGRES_URL"),
            mongo_url=_env("PI_MONGO_URL"),
            redis_url=_env("PI_REDIS_URL"),
            nidp_daas_base_url=_env("NIDP_DAAS_BASE_URL"),
            pan_encryption_key=_env("PI_PAN_ENCRYPTION_KEY"),
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.load()
    return _settings


def reset_settings_for_test() -> None:
    """Reset the module-level cache so tests can re-load with different env."""
    global _settings
    _settings = None
