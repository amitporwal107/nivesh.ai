"""Runtime settings for the Autonomous Trading Desk service. Read once from the environment.

AUTODESK_PG_URL         Postgres for the `autodesk` schema. Falls back to POSTGRES_URL (the app Postgres on staging).
AUTODESK_AUTO_MIGRATE   "1" (default) applies autodesk/db/migrations on start.
AUTODESK_TASK_DEADLINE  default per-task deadline in seconds (30).
AUTODESK_LLM_ENABLED    "0" (default): agents run their deterministic paths only; no LLM call is made.
AUTODESK_SCHEDULER      "0" (default): no real-time session cycle is started by the service itself.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    pg_url: str
    auto_migrate: bool
    task_deadline_s: float
    llm_enabled: bool
    scheduler_enabled: bool


def load() -> Settings:
    url = os.environ.get("AUTODESK_PG_URL") or os.environ.get("POSTGRES_URL") or ""
    return Settings(
        pg_url=url,
        auto_migrate=_flag("AUTODESK_AUTO_MIGRATE", "1"),
        task_deadline_s=float(os.environ.get("AUTODESK_TASK_DEADLINE", "30")),
        llm_enabled=_flag("AUTODESK_LLM_ENABLED", "0"),
        scheduler_enabled=_flag("AUTODESK_SCHEDULER", "0"),
    )
