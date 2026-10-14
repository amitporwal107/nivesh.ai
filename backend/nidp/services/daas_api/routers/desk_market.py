"""DaaS — market reads for the Smart trading desk (sector index returns, bulk/block deals, F&O OI build-up).

    GET /v1/desk/sector-returns                         NSE sectoral indices: latest close and 1-day / 1-week / 1-month returns
    GET /v1/desk/deals?days=5&kind=all&symbol=&limit=   NSE bulk and block deals over the last `days` calendar days
    GET /v1/desk/fno-buildup?date=                      stock-futures open-interest build-up, one row per underlying

Prefix /desk so these never fall under /fno/{symbol}. Read-only. Every answer names its source table and the
as-of date; a missing figure is null, never 0. No data → 200 with an empty list and the as-of date.

Definitions
  sector-returns  ret_Nd_pct = close / (the close N rows earlier in THAT index's own series) − 1, in percent;
                  N = 1, 5, 21 sessions (1d / 1w / 1m). null when the index has fewer than N + 1 closes. `date` on each
                  row is that index's own latest close, so a lagging index is visible rather than mixed in silently.
  deals           the window is `days` calendar days ending at the latest deal date across BOTH tables (a session
                  with no block deals is a real empty, not a reason to slide the window back).
                  value_cr = quantity × avg_price ÷ 1e7 (₹ crore).
  fno-buildup     stock futures (instrument_type 'STF') on the latest or given day, one row per underlying:
                  price_chg_pct  nearest expiry's close_price vs its prev_close_price
                  oi / oi_chg    open_interest / change_in_oi summed over every expiry, so a roll near expiry does not
                                 read as unwinding (null if any expiry's figure is missing)
                  oi_chg_pct     oi_chg ÷ (oi − oi_chg), the previous day's OI, in percent
                  label          price↑ OI↑ long_buildup · price↓ OI↑ short_buildup · price↑ OI↓ short_covering ·
                                 price↓ OI↓ long_unwinding · otherwise (either flat) neutral. null when the price or
                                 OI change is missing (counted as `no_data`). A reading of two figures, not a record
                                 of who traded.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import jsonify, normalise_symbol, parse_date

router = APIRouter(prefix="/desk", tags=["desk"], dependencies=[Depends(require_api_key)])

# ── sector returns ───────────────────────────────────────────────────────────

# NSE sectoral indices as named in nidp.index_eod (checked on staging 2026-10-14), each with the sector label the
# desk shows. One index per industry; sub-segments of these (NBFC, Insurance, Hospitals…) are left out.
SECTOR_INDICES: Tuple[Tuple[str, str], ...] = (
    ("Nifty Auto", "Auto"),
    ("Nifty Bank", "Banks"),
    ("Nifty Financial Services", "Financial Services"),
    ("Nifty FMCG", "FMCG"),
    ("Nifty IT", "IT"),
    ("Nifty Media", "Media"),
    ("Nifty Metal", "Metals"),
    ("Nifty Pharma", "Pharma"),
    ("Nifty PSU Bank", "PSU Banks"),
    ("Nifty Private Bank", "Private Banks"),
    ("Nifty Realty", "Realty"),
    ("Nifty Energy", "Energy"),
    ("Nifty Oil & Gas", "Oil & Gas"),
    ("Nifty Healthcare Index", "Healthcare"),
    ("Nifty Consumer Durables", "Consumer Durables"),
    ("Nifty Capital Goods", "Capital Goods"),
    ("Nifty Cement", "Cement"),
    ("Nifty Chemicals", "Chemicals"),
    ("Nifty Power", "Power"),
    ("Nifty Telecommunications", "Telecom"),
)
SESSIONS: Dict[str, int] = {"1d": 1, "1w": 5, "1m": 21}
_SECTOR_SOURCE = "NSE index close (nidp.index_eod)"

# The latest `$2` closes of each index, newest first. DISTINCT ON keeps one row per day should a second source
# ever load the same index, so "N rows earlier" stays "N sessions earlier".
SECTOR_SQL = """
    SELECT n.index_name, e.as_of_date, e.close_price
      FROM unnest($1::text[]) AS n(index_name)
      CROSS JOIN LATERAL (
            SELECT as_of_date, close_price
              FROM (SELECT DISTINCT ON (as_of_date) as_of_date, close_price
                      FROM nidp.index_eod
                     WHERE index_name = n.index_name AND close_price IS NOT NULL
                     ORDER BY as_of_date DESC, source) d
             ORDER BY as_of_date DESC
             LIMIT $2
      ) e
     ORDER BY n.index_name, e.as_of_date DESC
"""


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pct_return(close: Optional[float], base: Optional[float]) -> Optional[float]:
    """(close ÷ base − 1) × 100 to 2 decimals; None when either is missing or the base is not positive."""
    if close is None or base is None or base <= 0:
        return None
    return round((close / base - 1.0) * 100.0, 2)


def sector_row(index_name: str, sector: str, closes: Sequence[Tuple[date, float]]) -> Dict[str, Any]:
    """One sector from its closes, newest first. Returns are against the close N rows earlier in this series."""
    latest_day, latest = (closes[0][0], closes[0][1]) if closes else (None, None)
    row: Dict[str, Any] = {"index": index_name, "sector": sector,
                           "date": latest_day.isoformat() if latest_day else None, "close": latest}
    for key, n in SESSIONS.items():
        row[f"ret_{key}_pct"] = pct_return(latest, closes[n][1]) if len(closes) > n else None
    return row


@router.get("/sector-returns", summary="NSE sectoral indices: close and 1d / 1w / 1m returns")
async def sector_returns() -> Dict[str, Any]:
    names = [name for name, _ in SECTOR_INDICES]
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(SECTOR_SQL, names, max(SESSIONS.values()) + 1)
    series: Dict[str, List[Tuple[date, float]]] = {}
    for r in rows:
        close = _num(r["close_price"])
        if close is not None:
            series.setdefault(r["index_name"], []).append((r["as_of_date"], close))
    sectors = [sector_row(name, label, series.get(name, [])) for name, label in SECTOR_INDICES]
    days = [s["date"] for s in sectors if s["date"]]
    return {"as_of": max(days) if days else None, "source": _SECTOR_SOURCE, "sessions": dict(SESSIONS),
            "sectors": sectors}


# ── bulk and block deals ─────────────────────────────────────────────────────

_DEALS_SOURCE = "NSE bulk and block deals (nidp.bulk_deals, nidp.block_deals)"
DEALS_MAX_DAYS = 30
DEALS_MAX_LIMIT = 5_000

DEALS_LATEST_SQL = """
    SELECT GREATEST((SELECT MAX(as_of_date) FROM nidp.bulk_deals),
                    (SELECT MAX(as_of_date) FROM nidp.block_deals)) AS d
"""

# $1 latest day, $2 days, $3 kind, $4 symbol or NULL, $5 limit. `total` is the count before the limit.
DEALS_SQL = """
    SELECT as_of_date, kind, symbol, client_name, deal_type, quantity, avg_price,
           COUNT(*) OVER () AS total
      FROM (
            SELECT as_of_date, 'bulk' AS kind, symbol, client_name, deal_type, quantity, avg_price, deal_seq
              FROM nidp.bulk_deals
             WHERE $3::text IN ('all', 'bulk')
               AND as_of_date > $1::date - $2::int AND as_of_date <= $1::date
               AND ($4::text IS NULL OR symbol = $4)
            UNION ALL
            SELECT as_of_date, 'block' AS kind, symbol, client_name, deal_type, quantity, avg_price, deal_seq
              FROM nidp.block_deals
             WHERE $3::text IN ('all', 'block')
               AND as_of_date > $1::date - $2::int AND as_of_date <= $1::date
               AND ($4::text IS NULL OR symbol = $4)
           ) d
     ORDER BY as_of_date DESC, quantity * avg_price DESC NULLS LAST, symbol, client_name, deal_seq
     LIMIT $5
"""

_SIDE = {"BUY": "BUY", "B": "BUY", "SELL": "SELL", "S": "SELL"}


def deal_row(r: Any) -> Dict[str, Any]:
    qty, price = r["quantity"], _num(r["avg_price"])
    value_cr = round(qty * price / 1e7, 2) if qty is not None and price is not None else None
    return {
        "date": jsonify(r["as_of_date"]),
        "kind": r["kind"],
        "symbol": r["symbol"],
        "client_name": r["client_name"],
        "side": _SIDE.get((r["deal_type"] or "").strip().upper()),
        "quantity": int(qty) if qty is not None else None,
        "avg_price": price,
        "value_cr": value_cr,
    }


@router.get("/deals", summary="NSE bulk and block deals over the last N calendar days")
async def deals(
    days: int = Query(5, ge=1, le=DEALS_MAX_DAYS, description="Calendar days ending at the latest deal date"),
    kind: Literal["all", "bulk", "block"] = Query("all"),
    symbol: Optional[str] = Query(None, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9&\-]+$"),
    limit: int = Query(500, ge=1, le=DEALS_MAX_LIMIT),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol) if symbol else None
    out: Dict[str, Any] = {"as_of": None, "from": None, "days": days, "kind": kind, "symbol": sym,
                           "source": _DEALS_SOURCE, "count": 0, "total": 0, "rows": []}
    pool = await get_pool()
    async with pool.acquire() as conn:
        latest = await conn.fetchval(DEALS_LATEST_SQL)
        if latest is None:
            return out
        rows = await conn.fetch(DEALS_SQL, latest, days, kind, sym, limit)
    out["as_of"] = latest.isoformat()
    out["from"] = date.fromordinal(latest.toordinal() - days + 1).isoformat()
    out["rows"] = [deal_row(r) for r in rows]
    out["count"] = len(out["rows"])
    out["total"] = int(rows[0]["total"]) if rows else 0
    return out


# ── F&O open-interest build-up ───────────────────────────────────────────────

_FNO_SOURCE = "NSE F&O bhavcopy (nidp.fno_bhavcopy), stock futures"
LABELS = ("long_buildup", "short_buildup", "short_covering", "long_unwinding", "neutral")

FNO_LATEST_SQL = "SELECT MAX(as_of_date) AS d FROM nidp.fno_bhavcopy WHERE instrument_type = 'STF'"

# One row per underlying: the nearest expiry's prices, OI and its change summed over every expiry (NULL when any
# expiry's figure is missing, so a partial sum never passes for the whole). DISTINCT ON keeps one row per contract
# should a second source ever load the same day.
FNO_BUILDUP_SQL = """
    WITH fut AS (
        SELECT DISTINCT ON (ticker_symbol, expiry_date)
               ticker_symbol, expiry_date, close_price, prev_close_price, open_interest, change_in_oi
          FROM nidp.fno_bhavcopy
         WHERE as_of_date = $1 AND instrument_type = 'STF'
         ORDER BY ticker_symbol, expiry_date, source
    )
    SELECT ticker_symbol AS symbol,
           (ARRAY_AGG(expiry_date      ORDER BY expiry_date))[1] AS near_expiry,
           (ARRAY_AGG(close_price      ORDER BY expiry_date))[1] AS close,
           (ARRAY_AGG(prev_close_price ORDER BY expiry_date))[1] AS prev_close,
           CASE WHEN COUNT(open_interest) = COUNT(*) THEN SUM(open_interest) END AS oi,
           CASE WHEN COUNT(change_in_oi)  = COUNT(*) THEN SUM(change_in_oi)  END AS oi_chg,
           COUNT(*) AS expiries
      FROM fut
     GROUP BY ticker_symbol
"""


def buildup_label(price_chg: Optional[float], oi_chg: Optional[float]) -> Optional[str]:
    """The build-up reading of a price change and an OI change. None when either is missing."""
    if price_chg is None or oi_chg is None:
        return None
    if price_chg > 0 and oi_chg > 0:
        return "long_buildup"
    if price_chg < 0 and oi_chg > 0:
        return "short_buildup"
    if price_chg > 0 and oi_chg < 0:
        return "short_covering"
    if price_chg < 0 and oi_chg < 0:
        return "long_unwinding"
    return "neutral"


def buildup_row(r: Any) -> Dict[str, Any]:
    close, prev = _num(r["close"]), _num(r["prev_close"])
    oi = int(r["oi"]) if r["oi"] is not None else None
    oi_chg = int(r["oi_chg"]) if r["oi_chg"] is not None else None
    prev_oi = oi - oi_chg if oi is not None and oi_chg is not None else None
    # The label reads the raw changes, not the rounded percents: +0.004% is still up.
    price_move = close - prev if close is not None and prev is not None and prev > 0 else None
    return {
        "symbol": r["symbol"],
        "near_expiry": jsonify(r["near_expiry"]),
        "close": close,
        "prev_close": prev,
        "price_chg_pct": pct_return(close, prev),
        "oi": oi,
        "oi_chg": oi_chg,
        "oi_chg_pct": round(oi_chg / prev_oi * 100.0, 2) if prev_oi is not None and prev_oi > 0 else None,
        "expiries": int(r["expiries"]),
        "label": buildup_label(price_move, oi_chg),
    }


def _activity(row: Dict[str, Any]) -> Tuple[float, str]:
    """Sort key: the largest OI change in percent first (missing last), then symbol."""
    pct = row["oi_chg_pct"]
    return (-abs(pct) if pct is not None else float("inf"), row["symbol"])


@router.get("/fno-buildup", summary="Stock-futures OI build-up scan, one row per underlying")
async def fno_buildup(
    on: Optional[str] = Query(None, alias="date", description="Trading day YYYY-MM-DD; defaults to the latest"),
) -> Dict[str, Any]:
    day = parse_date(on, field="date")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if day is None:
            day = await conn.fetchval(FNO_LATEST_SQL)
        rows = await conn.fetch(FNO_BUILDUP_SQL, day) if day is not None else []
    out_rows = sorted((buildup_row(r) for r in rows), key=_activity)
    counts = {label: 0 for label in LABELS}
    counts["no_data"] = 0
    for row in out_rows:
        counts[row["label"] or "no_data"] += 1
    return {"as_of": day.isoformat() if day else None, "source": _FNO_SOURCE, "universe": len(out_rows),
            "counts": counts, "rows": out_rows}
