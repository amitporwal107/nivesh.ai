"""Cross-cutting FastAPI dependencies.

Kept deliberately small in this first slice: only ``Settings`` is wired. The
Postgres pool, MongoDB client and auth guard land here in later tasks
(T1.2, T1.5, Iter 2).
"""
from __future__ import annotations

from fastapi import Depends

from .config import Settings, get_settings


def settings_dependency() -> Settings:
    return get_settings()


SettingsDep = Depends(settings_dependency)
