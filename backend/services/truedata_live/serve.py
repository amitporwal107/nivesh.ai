"""TrueData SERVES the live feed (TS-9, TS-10 in test_reports/truedata_serving_TESTCASES.md).

Started by services/kite_live_feed/feed.start() when the market-data switch resolves to `truedata`
(backend/config/market_data_source.json, with TRUEDATA_INTEGRATED and the licence flag; nidp/shared/market_data_source.py).
It is the same `LiveFeed` as Kite's (snapshot, close, quote cache, chains, minute and intraday documents, status), given
TrueData's client and ticker (gateway.py) and `provider="truedata"`. The data-quality checks of the shadow keep running,
on the serving connection's own messages (`ServingChecks`): one TrueData login allows one connection, so no shadow
connection is opened beside it, and there is no Kite comparison (Kite is off). No password or token is stored or logged.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from nidp.shared.sources import truedata as td

from . import checks as ck
from . import gateway as tg
from . import protocol as pr
from . import shadow as sh

logger = logging.getLogger(__name__)

TICK_S = 5
STATUS_EVERY_S = 10


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ws_marker(env: Optional[Dict[str, str]] = None) -> str:
    """The feed's "token": a non-secret marker of the WebSocket login, so `not_connected` still means "no login" and a
    changed login restarts the session (the feed fingerprints it). Empty without a login."""
    creds = sh.ws_credentials(env)
    if creds is None:
        return ""
    digest = hashlib.sha256(f"{creds['TRUEDATA_WS_USERNAME']}:{creds['TRUEDATA_WS_PORT']}".encode()).hexdigest()[:16]
    return f"truedata:{digest}"


def rest_marker(env: Optional[Dict[str, str]] = None) -> str:
    """The feed's "API key": present when the REST login (for the symbol master) is configured."""
    return "truedata" if td.credentials_from_env(env) is not None else ""


class ServingChecks:
    """The shadow's per-tick and connection checks, fed by the serving ticker (its thread) and flushed by `run()` on the
    app's event loop. A lock guards the shared state; Mongo writes happen outside it."""

    def __init__(self, db, meta: Callable[[], Dict[str, ck.SymbolMeta]], *, env: Optional[Dict[str, str]] = None,
                 notifier=None, clock: Callable[[], datetime] = utcnow, sleep=asyncio.sleep):
        self.shadow = sh.TrueDataShadow(db, env=env, kite_reader=None, notifier=notifier, clock=clock, holder="serving")
        self.shadow.state = "starting"
        self._meta = meta
        self._lock = threading.Lock()
        self._clock, self._sleep = clock, sleep
        self._login_findings: List[tuple] = []

    # called on the ticker thread
    def on_login(self, info: pr.LoginInfo, now: datetime) -> None:
        with self._lock:
            self.shadow.login = info
            self.shadow.state = "connected" if info.ok else "login_refused"
            self.shadow.last_heartbeat = now
            self.shadow.subscribed, self.shadow.id_to_symbol = [], {}
            m = self.shadow._minute_for(now)
            for code, detail in ck.login_findings(info, 0, now.astimezone(pr.IST).date()):
                m.add(code, detail)
                self._login_findings.append((code, detail))

    def on_message(self, raw: Any, now: datetime) -> None:
        with self._lock:
            if not self.shadow.checker.meta:
                try:
                    self.shadow.checker.meta = dict(self._meta())
                except Exception as e:  # noqa: BLE001 — checks run without tick size / circuit until the master loads
                    logger.debug("truedata serving checks: meta unavailable (%s)", type(e).__name__)
            self.shadow.handle(raw, now)

    def set_requested(self, requested: List[str], over_limit: List[str]) -> None:
        with self._lock:
            self.shadow.requested, self.shadow.over_limit = list(requested), list(over_limit)

    # on the app's loop. The lock is held across the Mongo writes: the ticker thread then waits a few milliseconds
    # (its messages queue in the socket), and nothing on the app's loop ever waits for the ticker, so it cannot deadlock.
    async def flush_minute(self, now: datetime) -> Optional[dict]:
        session = await self.shadow._session(now)
        with self._lock:
            doc = await self.shadow.flush_minute(now, session)
            alerts, self._login_findings = self._login_findings, []
            for code, detail in alerts:
                if code in ("LOGIN_FAILED", "DUPLICATE_LOGIN", "LOGIN_EXPIRING", "SEGMENT_MISSING"):
                    await self.shadow._alert(code, detail, now,
                                             cooldown=24 * 3600 if code == "LOGIN_EXPIRING" else sh.ALERT_COOLDOWN_S)
        return doc

    async def write_status(self, now: datetime) -> None:
        session = await self.shadow._session(now)
        with self._lock:
            hb_state, _ = ck.heartbeat_state(self.shadow.last_heartbeat, now)
            if self.shadow.state in ("connected", "delayed", "lost"):
                self.shadow.state = "connected" if hb_state == "ok" else ("delayed" if hb_state == "delayed" else "lost")
            await self.shadow.write_status(now, session)

    async def run(self) -> None:
        last_status: Optional[datetime] = None
        while True:
            now = self._clock()
            try:
                key = now.astimezone(pr.IST).strftime("%Y-%m-%dT%H:%M")
                with self._lock:
                    due = self.shadow._minute is not None and self.shadow._minute.key != key
                if due:
                    await self.flush_minute(now)
                if last_status is None or (now - last_status).total_seconds() >= STATUS_EVERY_S:
                    await self.write_status(now)
                    last_status = now
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — the checks never stop the feed
                logger.warning("truedata serving checks: flush failed (%s)", type(e).__name__)
            await self._sleep(TICK_S)


def build_feed(db, *, env: Optional[Dict[str, str]] = None, client=None, connect=None, clock=None, **feed_kwargs):
    """The TrueData-served LiveFeed and its checks. `client` / `connect` are for tests (no network)."""
    from services.kite_live_feed import feed as kf
    env = dict(os.environ if env is None else env)
    adapter = tg.TrueDataAsKite(client=client or td.TrueDataClient(td.credentials_from_env(env)),
                                indices=tg.indices_from_env(env), clock=clock)
    checks = ServingChecks(db, lambda: adapter.meta, env=env, clock=clock or utcnow)

    def kite_factory(key: str, token: str):
        return adapter

    def ticker_factory(key: str, token: str):
        creds = sh.ws_credentials(env)
        t = tg.TrueDataKiteTicker(creds or {}, lambda: adapter.tokens, dq=checks, connect=connect, clock=clock)
        return t

    feed = kf.LiveFeed(db, token_getter=lambda: ws_marker(env), key_getter=lambda: rest_marker(env), kite_factory=kite_factory,
                       ticker_factory=ticker_factory, provider="truedata", clock=clock, **feed_kwargs)
    return feed, adapter, checks


_checks_task: Optional["asyncio.Task[None]"] = None


async def start_serving(db) -> bool:
    """Called by kite_live_feed.feed.start() when the switch resolves to `truedata`. The feed becomes the process's feed
    (get_feed() returns it), so every reader of the live snapshot and cache is unchanged."""
    global _checks_task
    from services.kite_live_feed import feed as kf
    feed, _adapter, checks = build_feed(db)
    kf._feed = feed
    kf._task = asyncio.ensure_future(feed.run())
    await db[sh.COL_MINUTES].create_index("saved_at", expireAfterSeconds=sh.MINUTES_TTL_DAYS * 86400, background=True)
    _checks_task = asyncio.ensure_future(checks.run())
    logger.info("live feed started on TrueData: cadence=%ss", feed.cadence)
    return True


async def stop_serving() -> None:
    global _checks_task
    if _checks_task is not None:
        _checks_task.cancel()
        try:
            await _checks_task
        except BaseException:  # noqa: BLE001
            pass
    _checks_task = None
