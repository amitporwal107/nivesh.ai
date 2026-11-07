"""GET /api/v1/health/status — one place to ask whether the desk is up (owner review item R14).

Public path: /autodesk/api/v1/health/status. It needs no sign-in, so it is status only and shows nothing private: no host
names, URLs, ports, tokens, tenant or account ids, symbols or exception messages (exception TYPE names only). It reads and
never writes, never calls Kite and never reads any broker's order data. `GET /api/v1/health` (routers/api.py, used by
Docker's healthcheck and the deploy check) is a different, faster route and is not touched.

  {"status": <worst part>, "as_of": <time>, "parts": {name: {"status": OK|DEGRADED|BLOCKED, "detail": <sentence>, "as_of": <time|null>}}}

HTTP is always 200: the status is in the body, and the route answers even when a dependency is down.

  database    SELECT 1 on the desk pool                                                       failure = BLOCKED
  data_api    tech_support.data_checks for the session being prepared (the pre-market check's  BLOCKED / DEGRADED / OK exactly
              own rules, one function for both)                                                as the pre-market check says
  redis       a ping through the client the desk already uses for the feed's quote cache      failure = DEGRADED (REST remains)
  quote_feed  the newest index tick in the feed's Redis cache, in market hours only            no fresh tick = DEGRADED
  scheduler   AUTODESK_SCHEDULER                                                               off = DEGRADED (open item R8)
  last_cycle  the newest non-simulation SESSION_CYCLE workflow, over all tenants               BLOCKED/FAILED = BLOCKED; old = DEGRADED

Protection of what is behind it, for unsigned callers: every probe has a hard timeout of PROBE_TIMEOUT_S, the probes run
together, and the whole answer is kept in this process for CACHE_TTL_S seconds (one set of probes however many callers).
The data API check makes up to three reads that can take longer than the timeout, so it runs as a background task of the
desk process and the route reports its last finished result with that result's own time (see `_Monitor._data_api`).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import config as cfgmod
from ..agents import tech_support
from ..market import calendar
from ..market.live_quotes import MAX_QUOTE_AGE_S, from_cache_row
from ..market.view import IST, DataUnavailable

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

OK, DEGRADED, BLOCKED = "OK", "DEGRADED", "BLOCKED"
RANK = {OK: 0, DEGRADED: 1, BLOCKED: 2}
PROBE_TIMEOUT_S = 3.0          # hard limit of every probe
CACHE_TTL_S = 15.0             # the whole answer is reused for this long
DATA_WAIT_S = 2.5              # how long a request waits for a running data check (less than PROBE_TIMEOUT_S)
DATA_REFRESH_S = 60.0          # the data check starts again at most this often
DATA_MAX_AGE_S = 300.0         # a finished data check older than this is not reported as current
DATA_RUN_DEADLINE_S = 40.0     # a data check that has not finished by now is a failure (its reads time out at 20 s each)
LOGIN_READ_S = 1.5             # the Kite login read (Mongo) must not hold up the quote feed part
FEED_INDEX_SYMBOLS = ("NIFTY 50", "NIFTY BANK")     # index ticks arrive all session, so a missing one means no feed
BACKGROUND_KEY = "health_data_check"

LABEL = {"database": "The desk database", "data_api": "The data API check", "redis": "Redis",
         "quote_feed": "The quote feed", "scheduler": "The scheduler", "last_cycle": "The last cycle"}
FAIL_STATUS = {"database": BLOCKED, "data_api": BLOCKED, "redis": DEGRADED, "quote_feed": DEGRADED,
               "scheduler": DEGRADED, "last_cycle": DEGRADED}
CYCLE_STATES = {"CREATED", "RUNNING", "WAITING_HUMAN", "COMPLETED", "BLOCKED", "FAILED", "CANCELLED"}

# The Tech Support check texts that are safe to show without a sign-in: counts and days only. Anything else it says (its
# "not readable: …" lines carry the data API's own error text) is replaced by a fixed sentence.
_SAFE_CHECK_TEXT = re.compile(
    r"^(?:\d+ (?:cash rows|F&O underlyings) for \d{4}-\d{2}-\d{2} \(need \d+\)"
    r"|(?:Cash|F&O) data is for \d{4}-\d{2}-\d{2}; the \d{4}-\d{2}-\d{2} session needs \d{4}-\d{2}-\d{2}"
    r"|India VIX \d+(?:\.\d+)?"
    r"|no India VIX for the session \(regime inputs will be listed as missing\))$")
_UNREADABLE = {"cash_eod": "cash end-of-day data could not be read", "fno_eod": "F&O end-of-day data could not be read",
               "vix": "India VIX could not be read"}


def _mono() -> float:
    return time.monotonic()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _part(status: str, detail: str, as_of: Optional[datetime]) -> dict:
    return {"status": status, "detail": detail, "as_of": as_of.astimezone(timezone.utc).isoformat() if as_of else None}


def worst(parts: dict) -> str:
    """The overall status: the worst of the parts."""
    return max((p["status"] for p in parts.values()), key=RANK.__getitem__)


def _ago(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 90:
        return f"{s} seconds"
    if s < 5400:
        return f"{round(s / 60)} minutes"
    if s < 172800:
        return f"{s / 3600:.1f} hours"
    return f"{s // 86400} days"


def _check_text(c, sd: date) -> str:
    if _SAFE_CHECK_TEXT.match(c.detail or ""):
        return c.detail
    if (c.detail or "").startswith("cannot tell which session precedes "):
        return f"cannot tell which session precedes {sd}"
    return _UNREADABLE.get(c.name, f"{c.name} could not be read")


def data_part(checks: list, cash_ok: bool, fno_ok: bool, sd: date, at: datetime) -> dict:
    """The data_api part from tech_support.data_checks' result: the same verdict the pre-market report gives for the data
    (no cash = BLOCKED, no F&O = DEGRADED, else READY; a missing India VIX is noted and does not change it)."""
    status = BLOCKED if not cash_ok else DEGRADED if not fno_ok else OK
    return _part(status, f"For the {sd} session: " + "; ".join(_check_text(c, sd) for c in checks) + ".", at)


def _market_state(now: datetime) -> Optional[bool]:
    """Whether the market is open now, by the desk's own rule (execution/settle._market_open: a session day, 09:15-15:30 IST);
    None when the holiday list cannot say whether today is a session day."""
    from ..execution import settle
    try:
        calendar.is_session(now.astimezone(IST).date())
    except calendar.CalendarUnavailable:
        return None
    return bool(settle._market_open(now))      # noqa: SLF001 — the desk's one market-hours function; not copied


async def _login_phrase(now: datetime) -> str:
    """Whether a Kite login is stored for today, from the platform's token document in Mongo (token_status: no token is read,
    no Kite call is made). It is the stored expiry (06:00 IST), not proof that Kite accepts the token."""
    try:
        from deps import db
        from services.kite_live_feed import platform_token
        s = await asyncio.wait_for(platform_token.token_status(db, now), LOGIN_READ_S)
    except asyncio.TimeoutError:
        return "today's Kite login could not be read in time"
    except Exception as e:  # noqa: BLE001 — a reason by type, never a message
        return f"today's Kite login could not be read ({type(e).__name__})"
    if s.get("stored") and not s.get("expired"):
        return "a Kite login is stored and has not expired"
    return "no unexpired Kite login is stored"


class _Monitor:
    """The probes, the 15 s cache and the background data check of one app. Lives on `app.state`."""

    def __init__(self) -> None:
        self._cached: Optional[tuple[float, dict]] = None
        self._inflight: Optional["asyncio.Future[dict]"] = None
        self._data: Optional[tuple[float, dict]] = None         # (finished at, the data_api part)

    # ── the answer, cached and shared ─────────────────────────────────────────────────────────────────────────────

    async def get(self, st: Any) -> dict:
        if self._cached is not None and _mono() - self._cached[0] < CACHE_TTL_S:
            return self._cached[1]
        if self._inflight is None or self._inflight.done():
            self._inflight = asyncio.ensure_future(self._compute(st))
        return await asyncio.shield(self._inflight)

    async def _compute(self, st: Any) -> dict:
        now = _utcnow()
        probes: dict[str, Awaitable[dict]] = {
            "database": self._database(st, now), "data_api": self._data_api(st), "redis": self._redis(now),
            "quote_feed": self._quote_feed(now), "scheduler": self._scheduler(), "last_cycle": self._last_cycle(st, now)}
        done = await asyncio.gather(*(self._guard(n, p, now) for n, p in probes.items()))
        parts = dict(zip(probes, done))
        body = {"status": worst(parts), "as_of": now.isoformat(), "parts": parts}
        self._cached = (_mono(), body)
        return body

    @staticmethod
    async def _guard(name: str, probe: Awaitable[dict], now: datetime) -> dict:
        """One probe, bounded. A timeout or an error is that part's failure status; only the exception type is shown."""
        try:
            return await asyncio.wait_for(probe, PROBE_TIMEOUT_S)
        except asyncio.TimeoutError:
            return _part(FAIL_STATUS[name], f"{LABEL[name]} did not answer within {PROBE_TIMEOUT_S:g} seconds.", now)
        except Exception as e:  # noqa: BLE001
            return _part(FAIL_STATUS[name], f"{LABEL[name]} check failed ({type(e).__name__}).", now)

    # ── the parts ─────────────────────────────────────────────────────────────────────────────────────────────────

    async def _database(self, st: Any, now: datetime) -> dict:
        async with st.pool.acquire() as c:
            ok = await c.fetchval("SELECT 1") == 1
        return _part(OK, "The desk database answers.", now) if ok else _part(BLOCKED, "The desk database gave a wrong answer.", now)

    async def _data_api(self, st: Any) -> dict:
        """The data API check is Tech Support's own (tech_support.data_checks): up to three data reads plus the holiday list,
        each allowed 20 s by the data client, so it cannot promise an answer inside the probe timeout. It therefore runs as a
        background task of the desk process (also held in `st.background`, so shutdown cancels it), started when the last
        result is older than DATA_REFRESH_S. A request waits DATA_WAIT_S for it, then reports the last finished result with
        that result's own time; a result older than DATA_MAX_AGE_S is not reported as current."""
        if self._data is None or _mono() - self._data[0] >= DATA_REFRESH_S:
            task = st.background.get(BACKGROUND_KEY)
            if task is None or task.done():
                task = st.background[BACKGROUND_KEY] = asyncio.ensure_future(self._run_data_check(st))
            try:
                await asyncio.wait_for(asyncio.shield(task), DATA_WAIT_S)
            except asyncio.TimeoutError:
                pass
        if self._data is None:
            return _part(DEGRADED, "The first data check is still running; ask again in a few seconds.", None)
        finished, part = self._data
        if _mono() - finished > DATA_MAX_AGE_S:
            return _part(DEGRADED, f"The last finished data check is {_ago(_mono() - finished)} old and a newer one has not "
                                   "finished.", datetime.fromisoformat(part["as_of"]) if part["as_of"] else None)
        return part

    async def _run_data_check(self, st: Any) -> None:
        """Never raises: its outcome, good or bad, becomes the stored data_api part."""
        at = _utcnow()
        try:
            part = await asyncio.wait_for(self._data_check(st, at), DATA_RUN_DEADLINE_S)
        except asyncio.TimeoutError:
            part = _part(BLOCKED, f"The data check did not finish within {DATA_RUN_DEADLINE_S:g} seconds.", at)
        except Exception as e:  # noqa: BLE001
            part = _part(BLOCKED, f"The data check failed ({type(e).__name__}).", at)
        self._data = (_mono(), part)

    @staticmethod
    async def _data_check(st: Any, at: datetime) -> dict:
        sd = await st.next_session(at)                 # the session being prepared, as the next session cycle would see it
        checks, _as_of, cash_ok, fno_ok = await tech_support.data_checks(st.market_factory(at), sd)
        return data_part(checks, cash_ok, fno_ok, sd, at)

    async def _redis(self, now: datetime) -> dict:
        from services.kite_live_feed import quote_cache
        c = await quote_cache.get_client()          # the shared client the desk's quote reads already use
        if c is None:
            return _part(DEGRADED, "Redis is not configured or did not connect; quotes then come from the REST path.", now)
        if not await c.ping():
            return _part(DEGRADED, "Redis did not answer its ping; quotes then come from the REST path.", now)
        return _part(OK, "Redis answers.", now)

    async def _quote_feed(self, now: datetime) -> dict:
        is_open = _market_state(now)
        if is_open is None:
            login = await _login_phrase(now)
            return _part(DEGRADED, f"Cannot tell whether the market is open because the holiday list is not loaded; {login}.", now)
        if not is_open:
            login = await _login_phrase(now)
            return _part(OK, f"The market is closed, so no ticks are expected; {login}.", now)
        from services.kite_live_feed import quote_cache
        rows, login = await asyncio.gather(quote_cache.read_quotes(list(FEED_INDEX_SYMBOLS)), _login_phrase(now))
        if rows is None:
            return _part(DEGRADED, f"The market is open but the feed's quote cache is not available; {login}.", now)
        seen = [q.received_at for q in (from_cache_row(k, r) for k, r in rows.items()) if q.received_at is not None]
        if not seen:
            return _part(DEGRADED, f"The market is open but the feed's cache holds no index ticks; {login}.", now)
        newest = max(seen)
        age = abs((now - newest).total_seconds())
        if newest.astimezone(IST).date() != now.astimezone(IST).date():
            return _part(DEGRADED, f"The market is open but the newest index tick is not from today; {login}.", newest)
        if age > MAX_QUOTE_AGE_S:
            return _part(DEGRADED, f"The market is open and the newest index tick is {age:.0f} seconds old "
                                   f"(limit {MAX_QUOTE_AGE_S:g} seconds); {login}.", newest)
        return _part(OK, f"The market is open and the newest index tick is {age:.0f} seconds old; {login}.", newest)

    async def _scheduler(self) -> dict:
        if cfgmod.load().scheduler_enabled:     # nothing in this version reads the flag, so "on" would prove nothing
            return _part(DEGRADED, "on: the setting is on, but this version has no scheduler that starts session cycles.", None)
        return _part(DEGRADED, "off: session cycles are started by hand", None)

    async def _last_cycle(self, st: Any, now: datetime) -> dict:
        async with st.pool.acquire() as c:
            async with c.transaction(readonly=True):
                row = await c.fetchrow("""SELECT state, session_date, created_at FROM autodesk.workflows
                                          WHERE kind = 'SESSION_CYCLE' AND simulation_id IS NULL
                                          ORDER BY created_at DESC LIMIT 1""")
        if row is None:
            return _part(DEGRADED, "No session cycle has been recorded yet.", None)
        state = row["state"] if row["state"] in CYCLE_STATES else "UNKNOWN"
        sd, started = row["session_date"], row["created_at"]
        what = f"The latest session cycle is {state}, for session {sd}, started {_ago((now - started).total_seconds())} ago"
        if state in ("BLOCKED", "FAILED"):
            return _part(BLOCKED, what + ".", started)
        if state == "CANCELLED":
            return _part(DEGRADED, what + ".", started)
        if sd is None:
            return _part(DEGRADED, what + " and has no session date.", started)
        try:
            prev = await st.market_factory(now).previous_session(await st.next_session(now))
        except (DataUnavailable, calendar.CalendarUnavailable):
            return _part(DEGRADED, what + "; the session before the next one could not be worked out.", started)
        if sd < prev:
            return _part(DEGRADED, what + f"; that is older than the previous session, {prev}.", started)
        return _part(OK, what + ".", started)


@router.get("/health/status")
async def health_status(request: Request):
    app = request.app
    monitor = getattr(app.state, "health_monitor", None)
    if monitor is None:
        monitor = app.state.health_monitor = _Monitor()
    body = await monitor.get(getattr(app.state, "desk", None))
    return JSONResponse(body, headers={"Cache-Control": "no-store"})
