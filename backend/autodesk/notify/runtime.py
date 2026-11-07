"""Process-wide notifier and the background pump that feeds it. Started by main.py with one line."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from .cursor import run_pending
from .notifier import Notifier, from_env

log = logging.getLogger("autodesk.notify")
INTERVAL_S = 15.0
_notifier: Optional[Notifier] = None


def get_notifier() -> Notifier:
    global _notifier
    if _notifier is None:
        _notifier = from_env(os.environ)
    return _notifier


def set_notifier(n: Optional[Notifier]) -> None:
    """Replace (or, with None, reset) the notifier. Tests use it with a fake transport."""
    global _notifier
    _notifier = n


async def _pump(pool) -> None:
    while True:
        try:
            async with pool.acquire() as c:
                await run_pending(c, get_notifier())
        except asyncio.CancelledError:
            raise
        except Exception:       # the desk must not feel a notifier fault; it tries again next round
            log.exception("notifier round failed (ignored)")
        await asyncio.sleep(INTERVAL_S)


def start(state) -> None:
    """Run the pump next to the desk. Does nothing when the notifier is not configured."""
    if get_notifier().enabled:
        state.background["slack_notifier"] = asyncio.create_task(_pump(state.pool))
    else:
        log.warning("Slack notifications are off (webhook URL not set)")
