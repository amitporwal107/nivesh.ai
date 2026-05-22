"""Benchmark Index Data Service — daily ingestion + metrics + read APIs.

Per PRD shared 2026-04-30:
  • Ingest daily OHLCV for NSE indices (yfinance primary, NSE direct
    fallback when wired).
  • Compute returns (1D / 1M / 3M / 6M / 1Y / 3Y / 5Y), annualised
    volatility, current drawdown, max drawdown.
  • Serve via three reads: latest, history, benchmark-for-category.
  • Daily refresh wired via apscheduler at 18:30 IST.

Data flow:
    yfinance  →  market_index_data  →  index_metrics
                                           ↓
                       Redis cache (latest snapshot)  →  /api/index/*

Indices are keyed by their NSE-style names (NIFTY_50, NIFTY_MIDCAP_150,
etc.). yfinance ticker maps live in `_YF_TICKERS` below — extend when
new indices are added.
"""
from __future__ import annotations
import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# yfinance ticker chains. NSE indices vary in yfinance coverage —
# Nifty 50 / Bank / IT have direct tickers (^NSEI, ^NSEBANK, ^CNXIT)
# but Midcap 150, Smallcap 250 and Nifty 500 don't, so we use index
# ETFs that track them 1:1 as the data source. Multiple tickers per
# index → first one that returns data wins; the rest are fallbacks.
#
# The four CRITICAL mappings the PRD calls out (Large Cap → Nifty 50,
# Mid Cap → Nifty Midcap 150, Small Cap → Nifty Smallcap 250, Flexicap
# → Nifty 500) are at the top of the file so the daily cron always
# refreshes them first.
_YF_TICKERS: Dict[str, List[str]] = {
    # Critical four (PRD §1 mapping)
    "NIFTY_50":              ["^NSEI"],
    "NIFTY_MIDCAP_150":      ["MID150.NS", "MID150BEES.NS", "0P0001N0L9.BO"],
    "NIFTY_SMALLCAP_250":    ["NIFTYSMLCAP250.NS", "SMALLCAP.NS",
                              "NIFTYIETF.NS"],
    "NIFTY_500":             ["NIFTY500.NS", "NIFTYBEES500.NS",
                              "0P0001BAYL.BO"],
    # BSE Sensex — requested by V3 performance screen
    "SENSEX":                ["^BSESN"],
    # Nifty Midcap 100 — V3 performance screen; ETF proxy
    "NIFTY_MIDCAP_100":      ["MIDCAP100.NS", "MID150.NS"],
    # Additional indices used by the action engine
    "NIFTY_LARGEMIDCAP_250": ["LARGEMID250.NS", "NIFTY500.NS"],
    "NIFTY_BANK":            ["^NSEBANK"],
    "NIFTY_IT":              ["^CNXIT"],
    "NIFTY_NEXT_50":         ["JUNIORBEES.NS"],
}

_RETURN_WINDOWS_DAYS = {
    "1d":   1,
    "1m":   30,
    "3m":   91,
    "6m":   182,
    "1y":   365,
    "3y":   365 * 3,
    "5y":   365 * 5,
}

_LATEST_CACHE_TTL_S = 3600          # 1h — index data is EOD anyway
_HISTORY_CACHE_TTL_S = 7200          # 2h
_BENCHMARK_MAP_CACHE_TTL_S = 86400   # 24h — almost-static lookup


# ── Storage helpers ────────────────────────────────────────────────────
async def _pool():
    from services import pg_client
    return await pg_client.get_pool()


async def upsert_index_data(rows: List[Dict[str, Any]]) -> int:
    """Bulk upsert into market_index_data. Returns count written.
    Each row needs: index_name, date, open, high, low, close, volume."""
    if not rows:
        return 0
    pool = await _pool()
    if pool is None:
        logger.warning("PG unavailable — skipping index data upsert (%d rows)", len(rows))
        return 0
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO market_index_data (index_name, date, open, high, low, close, volume, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (index_name, date) DO UPDATE
              SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                  close=EXCLUDED.close, volume=EXCLUDED.volume,
                  source=EXCLUDED.source, updated_at=NOW()
            """,
            [
                (r["index_name"], r["date"], r.get("open"), r.get("high"),
                 r.get("low"), r["close"], r.get("volume"), r.get("source", "yfinance"))
                for r in rows
            ],
        )
    return len(rows)


# ── yfinance fetch ─────────────────────────────────────────────────────
def _fetch_one_ticker(ticker: str, period: str) -> List[Dict[str, Any]]:
    """Fetch OHLC from a single yfinance ticker. Returns rows with
    `source` already populated. [] on any failure."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(period=period, auto_adjust=False)
        if df is None or df.empty:
            return []
        rows = []
        for idx, row in df.iterrows():
            d = idx.date() if hasattr(idx, "date") else idx
            close = row.get("Close")
            if _is_nan(close):
                continue
            rows.append({
                "date": d,
                "open": float(row.get("Open")) if not _is_nan(row.get("Open")) else None,
                "high": float(row.get("High")) if not _is_nan(row.get("High")) else None,
                "low":  float(row.get("Low"))  if not _is_nan(row.get("Low"))  else None,
                "close": float(close),
                "volume": int(row.get("Volume") or 0),
                "source": f"yfinance:{ticker}",
            })
        return rows
    except Exception as e:  # noqa: BLE001
        logger.warning("yfinance fetch failed for %s: %s", ticker, e)
        return []


def _fetch_yfinance_history(index_name: str, period: str = "5y") -> List[Dict[str, Any]]:
    """Walk the ticker chain for `index_name`. First chain entry that
    returns ≥ 30 days of data wins. Returns rows tagged with index_name +
    the source ticker so we can audit which proxy the data came from."""
    chain = _YF_TICKERS.get(index_name) or []
    if isinstance(chain, str):
        chain = [chain]
    if not chain:
        logger.warning("benchmark: no ticker chain for %s", index_name)
        return []
    for ticker in chain:
        rows = _fetch_one_ticker(ticker, period)
        if len(rows) >= 30:
            for r in rows:
                r["index_name"] = index_name
            logger.info("benchmark: %s ← %s (%d rows)", index_name, ticker, len(rows))
            return rows
        logger.info("benchmark: %s ticker %s returned only %d rows — falling through",
                    index_name, ticker, len(rows))
    logger.warning("benchmark: no ticker in chain returned data for %s", index_name)
    return []


def _is_nan(v) -> bool:
    try:
        return v is None or (isinstance(v, float) and math.isnan(v))
    except Exception:  # noqa: BLE001
        return True


# ── Metrics ────────────────────────────────────────────────────────────
def compute_metrics_from_series(
    series: List[Tuple[date, float]],
) -> Dict[str, Optional[float]]:
    """Pure function — feed a sorted list of (date, close) tuples,
    return the metric bundle for the LATEST date."""
    if not series:
        return {}
    series = sorted(series, key=lambda r: r[0])
    closes = [c for _, c in series]
    dates = [d for d, _ in series]
    today_idx = len(series) - 1
    today_close = closes[today_idx]
    today_date = dates[today_idx]
    out: Dict[str, Optional[float]] = {}

    # Returns over canonical windows
    for label, days in _RETURN_WINDOWS_DAYS.items():
        target = today_date - timedelta(days=days)
        # Find the closest trading day at or before `target`
        past_close = None
        for d, c in zip(reversed(dates), reversed(closes)):
            if d <= target:
                past_close = c
                break
        if past_close and past_close > 0:
            out[f"return_{label}"] = (today_close / past_close) - 1
        else:
            out[f"return_{label}"] = None

    # Annualised volatility from daily log returns over last ~250 sessions
    log_rets: List[float] = []
    n = min(252, len(series) - 1)
    for i in range(today_idx - n + 1, today_idx + 1):
        if i <= 0:
            continue
        prev = closes[i - 1]
        cur = closes[i]
        if prev > 0 and cur > 0:
            log_rets.append(math.log(cur / prev))
    if log_rets:
        mean = sum(log_rets) / len(log_rets)
        var = sum((r - mean) ** 2 for r in log_rets) / max(1, len(log_rets) - 1)
        out["volatility"] = math.sqrt(var) * math.sqrt(252)
    else:
        out["volatility"] = None

    # Drawdown — current vs trailing peak (full series for max_drawdown,
    # trailing 5y for current_drawdown).
    peak = max(closes)
    out["max_drawdown"] = (today_close / peak) - 1 if peak > 0 else None

    five_y_cutoff = today_date - timedelta(days=365 * 5)
    recent = [(d, c) for d, c in series if d >= five_y_cutoff]
    if recent:
        recent_peak = max(c for _, c in recent)
        out["drawdown"] = (today_close / recent_peak) - 1 if recent_peak > 0 else None
    else:
        out["drawdown"] = None

    return out


async def upsert_metrics(index_name: str, on_date: date,
                          metrics: Dict[str, Any]) -> bool:
    pool = await _pool()
    if pool is None:
        return False
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO index_metrics (
                index_name, date, return_1d, return_1m, return_3m, return_6m,
                return_1y, return_3y, return_5y, volatility, drawdown, max_drawdown
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (index_name, date) DO UPDATE SET
                return_1d=EXCLUDED.return_1d, return_1m=EXCLUDED.return_1m,
                return_3m=EXCLUDED.return_3m, return_6m=EXCLUDED.return_6m,
                return_1y=EXCLUDED.return_1y, return_3y=EXCLUDED.return_3y,
                return_5y=EXCLUDED.return_5y, volatility=EXCLUDED.volatility,
                drawdown=EXCLUDED.drawdown, max_drawdown=EXCLUDED.max_drawdown,
                updated_at=NOW()
            """,
            index_name, on_date,
            metrics.get("return_1d"), metrics.get("return_1m"),
            metrics.get("return_3m"), metrics.get("return_6m"),
            metrics.get("return_1y"), metrics.get("return_3y"),
            metrics.get("return_5y"), metrics.get("volatility"),
            metrics.get("drawdown"),  metrics.get("max_drawdown"),
        )
    return True


# ── Read APIs ──────────────────────────────────────────────────────────
async def get_latest_index(index_name: str) -> Optional[Dict[str, Any]]:
    """Fast read: Redis-cached latest snapshot per index.

    Index keys are uppercase canonical (NIFTY_50, NIFTY_MIDCAP_150…). We
    normalise here so callers passing 'nifty_50' / 'Nifty_50' all hit the
    same row. Without this, the advisor `nifty_50` default silently
    missed every uppercase row in `market_index_data`.
    """
    index_name = (index_name or "").strip().upper()
    if not index_name:
        return None
    cache_key = f"benchmark:latest:{index_name}"
    try:
        from services import redis_client as _rc
        cached = await _rc.cache_get(cache_key)
        if cached:
            return cached
    except Exception:  # noqa: BLE001
        pass

    pool = await _pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT mi.index_name, mi.date, mi.close, mi.open, mi.high, mi.low, mi.volume,
                   m.return_1d, m.return_1m, m.return_3m, m.return_6m,
                   m.return_1y, m.return_3y, m.return_5y,
                   m.volatility, m.drawdown, m.max_drawdown
            FROM market_index_data mi
            LEFT JOIN index_metrics m ON m.index_name=mi.index_name AND m.date=mi.date
            WHERE mi.index_name=$1
            ORDER BY mi.date DESC LIMIT 1
            """, index_name,
        )
    if not row:
        return None
    out = {
        "index": row["index_name"],
        "date": row["date"].isoformat() if row["date"] else None,
        "close": float(row["close"]),
        "open":  float(row["open"])  if row["open"]  is not None else None,
        "high":  float(row["high"])  if row["high"]  is not None else None,
        "low":   float(row["low"])   if row["low"]   is not None else None,
        "volume": int(row["volume"] or 0),
        "metrics": {
            k: float(row[k]) if row[k] is not None else None
            for k in ("return_1d", "return_1m", "return_3m", "return_6m",
                      "return_1y", "return_3y", "return_5y",
                      "volatility", "drawdown", "max_drawdown")
        },
    }
    try:
        from services import redis_client as _rc
        await _rc.cache_set(cache_key, out, ttl_s=_LATEST_CACHE_TTL_S)
    except Exception:  # noqa: BLE001
        pass
    return out


async def get_history(index_name: str, period: str = "1Y",
                       limit: int = 1500) -> List[Dict[str, Any]]:
    """Return OHLC history for the given period. `period` is a string
    like '1M' / '3M' / '6M' / '1Y' / '3Y' / '5Y' / 'MAX'."""
    index_name = (index_name or "").strip().upper()
    pool = await _pool()
    if pool is None or not index_name:
        return []
    days = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365, "3Y": 365 * 3,
            "5Y": 365 * 5, "MAX": 365 * 30}.get((period or "1Y").upper(), 365)
    cutoff = date.today() - timedelta(days=days)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date, open, high, low, close, volume
            FROM market_index_data
            WHERE index_name=$1 AND date >= $2
            ORDER BY date ASC LIMIT $3
            """,
            index_name, cutoff, limit,
        )
    return [{
        "date": r["date"].isoformat(),
        "open": float(r["open"]) if r["open"] is not None else None,
        "high": float(r["high"]) if r["high"] is not None else None,
        "low":  float(r["low"])  if r["low"]  is not None else None,
        "close": float(r["close"]),
        "volume": int(r["volume"] or 0),
    } for r in rows]


async def get_benchmark_for_category(category: str) -> Optional[str]:
    """Look up the configured benchmark index for a fund category."""
    if not category:
        return None
    cache_key = f"benchmark:map:{category.strip().lower()}"
    try:
        from services import redis_client as _rc
        cached = await _rc.cache_get(cache_key)
        if cached:
            return cached if isinstance(cached, str) else cached.get("benchmark")
    except Exception:  # noqa: BLE001
        pass
    pool = await _pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT benchmark_index FROM fund_benchmark_map WHERE LOWER(fund_category)=LOWER($1)",
            category.strip(),
        )
    bench = row["benchmark_index"] if row else None
    if bench:
        try:
            from services import redis_client as _rc
            await _rc.cache_set(cache_key, bench, ttl_s=_BENCHMARK_MAP_CACHE_TTL_S)
        except Exception:  # noqa: BLE001
            pass
    return bench


# ── Daily refresh job ──────────────────────────────────────────────────
async def refresh_index(index_name: str, period: str = "5y") -> Dict[str, Any]:
    """End-to-end pipeline for one index: fetch → upsert OHLC → compute
    metrics → upsert metrics → invalidate cache. Returns a stats dict."""
    index_name = (index_name or "").strip().upper()
    if not index_name:
        return {"index": "", "ok": False, "reason": "empty_name"}
    rows = _fetch_yfinance_history(index_name, period=period)
    if not rows:
        return {"index": index_name, "ok": False, "reason": "no_yfinance_data"}
    n_written = await upsert_index_data(rows)
    series = [(r["date"], r["close"]) for r in rows]
    metrics = compute_metrics_from_series(series)
    on_date = max(r["date"] for r in rows)
    await upsert_metrics(index_name, on_date, metrics)
    # Bust cache
    try:
        from services import redis_client as _rc
        await _rc.cache_del(f"benchmark:latest:{index_name}")
    except Exception:  # noqa: BLE001
        pass
    return {
        "index": index_name, "ok": True,
        "rows_written": n_written, "as_of": on_date.isoformat(),
        "return_1y": metrics.get("return_1y"),
        "volatility": metrics.get("volatility"),
        "drawdown": metrics.get("drawdown"),
    }


# PRD §1: these four indices MUST refresh successfully every day —
# they back the four core fund-category → benchmark pairings. The
# daily cron logs a WARNING if any of them returns ok=False.
_CORE_INDICES = (
    "NIFTY_50",
    "NIFTY_MIDCAP_150",
    "NIFTY_SMALLCAP_250",
    "NIFTY_500",
    "SENSEX",
    "NIFTY_MIDCAP_100",
)


async def refresh_all() -> List[Dict[str, Any]]:
    """Refresh every index in `_YF_TICKERS` — core PRD indices first,
    so a downstream failure on a peripheral ticker doesn't block them.
    Logs a WARNING when any core index fails."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    # 1) Core four — always run first
    for idx in _CORE_INDICES:
        seen.add(idx)
        try:
            res = await refresh_index(idx)
        except Exception as e:  # noqa: BLE001
            logger.exception("benchmark refresh failed for core index %s", idx)
            res = {"index": idx, "ok": False, "reason": str(e)[:200]}
        out.append(res)
        if not res.get("ok"):
            logger.warning("benchmark CORE refresh FAILED for %s: %s",
                            idx, res.get("reason"))
    # 2) Remaining indices — best-effort
    for idx in _YF_TICKERS.keys():
        if idx in seen:
            continue
        try:
            out.append(await refresh_index(idx))
        except Exception as e:  # noqa: BLE001
            logger.exception("benchmark refresh failed for %s", idx)
            out.append({"index": idx, "ok": False, "reason": str(e)[:200]})
    n_core_ok = sum(1 for r in out if r.get("index") in _CORE_INDICES and r.get("ok"))
    logger.info("benchmark refresh: core %d/4 OK · total %d/%d OK",
                n_core_ok, sum(1 for r in out if r.get("ok")), len(out))
    return out


# ── Migration runner (idempotent) ──────────────────────────────────────
async def ensure_schema() -> None:
    """Run migrations/014_benchmark_index.sql on startup if PG is up.
    Idempotent — ON CONFLICT clauses make re-runs safe."""
    pool = await _pool()
    if pool is None:
        return
    import os
    sql_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                              "migrations", "014_benchmark_index.sql")
    if not os.path.exists(sql_path):
        return
    sql = open(sql_path).read()
    async with pool.acquire() as conn:
        try:
            await conn.execute(sql)
        except Exception as e:  # noqa: BLE001
            logger.warning("benchmark schema apply failed: %s", e)
