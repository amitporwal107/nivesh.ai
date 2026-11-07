"""TrueData live feed in SHADOW: it runs beside the Kite live feed, serves nobody, and measures TrueData's quality.

Owner, 29 Oct 2026: "make sure we keep data quality checks on TrueData" → "go ahead". What it does, every session:
  * login → connection checks (group 1); subscribe a fixed, small symbol set within the login's symbol limit;
  * every message → per-tick checks (group 2), counted per minute with samples;
  * once a minute → compare each symbol with Kite's quote from the live-feed cache (group 4, live part) and list the
    symbols that went stale; write one document per minute (truedata_shadow_minutes) and the status document;
  * alert (email / Telegram, the live feed's channels) on a failed login, a lost heartbeat in market hours, a login
    about to expire, or Kite disagreeing on more than 5% of comparable quotes.
It writes only its own collections (truedata_shadow, truedata_shadow_minutes): never Kite's snapshot, cache or lease.
One TrueData login allows one connection, so a Mongo lease keeps it to one process across workers.

It starts only when the market-data switch has TrueData on (shadow or truedata) and the WebSocket login is configured
(TRUEDATA_WS_USERNAME / TRUEDATA_WS_PASSWORD / TRUEDATA_WS_PORT, or TRUEDATA_WS_CRED_FILE); TRUEDATA_SHADOW_ENABLED=0
turns it off. The password travels only in the connection URL, which is never logged; errors are logged by class name.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from . import checks as ck
from . import compare as cmp
from . import protocol as pr

logger = logging.getLogger(__name__)

COL = "truedata_shadow"                 # status, latest, lease documents
COL_MINUTES = "truedata_shadow_minutes"  # one document per minute
MINUTES_TTL_DAYS = 30
LEASE_ID = "lease"
LEASE_TTL_S = 45
LEASE_RENEW_S = 15
STATUS_EVERY_S = 10
ALERT_COOLDOWN_S = 30 * 60
KITE_ALERT_SHARE = 0.05
KITE_ALERT_MIN_COMPARABLE = 10
SAMPLES_PER_CODE = 3

DEFAULT_INDICES = ("NIFTY 50", "NIFTY BANK", "NIFTY FIN SERVICE", "NIFTY MID SELECT", "INDIA VIX")
DEFAULT_STOCKS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "BHARTIARTL", "ITC", "LT", "AXISBANK",
                  "KOTAKBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI", "SUNPHARMA", "NTPC", "M&M", "TITAN", "ADANIENT",
                  "IDEA")
DEFAULT_FUTURES = ("NIFTY", "BANKNIFTY", "RELIANCE", "IDEA")      # near month; IDEA carries the OI-above-int32 case


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ws_credentials(env: Optional[Dict[str, str]] = None) -> Optional[Dict[str, str]]:
    env = os.environ if env is None else env
    vals = {k: (env.get(k) or "").strip() for k in ("TRUEDATA_WS_USERNAME", "TRUEDATA_WS_PASSWORD", "TRUEDATA_WS_PORT")}
    if not all(vals.values()) and env.get("TRUEDATA_WS_CRED_FILE"):
        try:
            pairs = dict(l.split("=", 1) for l in open(env["TRUEDATA_WS_CRED_FILE"]).read().split() if "=" in l)
            vals = {k: pairs.get(k, "").strip() for k in vals}
        except OSError:
            return None
    if not (vals["TRUEDATA_WS_USERNAME"] and vals["TRUEDATA_WS_PASSWORD"]):
        return None
    vals["TRUEDATA_WS_PORT"] = vals["TRUEDATA_WS_PORT"] or "8084"
    return vals


def _default_connect(creds: Dict[str, str]):
    import urllib.parse
    import websockets
    url = (f"wss://push.truedata.in:{creds['TRUEDATA_WS_PORT']}?"
           + urllib.parse.urlencode({"user": creds["TRUEDATA_WS_USERNAME"], "password": creds["TRUEDATA_WS_PASSWORD"]}))
    return websockets.connect(url, open_timeout=20, close_timeout=5, ping_interval=20, max_size=2 ** 24)


def _wanted_symbols(env: Dict[str, str]) -> Dict[str, List[str]]:
    def lst(key, default):
        raw = (env.get(key) or "").strip()
        return [s.strip().upper() for s in raw.split(",") if s.strip()] if raw else list(default)
    return {"indices": lst("TRUEDATA_SHADOW_INDICES", DEFAULT_INDICES),
            "stocks": lst("TRUEDATA_SHADOW_STOCKS", DEFAULT_STOCKS),
            "futures": lst("TRUEDATA_SHADOW_FUTURES", DEFAULT_FUTURES)}


def load_meta(wanted: Dict[str, List[str]], client=None) -> Dict[str, Any]:
    """Tick size and circuit band per stock, and the near-month contract per future underlying, from TrueData's own
    symbol master (REST, needs TRUEDATA_USERNAME / TRUEDATA_PASSWORD). Blocking; called in a thread once a day. A symbol
    the master cannot answer keeps no meta (its tick and circuit checks are skipped, and that is reported)."""
    from nidp.shared.sources import truedata as td
    client = client or td.TrueDataClient()
    meta: Dict[str, ck.SymbolMeta] = {s: ck.SymbolMeta(kind="INDEX") for s in wanted["indices"]}
    futures: List[str] = []
    missing: List[str] = []
    for sym in wanted["stocks"]:
        meta[sym] = ck.SymbolMeta(kind="EQ")
        try:
            rows = [r for r in client.symbol_master("eq", sym, 10) if r.get("symbol") == sym and r.get("series") == "EQ"]
        except td.TrueDataError:
            rows = []
        if rows:
            meta[sym] = ck.SymbolMeta("EQ", rows[0].get("tick_size"), rows[0].get("circuit_low"), rows[0].get("circuit_high"))
        else:
            missing.append(sym)
    for u in wanted["futures"]:
        try:
            rows = [r for r in client.symbol_master("fo", u, 50) if r.get("symbol") == f"{u}-I"]
        except td.TrueDataError:
            rows = []
        if rows and rows[0].get("expiry_date"):
            name = td.future_symbol(u, rows[0]["expiry_date"])
            meta[name] = ck.SymbolMeta("FUT", rows[0].get("tick_size"), rows[0].get("circuit_low"), rows[0].get("circuit_high"))
        else:
            name = f"{u}-I"                                   # continuous: no Kite twin, but still checked
            meta[name] = ck.SymbolMeta("FUT")
            missing.append(u)
        futures.append(name)
    return {"meta": meta, "futures": futures, "meta_missing": missing}


class _Minute:
    def __init__(self, key: str):
        self.key = key
        self.messages = 0
        self.ticks = 0
        self.heartbeats = 0
        self.findings: Dict[str, int] = {}
        self.samples: Dict[str, List[Any]] = {}

    def add(self, code: str, sample: Any = None) -> None:
        self.findings[code] = self.findings.get(code, 0) + 1
        if sample is not None and len(self.samples.setdefault(code, [])) < SAMPLES_PER_CODE:
            self.samples[code].append(sample)


class TrueDataShadow:
    def __init__(self, db, *, env: Optional[Dict[str, str]] = None, connect: Optional[Callable] = None,
                 kite_reader: Optional[Callable[[List[str]], Awaitable[Optional[Dict[str, dict]]]]] = None,
                 meta_loader: Optional[Callable[[Dict[str, List[str]]], Dict[str, Any]]] = None,
                 holidays_loader: Optional[Callable[[date], Awaitable[Set[date]]]] = None,
                 notifier: Optional[Callable[[str, str], Any]] = None, clock: Callable[[], datetime] = utcnow,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, holder: Optional[str] = None):
        self.db = db
        self.env = dict(os.environ if env is None else env)
        self._connect = connect or _default_connect
        self._kite_reader = kite_reader
        self._meta_loader = meta_loader or load_meta
        self._holidays_loader = holidays_loader
        self._notifier = notifier
        self.clock, self._sleep = clock, sleep
        self.holder = holder or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.wanted = _wanted_symbols(self.env)
        self.checker = ck.TickChecker()
        self.quotes: Dict[str, Dict[str, Any]] = {}
        self.id_to_symbol: Dict[str, str] = {}
        self.requested: List[str] = []
        self.subscribed: List[str] = []
        self.over_limit: List[str] = []
        self.login: Optional[pr.LoginInfo] = None
        self.last_heartbeat: Optional[datetime] = None
        self.last_message: Optional[datetime] = None
        self.market_status: Optional[str] = None
        self.reconnects = 0
        self.state = "starting"
        self.last_error: Optional[str] = None
        self.meta_day: Optional[date] = None
        self.meta_missing: List[str] = []
        self.futures: List[str] = []
        self._holidays: Dict[date, Optional[Set[date]]] = {}
        self._minute: Optional[_Minute] = None
        self._alerted: Dict[str, datetime] = {}
        self._fails = 0

    # ── plumbing ──
    def _ist(self, now: datetime) -> datetime:
        return now.astimezone(pr.IST)

    async def _session(self, now: datetime) -> str:
        from services.kite_live_feed import config as kcfg
        day = self._ist(now).date()
        if day not in self._holidays:
            try:
                self._holidays[day] = await (self._holidays_loader or kcfg.load_holidays)(day)
            except Exception:                                    # noqa: BLE001 — unknown holidays: time window only
                self._holidays[day] = None
        return kcfg.session_of(now, self._holidays[day] or set())[0]

    async def _lease(self, now: datetime) -> bool:
        from services.kite_live_feed.feed import try_acquire_lease
        return await try_acquire_lease(self.db[COL], LEASE_ID, self.holder, now, LEASE_TTL_S)

    def _minute_for(self, now: datetime) -> _Minute:
        key = self._ist(now).strftime("%Y-%m-%dT%H:%M")
        if self._minute is None:
            self._minute = _Minute(key)
        return self._minute

    async def _alert(self, code: str, text: str, now: datetime, cooldown: float = ALERT_COOLDOWN_S) -> None:
        last = self._alerted.get(code)
        if last and (now - last).total_seconds() < cooldown:
            return
        self._alerted[code] = now
        subject = f"[Nivesh] TrueData live (shadow): {code}"
        try:
            notifier = self._notifier
            if notifier is None:
                from services.kite_live_feed.token_alert import default_notifier as notifier
            await asyncio.to_thread(notifier, subject, text)
        except Exception as exc:                                  # noqa: BLE001 — an alert must not stop the feed
            logger.warning("truedata shadow alert not sent: %s", type(exc).__name__)

    async def _ensure_meta(self, now: datetime) -> None:
        day = self._ist(now).date()
        if self.meta_day == day:
            return
        try:
            res = await asyncio.to_thread(self._meta_loader, self.wanted)
        except Exception as exc:                                  # noqa: BLE001
            logger.warning("truedata shadow: symbol master unavailable (%s)", type(exc).__name__)
            res = {"meta": {s: ck.SymbolMeta(kind="INDEX") for s in self.wanted["indices"]},
                   "futures": [f"{u}-I" for u in self.wanted["futures"]],
                   "meta_missing": self.wanted["stocks"] + self.wanted["futures"]}
            for s in self.wanted["stocks"]:
                res["meta"][s] = ck.SymbolMeta(kind="EQ")
            for f in res["futures"]:
                res["meta"][f] = ck.SymbolMeta(kind="FUT")
        self.checker.meta = res["meta"]
        self.futures = res["futures"]
        self.meta_missing = res["meta_missing"]
        self.meta_day = day

    def requested_symbols(self) -> List[str]:
        return list(dict.fromkeys(self.wanted["indices"] + self.futures + self.wanted["stocks"]))

    # ── message handling ──
    def handle(self, raw: Any, now: datetime) -> None:
        m = self._minute_for(now)
        m.messages += 1
        self.last_message = now
        try:
            msg = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except ValueError:
            m.add("MALFORMED", "not JSON")
            return
        kind = pr.kind_of(msg)
        try:
            if kind == "heartbeat":
                self.last_heartbeat = now
                m.heartbeats += 1
            elif kind == "marketstatus":
                self.market_status = str(msg.get("data") or "")[:80]
            elif kind == "touchline":
                for row in pr.parse_touchline(msg):
                    sym = row["symbol"].upper()
                    self.id_to_symbol[row["symbol_id"]] = sym
                    if msg.get("message") == "symbols added" and sym not in self.subscribed:
                        self.subscribed.append(sym)
                    self._tick(sym, pr.quote_from({**row, "symbol": sym}, now), now, m, kind)
            elif kind == "trade":
                row = pr.parse_trade(msg)
                sym = self.id_to_symbol.get(row["symbol_id"] or "")
                if sym is None:
                    m.add("UNMAPPED_ID", row["symbol_id"])
                    return
                self._tick(sym, pr.quote_from({**row, "symbol": sym}, now), now, m, kind)
            elif kind == "bidask":
                row = pr.parse_bidask(msg)
                sym = self.id_to_symbol.get(row["symbol_id"] or "")
                if sym is None:
                    m.add("UNMAPPED_ID", row["symbol_id"])
                    return
                q = self.quotes.get(sym)
                if q is not None:
                    before = (q.get("bid"), q.get("ask"))
                    q.update({k: row[k] for k in ("bid", "bid_qty", "ask", "ask_qty")}, received_at=now)
                    if (q["bid"] or 0) > 0 and (q["ask"] or 0) > 0 and q["bid"] > q["ask"] + ck.EPS:
                        # LT-4b: the raw fields, so a crossed book can be traced to what TrueData actually sent
                        m.add("CROSSED_BOOK", {"symbol": sym, "kind": "bidask", "bid": q["bid"], "ask": q["ask"],
                                               "ltp": q.get("ltp"), "bid_before": before[0], "ask_before": before[1],
                                               "raw": [str(v) for v in msg["bidask"][:len(pr.BIDASK_FIELDS)]]})
                st = self.checker.state.get(sym)
                if st is not None:
                    st.updated_at = now
            elif kind == "error":
                m.add("SYMBOL_NOT_SUBSCRIBED", str(msg.get("message") or "")[:120])
        except pr.Malformed as exc:
            m.add("MALFORMED", f"{kind}: {exc}"[:120])

    def _tick(self, sym: str, q: Dict[str, Any], now: datetime, m: _Minute, kind: Optional[str] = None) -> None:
        m.ticks += 1
        codes = self.checker.check(sym, q, now)
        for c in codes:
            m.add(c, {"symbol": sym, "kind": kind, "ltp": q.get("ltp"), "bid": q.get("bid"), "ask": q.get("ask"),
                      "ts": q["ts"].isoformat() if q.get("ts") else None})
        if not set(codes) & ck.UNUSABLE:
            self.quotes[sym] = q

    # ── once a minute ──
    async def flush_minute(self, now: datetime, session: str) -> Dict[str, Any]:
        m = self._minute_for(now)
        self._minute = None
        kite: Dict[str, int] = {"agree": 0, "disagree": 0, "not_comparable": 0, "no_kite_quote": 0}
        kite_samples: List[Dict[str, Any]] = []
        symbols = [s for s in self.subscribed if s in self.quotes]
        rows = None
        if symbols and self._kite_reader is not None:
            try:
                rows = await self._kite_reader(symbols)
            except Exception as exc:                              # noqa: BLE001 — Kite's cache down is not TrueData's fault
                logger.info("truedata shadow: kite cache unavailable (%s)", type(exc).__name__)
        for s in symbols:
            meta = self.checker.meta.get(s) or ck.SymbolMeta()
            outcome, codes, detail = cmp.compare(self.quotes[s], (rows or {}).get(s), meta.tick_size, meta.kind)
            kite[outcome] += 1
            for c in codes:
                m.add(c, detail)
            if detail.get("kite_ts_mislabelled"):
                m.add("KITE_TS_MISLABELLED", s)            # a bug in OUR Kite feed, reported, not TrueData's
            if outcome == "disagree" and len(kite_samples) < 5:
                kite_samples.append(detail)
        stale = self.checker.stale_symbols(now, self.subscribed) if session == "open" else []
        for s in stale:
            m.add("STALE_SYMBOL", s)
        doc = {"_id": m.key, "day": m.key[:10], "minute": m.key[11:], "session": session, "messages": m.messages,
               "ticks": m.ticks, "heartbeats": m.heartbeats, "findings": m.findings, "samples": m.samples,
               "kite": kite, "kite_samples": kite_samples, "stale": stale, "subscribed": len(self.subscribed),
               "saved_at": now}
        await self.db[COL_MINUTES].replace_one({"_id": m.key}, doc, upsert=True)
        comparable = kite["agree"] + kite["disagree"]
        if session == "open" and comparable >= KITE_ALERT_MIN_COMPARABLE and kite["disagree"] / comparable > KITE_ALERT_SHARE:
            await self._alert("KITE_DISAGREE", f"TrueData and Kite disagree on {kite['disagree']} of {comparable} "
                                               f"comparable quotes in minute {m.key} IST. Samples: {kite_samples}", now,
                              cooldown=3600)
        return doc

    async def write_status(self, now: datetime, session: Optional[str] = None) -> None:
        hb_state, hb_age = ck.heartbeat_state(self.last_heartbeat, now)
        await self.db[COL].update_one({"_id": "status"}, {"$set": {
            "state": self.state, "session": session, "holder": self.holder,
            "login": self.login.public() if self.login else None, "requested": self.requested,
            "subscribed": self.subscribed, "not_subscribed": [s for s in self.requested if s not in self.subscribed],
            "over_limit": self.over_limit, "meta_missing": self.meta_missing, "heartbeat": hb_state,
            "heartbeat_age_s": None if hb_age is None else round(hb_age, 1), "last_message_at": self.last_message,
            "market_status": self.market_status, "reconnects": self.reconnects, "last_error": self.last_error,
            "updated_at": now}}, upsert=True)

    # ── one connection ──
    async def connect_once(self) -> str:
        """Log in, subscribe, consume until the connection ends, the lease is lost or the heartbeat is lost.
        Returns why it ended (for the back-off): 'login_refused', 'lease_lost', 'heartbeat_lost', 'closed'."""
        creds = ws_credentials(self.env)
        if creds is None:
            self.state, self.last_error = "not_configured", "no TrueData WebSocket login"
            return "login_refused"
        now = self.clock()
        await self._ensure_meta(now)
        self.subscribed, self.over_limit, self.id_to_symbol = [], [], {}
        async with self._connect(creds) as ws:
            self.state = "logging_in"
            info = None
            while info is None:                                   # heartbeats can arrive before the login reply
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
                msg = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                if pr.kind_of(msg) == "heartbeat":
                    self.last_heartbeat = self.clock()
                    continue
                info = pr.parse_login(msg)
            self.login = info
            now = self.clock()
            requested = self.requested_symbols()
            m = self._minute_for(now)
            for code, detail in ck.login_findings(info, len(requested), self._ist(now).date()):
                m.add(code, detail)
                if code in ("LOGIN_FAILED", "DUPLICATE_LOGIN", "LOGIN_EXPIRING", "SEGMENT_MISSING"):
                    await self._alert(code, detail, now, cooldown=24 * 3600 if code == "LOGIN_EXPIRING" else ALERT_COOLDOWN_S)
            if not info.ok:
                self.state, self.last_error = "login_refused", info.message
                await self.write_status(now)
                return "login_refused"
            self.requested = requested[: info.maxsymbols] if info.maxsymbols else requested
            self.over_limit = requested[len(self.requested):]
            await ws.send(json.dumps({"method": "addsymbol", "symbols": self.requested}))
            self.state, self.last_error, self._fails = "connected", None, 0
            self.last_heartbeat = now                              # a fresh connection starts its own heartbeat clock
            subscribed_checked = False
            next_lease = next_status = now
            try:
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        self.handle(raw, self.clock())
                    except asyncio.TimeoutError:
                        pass
                    now = self.clock()
                    if not subscribed_checked and self.subscribed:
                        subscribed_checked = True
                        mm = self._minute_for(now)
                        for code, sym in ck.subscription_findings(self.requested, self.subscribed):
                            mm.add(code, sym)
                    if now >= next_lease:
                        next_lease = now + timedelta(seconds=LEASE_RENEW_S)
                        if not await self._lease(now):
                            self.state = "lease_lost"
                            return "lease_lost"
                    session = await self._session(now)
                    hb_state, hb_age = ck.heartbeat_state(self.last_heartbeat, now)
                    self.state = "connected" if hb_state == "ok" else ("delayed" if hb_state == "delayed" else "lost")
                    if hb_state == "lost":
                        self._minute_for(now).add("HEARTBEAT_LOST", round(hb_age or 0, 1))
                        if session == "open":
                            await self._alert("HEARTBEAT_LOST", f"no TrueData heartbeat for {round(hb_age or 0)} s in "
                                                                 "market hours; reconnecting", now)
                        await self.write_status(now, session)
                        return "heartbeat_lost"
                    if hb_state == "delayed":
                        self._minute_for(now).add("HEARTBEAT_LATE", round(hb_age or 0, 1))
                    if self._minute and self._minute.key != self._ist(now).strftime("%Y-%m-%dT%H:%M"):
                        await self.flush_minute(now, session)
                    if now >= next_status:
                        next_status = now + timedelta(seconds=STATUS_EVERY_S)
                        await self.write_status(now, session)
            finally:
                try:
                    if self._minute is not None and self._minute.messages:
                        t = self.clock()
                        await self.flush_minute(t, await self._session(t))
                except Exception:                                 # noqa: BLE001 — best effort on the way out
                    pass
                try:
                    await ws.send(json.dumps({"method": "logout"}))
                except Exception:                                 # noqa: BLE001 — the socket may already be gone
                    pass

    async def run(self) -> None:
        """Forever: hold the lease, keep one connection, back off on failures."""
        while True:
            now = self.clock()
            try:
                if not await self._lease(now):
                    self.state = "follower"
                    await self._sleep(LEASE_RENEW_S)
                    continue
                why = await self.connect_once()
                self._fails = 0 if why in ("lease_lost",) else self._fails + 1
                wait = 300 if why == "login_refused" else min(300, 5 * (2 ** min(self._fails, 6)))
            except asyncio.CancelledError:
                raise
            except Exception as exc:                              # noqa: BLE001 — class name only: the URL holds the password
                self._fails += 1
                self.last_error = type(exc).__name__
                self.state = "error"
                wait = min(300, 5 * (2 ** min(self._fails, 6)))
                logger.warning("truedata shadow: connection ended (%s); retry in %ss", type(exc).__name__, wait)
            self.reconnects += 1
            try:
                await self.write_status(self.clock())
            except Exception:                                     # noqa: BLE001
                pass
            await self._sleep(wait)


# ── module-level: start / stop / status (called from server.py and routes/live_quotes.py) ──────────────────────────

_shadow: Optional[TrueDataShadow] = None
_task: Optional[asyncio.Task] = None


def why_not_started(env: Optional[Dict[str, str]] = None) -> Optional[str]:
    from nidp.shared import market_data_source as mds
    env = os.environ if env is None else env
    if (env.get("TRUEDATA_SHADOW_ENABLED") or "1").strip() == "0":
        return "TRUEDATA_SHADOW_ENABLED=0"
    if not mds.truedata_is_on():
        return mds.truedata_off_message()
    if ws_credentials(env) is None:
        return "no TrueData WebSocket login (TRUEDATA_WS_USERNAME / TRUEDATA_WS_PASSWORD)"
    return None


async def start(db) -> bool:
    global _shadow, _task
    why = why_not_started()
    if why:
        logger.info("truedata shadow not started: %s", why)
        return False
    if _task is not None and not _task.done():
        return False
    await db[COL_MINUTES].create_index("saved_at", expireAfterSeconds=MINUTES_TTL_DAYS * 86400, background=True)
    from services.kite_live_feed import quote_cache as qc
    _shadow = TrueDataShadow(db, kite_reader=qc.read_quotes)
    _task = asyncio.ensure_future(_shadow.run())
    logger.info("truedata shadow started (symbols requested: %d)", len(_shadow.requested_symbols()))
    return True


async def stop(db=None) -> None:
    global _shadow, _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except BaseException:                                     # noqa: BLE001
            pass
    if _shadow is not None and db is not None:
        try:
            await db[COL].update_one({"_id": LEASE_ID, "holder": _shadow.holder}, {"$set": {"expires_at": utcnow()}})
        except Exception:                                         # noqa: BLE001
            pass
    _shadow = _task = None


async def status(db, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The status document plus today's totals from the minute documents (LR-5). No secret is stored, so none is shown."""
    from nidp.shared import market_data_source as mds
    now = now or utcnow()
    st = await db[COL].find_one({"_id": "status"}) or {}
    st.pop("_id", None)
    st.pop("holder", None)
    day = now.astimezone(pr.IST).date().isoformat()
    docs = await db[COL_MINUTES].find({"day": day}).to_list(length=2000)
    findings: Dict[str, int] = {}
    kite = {"agree": 0, "disagree": 0, "not_comparable": 0, "no_kite_quote": 0}
    for d in docs:
        for k, v in (d.get("findings") or {}).items():
            findings[k] = findings.get(k, 0) + v
        for k in kite:
            kite[k] += (d.get("kite") or {}).get(k, 0)
    comparable = kite["agree"] + kite["disagree"]
    r = mds.resolve()
    return {"switch": {"effective": r.effective, "truedata_on": r.truedata_feeds_on, "reasons": list(r.reasons)},
            "not_started_because": why_not_started(), "status": st,
            "today": {"day": day, "minutes_recorded": len(docs), "ticks": sum(d.get("ticks", 0) for d in docs),
                      "findings": dict(sorted(findings.items(), key=lambda kv: -kv[1])),
                      "severity": {k: ck.SEVERITY.get(k, "WARN") for k in findings},
                      "kite": kite, "kite_agreement_pct": round(100 * kite["agree"] / comparable, 2) if comparable else None}}
