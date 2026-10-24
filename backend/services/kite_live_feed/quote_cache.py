"""The latest live quote per symbol in Redis, written by the lease leader, read by every worker.

Keys (decode_responses JSON strings, each with a TTL of LIVE_QUOTE_CACHE_TTL_S, default 600 s):
  nivesh:quote:<EXCHANGE>:<SYMBOL>                 one quote row, e.g. nivesh:quote:NSE:RELIANCE, nivesh:quote:NFO:NIFTY26OCT25000CE
  nivesh:quote:chain:<UNDERLYING>:<YYYY-MM-DD>     hash "<strike>|<CE|PE>" -> "<EXCHANGE>:<SYMBOL>" for the cached option window

The cache is an accelerator, never a dependency: with REDIS_URL unset, Redis down or a command failing, every call here
returns "absent" (None / False / "unavailable") instead of raising, and a failure closes a process-local breaker for a few
seconds (doubling to a minute) so a dead Redis costs neither the feed nor a request more than one short timeout per window.
Failures are logged at warning at most once a minute, with the exception class name only.

The feed's own loop is asyncio (the KiteTicker thread only marks quotes as changed), so this uses the shared async client
from services.redis_client: same REDIS_URL resolution, one pool per worker.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PREFIX = "nivesh:quote:"
READ_TIMEOUT_SECONDS = 1.0             # Redis answers in milliseconds; past this the snapshot answers instead
WRITE_TIMEOUT_SECONDS = 4.0            # covers the shared client's 3 s connect on first use
ABSENT_RETRY_SECONDS = 60.0            # REDIS_URL unset, or the shared client could not connect
BACKOFF_MAX_SECONDS = 60.0
WARN_EVERY_SECONDS = 60.0


def quote_key(qkey: str) -> str:
    return PREFIX + qkey


def chain_key(underlying: str, expiry: str) -> str:
    return f"{PREFIX}chain:{underlying}:{expiry}"


def strike_field(strike: float, option_type: str) -> str:
    """25000.0, "CE" -> "25000|CE"; 102.5 -> "102.5|PE"."""
    return ("%.2f" % float(strike)).rstrip("0").rstrip(".") + "|" + option_type


def cache_row(q: dict, kind: str, session: Optional[str]) -> dict:
    """One feed quote as the cached row. kind is EQ | INDEX | FUT | OPT. Absent values are None, never 0."""
    deriv = kind in ("FUT", "OPT")
    return {"symbol": q["symbol"], "exchange": "NFO" if deriv else "NSE", "kind": kind,
            "underlying": q.get("underlying"), "expiry": q.get("expiry"), "strike": q.get("strike"),
            "option_type": q.get("option_type"), "lot_size": q.get("lot_size"),
            "ltp": q.get("ltp"), "change": q.get("change"), "change_pct": q.get("change_pct"),
            "ohlc": {"open": q.get("open"), "high": q.get("high"), "low": q.get("low"), "close": q.get("close")},
            "volume": q.get("volume"), "oi": q.get("oi"), "oi_high": q.get("oi_high"), "oi_low": q.get("oi_low"),
            "bid": q.get("bid"), "ask": q.get("ask"), "bid_qty": q.get("bid_qty"), "ask_qty": q.get("ask_qty"),
            "exchange_ts": q.get("exchange_ts"), "ts": q.get("ts"), "received_at": q.get("received_at"),
            "source": q.get("source"), "session": session}


def as_quote(row: dict) -> dict:
    """A cached row back in the snapshot's quote shape (what /api/live/quotes serves), so a quote looks the same whichever
    store answered it."""
    o = row.get("ohlc") or {}
    q = {"ltp": row.get("ltp"), "change": row.get("change"), "change_pct": row.get("change_pct"),
         "open": o.get("open"), "high": o.get("high"), "low": o.get("low"), "close": o.get("close"),
         "volume": row.get("volume"), "oi": row.get("oi"), "ts": row.get("ts"),
         "bid": row.get("bid"), "ask": row.get("ask"), "bid_qty": row.get("bid_qty"), "ask_qty": row.get("ask_qty"),
         "exchange_ts": row.get("exchange_ts"), "received_at": row.get("received_at"), "source": row.get("source")}
    kind = row.get("kind")
    if kind == "FUT":
        q.update({"instrument": "FUT", "underlying": row.get("underlying"), "expiry": row.get("expiry"),
                  "oi_high": row.get("oi_high"), "oi_low": row.get("oi_low"), "lot_size": row.get("lot_size")})
    elif kind == "OPT":
        q.update({"instrument": "OPT", "underlying": row.get("underlying"), "expiry": row.get("expiry"),
                  "strike": row.get("strike"), "option_type": row.get("option_type"), "lot_size": row.get("lot_size")})
    return q


def minute_row(q: dict) -> dict:
    """The compact replay row: s symbol, p price, b/a bid/ask, bq/aq their quantities, o open interest, v volume, t the
    quote's stamp; derivatives add u underlying, x expiry, and options k strike, ot CE/PE. A null value is left out."""
    r = {"s": q.get("symbol"), "p": q.get("ltp"), "b": q.get("bid"), "a": q.get("ask"), "bq": q.get("bid_qty"),
         "aq": q.get("ask_qty"), "o": q.get("oi"), "v": q.get("volume"), "t": q.get("ts")}
    if q.get("instrument") in ("FUT", "OPT"):
        r.update({"u": q.get("underlying"), "x": q.get("expiry")})
    if q.get("instrument") == "OPT":
        r.update({"k": q.get("strike"), "ot": q.get("option_type")})
    return {k: v for k, v in r.items() if v is not None}


def _mono() -> float:
    return time.monotonic()


class _Gate:
    """Process-local breaker in front of Redis."""

    def __init__(self) -> None:
        self.down_until = 0.0
        self.fails = 0
        self.warned_at: Optional[float] = None

    def closed(self) -> bool:
        return _mono() < self.down_until

    def fail(self, what: str, exc: BaseException) -> None:
        now = _mono()
        self.fails += 1
        self.down_until = now + min(BACKOFF_MAX_SECONDS, 2.0 ** min(self.fails, 6))
        if self.warned_at is None or now - self.warned_at >= WARN_EVERY_SECONDS:
            self.warned_at = now
            logger.warning("live quote cache: redis %s failed (%s); serving without the cache until it recovers",
                           what, type(exc).__name__)

    def absent(self) -> None:
        self.down_until = _mono() + ABSENT_RETRY_SECONDS

    def ok(self) -> None:
        self.fails, self.down_until = 0, 0.0


_gate = _Gate()


async def get_client():
    """The shared async client (None when REDIS_URL is unset or it cannot connect; services.redis_client logs that)."""
    from services import redis_client
    return await redis_client.get_client()


async def _client(timeout: float):
    if _gate.closed():
        return None
    try:
        c = await asyncio.wait_for(get_client(), timeout)
    except Exception as e:  # noqa: BLE001 — absent, not fatal
        _gate.fail("connect", e)
        return None
    if c is None:
        _gate.absent()
    return c


def _load(raw: Any) -> Optional[dict]:
    if not raw:
        return None
    try:
        row = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return row if isinstance(row, dict) else None


async def write(rows: List[dict], chains: Dict[str, Dict[str, str]], ttl: int) -> bool:
    """One MULTI/EXEC pipeline: every row SET with EX ttl, and every chain hash replaced (DEL, then HSET + EXPIRE ttl when it
    has entries; an empty mapping just deletes the hash). False when the cache is absent or the write failed; never raises."""
    if not rows and not chains:
        return True
    c = await _client(WRITE_TIMEOUT_SECONDS)
    if c is None:
        return False
    try:
        async with c.pipeline(transaction=True) as pipe:
            for r in rows:
                pipe.set(quote_key(f"{r['exchange']}:{r['symbol']}"), json.dumps(r, separators=(",", ":"), default=str), ex=ttl)
            for key, mapping in chains.items():
                pipe.delete(key)
                if mapping:
                    pipe.hset(key, mapping=mapping)
                    pipe.expire(key, ttl)
            await asyncio.wait_for(pipe.execute(), WRITE_TIMEOUT_SECONDS)
    except Exception as e:  # noqa: BLE001
        _gate.fail("write", e)
        return False
    _gate.ok()
    return True


async def read_quotes(symbols: List[str]) -> Optional[Dict[str, dict]]:
    """{symbol: row} for the requested symbols the cache holds (one MGET), or None when the cache is unavailable.
    A symbol that looks like a contract (ends FUT/CE/PE) is also looked up under NFO; only a key the leader wrote exists."""
    if not symbols:
        return {}
    c = await _client(READ_TIMEOUT_SECONDS)
    if c is None:
        return None
    keys: List[str] = []
    for s in symbols:
        keys.append(quote_key("NSE:" + s))
        if s.endswith(("FUT", "CE", "PE")):
            keys.append(quote_key("NFO:" + s))
    try:
        vals = await asyncio.wait_for(c.mget(keys), READ_TIMEOUT_SECONDS)
    except Exception as e:  # noqa: BLE001
        _gate.fail("read", e)
        return None
    _gate.ok()
    out: Dict[str, dict] = {}
    for v in vals or []:
        row = _load(v)
        if row and row.get("symbol") and row.get("ltp") is not None:
            out.setdefault(row["symbol"], row)
    return out


async def read_chain(underlying: str, expiry: str) -> Tuple[str, List[dict]]:
    """("ok", rows) | ("empty", []) when no chain is cached for that underlying and expiry | ("unavailable", []) when Redis
    cannot be read. Rows are whatever the leader cached; nothing is filled in."""
    c = await _client(READ_TIMEOUT_SECONDS)
    if c is None:
        return "unavailable", []
    try:
        idx = await asyncio.wait_for(c.hgetall(chain_key(underlying, expiry)), READ_TIMEOUT_SECONDS)
        if not idx:
            _gate.ok()
            return "empty", []
        qkeys = sorted(set(idx.values()))
        vals = await asyncio.wait_for(c.mget([quote_key(k) for k in qkeys]), READ_TIMEOUT_SECONDS)
    except Exception as e:  # noqa: BLE001
        _gate.fail("read", e)
        return "unavailable", []
    _gate.ok()
    return "ok", [r for r in (_load(v) for v in vals or []) if r]
