"""Scan Builder data: every number a scan reads, from our own stack only (never from Chartink).

Three parts, each cached so a scan can re-run every 10 seconds (docs/scan_builder/DESIGN.md §2):

  * the daily price panel: NSE end-of-day bars, split/bonus adjusted (nidp.prices_eod_adjusted through DaaS
    POST /v1/prices/adjusted/bulk), all symbols from 2024-04-01, as float arrays (dates × symbols, NaN = no bar). Loaded once
    per end-of-day date. The backend runs four worker processes, so the first one to need a new date loads it from DaaS and
    writes a file; the others wait on a file lock and read the file (DaaS is asked once, not four times).
  * reference data: symbol names, the F&O list, index constituents and the latest fundamentals (DaaS /v1/symbols/universe,
    /v1/indices/{name}/constituents, /v1/stocks/screener), refreshed every 30 minutes.
  * today's candle, by the owner's rule of 29 Oct (services/kite_live_feed/day_quote.py): market open → the Kite live quote,
    after the close → the saved Kite close, once the exchange's EOD file is in → nothing is added. The live feed carries about
    600 cash stocks; the rest of a scan's universe is read with Kite REST quote() through one shared cache (RestQuotes). A
    candle joins the adjusted series only when Kite's previous close equals the series' last close (the day_quote rule), so a
    pending split or bonus never corrupts the history.

Reads only. Nothing here logs a credential or a quote payload.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

from services.kite_live_feed import config as kcfg
from services.kite_live_feed import day_quote as dq
from services.kite_live_feed import gateway as gw

logger = logging.getLogger(__name__)

PANEL_START = date(2024, 4, 1)          # nidp.prices_eod_adjusted starts here
BULK_CHUNK = 300                        # DaaS _BULK_MAX_SYMBOLS
BULK_CONCURRENCY = 2                    # gentle on the shared DaaS
BULK_TIMEOUT_S = 90.0
PROBE_SYMBOLS = ("RELIANCE", "HDFCBANK", "TCS", "INFY", "ITC", "SBIN")
PANEL_CHECK_S = 900                     # how often a worker asks DaaS whether a newer EOD day is in
RECENT_DAYS = 14                        # a symbol whose last price is older than this (calendar days) is left out of the panel
REF_TTL_S = 1800
CACHE_DIR = Path(os.environ.get("SCAN_BUILDER_CACHE_DIR", "/tmp/scan_builder"))
PANEL_FILE, META_FILE, LOCK_FILE = "panel.npz", "panel.json", "panel.lock"

# Universe key -> the index_name in nidp.index_constituents (cash and fno are not indices).
INDEX_NAMES: Dict[str, str] = {
    "nifty50": "Nifty 50", "nifty100": "Nifty 100", "nifty200": "Nifty 200", "nifty500": "Nifty 500",
    "midcap150": "Nifty Midcap 150", "smallcap250": "Nifty Smallcap 250", "niftybank": "Nifty Bank",
}
SOURCE_PRICES = "NSE end-of-day bars (split/bonus adjusted), NIDP warehouse"
SOURCE_TODAY = {"live": "Kite live", "kite_close": "Kite close (provisional until the exchange's end-of-day file)", "eod": None}

# F&O fields (DESIGN.md §7.3): stock futures from the NSE F&O bhavcopy, via DaaS /v1/desk/fno-buildup.
FNO_TTL_S = 600
FNO_PREV_WALK_DAYS = 7                  # calendar days walked back from the latest session to find the one before
FNO_ROW_FIELDS = (("fno_price_chg_pct", "price_chg_pct"), ("fno_oi_chg_pct", "oi_chg_pct"))
FNO_PREV_FIELDS = (("fno_prev_price_chg_pct", "price_chg_pct"), ("fno_prev_oi_chg_pct", "oi_chg_pct"))


class DataUnavailable(Exception):
    """The price panel or the reference data could not be read and there is no earlier copy to fall back on."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class BasePanel:
    """The end-of-day panel: `dates` (T,) datetime64[D] ascending, OHLCV arrays (T, N) float64, NaN = no bar that day."""
    symbols: List[str]
    dates: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    eod_date: date
    index: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.index:
            self.index = {s: i for i, s in enumerate(self.symbols)}


@dataclass
class Reference:
    names: Dict[str, str]
    fno: Set[str]
    members: Dict[str, Set[str]]                     # index universe key -> symbols (latest constituent snapshot)
    members_as_of: Optional[str]
    fundamentals: Dict[str, Dict[str, float]]       # field -> symbol -> value
    fundamentals_as_of: Optional[str]
    recent: Dict[str, str]                           # symbol -> last_price_date (ISO)


@dataclass
class FnoFields:
    """Per-stock futures figures for the `fno_*` fields: field -> symbol -> value. A null in the bhavcopy stays missing."""
    values: Dict[str, Dict[str, float]] = field(default_factory=dict)
    as_of: Optional[str] = None                      # the latest F&O session read (ISO day)
    prev_as_of: Optional[str] = None                 # the session before it
    source: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class TodayOverlay:
    """Today's candles to append to the panel, and what happened. `bars` maps a panel column to [o, h, l, c, v]."""
    mode: str                                        # live | kite_close | eod
    day: date                                        # the day 'latest' means
    bars: Dict[int, List[float]] = field(default_factory=dict)
    quote_as_of: Optional[str] = None
    counts: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    session_open: bool = False                       # 09:15-15:30 IST on a weekday (the clock, not whether quotes joined)


def _f(v: Any) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return x if np.isfinite(x) else float("nan")


Compact = Tuple[np.ndarray, np.ndarray]           # (dates (n,) datetime64[D], values (n, 5) o/h/l/c/v float64)


def compact(rows: Iterable[Dict[str, Any]]) -> Compact:
    """One symbol's DaaS bulk rows as two small arrays (a few bytes a bar instead of a dict a bar). A row without a positive
    close is no bar."""
    days: List[str] = []
    vals: List[Tuple[float, float, float, float, float]] = []
    for r in rows:
        d = str(r.get("as_of_date") or "")[:10]
        c = _f(r.get("adj_close"))
        if not d or not (c > 0):
            continue
        days.append(d)
        vals.append((_f(r.get("adj_open")), _f(r.get("adj_high")), _f(r.get("adj_low")), c, _f(r.get("adj_volume"))))
    return np.array(days, dtype="datetime64[D]"), np.array(vals, dtype=np.float64).reshape(-1, 5)


def build_panel_compact(by_symbol: Dict[str, Compact], symbols: Sequence[str]) -> BasePanel:
    """Arrays on one common calendar (every day any symbol has a bar). `symbols` fixes the column order; a symbol with no
    bars stays all-NaN."""
    parts = [by_symbol[s][0] for s in symbols if s in by_symbol and by_symbol[s][0].size]
    cal = np.unique(np.concatenate(parts)) if parts else np.array([], dtype="datetime64[D]")
    t, n = cal.size, len(symbols)
    arr = np.full((5, t, n), np.nan)
    for j, s in enumerate(symbols):
        d, v = by_symbol.get(s, (None, None))
        if d is None or not d.size:
            continue
        rows = np.searchsorted(cal, d)
        arr[:, rows, j] = v.T
    eod = date.fromisoformat(str(cal[-1])) if t else PANEL_START
    return BasePanel(symbols=list(symbols), dates=cal, eod_date=eod, open=arr[0], high=arr[1], low=arr[2], close=arr[3],
                     volume=arr[4])


def build_panel(rows_by_symbol: Dict[str, List[Dict[str, Any]]], symbols: Sequence[str]) -> BasePanel:
    """The panel from DaaS bulk rows ({symbol: [{as_of_date, adj_open, adj_high, adj_low, adj_close, adj_volume}, ...]})."""
    return build_panel_compact({s: compact(rows_by_symbol.get(s) or ()) for s in symbols}, symbols)


def save_panel(p: BasePanel, folder: Path) -> None:
    """Write the panel atomically (temp file + rename): float32 on disk halves it (prices keep 2 decimals at these sizes)."""
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / (PANEL_FILE + ".tmp.npz")
    np.savez(tmp, symbols=np.array(p.symbols), dates=p.dates.astype("int64"),
             **{k: getattr(p, k).astype(np.float32) for k in ("open", "high", "low", "close", "volume")})
    os.replace(tmp, folder / PANEL_FILE)
    meta_tmp = folder / (META_FILE + ".tmp")
    meta_tmp.write_text(json.dumps({"eod_date": p.eod_date.isoformat(), "symbols": len(p.symbols), "days": int(p.dates.size),
                                    "written_at": datetime.now(timezone.utc).isoformat()}))
    os.replace(meta_tmp, folder / META_FILE)


def read_meta(folder: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads((folder / META_FILE).read_text())
    except (OSError, ValueError):
        return None


def load_panel_file(folder: Path) -> BasePanel:
    with np.load(folder / PANEL_FILE, allow_pickle=False) as z:
        dates = z["dates"].astype("datetime64[D]")
        arrays = {k: z[k].astype(np.float64) for k in ("open", "high", "low", "close", "volume")}
        symbols = [str(s) for s in z["symbols"]]
    eod = date.fromisoformat(str(dates[-1])) if dates.size else PANEL_START
    return BasePanel(symbols=symbols, dates=dates, eod_date=eod, **arrays)


class _FileLock:
    """An exclusive flock on `path`, taken in a thread so the event loop never blocks. Shared by the worker processes."""

    def __init__(self, path: Path):
        self.path = path
        self._fd: Optional[int] = None

    async def __aenter__(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        await asyncio.to_thread(fcntl.flock, fd, fcntl.LOCK_EX)
        self._fd = fd
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


class RestQuotes:
    """Kite REST quote() for stocks the live feed does not carry, shared by every scan in this process.

    One fetch at a time; batches of at most REST_BATCH (500) symbols at least REST_SPACING_SECONDS (1.1 s) apart (Kite allows
    one quote call a second); a symbol is re-read only when its copy is older than the TTL (30 s while the market is open,
    10 minutes otherwise). After Kite refuses, nothing is asked for FAIL_BACKOFF_S. Without a token or key nothing is called."""

    TTL_OPEN_S, TTL_CLOSED_S, FAIL_BACKOFF_S, MAX_SYMBOLS = 30.0, 600.0, 30.0, 3000

    def __init__(self, *, token_getter: Callable[[], str] = kcfg.get_token, key_getter: Callable[[], str] = kcfg.get_api_key,
                 kite_factory: Callable[[str, str], Any] = gw.default_kite_factory,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 spacing: float = kcfg.REST_SPACING_SECONDS, batch: int = kcfg.REST_BATCH):
        self._token, self._key, self._factory = token_getter, key_getter, kite_factory
        self._clock, self._wall, self._sleep = clock, wall, sleep
        self._spacing, self._batch = spacing, batch
        self._cache: Dict[str, Tuple[float, dict]] = {}
        self._lock = asyncio.Lock()
        self._last_call = float("-inf")
        self._fail_until = float("-inf")
        self.calls = 0                                   # quote() calls made (tests and the run's counts read it)
        self.last_fetch_at: Optional[str] = None

    async def get(self, symbols: Iterable[str], *, open_session: bool) -> Tuple[Dict[str, dict], Optional[str]]:
        """({symbol: quote in the live feed's shape}, why) — why is None, no_kite_token or kite_refused."""
        from services.kite_live_feed.feed import make_quote

        ttl = self.TTL_OPEN_S if open_session else self.TTL_CLOSED_S
        want = [s for s in dict.fromkeys(gw.canon(x) for x in symbols) if s][: self.MAX_SYMBOLS]
        why: Optional[str] = None
        async with self._lock:
            now = self._clock()
            stale = [s for s in want if s not in self._cache or now - self._cache[s][0] > ttl]
            if stale and now < self._fail_until:
                why = "kite_refused"
            elif stale:
                token, key = await asyncio.to_thread(self._token), await asyncio.to_thread(self._key)
                if not token or not key:
                    why = "no_kite_token"
                else:
                    kite = self._factory(key, token)
                    for i in range(0, len(stale), self._batch):
                        wait = self._last_call + self._spacing - self._clock()
                        if wait > 0:
                            await self._sleep(wait)
                        self._last_call = self._clock()
                        chunk = stale[i:i + self._batch]
                        try:
                            data = await asyncio.to_thread(kite.quote, [f"NSE:{s}" for s in chunk])
                        except Exception as e:  # noqa: BLE001 — a refusal (token, limit, network) ends this fetch; cached copies stay
                            logger.warning("scan builder: Kite quote() refused (%s)", type(e).__name__)
                            self._fail_until = self._clock() + self.FAIL_BACKOFF_S
                            why = "kite_refused"
                            break
                        self.calls += 1
                        stamp, at = self._clock(), self._wall()
                        for k, v in (data or {}).items():
                            q = make_quote(gw.canon(k), v.get("last_price"), v.get("ohlc"), v.get("volume"), None,
                                           v.get("timestamp"), at)
                            if q:
                                self._cache[gw.canon(k)] = (stamp, q)
                        self.last_fetch_at = at.isoformat()
            now = self._clock()
            out = {s: self._cache[s][1] for s in want if s in self._cache and now - self._cache[s][0] <= ttl}
        return out, why


DaasGet = Callable[..., Awaitable[Any]]


async def _market_window(now: datetime) -> Any:
    from services import market_freshness   # lazy: its holiday reader imports the app's routes
    return await market_freshness.window(now)


def _iso(v: Any) -> Optional[str]:
    if isinstance(v, str) and len(v) >= 10:
        try:
            return date.fromisoformat(v[:10]).isoformat()
        except ValueError:
            return None
    return None


def _fill_fno(values: Dict[str, Dict[str, float]], rows: Iterable[Dict[str, Any]], pairs: Sequence[Tuple[str, str]]) -> None:
    """Copy each row's figures into values[field][symbol]; a null or non-number is left out (missing, never 0)."""
    for fld, _ in pairs:
        values.setdefault(fld, {})
    for r in rows:
        sym = r.get("symbol") if isinstance(r, dict) else None
        if not isinstance(sym, str) or not sym:
            continue
        for fld, key in pairs:
            v = r.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v):
                values[fld][sym] = float(v)


class ScanData:
    """The per-process holder of the panel and reference data, plus today's candles. One instance per worker (`get_data`)."""

    def __init__(self, *, daas_get: Optional[DaasGet] = None, daas_post: Optional[DaasGet] = None,
                 cache_dir: Path = CACHE_DIR, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 day_quotes: Callable[..., Awaitable[Dict[str, Any]]] = dq.day_quotes,
                 holidays: Callable[[str, str], Awaitable[Optional[Set[date]]]] = dq.holidays_between,
                 rest: Optional[RestQuotes] = None, probe_symbols: Sequence[str] = PROBE_SYMBOLS,
                 freshness: Optional[Callable[[datetime], Awaitable[Any]]] = None):
        if daas_get is None or daas_post is None:
            from services.copilot_tools import daas_client
            daas_get, daas_post = daas_get or daas_client._get, daas_post or daas_client._post
        self._get, self._post = daas_get, daas_post
        self._dir, self._clock, self._now = cache_dir, clock, now
        self._day_quotes, self._holidays = day_quotes, holidays
        self.rest = rest or RestQuotes()
        self._probe = list(probe_symbols)
        self._base: Optional[BasePanel] = None
        self._checked = float("-inf")
        self._ref: Optional[Reference] = None
        self._ref_at = float("-inf")
        self._panel_lock = asyncio.Lock()
        self._ref_lock = asyncio.Lock()
        self._warm_task: Optional[asyncio.Task] = None
        self.panel_source: Optional[str] = None          # "memory" | "file" | "daas" — how the last panel() call was served
        self._freshness = freshness or _market_window
        self._fno: Optional[FnoFields] = None
        self._fno_at = float("-inf")
        self._fno_lock = asyncio.Lock()

    @property
    def loaded_panel(self) -> Optional[BasePanel]:
        """The panel in memory, if any (no load is started)."""
        return self._base

    # ── reference data ──────────────────────────────────────────────────────────────────────────────────────────────
    async def reference(self) -> Reference:
        async with self._ref_lock:
            if self._ref is not None and self._clock() - self._ref_at < REF_TTL_S:
                return self._ref
            try:
                ref = await self._load_reference()
            except DataUnavailable:
                if self._ref is not None:
                    logger.warning("scan builder: reference refresh failed; keeping the copy from %.0f s ago",
                                   self._clock() - self._ref_at)
                    return self._ref
                raise
            self._ref, self._ref_at = ref, self._clock()
            return ref

    # ── F&O fields (DESIGN.md §7.3) ─────────────────────────────────────────────────────────────────────────────────
    async def fno_fields(self) -> FnoFields:
        """The `fno_*` fields of the latest F&O session and the one before, cached FNO_TTL_S. Never raises: a read failure or
        a latest session older than the previous trading session answers no values and a warning (owner rule 28 Oct)."""
        async with self._fno_lock:
            if self._fno is not None and self._clock() - self._fno_at < FNO_TTL_S:
                return self._fno
            out = await self._load_fno()
            self._fno, self._fno_at = out, self._clock()
            return out

    async def _load_fno(self) -> FnoFields:
        try:
            latest = await self._get("/desk/fno-buildup", timeout=30.0)
        except Exception as e:  # noqa: BLE001 — the scan still runs; the F&O fields are missing and the warning says why
            logger.warning("scan builder: F&O build-up unreadable (%s)", type(e).__name__)
            return FnoFields(warnings=["The F&O fields are not available: the F&O data could not be read."])
        rows = latest.get("rows") if isinstance(latest, dict) else None
        as_of = _iso(latest.get("as_of")) if isinstance(latest, dict) else None
        if not isinstance(rows, list) or not rows or as_of is None:
            return FnoFields(as_of=as_of, warnings=["The F&O fields are not available: no stock-futures rows were found."])
        window = await self._freshness(self._now())
        if not window.current(as_of):
            return FnoFields(as_of=as_of, warnings=[window.stale_reason("the F&O fields", as_of)])
        out = FnoFields(as_of=as_of)
        _fill_fno(out.values, rows, FNO_ROW_FIELDS)
        for fld, _ in FNO_PREV_FIELDS:
            out.values.setdefault(fld, {})                # all four fields present once the latest session is current
        prev_day, prev_rows = await self._previous_fno(date.fromisoformat(as_of))
        if prev_day is None:
            out.warnings.append("The session before the latest F&O session could not be read; the 'session before' fields are missing.")
        else:
            out.prev_as_of = prev_day.isoformat()
            _fill_fno(out.values, prev_rows, FNO_PREV_FIELDS)
        latest_txt = date.fromisoformat(as_of).strftime("%d %b %Y")
        out.source = (f"NSE F&O bhavcopy, {latest_txt} (stock futures; price of the nearest expiry, OI summed over expiries)"
                      + (f"; session before: {prev_day.strftime('%d %b %Y')}" if prev_day else ""))
        return out

    async def _previous_fno(self, latest: date) -> Tuple[Optional[date], List[Dict[str, Any]]]:
        """The F&O session before `latest`: weekdays walked back (at most FNO_PREV_WALK_DAYS calendar days) until DaaS has rows."""
        d = latest
        for _ in range(FNO_PREV_WALK_DAYS):
            d -= timedelta(days=1)
            if d.weekday() >= 5:
                continue
            try:
                body = await self._get("/desk/fno-buildup", {"date": d.isoformat()}, timeout=30.0)
            except Exception as e:  # noqa: BLE001 — the 'session before' fields are then missing, with a warning
                logger.warning("scan builder: F&O build-up for %s unreadable (%s)", d.isoformat(), type(e).__name__)
                return None, []
            rows = body.get("rows") if isinstance(body, dict) else None
            if isinstance(rows, list) and rows:
                return d, rows
        return None, []

    async def _load_reference(self) -> Reference:
        try:
            uni = await self._get("/symbols/universe", timeout=30.0)
            scr = await self._get("/stocks/screener", {"limit": 5000}, timeout=60.0)
            idx = await asyncio.gather(*[self._get(f"/indices/{urllib.parse.quote(name)}/constituents", {"limit": 1000}, timeout=30.0)
                                         for name in INDEX_NAMES.values()])
        except Exception as e:  # noqa: BLE001 — DaasError, timeouts: one typed failure
            raise DataUnavailable(f"The data platform could not be read for the stock list ({type(e).__name__}).") from e
        rows = (uni or {}).get("data") or []
        if not rows:
            raise DataUnavailable("The data platform returned no stock list.")
        names = {str(r["symbol"]).upper(): (r.get("company_name") or "") for r in rows if r.get("symbol")}
        fno = {str(r["symbol"]).upper() for r in rows if r.get("symbol") and r.get("fno_eligible")}
        recent = {str(r["symbol"]).upper(): str(r.get("last_price_date") or "")[:10] for r in rows if r.get("symbol")}
        members: Dict[str, Set[str]] = {}
        as_of = None
        for key, body in zip(INDEX_NAMES, idx):
            data = (body or {}).get("data") or []
            members[key] = {str(r["symbol"]).upper() for r in data if r.get("symbol")}
            as_of = as_of or (body or {}).get("as_of")
        fundamentals: Dict[str, Dict[str, float]] = {}
        for r in (scr or {}).get("data") or []:
            sym = str(r.get("symbol") or "").upper()
            if not sym:
                continue
            for k, v in r.items():
                x = _f(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else float("nan")
                if np.isfinite(x):
                    fundamentals.setdefault(k, {})[sym] = x
        return Reference(names=names, fno=fno, members=members, members_as_of=str(as_of) if as_of else None,
                         fundamentals=fundamentals, fundamentals_as_of=(scr or {}).get("as_of_date"), recent=recent)

    # ── the price panel ─────────────────────────────────────────────────────────────────────────────────────────────
    def warm(self) -> None:
        """Start loading the panel in the background (the catalog call does this, so the first Run is warm)."""
        if self._warm_task is None or self._warm_task.done():
            self._warm_task = asyncio.create_task(self._warm())

    async def _warm(self) -> None:
        try:
            await self.panel()
        except DataUnavailable as e:
            logger.warning("scan builder: warm-up failed: %s", e.message)

    async def _latest_eod(self) -> Optional[date]:
        start = (self._now().astimezone(kcfg.IST).date() - timedelta(days=15)).isoformat()
        body = await self._post("/prices/adjusted/bulk", {"symbols": self._probe, "start": start, "end": None},
                                timeout=30.0)
        days = [str(r.get("as_of_date"))[:10] for rows in ((body or {}).get("data") or {}).values() for r in rows
                if r.get("adj_close") is not None]
        return date.fromisoformat(max(days)) if days else None

    async def panel(self) -> BasePanel:
        async with self._panel_lock:
            if self._base is not None and self._clock() - self._checked < PANEL_CHECK_S:
                self.panel_source = "memory"
                return self._base
            try:
                latest = await self._latest_eod()
            except Exception as e:  # noqa: BLE001
                if self._base is not None:
                    logger.warning("scan builder: EOD probe failed (%s); keeping the %s panel", type(e).__name__, self._base.eod_date)
                    self._checked = self._clock()
                    self.panel_source = "memory"
                    return self._base
                raise DataUnavailable(f"The data platform could not be reached for prices ({type(e).__name__}).") from e
            if latest is None:
                if self._base is not None:
                    self.panel_source = "memory"
                    return self._base
                raise DataUnavailable("The data platform returned no recent end-of-day prices.")
            if self._base is not None and self._base.eod_date >= latest:
                self._checked = self._clock()
                self.panel_source = "memory"
                return self._base
            base = await self._load_shared(latest)
            self._base, self._checked = base, self._clock()
            return base

    async def _load_shared(self, latest: date) -> BasePanel:
        async with _FileLock(self._dir / LOCK_FILE):
            meta = read_meta(self._dir)
            if meta and meta.get("eod_date") == latest.isoformat() and (self._dir / PANEL_FILE).exists():
                try:
                    base = await asyncio.to_thread(load_panel_file, self._dir)
                    self.panel_source = "file"
                    return base
                except (OSError, ValueError, KeyError) as e:
                    logger.warning("scan builder: panel file unreadable (%s); reloading from DaaS", type(e).__name__)
            base = await self._load_from_daas(latest)
            try:
                await asyncio.to_thread(save_panel, base, self._dir)
            except OSError as e:
                logger.warning("scan builder: panel file not written (%s); this worker keeps it in memory", type(e).__name__)
            self.panel_source = "daas"
            return base

    async def _load_from_daas(self, latest: date) -> BasePanel:
        ref = await self.reference()
        floor = (latest - timedelta(days=RECENT_DAYS)).isoformat()
        symbols = sorted(s for s, d in ref.recent.items() if d and d >= floor)
        if not symbols:
            raise DataUnavailable("No stock has a recent end-of-day price on the data platform.")
        sem = asyncio.Semaphore(BULK_CONCURRENCY)
        rows: Dict[str, Compact] = {}

        async def one(chunk: List[str]) -> None:
            async with sem:
                body = await self._post("/prices/adjusted/bulk",
                                        {"symbols": chunk, "start": PANEL_START.isoformat(), "end": latest.isoformat()},
                                        timeout=BULK_TIMEOUT_S)
                # Compact each chunk as it arrives so at most BULK_CONCURRENCY chunks of parsed JSON are alive at once.
                for s, rs in ((body or {}).get("data") or {}).items():
                    rows[str(s).upper()] = compact(rs)
                del body

        t0 = time.monotonic()
        try:
            await asyncio.gather(*[one(symbols[i:i + BULK_CHUNK]) for i in range(0, len(symbols), BULK_CHUNK)])
        except Exception as e:  # noqa: BLE001
            raise DataUnavailable(f"End-of-day prices could not be loaded from the data platform ({type(e).__name__}).") from e
        have = [s for s in symbols if s in rows and rows[s][0].size]
        base = await asyncio.to_thread(build_panel_compact, rows, have)
        logger.info("scan builder: panel %s loaded from DaaS: %d symbols, %d days in %.1f s",
                    base.eod_date, len(have), base.dates.size, time.monotonic() - t0)
        return base

    # ── today's candle ──────────────────────────────────────────────────────────────────────────────────────────────
    async def today(self, base: BasePanel, symbols: Sequence[str]) -> TodayOverlay:
        """Today's candles for `symbols` (panel symbols), by the owner's rule, or an EOD overlay with the reason."""
        now = self._now()
        session = dq.in_session(now)
        day = (now.astimezone(kcfg.IST).date() if session else kcfg.last_close(now).astimezone(kcfg.IST).date())
        if base.eod_date >= day:
            return TodayOverlay(mode="eod", day=base.eod_date, counts={"joined": 0}, session_open=session)
        res = await self._day_quotes(symbols, now=now)
        quotes: Dict[str, dict] = dict(res.get("quotes") or {})
        q_day = res.get("day") or day.isoformat()
        out = TodayOverlay(mode="live" if session else "kite_close", day=date.fromisoformat(q_day),
                           quote_as_of=res.get("as_of"), session_open=session)
        feed_n = len(quotes)
        missing = [s for s in symbols if s not in quotes]
        rest_n, rest_why = 0, None
        if missing:
            got, rest_why = await self.rest.get(missing, open_session=session)
            for s, q in got.items():
                if dq.traded_on(q, q_day):
                    quotes[s] = q
                    rest_n += 1
            if rest_n and not out.quote_as_of:
                out.quote_as_of = self.rest.last_fetch_at
        gap = dq._weekdays_between(base.eod_date.isoformat(), q_day)
        if gap:
            hol = await self._holidays(base.eod_date.isoformat(), q_day)
            if hol is None or any(d not in hol for d in gap):
                out.mode, out.day = "eod", base.eod_date
                out.warnings.append(f"The end-of-day series ends {base.eod_date.isoformat()} and a session before {q_day} is "
                                    f"missing, so today's Kite prices are not joined; the scan uses the {base.eod_date.isoformat()} close.")
                out.counts = {"joined": 0}
                return out
        last_close = base.close[-1]
        joined = no_join = 0
        for s in symbols:
            j = base.index.get(s)
            q = quotes.get(s)
            if j is None or q is None or not np.isfinite(last_close[j]):
                continue
            prev = dq._num(q.get("close"))
            if prev is None or abs(prev - last_close[j]) > dq.JOIN_TOLERANCE * last_close[j]:
                no_join += 1
                continue
            bar = dq.day_bar(q, q_day)
            if bar is None:
                continue
            out.bars[j] = [float(x) for x in bar[1:]]
            joined += 1
        out.counts = {"feed_quotes": feed_n, "rest_quotes": rest_n, "joined": joined, "does_not_join": no_join}
        if not joined:
            why = res.get("why") or rest_why
            d = date.fromisoformat(q_day)
            hol = await self._holidays((d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat())
            if hol and d in hol:
                why = "holiday"
            reason = {"holiday": "it is an NSE holiday",
                      "feed_not_live": "the Kite live feed is not live (the daily Kite login may be pending)",
                      "no_saved_close": "no Kite close was saved for the day",
                      "no_kite_token": "there is no Kite login for the day",
                      "kite_refused": "Kite refused the quote request",
                      "unreadable": "the live quotes could not be read"}.get(why or "", "no Kite quote joined the series")
            out.warnings.append(f"No today's candle for {q_day}: {reason}. The scan uses the {base.eod_date.isoformat()} close.")
            out.mode, out.day = "eod", base.eod_date
            return out
        if rest_why and missing:
            out.warnings.append("Some stocks outside the live feed have no Kite quote "
                                f"({'no Kite login' if rest_why == 'no_kite_token' else 'Kite refused the request'}); they are left out.")
        if no_join:
            out.warnings.append(f"{no_join} stock(s) are left out because Kite's previous close differs from the end-of-day "
                                "close (a split, bonus or missing session not yet in the adjusted series).")
        return out


_DATA: Optional[ScanData] = None


def get_data() -> ScanData:
    global _DATA
    if _DATA is None:
        _DATA = ScanData()
    return _DATA
