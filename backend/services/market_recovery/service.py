"""Market Recovery: loads the data for engine.compute() and keeps one result per worker (docs/market_recovery/DESIGN.md).

Reads only, all from sources the app already uses:
  * the scan builder's daily price panel (NSE end-of-day bars, split/bonus adjusted) and its reference data (names, the
    Nifty 100 / Midcap 150 / Smallcap 250 members) — services/scan_builder/data.py, shared file cache;
  * DaaS: the Nifty 500 constituent list with NSE industries, the Nifty 50 / Nifty 500 / India VIX closes, the feature store
    rows of the last ~12 sessions (POST /features/bulk), the daily delivery % of the last sessions (GET /prices/eod?on=);
  * the scan builder's futures fields (price and open-interest change, NSE F&O bhavcopy) for the short-covering check.

One computation per end-of-day date per worker, reused for CACHE_S; concurrent viewers wait for the same run. A failure of
the core reads (prices, members, Nifty) raises DataUnavailable; a failure of an optional read (VIX, features, delivery, F&O)
becomes a warning on the page and the affected parts show as gaps. Nothing here logs a credential.
"""
from __future__ import annotations

import asyncio
import logging
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import numpy as np

from services.kite_live_feed.config import IST
from services.scan_builder.data import DataUnavailable, ScanData, get_data

from . import engine

logger = logging.getLogger(__name__)

CACHE_S = 900.0
WINDOW = 320                      # sessions of history used (SMA200 + 250-session volume average + margin)
FEATURE_SESSIONS = 12
DELIVERY_LOOKBACK = 8             # sessions searched for the last 5 with delivery data
DELIVERY_SESSIONS = 5
DELIVERY_MIN_SHARE = 0.5          # a session counts when at least half the members have a delivery %
BULK_CHUNK = 300                  # DaaS _BULK_MAX_SYMBOLS
SOURCE_PRICES = "NSE end-of-day bars (split/bonus adjusted), NIDP warehouse"

Getter = Callable[..., Awaitable[Any]]


def _iso(d: Any) -> str:
    return str(d)[:10]


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


class RecoveryService:
    def __init__(self, *, data: Optional[ScanData] = None, daas_get: Optional[Getter] = None,
                 daas_post: Optional[Getter] = None, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        if daas_get is None or daas_post is None:
            from services.copilot_tools import daas_client
            daas_get, daas_post = daas_get or daas_client._get, daas_post or daas_client._post
        self._data = data
        self._get, self._post = daas_get, daas_post
        self._clock, self._now = clock, now
        self._lock = asyncio.Lock()
        self._cached: Optional[Tuple[str, float, Dict[str, Any]]] = None    # (eod date, when, result)
        self._context: Dict[str, Dict[str, Any]] = {}                        # per scored stock, from the same run

    @property
    def data(self) -> ScanData:
        return self._data or get_data()

    async def get(self) -> Dict[str, Any]:
        base = await self.data.panel()
        eod = base.eod_date.isoformat()
        async with self._lock:
            if self._cached and self._cached[0] == eod and self._clock() - self._cached[1] < CACHE_S:
                return self._cached[2]
            inp = await self.load()
            today = self._now().astimezone(IST).date()
            result = engine.compute(inp, today=today, computed_at=self._now().strftime("%Y-%m-%dT%H:%M:%SZ"))
            self._cached = (eod, self._clock(), result)
            self._context = dict(inp.context)
            return result

    async def stock_context(self, symbol: str) -> Optional[Dict[str, Any]]:
        """The scored stock's close, plan, beta, name and sector from the current page run (None when it is not scored)."""
        await self.get()
        return self._context.get(symbol.upper())

    # ── loading ─────────────────────────────────────────────────────────────────────────────────────────────────────
    async def load(self) -> engine.Inputs:
        data = self.data
        base = await data.panel()
        ref = await data.reference()
        as_of = base.eod_date
        cons = await self._constituents()
        members = [r["symbol"] for r in cons]
        industry = {r["symbol"]: r["industry"] for r in cons if r.get("industry")}
        cols = [base.index[s] for s in members if s in base.index]
        syms = [s for s in members if s in base.index]
        if not cols:
            raise DataUnavailable("None of the Nifty 500 members is in the price panel.")
        rows = slice(max(0, base.close.shape[0] - WINDOW), None)
        dates = base.dates[rows]
        warnings: List[str] = []
        missing = len(members) - len(syms)
        if missing:
            warnings.append(f"{missing} Nifty 500 member(s) have no end-of-day series in the price panel (e.g. trade-for-trade "
                            f"series) and are not scored.")

        start = (as_of - timedelta(days=240)).isoformat()
        n50, n500 = await asyncio.gather(self._index("Nifty 50", start, as_of), self._index("Nifty 500", start, as_of))
        if len(n50) < 26 or len(n500) < 26:
            raise DataUnavailable("The Nifty 50 / Nifty 500 closes could not be read for the last 25 sessions.")
        try:
            vix = await self._index("India VIX", start, as_of)
        except DataUnavailable:
            vix = []
        if not vix:
            warnings.append("India VIX closes could not be read; its check shows as unknown.")

        sess = [_day(d) for d in dates]
        feats_now, feats_then, feats_as_of = await self._features(syms, sess, warnings)
        delivery, deliv_as_of = await self._delivery(syms, sess, warnings)
        fno, fno_as_of = await self._fno(warnings)

        caps = {"large": set(ref.members.get("nifty100") or ()), "mid": set(ref.members.get("midcap150") or ()),
                "small": set(ref.members.get("smallcap250") or ())}
        names = {s: (ref.names.get(s) or next((r.get("company_name") for r in cons if r["symbol"] == s), None) or s)
                 for s in syms}
        sources = [
            {"what": "Daily prices", "source": SOURCE_PRICES, "as_of": as_of.isoformat()},
            {"what": "Nifty 500 members and industries", "source": "NSE index constituents, NIDP warehouse",
             "as_of": cons[0].get("as_of") if cons else None},
            {"what": "Nifty 50, Nifty 500, India VIX", "source": "NSE index closes, NIDP warehouse",
             "as_of": n50[-1][0].isoformat() if n50 else None},
            {"what": "Fundamentals, delivery averages, FII change, accumulation score",
             "source": "NIDP feature store (stock_features_daily)", "as_of": feats_as_of},
            {"what": "Daily delivery %", "source": "NSE bhavcopy delivery data, NIDP warehouse", "as_of": deliv_as_of},
            {"what": "Futures price and open interest", "source": "NSE F&O bhavcopy, NIDP warehouse", "as_of": fno_as_of},
        ]
        return engine.Inputs(
            as_of=as_of, dates=dates, symbols=syms,
            close=base.close[rows][:, cols], high=base.high[rows][:, cols], low=base.low[rows][:, cols],
            volume=base.volume[rows][:, cols], industry=industry, names=names, caps=caps,
            nifty50=n50, nifty500=n500, vix=vix, features_now=feats_now, features_then=feats_then,
            features_as_of=feats_as_of, delivery=delivery, delivery_as_of=deliv_as_of, fno=fno, fno_as_of=fno_as_of,
            members_total=len(members), members_as_of=cons[0].get("as_of") if cons else None,
            warnings=warnings, sources=sources,
        )

    async def _constituents(self) -> List[Dict[str, Any]]:
        try:
            body = await self._get(f"/indices/{urllib.parse.quote('Nifty 500')}/constituents", {"limit": 1000}, timeout=30.0)
        except Exception as e:  # noqa: BLE001 — DaasError, timeouts: one typed failure
            raise DataUnavailable(f"The Nifty 500 member list could not be read ({type(e).__name__}).") from e
        rows = (body or {}).get("data") or []
        out = []
        for r in rows:
            sym = str(r.get("symbol") or "").upper()
            if sym:
                out.append({"symbol": sym, "industry": (r.get("industry") or "").strip() or None,
                            "company_name": r.get("company_name"), "as_of": _iso(r.get("as_of_date") or (body or {}).get("as_of"))})
        if len(out) < 400:
            raise DataUnavailable(f"The Nifty 500 member list has only {len(out)} names.")
        return out

    async def _index(self, name: str, start: str, as_of: date) -> List[Tuple[date, float]]:
        try:
            body = await self._get(f"/indices/{urllib.parse.quote(name)}/eod",
                                   {"start": start, "end": as_of.isoformat(), "limit": 400}, timeout=30.0)
        except Exception as e:  # noqa: BLE001
            raise DataUnavailable(f"{name} closes could not be read ({type(e).__name__}).") from e
        out = []
        for r in (body or {}).get("data") or []:
            d, c = _day(r.get("as_of_date")), engine.fnum(r.get("close_price"))
            if d is not None and c is not None and c > 0:
                out.append((d, c))
        out.sort()
        return out

    async def _features(self, syms: List[str], sess: List[Optional[date]], warnings: List[str]):
        """The latest feature row per stock on or before the scored session, and the row 5 sessions earlier."""
        days = [d for d in sess if d is not None]
        if len(days) <= engine.LAG:
            return {}, {}, None
        as_of, then = days[-1], days[-1 - engine.LAG]
        start = days[-min(FEATURE_SESSIONS, len(days))].isoformat()
        rows: Dict[str, List[Dict[str, Any]]] = {}
        try:
            for i in range(0, len(syms), BULK_CHUNK):
                body = await self._post("/features/bulk", {"symbols": syms[i:i + BULK_CHUNK], "start": start,
                                                            "end": as_of.isoformat()}, timeout=60.0)
                for sym, rs in ((body or {}).get("data") or {}).items():
                    rows[str(sym).upper()] = rs
        except Exception as e:  # noqa: BLE001
            warnings.append(f"The feature store could not be read ({type(e).__name__}): fundamentals, delivery averages and "
                            f"smart-money parts show as gaps.")
            return {}, {}, None
        now, before, latest = {}, {}, None
        for sym, rs in rows.items():
            rs = sorted((r for r in rs if _day(r.get("as_of_date")) and _day(r.get("as_of_date")) <= as_of),
                        key=lambda r: _iso(r.get("as_of_date")))
            if not rs:
                continue
            now[sym] = rs[-1]
            d = _day(rs[-1].get("as_of_date"))
            latest = d if latest is None or (d and d > latest) else latest
            older = [r for r in rs if _day(r.get("as_of_date")) <= then]
            if older:
                before[sym] = older[-1]
        if latest is not None and latest < as_of:
            warnings.append(f"Feature-store rows are as of {latest.isoformat()}, one or more sessions behind the prices.")
        if now and not any("cfo_pat_ratio" in r for r in now.values()):
            warnings.append("Cash flow (CFO / PAT) is not served by the data platform yet; fundamental quality is scored on "
                            "the other parts.")
        return now, before, (latest.isoformat() if latest else None)

    async def _delivery(self, syms: List[str], sess: List[Optional[date]], warnings: List[str]):
        """Daily delivery % of the last DELIVERY_SESSIONS sessions that have it (it lands one session after prices)."""
        days = [d for d in sess if d is not None][-DELIVERY_LOOKBACK:]
        want = set(syms)
        sem = asyncio.Semaphore(3)

        async def one(d: date) -> Tuple[date, Dict[str, float]]:
            async with sem:
                body = await self._get("/prices/eod", {"on": d.isoformat(), "limit": 5000}, timeout=45.0)
            out = {}
            for r in (body or {}).get("data") or []:
                sym, v = str(r.get("symbol") or "").upper(), engine.fnum(r.get("deliv_pct"))
                if sym in want and v is not None:
                    out[sym] = v
            return d, out

        try:
            got = await asyncio.gather(*[one(d) for d in days])
        except Exception as e:  # noqa: BLE001
            warnings.append(f"Daily delivery % could not be read ({type(e).__name__}); delivery parts show as gaps.")
            return {}, None
        good = sorted((d, m) for d, m in got if len(m) >= DELIVERY_MIN_SHARE * max(1, len(syms)))
        good = good[-DELIVERY_SESSIONS:]
        if not good:
            warnings.append("No recent session has delivery data; delivery parts show as gaps.")
            return {}, None
        series: Dict[str, List[float]] = {}
        for _, m in good:
            for sym, v in m.items():
                series.setdefault(sym, []).append(v)
        return series, good[-1][0].isoformat()

    async def _fno(self, warnings: List[str]):
        try:
            ff = await self.data.fno_fields()
        except Exception as e:  # noqa: BLE001
            warnings.append(f"Futures data could not be read ({type(e).__name__}); the short-covering check is skipped.")
            return {}, None
        v = ff.values or {}
        out: Dict[str, Dict[str, Optional[float]]] = {}
        for key, field in (("price_chg", "fno_price_chg_pct"), ("oi_chg", "fno_oi_chg_pct"),
                           ("prev_price_chg", "fno_prev_price_chg_pct"), ("prev_oi_chg", "fno_prev_oi_chg_pct")):
            for sym, x in (v.get(field) or {}).items():
                out.setdefault(sym, {})[key] = engine.fnum(x)
        for w in ff.warnings or []:
            warnings.append(f"Futures data: {w}")
        return out, ff.as_of


_service: Optional[RecoveryService] = None


def get_service() -> RecoveryService:
    global _service
    if _service is None:
        _service = RecoveryService()
    return _service
