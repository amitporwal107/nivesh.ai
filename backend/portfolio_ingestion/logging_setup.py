"""Logging bootstrap that delegates to the host backend's ``core.logging_config``.

Imported read-only; the existing module is never modified. If the host module
cannot be resolved (e.g. when the package is shipped in a tighter image), we
fall back to ``logging.basicConfig`` so the service still boots.
"""
from __future__ import annotations

import logging

from .config import Settings


def configure(settings: Settings) -> None:
    try:
        from core.logging_config import configure_logging  # type: ignore[import-not-found]
    except ImportError:
        logging.basicConfig(
            level=settings.log_level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        logging.getLogger(__name__).warning(
            "core.logging_config unavailable; using basicConfig fallback"
        )
        return

    configure_logging(
        service=settings.service_name,
        level=settings.log_level,
        env=settings.app_env,
        version=settings.version,
    )
