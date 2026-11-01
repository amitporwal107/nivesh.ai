"""Quick Hedge inputs, all read on the server (a client value for any of these is never read):

    portfolio   the user's holdings split into HEDGEABLE (direct equity, equity mutual funds, equity-index ETFs) and
                EXCLUDED (hybrid, debt, gold, other, unclassified) with the value of each excluded bucket, so nothing
                is silently dropped. Fund category comes from the fund primitives (the holding rows carry none).
    beta        value-weighted beta_1y of the hedgeable holdings that have one. Fewer than BETA_MIN_COVERAGE of the
                hedgeable value covered -> no beta, so no hedge is sized on a guess.
    fit         R-squared of the portfolio's daily returns against Nifty 50 over the last FIT_WINDOW sessions, from
                the price / NAV history of the largest hedgeable holdings (at most FIT_MAX_SERIES, covering at least
                FIT_MIN_COVERAGE of the hedgeable value). Unknown when it cannot be measured; never defaulted.
    market      Nifty's last close, exchange lot, listed expiries and the puts that TRADED on the bhavcopy day with open
                interest of at least MIN_PUT_OI, for the expiry nearest the chosen tenor (routes/fno.py helpers).

THRESHOLDS ARE PLACEHOLDERS to calibrate on real portfolios: BETA_MIN_COVERAGE, FIT_MIN_COVERAGE, MIN_PUT_OI.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

TENOR_DAYS = {"1w": 7, "2w": 14, "1m": 30, "3m": 90}
MAX_TENOR_DAYS = 100
MIN_TENOR_DAYS = 2
MIN_PUT_OI = 500
BETA_MIN_COVERAGE = 0.8
FIT_MIN_COVERAGE = 0.7
FIT_MAX_SERIES = 30
FIT_MIN_OBS = 120
FIT_WINDOW = 252
FETCH_CONCURRENCY = 6
NIFTY_INDEX = "Nifty 50"
EXCLUDED = ("hybrid", "debt", "gold", "overseas", "other", "unclassified")
_INDEXLIKE = ("index", "nifty", "sensex", "equity")
_OVERSEAS = ("overseas", "nyse", "nasdaq", "fang", "s&p 500", "international", "global x")   # Nifty does not hedge these
_DEBTLIKE = ("liquid", "overnight", "1d rate")


def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _is_isin(s: str) -> bool:
    return len(s) == 12 and s[:2].upper() == "IN" and s[-1].isdigit()      # 2 letters, 9 alphanumerics, a check digit


def stock_symbol(h: Dict[str, Any]) -> Optional[str]:
    """The NSE symbol of a direct equity holding. The holding's `ticker` is often an ISIN, which is not a symbol."""
    for key in ("nse_symbol", "symbol", "ticker"):
        v = str(h.get(key) or "").strip().upper()
        if v and not _is_isin(v):
            return v
    return None


def fund_bucket(prim: Optional[Dict[str, Any]], asset_type: str) -> str:
    """equity | hybrid | debt | gold | overseas | other | unclassified, from the fund primitives' category."""
    if not prim:
        return "unclassified"
    cat = str(prim.get("category") or "").lower()
    sub = str(prim.get("sub_category") or "").lower()
    name = str(prim.get("scheme_name") or "").lower()
    if "gold" in sub or "gold" in cat or "silver" in sub:
        return "gold"
    if any(w in f"{cat} {sub} {name}" for w in _OVERSEAS):
        return "overseas"
    if any(w in f"{sub} {name}" for w in _DEBTLIKE):
        return "debt"
    if cat.startswith("equity"):
        return "equity"
    if "exchange traded" in cat or asset_type == "etf":
        return "equity" if any(w in sub for w in _INDEXLIKE) else "unclassified"
    if cat.startswith("hybrid"):
        return "hybrid"
    if "debt" in cat or "income" in cat or "liquid" in cat:
        return "debt"
    return "other"


def build_portfolio(holdings: Sequence[Dict[str, Any]], stock_prims: Dict[str, Dict[str, Any]],
                    mf_prims: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Pure: holdings + primitives -> value split, hedgeable holdings and the value-weighted beta."""
    total = 0.0
    excluded = {k: 0.0 for k in EXCLUDED}
    hedgeable: List[Dict[str, Any]] = []
    for h in holdings:
        value = (_num(h.get("quantity")) or 0.0) * (_num(h.get("current_price")) or 0.0)
        if value <= 0:
            continue
        total += value
        atype = str(h.get("asset_type") or "").lower()
        if atype in ("equity", "stock"):
            sym = stock_symbol(h)
            prim = stock_prims.get(sym) if sym else None
            if sym is None:
                excluded["unclassified"] += value
                continue
            hedgeable.append({"kind": "stock", "key": sym, "name": h.get("name") or sym, "value_rs": value,
                              "beta": _num((prim or {}).get("beta_1y"))})
        elif atype in ("mutual_fund", "etf"):
            prim = mf_prims.get(str(h.get("ticker") or ""))
            bucket = fund_bucket(prim, atype)
            if bucket == "equity":
                hedgeable.append({"kind": "fund", "key": str(h.get("ticker")), "scheme_code": (prim or {}).get("scheme_code"),
                                  "name": h.get("name") or h.get("ticker"), "value_rs": value,
                                  "beta": _num((prim or {}).get("beta_1y"))})
            else:
                excluded[bucket] += value
        elif atype == "gold":
            excluded["gold"] += value
        else:
            excluded["other"] += value
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}      # the same instrument in several rows or folios is one position
    for x in hedgeable:
        cur = merged.get((x["kind"], x["key"]))
        if cur is None:
            merged[(x["kind"], x["key"])] = dict(x)
        else:
            cur["value_rs"] += x["value_rs"]
    hedgeable = list(merged.values())
    hv = sum(x["value_rs"] for x in hedgeable)
    covered = [x for x in hedgeable if x["beta"] is not None]
    cov_value = sum(x["value_rs"] for x in covered)
    coverage = cov_value / hv if hv > 0 else 0.0
    beta = sum(x["beta"] * x["value_rs"] for x in covered) / cov_value if cov_value > 0 and coverage >= BETA_MIN_COVERAGE else None
    reasons: List[Dict[str, str]] = []
    if hv <= 0:
        reasons.append({"code": "missing_portfolio", "message": "There are no equity-linked holdings to hedge."})
    elif beta is None:
        reasons.append({"code": "beta_coverage_low", "message":
                        f"Beta is known for only {coverage:.0%} of your equity-linked value (at least {BETA_MIN_COVERAGE:.0%} is needed), so no hedge is sized."})
    stamps = [str(h.get("uploaded_at") or h.get("created_at") or "")[:10] for h in holdings]
    return {"portfolio_value_rs": total, "hedgeable_value_rs": hv, "excluded_rs": excluded, "holdings": hedgeable,
            "beta": beta, "beta_coverage": coverage, "reasons": reasons, "as_of": max((s for s in stamps if s), default=None)}


# ── fit to Nifty (pure) ─────────────────────────────────────────────────────────────────────────────────────────
def _ffill(series: Sequence[Tuple[str, float]], grid: Sequence[str]) -> List[Optional[float]]:
    """Each grid day's last known value on or before it; None until the series first has a value."""
    out: List[Optional[float]] = []
    pts = sorted(series)
    i, last = 0, None
    for d in grid:
        while i < len(pts) and pts[i][0] <= d:
            last = pts[i][1]
            i += 1
        out.append(last)
    return out


def fit_to_nifty(series: Dict[str, Sequence[Tuple[str, float]]], weights: Dict[str, float],
                 nifty: Sequence[Tuple[str, float]], total_weight: Optional[float] = None, window: int = FIT_WINDOW) -> Dict[str, Any]:
    """R-squared (and correlation, regression beta) of the weighted portfolio's daily returns against Nifty over the last
    `window` Nifty sessions. `weights` are rupee values; `total_weight` is the whole hedgeable value for the coverage share."""
    out: Dict[str, Any] = {"r2": None, "correlation": None, "regression_beta": None, "observations": 0, "coverage": 0.0,
                           "series_used": 0, "window_start": None, "window_end": None, "reason": None}
    grid_all = [d for d, _ in sorted(nifty)]
    close = dict(nifty)
    grid = grid_all[-(window + 1):]
    if len(grid) < FIT_MIN_OBS + 1:
        out["reason"] = {"code": "fit_history_short", "message": "Not enough Nifty history to measure the fit."}
        return out
    cols: Dict[str, List[float]] = {}
    for key, pts in series.items():
        filled = _ffill(pts, grid)
        if filled[0] is None or any(v is None or v <= 0 for v in filled):
            continue                                  # history does not span the window: left out, counted in coverage
        cols[key] = [filled[i] / filled[i - 1] - 1.0 for i in range(1, len(filled))]
    wsum = sum(weights[k] for k in cols)
    tw = total_weight if total_weight else sum(weights.values())
    out["coverage"] = wsum / tw if tw else 0.0
    out["series_used"] = len(cols)
    if wsum <= 0 or out["coverage"] < FIT_MIN_COVERAGE:
        out["reason"] = {"code": "fit_coverage_low", "message":
                         f"Price history covers only {out['coverage']:.0%} of your equity-linked value (at least {FIT_MIN_COVERAGE:.0%} is needed) to measure the fit to Nifty."}
        return out
    rm = [close[grid[i]] / close[grid[i - 1]] - 1.0 for i in range(1, len(grid))]
    rp = [sum(weights[k] * cols[k][t] for k in cols) / wsum for t in range(len(rm))]
    n = len(rm)
    mp, mm = sum(rp) / n, sum(rm) / n
    cov = sum((a - mp) * (b - mm) for a, b in zip(rp, rm)) / (n - 1)
    vp = sum((a - mp) ** 2 for a in rp) / (n - 1)
    vm = sum((b - mm) ** 2 for b in rm) / (n - 1)
    out.update(observations=n, window_start=grid[0], window_end=grid[-1])
    if vp <= 0 or vm <= 0:
        out["reason"] = {"code": "fit_flat_series", "message": "The return series were flat, so the fit could not be measured."}
        return out
    corr = cov / math.sqrt(vp * vm)
    out.update(correlation=corr, r2=corr * corr, regression_beta=cov / vm)
    return out


# ── readers (I/O) ───────────────────────────────────────────────────────────────────────────────────────────────
async def load_portfolio(db, user_id: str) -> Dict[str, Any]:
    from services.copilot_tools import daas_client as daas
    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0, "name": 1, "ticker": 1, "isin": 1, "nse_symbol": 1,
                                                              "symbol": 1, "asset_type": 1, "quantity": 1, "current_price": 1,
                                                              "uploaded_at": 1, "created_at": 1}).to_list(2000)
    if not holdings:
        from services.pi_bridge import pi_holdings_for_user
        holdings = await pi_holdings_for_user(user_id)
    syms = sorted({s for s in (stock_symbol(h) for h in holdings if str(h.get("asset_type") or "").lower() in ("equity", "stock")) if s})
    isins = sorted({str(h["ticker"]) for h in holdings if str(h.get("asset_type") or "").lower() in ("mutual_fund", "etf") and h.get("ticker")})
    stock_prims, mf_prims = await asyncio.gather(
        daas.get_v3_stock_primitives_bulk(syms) if syms else _empty(),
        daas.get_v3_mf_primitives_bulk(isins) if isins else _empty())
    return build_portfolio(holdings, stock_prims or {}, mf_prims or {})


async def _empty() -> Dict[str, Any]:
    return {}


async def load_fit(portfolio: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
    """Measure the portfolio's fit to Nifty from the largest hedgeable holdings' price / NAV history."""
    from routes import research_chart
    from services.copilot_tools import daas_client as daas
    top = sorted(portfolio["holdings"], key=lambda x: -x["value_rs"])[:FIT_MAX_SERIES]
    start = ((today or date.today()) - timedelta(days=FIT_WINDOW * 2)).isoformat()
    sem = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def one(h: Dict[str, Any]) -> Tuple[str, List[Tuple[str, float]]]:
        async with sem:
            try:
                if h["kind"] == "stock":
                    bars = await research_chart._live_bars(h["key"])
                    pts = [(str(b[0])[:10], float(b[4])) for b in bars if len(b) > 4 and _num(b[4])]
                else:
                    rows = await daas.get_mf_nav_history(str(h.get("scheme_code") or ""), start=start)
                    pts = [(str(r.get("nav_date"))[:10], float(r["nav"])) for r in rows if _num(r.get("nav"))]
            except Exception as e:  # noqa: BLE001 — one name failing lowers coverage; it never stops the fit
                logger.warning("quick_hedge fit: %s unavailable (%s)", h.get("key"), type(e).__name__)
                pts = []
            return h["key"], pts

    results, nifty_rows = await asyncio.gather(asyncio.gather(*[one(h) for h in top]),
                                               daas.get_index_eod_history(NIFTY_INDEX, start=start))
    nifty = [(str(r.get("as_of_date"))[:10], float(r["close_price"])) for r in nifty_rows if _num(r.get("close_price"))]
    return fit_to_nifty({k: v for k, v in results if v}, {h["key"]: h["value_rs"] for h in top}, nifty,
                        total_weight=portfolio["hedgeable_value_rs"])


def choose_expiry(expiries: Sequence[Dict[str, Any]], tenor: str) -> Optional[Dict[str, Any]]:
    """The listed expiry nearest the tenor's target days, within [MIN_TENOR_DAYS, MAX_TENOR_DAYS]; ties go to the nearer one."""
    target = TENOR_DAYS.get(tenor)
    if target is None:
        return None
    ok = [e for e in expiries if MIN_TENOR_DAYS <= int(e.get("days_to_expiry") or 0) <= MAX_TENOR_DAYS]
    return min(ok, key=lambda e: (abs(e["days_to_expiry"] - target), e["days_to_expiry"])) if ok else None


def traded_puts(strikes: Sequence[Dict[str, Any]], min_oi: int = MIN_PUT_OI) -> Dict[float, float]:
    """{strike: close} for the puts that traded on the day and carry open interest of at least `min_oi`."""
    out: Dict[float, float] = {}
    for row in strikes:
        put = row.get("put")
        if put and _num(put.get("close")) and (put.get("oi") or 0) >= min_oi:
            out[float(row["strike"])] = float(put["close"])
    return out


async def nifty_market(tenor: str) -> Dict[str, Any]:
    """Nifty's close, lot, the chosen expiry and its traded puts, or {ok: False, reason}."""
    from fastapi import HTTPException
    from routes import fno
    from services import market_freshness

    def fail(code: str, message: str) -> Dict[str, Any]:
        return {"ok": False, "reason": {"code": code, "message": message}}

    try:
        w = await market_freshness.window()
        as_of, expiries = await fno._current_expiries("NIFTY", w)
        pick = choose_expiry(expiries, tenor)
        if pick is None:
            return fail("no_listed_expiry", "No Nifty option expiry is listed for that protection period.")
        body = await fno._daas("/fno/NIFTY/chain", {"expiry": pick["expiry"]}, "NIFTY")
        fno.require_current("NIFTY", fno._iso_day(body.get("as_of")), w)
    except HTTPException as e:
        return fail("market_data_unavailable", str(e.detail))
    raw = body.get("strikes")
    sides = [item.get(s) for item in raw if isinstance(item, dict) for s in ("CE", "PE")] if isinstance(raw, list) else []
    strikes = fno.shape_strikes(raw)
    return {"ok": True, "as_of": fno._iso_day(body.get("as_of")), "spot": fno.find_spot(sides), "lot": fno.find_lot_size(sides),
            "expiry": pick["expiry"], "days_to_expiry": pick["days_to_expiry"], "tenor": tenor,
            "expiries": [e["expiry"] for e in expiries], "puts": traded_puts(strikes),
            "source": "NSE F&O bhavcopy via the data platform (end of day)"}
