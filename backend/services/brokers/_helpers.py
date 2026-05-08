"""Shared helpers for broker adapters.

Keeps per-broker modules small and consistent. All helpers are pure (no
DB, no Mongo) so adapters can be unit-tested with minimal setup.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def conf(key: str) -> str:
    """Read a Nivesh secret with env fallback. Empty string when unset.

    Adapters use this for `BROKER_<SLUG>_API_KEY` etc.
    """
    try:
        from helpers import secrets as _s
        v = (_s.get(key) or "").strip()
        if v:
            return v
    except Exception:  # noqa: BLE001
        pass
    return (os.environ.get(key) or "").strip()


async def to_thread(fn: Callable[..., T], *args, **kwargs) -> T:
    """Run a sync broker-SDK call in the default executor without blocking
    the event loop. Adapters use this for SDK methods that are sync-only.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


def require(key: str, msg: str | None = None) -> str:
    """Read a config value or raise a clean RuntimeError pointing the
    operator at the secret they need to register.
    """
    v = conf(key)
    if not v:
        raise RuntimeError(
            msg
            or f"{key} is not configured — operator must register the broker app and set this secret.",
        )
    return v


def require_sdk(module_name: str, install_hint: str) -> Any:
    """Lazy-import a broker SDK and surface a clean error when missing.
    Keeps the backend bootable without any SDK installed.
    """
    try:
        import importlib
        return importlib.import_module(module_name)
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError(
            f"{module_name} not installed. {install_hint}",
        ) from e


def detect_etf(symbol: str, name: str = "") -> bool:
    """Cheap symbol-pattern check for ETFs (BeES, GOLDM, ETF tags)."""
    s = (symbol or "").upper() + " " + (name or "").upper()
    return any(tag in s for tag in ("BEES", "ETF", "GOLDM", "NIFTY1D"))
