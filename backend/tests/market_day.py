"""Pins services.market_freshness.window for route tests with dated fixtures.

The F&O routes refuse data older than the previous session and contracts that expired before today (owner rule,
2026-10-28), against the real clock. A fixture dated 2026-10-12 is current only on a "today" around that day, so each
harness pins the day its fixtures describe. The freshness rule itself is tested with its own pins.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from services import market_freshness


def pin(monkeypatch, today: str, floor: Optional[str] = None) -> market_freshness.Window:
    w = market_freshness.Window(today=date.fromisoformat(today), floor=date.fromisoformat(floor or today),
                                calendar_checked=True)

    async def fixed(now=None, holiday=None):
        return w

    monkeypatch.setattr(market_freshness, "window", fixed)
    return w
