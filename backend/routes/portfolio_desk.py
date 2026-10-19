"""Smart trading desk — portfolio reads: holdings correlation, the large/mid/small-cap split and holding risk.

    GET /api/portfolio/correlation?sessions=120&limit=10   → DaaS /prices/adjusted/{symbol}, one read per stock held
    GET /api/portfolio/market-cap-split                    → DaaS /indices/{index}/constituents
    GET /api/portfolio/holding-risk?sessions=250           → DaaS /prices/adjusted/{symbol}, one read per stock held:
        liquidity and the days to sell each position, overnight gaps, and today's stocks held together over the
        window (drawdown, 1-month volatility), each level with its rule (`rules`) — PRD §8.4, backend addition B15

Holdings are the signed-in user's, read exactly as GET /api/portfolio/holdings-enriched reads them
(services.portfolio_enrichment.build_enriched_portfolio, same 5-minute cache): value = quantity × current price,
weight = share of the whole portfolio. Only direct stocks (asset type equity / stock, as the desk's frontend filters)
are used; a stock held in two accounts counts once, with its values and weights added. Funds are never correlated
or split. The warehouse is never queried from here: prices and index lists come through DaaS.

Correlation. Daily log returns of split/bonus adjusted closes (`adj_close`, nidp.prices_eod_adjusted). The session
calendar is every date any held stock has a bar on, newest `sessions + 1` dates; a return on a date needs that stock's
close on the date and on the calendar session before it, so a suspension leaves a gap rather than a multi-day return.
A stock with fewer than MIN_SESSIONS returns in the window is skipped with its reason. Each pair is Pearson over the
dates both stocks have a return (a pair under MIN_SESSIONS common dates is left out and counted in
`pairs_excluded`). `avg_corr` is the plain mean over every pair worked out, not only the `limit` returned.

Market-cap split. NSE index membership on each list's latest constituents date: Large = Nifty 100, Mid = Nifty
Midcap 150, Small = Nifty Smallcap 250, Micro = the rest of Nifty Total Market, Unclassified = in none of them.
A holding matches a list by ISIN, else by symbol. A bucket is reported only when every list that decides it is in
the warehouse; holdings that cannot be placed yet are reported together under `unsplit`, never guessed into a bucket.

Errors: DaaS not configured / unreachable / non-200 → 502 `upstream_unavailable` (correlation: only when every price
read failed; one failed read skips that stock and says so). Holdings unreadable → 503 `holdings_unavailable`.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request

from deps import get_current_user
from services import portfolio_enrichment as _pe
from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["portfolio-desk"])

EQUITY_TYPES = ("equity", "stock")
SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{1,32}$")
UNAVAILABLE = "upstream_unavailable"

# ── correlation ──────────────────────────────────────────────────────────
MIN_SESSIONS = 60
HIGH_THRESHOLD = 0.7
PRICE_READS_AT_ONCE = 6
CORR_METHOD = "Pearson correlation of daily log returns, split and bonus adjusted closes"
CORR_SOURCE = "nidp.prices_eod_adjusted via DaaS"

# ── market-cap split ─────────────────────────────────────────────────────
# (bucket, NSE index whose membership places a holding in it), in the order a holding is tested.
CAP_LISTS: Tuple[Tuple[str, str], ...] = (
    ("large", "Nifty 100"),
    ("mid", "Nifty Midcap 150"),
    ("small", "Nifty Smallcap 250"),
    ("micro", "Nifty Total Market"),
)
CONSTITUENTS_LIMIT = 1000          # Nifty Total Market is ~750 names
CAP_METHOD = ("NSE index membership: Large = Nifty 100, Mid = Nifty Midcap 150, Small = Nifty Smallcap 250, "
              "Micro = rest of Nifty Total Market, Unclassified = in none of them")
CAP_SOURCE = ("Holdings and values as in /api/portfolio/holdings-enriched; index membership from "
              "nidp.index_constituents (NSE index lists) via DaaS")
FUNDS_NOTE = "Mutual funds, ETFs and other non-stock holdings are not split by market cap"

# ── holding risk (B15) ───────────────────────────────────────────────────
# Every rule the levels use, in one place, returned with the answer so the screen shows the rule beside the level.
ADV_SESSIONS = 20
SHORT_VOL_SESSIONS = 21
TRADING_DAYS = 252
LIQUIDITY_RULE = {
    "min_adv_cr": 10.0,           # the desk's liquidity threshold (scanner "Liquid only": ₹10 Cr a day)
    "adv_sessions": ADV_SESSIONS,
    "participation_pct": 10.0,    # a position is sold at no more than this share of the average daily volume
    "days_low": 1.0,
    "days_high": 5.0,
    "text": ("Average traded value (close × volume) over the last 20 sessions, and the days to sell the position at "
             "10% of the average daily volume. High: a holding needs more than 5 days. Medium: a holding needs more "
             "than 1 day, or trades under ₹10 Cr a day. Low: otherwise."),
}
GAP_RULE = {
    "gap_pct": 2.0,
    "low_below_pct": 5.0,
    "high_above_pct": 15.0,
    "text": ("An overnight gap is a session that opened 2% or more away from the previous close (split-adjusted). "
             "Rate = the share of sessions with one, value-weighted over the stocks. Low under 5%, medium 5–15%, "
             "high above 15%."),
}
VOL_RULE = {
    "bands_pct": [10.0, 18.0, 28.0],
    "sessions": SHORT_VOL_SESSIONS,
    "text": ("Annualised standard deviation of the daily returns of today's stocks held together over the last 21 "
             "sessions. Low under 10%, medium under 18%, high under 28%, very high above (the bands of the overall "
             "risk rating)."),
}
DRAWDOWN_RULE = {
    "low_above_pct": -10.0,
    "high_below_pct": -20.0,
    "text": ("The largest fall from a peak in the value of today's stocks held together over the window "
             "(split-adjusted closes, today's quantities). Low above −10%, medium −10% to −20%, high below −20%."),
}
HOLDING_RISK_METHOD = ("Per stock held: split-adjusted daily bars (nidp.prices_eod_adjusted via DaaS). Today's stocks "
                       "held together: today's value of each stock carried back on its adjusted closes, on the dates "
                       "every included stock has a close. A stock whose last bar is older than the newest is left "
                       "out of the series and listed as stale; nothing is filled in.")


# ── holdings (shared) ────────────────────────────────────────────────────
async def _holdings(user_id: str) -> List[Dict[str, Any]]:
    """Every holding row of the signed-in user, exactly as /api/portfolio/holdings-enriched builds it."""
    try:
        payload = await _pe.build_enriched_portfolio(user_id)
    except Exception as e:  # noqa: BLE001 — Mongo / enrichment failure: say so, never an empty portfolio
        logger.exception("portfolio desk: holdings read failed for %s: %s", user_id, e)
        raise HTTPException(status_code=503, detail="holdings_unavailable")
    rows = payload.get("holdings") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        logger.warning("portfolio desk: holdings payload had no list for %s", user_id)
        raise HTTPException(status_code=503, detail="holdings_unavailable")
    return [r for r in rows if isinstance(r, dict)]


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def split_holdings(holdings: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(direct stocks merged into one position per stock, every other holding).

    Merge key is the NSE symbol, else the ISIN, else the holding id. A merged position's value and weight are sums;
    a weight is null when any part has none (never a partial sum presented as the whole)."""
    positions: Dict[str, Dict[str, Any]] = {}
    others: List[Dict[str, Any]] = []
    for h in holdings:
        if str(h.get("asset_type") or "").strip().lower() not in EQUITY_TYPES:
            others.append(h)
            continue
        sym = str(h.get("nse_symbol") or "").strip().upper() or None
        isin = str(h.get("isin") or "").strip().upper() or None
        key = sym or isin or f"id:{h.get('holding_id')}"
        value, weight, qty = _num(h.get("value_rs")), _num(h.get("weight_pct")), _num(h.get("quantity"))
        p = positions.get(key)
        if p is None:
            positions[key] = {"symbol": sym, "isin": isin, "name": h.get("name"),
                              "value_rs": value, "weight_pct": weight, "quantity": qty}
            continue
        p["isin"] = p["isin"] or isin
        p["value_rs"] = None if p["value_rs"] is None or value is None else p["value_rs"] + value
        p["weight_pct"] = None if p["weight_pct"] is None or weight is None else p["weight_pct"] + weight
        p["quantity"] = None if p["quantity"] is None or qty is None else p["quantity"] + qty
    return list(positions.values()), others


def _label(p: Dict[str, Any]) -> str:
    return p.get("symbol") or p.get("isin") or str(p.get("name") or "unknown holding")


# ── correlation maths (pure) ─────────────────────────────────────────────
def session_calendar(closes: Dict[str, Dict[str, float]], sessions: int) -> List[str]:
    """The newest `sessions + 1` dates any series has a bar on, oldest first."""
    days = sorted({d for series in closes.values() for d in series})
    return days[-(sessions + 1):]


def log_returns(series: Dict[str, float], calendar: List[str]) -> Dict[str, float]:
    """date → ln(close / previous calendar session's close), only where both closes exist and are positive."""
    out: Dict[str, float] = {}
    for prev, day in zip(calendar, calendar[1:]):
        a, b = series.get(prev), series.get(day)
        if a is not None and b is not None and a > 0 and b > 0:
            out[day] = math.log(b / a)
    return out


def pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    """Pearson correlation; None when either side does not vary (undefined, not zero)."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))


def correlate(closes: Dict[str, Dict[str, float]], sessions: int,
              min_sessions: int = MIN_SESSIONS) -> Dict[str, Any]:
    """Pairwise correlations over the window. `closes`: symbol → {YYYY-MM-DD: adjusted close}.

    Returns {as_of, used: [symbols], skipped: [{symbol, reason}], pairs: [{a, b, corr, common_sessions}] at full
    precision sorted by corr desc, pairs_excluded}."""
    calendar = session_calendar(closes, sessions)
    returns: Dict[str, Dict[str, float]] = {}
    skipped: List[Dict[str, str]] = []
    for sym in sorted(closes):
        if not closes[sym]:
            skipped.append({"symbol": sym, "reason": "no adjusted prices at the data platform"})
            continue
        r = log_returns(closes[sym], calendar)
        if len(r) < min_sessions:
            skipped.append({"symbol": sym, "reason": f"fewer than {min_sessions} sessions of prices "
                                                     f"({len(r)} in the last {sessions})"})
            continue
        if len(set(r.values())) < 2:
            skipped.append({"symbol": sym, "reason": "price did not change in the window"})
            continue
        returns[sym] = r
    used = sorted(returns)
    pairs: List[Dict[str, Any]] = []
    excluded = 0
    for i, a in enumerate(used):
        for b in used[i + 1:]:
            common = sorted(returns[a].keys() & returns[b].keys())
            c = (pearson([returns[a][d] for d in common], [returns[b][d] for d in common])
                 if len(common) >= min_sessions else None)
            if c is None:
                excluded += 1
                continue
            pairs.append({"a": a, "b": b, "corr": c, "common_sessions": len(common)})
    pairs.sort(key=lambda p: (-p["corr"], p["a"], p["b"]))
    return {"as_of": calendar[-1] if calendar else None, "used": used, "skipped": skipped,
            "pairs": pairs, "pairs_excluded": excluded}


# ── market-cap maths (pure) ──────────────────────────────────────────────
def membership(rows: List[Dict[str, Any]]) -> Dict[str, set]:
    """ISINs and symbols of one index list's member rows."""
    return {"isin": {str(r["isin"]).strip().upper() for r in rows if r.get("isin")},
            "symbol": {str(r["symbol"]).strip().upper() for r in rows if r.get("symbol")}}


def _is_member(p: Dict[str, Any], m: Dict[str, set]) -> bool:
    return bool((p.get("isin") and p["isin"] in m["isin"]) or (p.get("symbol") and p["symbol"] in m["symbol"]))


def split_by_cap(stocks: List[Dict[str, Any]], lists: Dict[str, Optional[Dict[str, set]]]) -> Dict[str, Any]:
    """Place each stock position in a bucket. `lists`: bucket → membership(), or None when that index list is not in
    the warehouse. A stock goes to the first bucket whose list holds it, but only while every list tested before it is
    available; otherwise it goes to `unsplit`. Returns {total_value_rs, available, buckets, unsplit (None when every
    list is available)}."""
    order = [b for b, _ in CAP_LISTS]
    placed: Dict[str, List[Dict[str, Any]]] = {b: [] for b in order + ["unclassified", "unsplit"]}
    for p in stocks:
        target = "unclassified"
        for bucket in order:
            m = lists.get(bucket)
            if m is None:
                target = "unsplit"
                break
            if _is_member(p, m):
                target = bucket
                break
        placed[target].append(p)
    total = sum(p["value_rs"] or 0.0 for p in stocks)

    def figures(members: List[Dict[str, Any]]) -> Dict[str, Any]:
        value = sum(p["value_rs"] or 0.0 for p in members)
        members = sorted(members, key=lambda p: -(p["value_rs"] or 0.0))
        return {"value_rs": round(value, 2), "weight_pct": round(value / total * 100, 2) if total > 0 else None,
                "count": len(members), "symbols": [_label(p) for p in members]}

    buckets: List[Dict[str, Any]] = []
    for i, name in enumerate(order + ["unclassified"]):
        absent = [idx for b, idx in CAP_LISTS[: i + 1] if lists.get(b) is None]
        if absent:
            buckets.append({"bucket": name, "available": False, "value_rs": None, "weight_pct": None,
                            "count": None, "symbols": None,
                            "reason": f"{', '.join(absent)} constituents are not in the warehouse yet"})
        else:
            buckets.append({"bucket": name, "available": True, **figures(placed[name])})
    missing = [idx for b, idx in CAP_LISTS if lists.get(b) is None]
    unsplit = None
    if missing:
        unsplit = {**figures(placed["unsplit"]),
                   "reason": (f"{', '.join(missing)} constituents are not in the warehouse yet, so these holdings "
                              "cannot be placed in a bucket")}
    return {"total_value_rs": round(total, 2), "available": not missing, "buckets": buckets, "unsplit": unsplit}


# ── holding-risk maths (pure) ────────────────────────────────────────────
def gap_stats(opens: Dict[str, float], closes: Dict[str, float], calendar: List[str], gap_pct: float) -> Dict[str, Any]:
    """Overnight gaps of one stock: open on a calendar session vs. the close on the calendar session before it (both
    must exist). {sessions, gap_sessions, rate_pct, largest_down_pct, largest_down_date, largest_up_pct}."""
    gaps: List[Tuple[str, float]] = []
    for prev, day in zip(calendar, calendar[1:]):
        c, o = closes.get(prev), opens.get(day)
        if c is not None and o is not None and c > 0 and o > 0:
            gaps.append((day, (o / c - 1) * 100))
    big = [g for g in gaps if abs(g[1]) >= gap_pct - 1e-9]
    down = min(gaps, key=lambda g: g[1]) if gaps else None
    up = max(gaps, key=lambda g: g[1]) if gaps else None
    return {
        "sessions": len(gaps),
        "gap_sessions": len(big),
        "rate_pct": round(len(big) / len(gaps) * 100, 1) if gaps else None,
        "largest_down_pct": round(down[1], 2) if down and down[1] < 0 else (0.0 if down else None),
        "largest_down_date": down[0] if down and down[1] < 0 else None,
        "largest_up_pct": round(up[1], 2) if up and up[1] > 0 else (0.0 if up else None),
    }


def liquidity_of(rows: List[Dict[str, Any]], quantity: Optional[float]) -> Dict[str, Any]:
    """Liquidity of one position from its newest ADV_SESSIONS bars (raw close × raw volume)."""
    pairs = [(_num(r.get("raw_close")), _num(r.get("raw_volume"))) for r in rows[:ADV_SESSIONS]]
    pairs = [(c, v) for c, v in pairs if c is not None and v is not None and c > 0 and v >= 0]
    if not pairs:
        return {"adv_rs": None, "adv_cr": None, "avg_volume": None, "days_to_exit": None, "below_threshold": None,
                "level": None, "sessions": 0}
    adv = sum(c * v for c, v in pairs) / len(pairs)
    avg_vol = sum(v for _, v in pairs) / len(pairs)
    rule = LIQUIDITY_RULE
    days = (quantity / (avg_vol * rule["participation_pct"] / 100)) if quantity and avg_vol > 0 else None
    below = adv / 1e7 < rule["min_adv_cr"]
    if days is not None and days > rule["days_high"]:
        level = "high"
    elif (days is not None and days > rule["days_low"]) or below:
        level = "medium"
    else:
        level = "low" if days is not None else ("medium" if below else None)
    return {"adv_rs": round(adv, 2), "adv_cr": round(adv / 1e7, 2), "avg_volume": round(avg_vol, 2),
            "days_to_exit": round(days, 2) if days is not None else None, "below_threshold": below, "level": level,
            "sessions": len(pairs)}


def value_series(closes: Dict[str, Dict[str, float]], values: Dict[str, float], calendar: List[str]) -> Tuple[List[str], List[float]]:
    """Today's value of each stock carried back on its adjusted closes (shares = value ÷ latest adjusted close), summed
    on the calendar dates where every stock has a close."""
    shares = {}
    for sym, series in closes.items():
        last = series.get(max(series)) if series else None
        if last and values.get(sym):
            shares[sym] = values[sym] / last
    dates = [d for d in calendar if shares and all(d in closes[s] for s in shares)]
    return dates, [sum(shares[s] * closes[s][d] for s in shares) for d in dates]


def drawdown_of(values: List[float], dates: List[str]) -> Dict[str, Any]:
    """Largest fall from a running peak, percent (≤ 0), its peak and trough dates, and the fall from the peak now."""
    if not values:
        return {"max_pct": None, "peak_date": None, "trough_date": None, "current_pct": None}
    peak_i, best, best_peak, best_trough = 0, 0.0, None, None
    for i, v in enumerate(values):
        if v > values[peak_i]:
            peak_i = i
        dd = v / values[peak_i] - 1
        if dd < best:
            best, best_peak, best_trough = dd, dates[peak_i], dates[i]
    top = max(values)
    return {"max_pct": round(best * 100, 2), "peak_date": best_peak, "trough_date": best_trough,
            "current_pct": round((values[-1] / top - 1) * 100, 2)}


def annualised_vol(values: List[float], last: int) -> Optional[float]:
    """Annualised standard deviation of the last `last` daily log returns, percent; None under 2 returns."""
    rets = [math.log(b / a) for a, b in zip(values, values[1:]) if a > 0 and b > 0][-last:]
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
    return round(sd * math.sqrt(TRADING_DAYS) * 100, 2)


def level_for(kind: str, value: Optional[float]) -> Optional[str]:
    """The level a figure sits at under its rule (GAP_RULE, VOL_RULE, DRAWDOWN_RULE); None without a figure."""
    if value is None:
        return None
    if kind == "gap":
        return "low" if value < GAP_RULE["low_below_pct"] else "high" if value > GAP_RULE["high_above_pct"] else "medium"
    if kind == "volatility":
        a, b, c = VOL_RULE["bands_pct"]
        return "low" if value < a else "medium" if value < b else "high" if value < c else "very_high"
    if kind == "drawdown":
        return "low" if value > DRAWDOWN_RULE["low_above_pct"] else "high" if value < DRAWDOWN_RULE["high_below_pct"] else "medium"
    raise ValueError(kind)


# ── DaaS reads ───────────────────────────────────────────────────────────
def _closes_from_rows(rows: List[Any]) -> Dict[str, float]:
    """{date: adj_close} from DaaS /prices/adjusted rows (newest first); a row without a usable close is dropped."""
    out: Dict[str, float] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        d, c = str(r.get("as_of_date") or "")[:10], _num(r.get("adj_close"))
        if len(d) == 10 and c is not None and c > 0 and d not in out:
            out[d] = c
    return out


async def _adjusted_rows(symbols: List[str], bars: int) -> Tuple[Dict[str, List[Dict[str, Any]]], List[str]]:
    """(symbol → DaaS /prices/adjusted rows, newest first; symbols whose read failed). At most PRICE_READS_AT_ONCE
    reads in flight."""
    gate = asyncio.Semaphore(PRICE_READS_AT_ONCE)

    async def one(sym: str) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        async with gate:
            try:
                status, body = await daas_client.get_raw(
                    f"/prices/adjusted/{urllib.parse.quote(sym, safe='')}", {"limit": bars})
            except daas_client.DaasError as e:
                logger.warning("portfolio desk: DaaS prices %s failed: %s", sym, e)
                return sym, None
        rows = body.get("data") if status == 200 and isinstance(body, dict) else None
        if not isinstance(rows, list):
            logger.warning("portfolio desk: DaaS prices %s answered HTTP %s", sym, status)
            return sym, None
        return sym, [r for r in rows if isinstance(r, dict)]

    results = await asyncio.gather(*(one(s) for s in symbols))
    return ({s: r for s, r in results if r is not None}, [s for s, r in results if r is None])


async def _adjusted_closes(symbols: List[str], bars: int) -> Tuple[Dict[str, Dict[str, float]], List[str]]:
    """(symbol → {date: adjusted close}, symbols whose read failed)."""
    rows, failed = await _adjusted_rows(symbols, bars)
    return {s: _closes_from_rows(r) for s, r in rows.items()}, failed


async def _constituents(index_name: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """(latest constituents date, member rows); (None, []) when the warehouse has no list. Any failure → 502."""
    path = f"/indices/{urllib.parse.quote(index_name, safe='')}/constituents"
    try:
        status, body = await daas_client.get_raw(path, {"limit": CONSTITUENTS_LIMIT})
    except daas_client.DaasError as e:
        logger.warning("market-cap split: DaaS %s failed: %s", path, e)
        raise HTTPException(status_code=502, detail=UNAVAILABLE)
    rows = body.get("data") if status == 200 and isinstance(body, dict) else None
    if not isinstance(rows, list):
        logger.warning("market-cap split: DaaS %s answered HTTP %s", path, status)
        raise HTTPException(status_code=502, detail=UNAVAILABLE)
    as_of = body.get("as_of")
    if not rows or not as_of:
        return None, []
    return str(as_of)[:10], [r for r in rows if isinstance(r, dict)]


# ── routes ───────────────────────────────────────────────────────────────
@router.get("/correlation")
async def holdings_correlation(request: Request,
                               sessions: int = Query(120, ge=60, le=250),
                               limit: int = Query(10, ge=1, le=50)) -> Dict[str, Any]:
    user = await get_current_user(request)
    stocks, _ = split_holdings(await _holdings(user["user_id"]))

    skipped: List[Dict[str, str]] = []
    by_symbol: Dict[str, Dict[str, Any]] = {}
    for p in stocks:
        if not p["symbol"]:
            skipped.append({"symbol": _label(p), "reason": "no NSE symbol on record"})
        elif not SYMBOL_RE.match(p["symbol"]):
            skipped.append({"symbol": p["symbol"], "reason": "symbol is not an NSE ticker"})
        else:
            by_symbol[p["symbol"]] = p

    result: Dict[str, Any] = {"as_of": None, "used": [], "skipped": [], "pairs": [], "pairs_excluded": 0}
    if by_symbol:
        if not daas_client.is_configured():
            raise HTTPException(status_code=502, detail=UNAVAILABLE)
        closes, failed = await _adjusted_closes(sorted(by_symbol), sessions + 1)
        if failed and not closes:
            raise HTTPException(status_code=502, detail=UNAVAILABLE)
        skipped += [{"symbol": s, "reason": "price read failed at the data platform"} for s in failed]
        result = correlate(closes, sessions)
        skipped += result["skipped"]

    pairs = result["pairs"]

    def weight(sym: str) -> Optional[float]:
        w = by_symbol[sym]["weight_pct"]
        return round(w, 2) if w is not None else None

    return {
        "as_of": result["as_of"],
        "sessions": sessions,
        "min_sessions": MIN_SESSIONS,
        "method": CORR_METHOD,
        "source": CORR_SOURCE,
        "holdings_used": len(result["used"]),
        "holdings_skipped": skipped,
        "high_threshold": HIGH_THRESHOLD,
        "high_pairs": sum(1 for p in pairs if p["corr"] >= HIGH_THRESHOLD),
        "avg_corr": round(sum(p["corr"] for p in pairs) / len(pairs), 2) if pairs else None,
        "pairs_total": len(pairs),
        "pairs_excluded": result["pairs_excluded"],
        "pairs": [{"a": p["a"], "b": p["b"], "corr": round(p["corr"], 2), "common_sessions": p["common_sessions"],
                   "weight_a_pct": weight(p["a"]), "weight_b_pct": weight(p["b"])} for p in pairs[:limit]],
    }


@router.get("/market-cap-split")
async def market_cap_split(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    stocks, others = split_holdings(await _holdings(user["user_id"]))
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail=UNAVAILABLE)
    reads = await asyncio.gather(*(_constituents(idx) for _, idx in CAP_LISTS))

    lists: Dict[str, Optional[Dict[str, set]]] = {}
    indices: List[Dict[str, Any]] = []
    for (bucket, idx), (as_of, rows) in zip(CAP_LISTS, reads):
        lists[bucket] = membership(rows) if as_of else None
        indices.append({"bucket": bucket, "index": idx, "as_of": as_of, "available": bool(as_of),
                        "members": len(rows) if as_of else None})
    split = split_by_cap(stocks, lists)
    dates = [i["as_of"] for i in indices if i["as_of"]]
    missing = [i["index"] for i in indices if not i["available"]]
    return {
        "as_of": max(dates) if dates else None,
        "method": CAP_METHOD,
        "source": CAP_SOURCE,
        "total_value_rs": split["total_value_rs"],
        "available": split["available"],
        "reason": (f"{', '.join(missing)} constituents are not in the warehouse yet; "
                   "the buckets they decide are not reported" if missing else None),
        "buckets": split["buckets"],
        "unsplit": split["unsplit"],
        "indices": indices,
        "excluded": {"funds_value_rs": round(sum(_num(h.get("value_rs")) or 0.0 for h in others), 2),
                     "holdings": len(others), "note": FUNDS_NOTE},
    }


@router.get("/holding-risk")
async def holding_risk(request: Request, sessions: int = Query(250, ge=60, le=250)) -> Dict[str, Any]:
    """Liquidity, gap risk, volatility and drawdown of the user's direct stocks (PRD §8.4, B15), with the rules."""
    user = await get_current_user(request)
    stocks, _ = split_holdings(await _holdings(user["user_id"]))
    no_symbol = [_label(p) for p in stocks if not p["symbol"] or not SYMBOL_RE.match(p["symbol"])]
    by_symbol = {p["symbol"]: p for p in stocks if p["symbol"] and SYMBOL_RE.match(p["symbol"])}

    rows_by: Dict[str, List[Dict[str, Any]]] = {}
    failed: List[str] = []
    if by_symbol:
        if not daas_client.is_configured():
            raise HTTPException(status_code=502, detail=UNAVAILABLE)
        rows_by, failed = await _adjusted_rows(sorted(by_symbol), sessions + 1)
        if failed and not rows_by:
            raise HTTPException(status_code=502, detail=UNAVAILABLE)

    closes = {s: _closes_from_rows(r) for s, r in rows_by.items()}
    opens: Dict[str, Dict[str, float]] = {}
    for s, rows in rows_by.items():
        o: Dict[str, float] = {}
        for r in rows:
            d, v = str(r.get("as_of_date") or "")[:10], _num(r.get("adj_open"))
            if len(d) == 10 and v is not None and v > 0 and d not in o:
                o[d] = v
        opens[s] = o
    calendar = session_calendar(closes, sessions)
    latest = calendar[-1] if calendar else None
    no_prices = sorted(s for s in rows_by if not closes[s]) + sorted(failed)

    holdings: List[Dict[str, Any]] = []
    for sym in sorted(by_symbol):
        p = by_symbol[sym]
        rows = rows_by.get(sym) or []
        last = max(closes[sym]) if closes.get(sym) else None
        raw_last = next((_num(r.get("raw_close")) for r in rows if _num(r.get("raw_close"))), None)
        qty = p["quantity"] if p.get("quantity") else ((p["value_rs"] / raw_last) if p.get("value_rs") and raw_last else None)
        liq = liquidity_of(rows, qty)
        gaps = gap_stats(opens.get(sym, {}), closes.get(sym, {}), calendar, GAP_RULE["gap_pct"])
        own = sorted(closes.get(sym, {}))
        holdings.append({
            "symbol": sym, "isin": p.get("isin"), "name": p.get("name"),
            "value_rs": round(p["value_rs"], 2) if p.get("value_rs") is not None else None,
            "weight_pct": round(p["weight_pct"], 2) if p.get("weight_pct") is not None else None,
            "quantity": round(qty, 4) if qty is not None else None,
            "last_session": last, "stale": bool(last and latest and last < latest), "bars": len(own),
            "adv_rs": liq["adv_rs"], "adv_cr": liq["adv_cr"], "avg_volume": liq["avg_volume"],
            "days_to_exit": liq["days_to_exit"], "below_threshold": liq["below_threshold"], "liquidity_level": liq["level"],
            "gap_sessions": gaps["gap_sessions"], "gap_rate_pct": gaps["rate_pct"],
            "largest_gap_down_pct": gaps["largest_down_pct"], "largest_gap_down_date": gaps["largest_down_date"],
            "largest_gap_up_pct": gaps["largest_up_pct"],
            "volatility_1m_pct": annualised_vol([closes[sym][d] for d in own], SHORT_VOL_SESSIONS) if own else None,
            "drawdown_pct": drawdown_of([closes[sym][d] for d in own], own)["max_pct"] if own else None,
        })

    priced = [h for h in holdings if h["last_session"] and h["value_rs"]]
    priced_value = sum(h["value_rs"] for h in priced)
    stock_value = sum(p["value_rs"] or 0.0 for p in stocks)

    # Liquidity: the worst holding decides; the share of value under the ₹10 Cr threshold says how much.
    liq_rows = [h for h in priced if h["liquidity_level"]]
    order = {"low": 0, "medium": 1, "high": 2}
    liq_level = max((h["liquidity_level"] for h in liq_rows), key=order.get) if liq_rows else None
    slow = max((h for h in liq_rows if h["days_to_exit"] is not None), key=lambda h: h["days_to_exit"], default=None)
    below_value = sum(h["value_rs"] for h in liq_rows if h["below_threshold"])
    # Gaps: value-weighted rate over the stocks with gap observations.
    gap_rows = [h for h in priced if h["gap_rate_pct"] is not None]
    gap_value = sum(h["value_rs"] for h in gap_rows)
    gap_rate = round(sum(h["gap_rate_pct"] * h["value_rs"] for h in gap_rows) / gap_value, 1) if gap_value > 0 else None
    worst_gap = min((h for h in gap_rows if h["largest_gap_down_pct"] is not None), key=lambda h: h["largest_gap_down_pct"], default=None)

    # Today's stocks held together: current (not stale) stocks with at least MIN_SESSIONS closes in the window.
    excluded: List[Dict[str, str]] = []
    series_closes: Dict[str, Dict[str, float]] = {}
    window = set(calendar)
    for h in priced:
        sym = h["symbol"]
        in_window = {d: c for d, c in closes[sym].items() if d in window}
        if h["stale"]:
            excluded.append({"symbol": sym, "reason": f"price is stale (last {h['last_session']})"})
        elif len(in_window) < MIN_SESSIONS:
            excluded.append({"symbol": sym, "reason": f"fewer than {MIN_SESSIONS} sessions of prices"})
        else:
            series_closes[sym] = in_window
    dates, values = value_series(series_closes, {s: by_symbol[s]["value_rs"] or 0.0 for s in series_closes}, calendar)
    if len(dates) < MIN_SESSIONS:
        dates, values = [], []
    dd = drawdown_of(values, dates)
    vol = annualised_vol(values, SHORT_VOL_SESSIONS) if values else None
    series_value = sum(by_symbol[s]["value_rs"] or 0.0 for s in series_closes) if values else 0.0

    return {
        "as_of": latest,
        "sessions": sessions,
        "method": HOLDING_RISK_METHOD,
        "source": CORR_SOURCE,
        "rules": {"liquidity": LIQUIDITY_RULE, "gap": GAP_RULE, "volatility": VOL_RULE, "drawdown": DRAWDOWN_RULE},
        "holdings": holdings,
        "portfolio": {
            "liquidity": {
                "level": liq_level,
                "below_threshold_value_pct": round(below_value / priced_value * 100, 1) if liq_rows and priced_value > 0 else None,
                "slowest": {"symbol": slow["symbol"], "days_to_exit": slow["days_to_exit"]} if slow else None,
            },
            "gap": {
                "level": level_for("gap", gap_rate), "rate_pct": gap_rate,
                "largest": ({"symbol": worst_gap["symbol"], "pct": worst_gap["largest_gap_down_pct"],
                             "date": worst_gap["largest_gap_down_date"]} if worst_gap else None),
            },
            "volatility_1m": {"pct": vol, "level": level_for("volatility", vol)},
            "drawdown": {**dd, "level": level_for("drawdown", dd["max_pct"]), "sessions": len(dates)},
            "series": {
                "symbols": sorted(series_closes) if values else [],
                "excluded": excluded,
                "start": dates[0] if dates else None, "end": dates[-1] if dates else None,
                "coverage_pct": round(series_value / stock_value * 100, 1) if values and stock_value > 0 else None,
            },
        },
        "missing": {"no_symbol": no_symbol, "no_prices": no_prices,
                    "stale": [{"symbol": h["symbol"], "last_session": h["last_session"]} for h in holdings if h["stale"]],
                    "latest_session": latest},
    }
