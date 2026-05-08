"""Market Dashboard — the gating-layer the user's BTST framework calls for.

Aggregates:
  • Nifty close + 1d change + trend (SMA 20)
  • Breadth: % above 20EMA, % above 50EMA, advance/decline ratio,
    new 52-week highs / lows
  • Sector heatmap: per-sector mean 5d return, RS vs Nifty, hot/warm/
    cool/cold tone, leader stock per sector
  • Macro overlay: latest macro_state risk + multiplier (passthrough)

… and produces a single 4-bucket deploy verdict so the UI can show
"deploy aggressively / normally / cautiously / defensively" without
the user reading a wall of numbers.

All inputs are existing tables (`stock_ohlcv`, `stock_master`,
`macro_state`) — no extra data feed required for v1.

The function is intentionally single-pass + single SQL round-trip per
asset; intended for a 60-second cache on the route, not real-time.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from services import pg_client

from . import sector_strength

logger = logging.getLogger(__name__)


# ── Verdict policy ──────────────────────────────────────────────────────
def _deploy_verdict(*,
                    macro_risk: Optional[str],
                    breadth_20: Optional[float],
                    breadth_50: Optional[float],
                    nifty_trend: str,
                    hot_sectors: int) -> Dict[str, str]:
    """Return {verdict, reason}.

    Hierarchy: macro risk first (regime gate), then breadth, then trend.
    """
    risk = (macro_risk or "").upper()
    if risk == "HIGH":
        return {
            "verdict": "DEFENSIVE",
            "reason": "Macro risk HIGH — keep cash, hedge longs, avoid new positions",
        }
    if risk == "MEDIUM":
        return {
            "verdict": "CAUTIOUS",
            "reason": "Macro risk MEDIUM — half size, only highest-conviction setups",
        }

    # Macro is LOW or unavailable. Use breadth + trend.
    b20 = breadth_20 or 0.0
    if nifty_trend == "DOWN":
        return {
            "verdict": "CAUTIOUS",
            "reason": f"Nifty below 20-DMA · breadth {b20:.0f}% — no aggressive entries",
        }
    if b20 >= 65.0 and hot_sectors >= 2:
        return {
            "verdict": "AGGRESSIVE",
            "reason": f"Strong breadth {b20:.0f}% above 20EMA · {hot_sectors} sectors hot · Nifty trending up",
        }
    if b20 >= 50.0:
        return {
            "verdict": "NORMAL",
            "reason": f"Breadth {b20:.0f}% above 20EMA — selective entries, full size on A+ setups",
        }
    return {
        "verdict": "CAUTIOUS",
        "reason": f"Weak breadth ({b20:.0f}% above 20EMA) — wait for confirmation",
    }


def _sector_tone(rs_5d: Optional[float]) -> str:
    """RS in pp vs Nifty 5d → tone bucket."""
    if rs_5d is None:
        return "COOL"
    if rs_5d >= 3.0:
        return "HOT"
    if rs_5d >= 1.0:
        return "WARM"
    if rs_5d >= -1.0:
        return "COOL"
    return "COLD"


# ── Main builder ────────────────────────────────────────────────────────
async def build(target_date: Optional[date] = None) -> Dict[str, Any]:
    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no_pg_pool"}

    async with pool.acquire() as conn:
        if target_date is None:
            row = await conn.fetchrow("SELECT MAX(bar_date) AS d FROM stock_ohlcv")
            target_date = row["d"] if row else None
        if target_date is None:
            return {"ok": False, "error": "no_ohlcv"}

        # Latest 80 bars per symbol — enough for SMA20/50 + 5d return.
        rows = await conn.fetch(
            """
            SELECT o.nse_symbol, o.bar_date,
                   o.close_price AS close,
                   o.high_price  AS high,
                   o.low_price   AS low,
                   o.volume,
                   sm.sector
            FROM stock_ohlcv o
            LEFT JOIN stock_master sm ON sm.nse_symbol = o.nse_symbol
            WHERE o.bar_date <= $1
              AND o.bar_date > $1 - INTERVAL '80 days'
            ORDER BY o.nse_symbol, o.bar_date ASC
            """,
            target_date,
        )

    by_sym: Dict[str, List[dict]] = {}
    sector_by_sym: Dict[str, Optional[str]] = {}
    for r in rows:
        sym = r["nse_symbol"]
        by_sym.setdefault(sym, []).append({
            "date":   r["bar_date"],
            "close":  float(r["close"]) if r["close"] is not None else None,
            "high":   float(r["high"]) if r["high"] is not None else None,
            "low":    float(r["low"]) if r["low"] is not None else None,
            "volume": int(r["volume"]) if r["volume"] is not None else 0,
        })
        sector_by_sym.setdefault(sym, r["sector"])

    # ── Per-symbol stats ──────────────────────────────────────────────
    above_20: List[bool] = []
    above_50: List[bool] = []
    advances: int = 0
    declines: int = 0
    new_52w_highs: int = 0
    new_52w_lows: int = 0
    sector_returns: Dict[str, List[float]] = {}
    sector_leaders: Dict[str, Dict[str, Any]] = {}

    # We need 52w highs/lows — load a wider window for that subset.
    async with pool.acquire() as conn:
        wk52_rows = await conn.fetch(
            """
            SELECT nse_symbol,
                   MAX(high_price) AS high_52w,
                   MIN(low_price)  AS low_52w
            FROM stock_ohlcv
            WHERE bar_date <= $1
              AND bar_date > $1 - INTERVAL '370 days'
            GROUP BY nse_symbol
            """,
            target_date,
        )
    wk52 = {r["nse_symbol"]: (
        float(r["high_52w"]) if r["high_52w"] else None,
        float(r["low_52w"]) if r["low_52w"] else None,
    ) for r in wk52_rows}

    for sym, bars in by_sym.items():
        if len(bars) < 21:
            continue
        closes = [b["close"] for b in bars if b["close"] is not None]
        if len(closes) < 21:
            continue
        last = closes[-1]
        prev = closes[-2]
        sma20 = sum(closes[-20:]) / 20
        sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
        ret_5d = (last / closes[-6] - 1.0) * 100 if len(closes) >= 6 else None

        above_20.append(last > sma20)
        if sma50 is not None:
            above_50.append(last > sma50)
        if last > prev:
            advances += 1
        elif last < prev:
            declines += 1

        h52, l52 = wk52.get(sym, (None, None))
        if h52 is not None and bars[-1]["high"] is not None and bars[-1]["high"] >= h52 - 0.01:
            new_52w_highs += 1
        if l52 is not None and bars[-1]["low"] is not None and bars[-1]["low"] <= l52 + 0.01:
            new_52w_lows += 1

        sec = sector_by_sym.get(sym) or "Other"
        if ret_5d is not None:
            sector_returns.setdefault(sec, []).append(ret_5d)
            cur_leader = sector_leaders.get(sec)
            if cur_leader is None or ret_5d > cur_leader["ret_5d_pct"]:
                sector_leaders[sec] = {
                    "nse_symbol": sym,
                    "ret_5d_pct": round(ret_5d, 2),
                    "close": last,
                }

    n_total = len(above_20) or 1
    pct_above_20 = round(100.0 * sum(above_20) / n_total, 1)
    pct_above_50 = round(100.0 * sum(above_50) / max(len(above_50), 1), 1) if above_50 else None
    ad_ratio = round(advances / declines, 2) if declines > 0 else None

    # ── Nifty (NIFTYBEES) ─────────────────────────────────────────────
    bench = by_sym.get(sector_strength.NIFTY_SYMBOL) or []
    nifty_close = None
    nifty_change_pct = None
    nifty_trend = "FLAT"
    bench_ret_5d = 0.0
    if len(bench) >= 21:
        nclose = [b["close"] for b in bench if b["close"] is not None]
        if len(nclose) >= 21:
            nifty_close = round(nclose[-1], 2)
            nifty_change_pct = round((nclose[-1] / nclose[-2] - 1.0) * 100, 2)
            nsma20 = sum(nclose[-20:]) / 20
            if nclose[-1] > nsma20 * 1.005:
                nifty_trend = "UP"
            elif nclose[-1] < nsma20 * 0.995:
                nifty_trend = "DOWN"
            if len(nclose) >= 6:
                bench_ret_5d = (nclose[-1] / nclose[-6] - 1.0) * 100

    # ── Sector heatmap ────────────────────────────────────────────────
    heatmap: List[Dict[str, Any]] = []
    for sec, rets in sector_returns.items():
        if not rets or sec == "Other" or len(rets) < 3:
            continue
        mean_ret = sum(rets) / len(rets)
        rs_5d = mean_ret - bench_ret_5d
        heatmap.append({
            "sector":     sec,
            "stocks":     len(rets),
            "ret_5d_pct": round(mean_ret, 2),
            "rs_5d_pp":   round(rs_5d, 2),
            "tone":       _sector_tone(rs_5d),
            "leader":     sector_leaders.get(sec),
        })
    heatmap.sort(key=lambda r: r["rs_5d_pp"], reverse=True)
    hot_sectors = sum(1 for h in heatmap if h["tone"] == "HOT")

    # ── VIX (best-effort, yfinance) ───────────────────────────────────
    vix: Dict[str, Any] = {"value": None, "trend": "UNKNOWN"}
    try:
        import yfinance as yf
        v = yf.download("^INDIAVIX", period="10d", progress=False, threads=False)
        if not v.empty and "Close" in v.columns:
            vc = v["Close"].dropna()
            if len(vc) >= 2:
                cur = float(vc.iloc[-1])
                prev = float(vc.iloc[-2])
                vix["value"] = round(cur, 2)
                vix["trend"] = "RISING" if cur > prev * 1.02 else (
                    "FALLING" if cur < prev * 0.98 else "FLAT"
                )
    except Exception as e:  # noqa: BLE001
        logger.debug("vix fetch failed: %s", e)

    # ── Macro passthrough ─────────────────────────────────────────────
    macro_risk = None
    macro_multiplier = 1.0
    try:
        from services import macro_engine
        st = await macro_engine.latest_state()
        if st:
            macro_risk = st.get("risk")
            macro_multiplier = float(st.get("multiplier") or 1.0)
    except Exception as e:  # noqa: BLE001
        logger.debug("macro state lookup failed: %s", e)

    verdict = _deploy_verdict(
        macro_risk=macro_risk,
        breadth_20=pct_above_20,
        breadth_50=pct_above_50,
        nifty_trend=nifty_trend,
        hot_sectors=hot_sectors,
    )

    # ── Live overlay (NSE allIndices) ─────────────────────────────────
    # Live values supersede the EOD-derived ones for: Nifty close + change,
    # VIX, A/D ratio, sector heatmap. Breadth (% above 20EMA), 52w highs/
    # lows, sector "stocks count + leader" stay EOD — those are structural,
    # not tickable.
    live_snapshot = None
    try:
        from . import nse_live
        live_snapshot = await nse_live.get_live_snapshot()
    except Exception as e:  # noqa: BLE001
        logger.debug("live nse snapshot failed: %s", e)

    nifty_block = {
        "close":      nifty_close,
        "change_pct": nifty_change_pct,
        "trend":      nifty_trend,
        "source":     "eod_bhavcopy",
    }
    vix_block = {**vix, "source": "yfinance"}
    sector_heatmap_out = heatmap[:14]
    ad_ratio_live = None
    is_live = False
    fetched_at = None
    nifty_trend_live = nifty_trend
    hot_sectors_live = hot_sectors

    if live_snapshot:
        is_live = bool(live_snapshot.get("is_live"))
        fetched_at = live_snapshot.get("fetched_at")
        ln = live_snapshot.get("nifty50") or {}
        if ln.get("close") is not None:
            change_pct = ln.get("change_pct") or 0.0
            nifty_trend_live = (
                "UP" if change_pct > 0.1 else
                "DOWN" if change_pct < -0.1 else "FLAT"
            )
            nifty_block = {
                "close":      ln["close"],
                "change_pct": ln.get("change_pct"),
                "trend":      nifty_trend_live,
                "source":     "nse_live",
            }
        lv = live_snapshot.get("vix") or {}
        if lv.get("value") is not None:
            vix_block = {
                "value":      lv["value"],
                "change_pct": lv.get("change_pct"),
                "trend":      lv.get("trend") or "FLAT",
                "source":     "nse_live",
            }
        if live_snapshot.get("advance_decline") is not None:
            ad_ratio_live = live_snapshot["advance_decline"]
        # Replace sector heatmap with live sectoral indices when available.
        # Keep the EOD leader-stock+stocks-count info if we can match by name.
        eod_meta = {h["sector"]: h for h in heatmap}
        live_sectors = []
        for s in (live_snapshot.get("sectors") or [])[:14]:
            name = s["sector"]
            meta = None
            for k in eod_meta:
                if k.lower() in name.lower() or name.lower() in k.lower():
                    meta = eod_meta[k]
                    break
            live_sectors.append({
                "sector":     name,
                "ret_5d_pct": s.get("change_pct"),
                "rs_5d_pp":   s.get("rs_vs_nifty_pp"),
                "tone":       s.get("tone"),
                "stocks":     (meta or {}).get("stocks"),
                "leader":     (meta or {}).get("leader"),
                "source":     "nse_live",
            })
        if live_sectors:
            sector_heatmap_out = live_sectors
            hot_sectors_live = sum(1 for s in live_sectors if s["tone"] == "HOT")

        # Recompute verdict with live data — gives an intraday-tape
        # verdict during market hours.
        verdict = _deploy_verdict(
            macro_risk=macro_risk,
            breadth_20=pct_above_20,
            breadth_50=pct_above_50,
            nifty_trend=nifty_trend_live,
            hot_sectors=hot_sectors_live,
        )

    return {
        "ok": True,
        "as_of_date": str(target_date),
        "is_live": is_live,
        "fetched_at": fetched_at,
        "deploy_verdict": verdict["verdict"],
        "verdict_reason": verdict["reason"],
        "nifty": nifty_block,
        "vix": vix_block,
        "breadth": {
            "pct_above_20ema":       pct_above_20,
            "pct_above_50ema":       pct_above_50,
            "advance_decline_ratio": ad_ratio_live if ad_ratio_live is not None else ad_ratio,
            "advances":              advances,
            "declines":              declines,
            "new_52w_highs":         new_52w_highs,
            "new_52w_lows":          new_52w_lows,
            "universe_size":         n_total,
        },
        "sector_heatmap": sector_heatmap_out,
        "macro": {
            "risk":       macro_risk,
            "multiplier": macro_multiplier,
        },
    }
