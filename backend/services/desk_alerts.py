"""Smart trading desk — the alert conditions of PRD §6.7, beside the price alerts of services/desk_trading.py.

Alerts are in-app only: a fired alert is listed with the reason it fired (GET /api/desk/alerts); nothing is sent
anywhere and nothing places an order. Every alert lives in the same store (desk_price_alerts) under the same rules:
one owner (`user_id`), at most MAX_ACTIVE_ALERTS active per user, one-shot (active → fired, written with the status
in the update filter so a second check never fires it twice), and an active alert identical to one the user already
has is refused (409 duplicate_alert).

Conditions (`condition`, with the fields each takes besides `note`):
    above / below  symbol, level         a session's high reaches the level / its low reaches it (desk_trading.py)
    filing         symbol, impact?       the stock's first exchange filing (NSE or BSE) filed after the alert was
                                         made; impact "high" keeps only filings the classifier rated high impact
                                         (an AI label, said so in the reason)
    category       category, symbol?     the first filing in that classifier category (any stock, or one stock), or
                                         with category "deal" the stock's first bulk or block deal (symbol needed)
    volume         symbol, multiple      a session's traded volume reaches `multiple` × the mean volume of the 20
                                         sessions before it
    scanner        symbol, stage?        the stock is in the positional scanner's picks (positional_signals) on a
                                         signal date after the alert was made, in that stage when one is given
    sector         index, threshold_pct, direction
                                         an NSE sector index's 1-day close-to-close return reaches the threshold,
                                         up, down or either way
    risk           symbol, level         the stock's 14-session ATR (Wilder) as a percent of its close reaches the
                                         level (the desk's risk classes: below 2 % low, 2–4 % medium, above 4 % high)

Timing: a filing counts when its exchange time (filed_at) is after the moment the alert was made. Everything read
from daily data (prices, volume, ATR, sector closes, deals, scanner dates) counts from the first session strictly
after the IST calendar date the alert was made, as the price alerts do. A session whose figure is missing ends that
alert's scan for now; it is never skipped.

Sources: end-of-day bars from DaaS /v1/prices/eod (desk_trading.fetch_bars), filings from /v1/announcements, deals
from /v1/flows/bulk-deals and /block-deals, sector closes from /v1/indices/{index}/eod, scanner picks from the app's
positional_signals table. A source that cannot be read leaves its alerts active and says so (`check_errors`); an
alert is never fired, and never shown as checked, on data that was not read.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from services import desk_trading as svc

logger = logging.getLogger(__name__)

PRICE_CONDITIONS = ("above", "below")
BAR_CONDITIONS = ("above", "below", "volume", "risk")
CONDITIONS = ("above", "below", "filing", "category", "volume", "scanner", "sector", "risk")

# The classifier's event categories (nidp.corporate_announcements.event_category), and "deal" for bulk / block deals.
FILING_CATEGORIES = ("earnings", "orders", "mna", "capex", "management", "dividend", "buyback", "qip", "rating",
                     "litigation", "regulatory")
CATEGORIES = FILING_CATEGORIES + ("deal",)
CATEGORY_LABEL = {
    "earnings": "Results", "orders": "Order", "mna": "M&A", "capex": "Capex", "management": "Management",
    "dividend": "Dividend", "buyback": "Buyback", "qip": "QIP", "rating": "Rating", "litigation": "Litigation",
    "regulatory": "Regulatory", "deal": "Bulk or block deal",
}
# Stages the positional engine writes to positional_signals (services/positional_engine/scorer.py classify_stage;
# WEAK and EXTENDED never become picks).
SCANNER_STAGES = ("BREAKOUT", "EARLY_BREAKOUT", "ACCUMULATION")
# The sector indices of the desk (nidp/services/daas_api/routers/desk_market.py SECTOR_INDICES; a unit test keeps
# the two lists equal).
SECTOR_INDEX_NAMES = (
    "Nifty Auto", "Nifty Bank", "Nifty Financial Services", "Nifty FMCG", "Nifty IT", "Nifty Media", "Nifty Metal",
    "Nifty Pharma", "Nifty PSU Bank", "Nifty Private Bank", "Nifty Realty", "Nifty Energy", "Nifty Oil & Gas",
    "Nifty Healthcare Index", "Nifty Consumer Durables", "Nifty Capital Goods", "Nifty Cement", "Nifty Chemicals",
    "Nifty Power", "Nifty Telecommunications",
)
DIRECTIONS = ("up", "down", "either")

VOLUME_BASE_SESSIONS = 20
MULTIPLE_RANGE = (1.5, 20.0)
ATR_SESSIONS = 14
RISK_RANGE = (0.5, 20.0)
THRESHOLD_RANGE = (0.5, 10.0)
BAR_LOOKBACK_DAYS = 60          # calendar days of bars read before the alert date for the volume base and the ATR
INDEX_LOOKBACK_DAYS = 10        # an index close before the first session, for its 1-day return
READ_LIMIT = 1000

_FIELDS = {
    "above": {"symbol", "condition", "level", "note"},
    "below": {"symbol", "condition", "level", "note"},
    "filing": {"condition", "symbol", "impact", "note"},
    "category": {"condition", "category", "symbol", "note"},
    "volume": {"condition", "symbol", "multiple", "note"},
    "scanner": {"condition", "symbol", "stage", "note"},
    "sector": {"condition", "index", "threshold_pct", "direction", "note"},
    "risk": {"condition", "symbol", "level", "note"},
}

RULES = {
    "above": "A session's high reaches the level (end-of-day bars).",
    "below": "A session's low reaches the level (end-of-day bars).",
    "filing": "The stock's first exchange filing (NSE or BSE) filed after the alert was made.",
    "category": "The first filing in that category (the classifier's label, an AI label) after the alert was made; "
                "for bulk or block deals, the stock's first deal disclosed by NSE for a later session.",
    "volume": f"A session's traded volume reaches the multiple × the mean volume of the {VOLUME_BASE_SESSIONS} sessions before it.",
    "scanner": "The stock is in the positional scanner's picks on a signal date after the alert was made.",
    "sector": "The sector index's 1-day close-to-close return reaches the threshold in the chosen direction.",
    "risk": f"The stock's {ATR_SESSIONS}-session ATR (Wilder) as a percent of its close reaches the level.",
}
CHECK_NOTE = ("Checked when you open the alerts and once each weekday evening; shown in this list only "
              "(in-app). Counted from the first session after the day the alert was made; a filing counts from the "
              "moment it was made.")

IST = timezone(timedelta(hours=5, minutes=30))

SOURCE_UNAVAILABLE = "source_unavailable"


class SourceUnavailable(RuntimeError):
    """A data source could not be read."""


# ── validation ───────────────────────────────────────────────────────────────
def _range(raw: Any, lo: float, hi: float, code: str) -> float:
    n = svc._number(raw)
    if n is None or not lo <= n <= hi:
        raise svc.DeskInputError(code)
    return round(n, 4)


def new_alert(user_id: str, body: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """An alert document for any condition; raises DeskInputError with the code the client is told."""
    if not isinstance(body, dict):
        raise svc.DeskInputError("invalid_body")
    condition = body.get("condition")
    if condition not in CONDITIONS:
        raise svc.DeskInputError("invalid_condition")
    if condition in PRICE_CONDITIONS:
        doc = svc.new_alert(user_id, body, now)
        doc.update(params={}, reason=None, evidence=None)
        return doc
    body = svc._object(body, _FIELDS[condition])
    symbol: Optional[str] = None
    level: Optional[float] = None
    params: Dict[str, Any] = {}
    if condition == "filing":
        symbol = svc.clean_symbol(body.get("symbol"))
        impact = body.get("impact") or "any"
        if impact not in ("any", "high"):
            raise svc.DeskInputError("invalid_impact")
        params["impact"] = impact
    elif condition == "category":
        category = body.get("category")
        if category not in CATEGORIES:
            raise svc.DeskInputError("invalid_category")
        params["category"] = category
        if body.get("symbol") is not None or category == "deal":
            symbol = svc.clean_symbol(body.get("symbol"))
    elif condition == "volume":
        symbol = svc.clean_symbol(body.get("symbol"))
        params["multiple"] = _range(body.get("multiple"), *MULTIPLE_RANGE, "invalid_multiple")
    elif condition == "scanner":
        symbol = svc.clean_symbol(body.get("symbol"))
        stage = body.get("stage")
        if stage is not None and stage not in SCANNER_STAGES:
            raise svc.DeskInputError("invalid_stage")
        params["stage"] = stage
    elif condition == "sector":
        index = body.get("index")
        if index not in SECTOR_INDEX_NAMES:
            raise svc.DeskInputError("invalid_index")
        direction = body.get("direction") or "either"
        if direction not in DIRECTIONS:
            raise svc.DeskInputError("invalid_direction")
        params.update(index=index, threshold_pct=_range(body.get("threshold_pct"), *THRESHOLD_RANGE, "invalid_threshold"),
                      direction=direction)
    elif condition == "risk":
        symbol = svc.clean_symbol(body.get("symbol"))
        level = _range(body.get("level"), *RISK_RANGE, "invalid_level")
    stamp = svc._iso(now or svc.utcnow())
    return {
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "symbol": symbol,
        "condition": condition,
        "level": level,
        "params": params,
        "note": svc.clean_note(body.get("note")),
        "created_at": stamp,
        "status": "active",
        "fired_at": None,
        "fired_session": None,
        "fired_price": None,
        "reason": None,
        "evidence": None,
        "updated_at": stamp,
    }


def dedupe_key(doc: Dict[str, Any]) -> Tuple[Any, ...]:
    """What makes two alerts the same alert: the condition, the stock, the level and the parameters."""
    level = doc.get("level")
    params = doc.get("params") or {}
    return (doc.get("condition"), doc.get("symbol"), round(float(level), 4) if level is not None else None,
            tuple(sorted((k, v) for k, v in params.items() if v is not None)))


# ── reading the sources ──────────────────────────────────────────────────────
async def _daas(path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The `data` list of a DaaS envelope; [] for a 404; SourceUnavailable when it cannot be read."""
    if not svc.daas_client.is_configured():
        raise SourceUnavailable("the data platform is not configured")
    try:
        body = await svc.daas_client._get(path, params=params, timeout=svc.FETCH_TIMEOUT_S)
    except svc.daas_client.DaasError as exc:
        raise SourceUnavailable(str(exc)) from exc
    if body is None:
        return []
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise SourceUnavailable(f"unexpected answer from {path}")
    return [r for r in data if isinstance(r, dict)]


async def read_filings(symbol: Optional[str], category: Optional[str], since: date) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"filed_from": since.isoformat(), "limit": READ_LIMIT, "offset": 0}
    if symbol:
        params["symbol"] = symbol
    if category:
        params["category"] = category
    return await _daas("/announcements", params)


async def read_deals(symbol: str, since: date) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for kind in ("bulk", "block"):
        for r in await _daas(f"/flows/{kind}-deals", {"symbol": symbol, "start": since.isoformat(), "limit": READ_LIMIT, "offset": 0}):
            rows.append({**r, "kind": r.get("kind") or kind})
    return rows


async def read_index(index: str, start: date) -> List[Dict[str, Any]]:
    return await _daas(f"/indices/{quote(index, safe='')}/eod", {"start": start.isoformat(), "limit": READ_LIMIT, "offset": 0})


async def read_scanner(symbols: List[str], after: date) -> List[Dict[str, Any]]:
    """positional_signals rows for the symbols on signal dates after `after` (the app database)."""
    from services import pg_client
    pool = await pg_client.get_pool()
    if pool is None:
        raise SourceUnavailable("the scanner database is not configured")
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT nse_symbol, signal_date, stage, final_score FROM positional_signals "
                "WHERE nse_symbol = ANY($1::text[]) AND signal_date > $2 ORDER BY signal_date, nse_symbol",
                symbols, after)
    except Exception as exc:  # noqa: BLE001 — a missing table or a dropped connection is "not read", never "no picks"
        raise SourceUnavailable(str(exc)) from exc
    return [dict(r) for r in rows]


def bar_starts(alerts: Iterable[Dict[str, Any]]) -> Dict[str, date]:
    """{symbol: first day to read} for every bar-based alert: 14 days before the alert date for a price alert (its
    last close), 60 for volume and risk (the 20-session base and the ATR)."""
    starts: Dict[str, date] = {}
    for doc in alerts:
        if doc.get("condition") not in BAR_CONDITIONS or not doc.get("symbol"):
            continue
        back = svc.LOOKBACK_DAYS if doc["condition"] in PRICE_CONDITIONS else BAR_LOOKBACK_DAYS
        start = svc.ist_date(doc["created_at"]) - timedelta(days=back)
        if doc["symbol"] not in starts or start < starts[doc["symbol"]]:
            starts[doc["symbol"]] = start
    return starts


# ── the rules (pure) ─────────────────────────────────────────────────────────
def _day_text(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def _rs(v: float) -> str:
    return f"₹{v:,.2f}"


def _when(stamp: Any) -> Optional[datetime]:
    if not isinstance(stamp, str):
        return None
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _exchange(source: Any) -> str:
    s = str(source or "").upper()
    return "NSE" if s.startswith("NSE") else "BSE" if s.startswith("BSE") else (str(source) if source else "the exchange")


def price_fire(alert: Dict[str, Any], bars: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[date]]:
    fire, checked = svc.find_alert_fire(alert, bars)
    if fire is None:
        return None, checked
    session = fire["fired_session"]
    bar = next((b for b in bars if b["date"] == session), None)
    level = float(alert["level"])
    above = alert["condition"] == "above"
    hit = (bar or {}).get("high" if above else "low")
    word = "high" if above else "low"
    reason = (f"{alert['symbol']}'s {word} of {_rs(hit)} on {_day_text(session)} reached your level of {_rs(level)}."
              if hit is not None else f"{alert['symbol']} reached your level of {_rs(level)} on {_day_text(session)}.")
    return {**fire, "reason": reason, "evidence": {"session": session.isoformat(), word: hit, "level": level}}, session


def volume_fire(alert: Dict[str, Any], bars: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[date]]:
    """The first session after the alert date whose volume reaches multiple × the mean of the 20 sessions before it.
    A session without a volume ends the scan; a session with fewer than 20 sessions before it is passed over."""
    multiple = float(alert["params"]["multiple"])
    after = svc.ist_date(alert["created_at"])
    checked: Optional[date] = None
    for i, bar in enumerate(bars):
        if bar["date"] <= after:
            continue
        vol = bar.get("volume")
        if vol is None:
            return None, checked
        base = [b.get("volume") for b in bars[max(0, i - VOLUME_BASE_SESSIONS):i]]
        checked = bar["date"]
        if len(base) < VOLUME_BASE_SESSIONS or any(v is None for v in base):
            continue
        avg = sum(base) / VOLUME_BASE_SESSIONS
        if avg > 0 and vol >= multiple * avg:
            ratio = vol / avg
            return {
                "fired_session": bar["date"], "fired_price": None,
                "reason": (f"{alert['symbol']} traded {vol:,.0f} shares on {_day_text(bar['date'])}, {ratio:.1f}× its "
                           f"average of {avg:,.0f} over the {VOLUME_BASE_SESSIONS} sessions before (your level: {multiple:g}×)."),
                "evidence": {"session": bar["date"].isoformat(), "volume": vol, "average": round(avg, 2),
                             "ratio": round(ratio, 2), "multiple": multiple},
            }, bar["date"]
    return None, checked


def atr_pct_series(bars: List[Dict[str, Any]], n: int = ATR_SESSIONS) -> List[Optional[float]]:
    """Wilder ATR as a percent of the close, per bar (None until n true ranges exist or when a figure is missing)."""
    out: List[Optional[float]] = [None] * len(bars)
    trs: List[float] = []
    atr: Optional[float] = None
    for i, b in enumerate(bars):
        if i == 0:
            continue
        prev = bars[i - 1].get("close")
        if None in (b.get("high"), b.get("low"), prev, b.get("close")):
            return out[:i] + [None] * (len(bars) - i)
        tr = max(b["high"] - b["low"], abs(b["high"] - prev), abs(b["low"] - prev))
        if atr is None:
            trs.append(tr)
            if len(trs) == n:
                atr = sum(trs) / n
        else:
            atr = (atr * (n - 1) + tr) / n
        if atr is not None and b["close"] > 0:
            out[i] = atr / b["close"] * 100.0
    return out


def risk_fire(alert: Dict[str, Any], bars: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[date]]:
    level = float(alert["level"])
    after = svc.ist_date(alert["created_at"])
    series = atr_pct_series(bars)
    checked: Optional[date] = None
    for bar, pct in zip(bars, series):
        if bar["date"] <= after:
            continue
        if pct is None:
            if bar.get("high") is None or bar.get("low") is None or bar.get("close") is None:
                return None, checked
            continue
        checked = bar["date"]
        if pct >= level:
            return {
                "fired_session": bar["date"], "fired_price": None,
                "reason": (f"{alert['symbol']}'s {ATR_SESSIONS}-session ATR reached {pct:.2f}% of its close on "
                           f"{_day_text(bar['date'])} (your level: {level:g}%)."),
                "evidence": {"session": bar["date"].isoformat(), "atr_pct": round(pct, 2), "level": level},
            }, bar["date"]
    return None, checked


def filing_fire(alert: Dict[str, Any], rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The earliest filing made after the alert (and, for impact "high", rated high impact by the classifier)."""
    made = _when(alert["created_at"])
    params = alert.get("params") or {}
    category = params.get("category")
    hits = []
    for r in rows:
        at = _when(r.get("filed_at"))
        if at is None or made is None or at <= made:
            continue
        if alert["symbol"] and str(r.get("ticker_symbol") or "").upper() != alert["symbol"]:
            continue
        if category and r.get("event_category") != category:
            continue
        if params.get("impact") == "high" and r.get("impact_score") != "high":
            continue
        hits.append((at, str(r.get("announcement_id") or ""), r))
    if not hits:
        return None
    at, _, r = min(hits, key=lambda h: (h[0], h[1]))
    local = at.astimezone(IST)
    who = alert["symbol"] or r.get("ticker_symbol") or r.get("company_name") or "A company"
    subject = (r.get("subject") or "a filing").strip()
    reason = f"{who} filed “{subject}” with {_exchange(r.get('source'))} at {local.strftime('%H:%M')} IST on {_day_text(local.date())}."
    if category:
        reason += f" The classifier labelled it {CATEGORY_LABEL[category]} (an AI label)."
    elif params.get("impact") == "high":
        reason += " The classifier rated it high impact (an AI label)."
    return {
        "fired_session": local.date(), "fired_price": None, "reason": reason,
        "evidence": {"announcement_id": r.get("announcement_id"), "source": r.get("source"), "subject": subject,
                     "filed_at": r.get("filed_at"), "url": r.get("attachment_url"), "symbol": r.get("ticker_symbol"),
                     "event_category": r.get("event_category"), "impact": r.get("impact_score")},
    }


_SIDE_WORD = {"BUY": "bought", "B": "bought", "SELL": "sold", "S": "sold"}


def deal_fire(alert: Dict[str, Any], rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    after = svc.ist_date(alert["created_at"])
    hits = []
    for r in rows:
        try:
            day = date.fromisoformat(str(r.get("as_of_date"))[:10])
        except ValueError:
            continue
        if day > after:
            hits.append((day, r.get("kind") or "", r.get("deal_seq") or 0, r))
    if not hits:
        return None
    day, kind, _, r = min(hits, key=lambda h: (h[0], h[1], h[2]))
    qty = r.get("quantity")
    price = svc._number(r.get("avg_price"))
    verb = _SIDE_WORD.get(str(r.get("deal_type") or "").strip().upper(), "traded")
    reason = (f"{r.get('client_name') or 'A client'} {verb} {qty:,} shares of {alert['symbol']}"
              f"{f' at {_rs(price)}' if price is not None else ''} in a {kind} deal on {_day_text(day)} "
              "(NSE's own deal disclosure).") if isinstance(qty, int) else (
              f"A {kind} deal in {alert['symbol']} on {_day_text(day)} (NSE's own deal disclosure).")
    return {"fired_session": day, "fired_price": None, "reason": reason,
            "evidence": {"session": day.isoformat(), "kind": kind, "client": r.get("client_name"),
                         "side": r.get("deal_type"), "quantity": qty, "price": price,
                         "pct_of_shares": r.get("pct_of_shares")}}


def scanner_fire(alert: Dict[str, Any], rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    after = svc.ist_date(alert["created_at"])
    stage = (alert.get("params") or {}).get("stage")
    for r in sorted(rows, key=lambda x: x["signal_date"]):
        if r["nse_symbol"] != alert["symbol"] or r["signal_date"] <= after or (stage and r["stage"] != stage):
            continue
        score = svc._number(float(r["final_score"])) if r.get("final_score") is not None else None
        return {"fired_session": r["signal_date"], "fired_price": None,
                "reason": (f"{alert['symbol']} entered the scanner's picks on {_day_text(r['signal_date'])} as "
                           f"{str(r['stage']).replace('_', ' ').lower()}{f' (score {score:.2f})' if score is not None else ''}."),
                "evidence": {"session": r["signal_date"].isoformat(), "stage": r["stage"], "score": score}}
    return None


def sector_fire(alert: Dict[str, Any], rows: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[date]]:
    """The first session after the alert date whose index close-to-close return reaches the threshold."""
    p = alert["params"]
    threshold, direction = float(p["threshold_pct"]), p["direction"]
    after = svc.ist_date(alert["created_at"])
    series = []
    for r in rows:
        close = svc._number(float(r["close_price"])) if r.get("close_price") is not None else None
        try:
            day = date.fromisoformat(str(r.get("as_of_date"))[:10])
        except ValueError:
            continue
        series.append((day, close))
    series.sort()
    checked: Optional[date] = None
    for (d0, c0), (d1, c1) in zip(series, series[1:]):
        if d1 <= after:
            continue
        if c0 is None or c1 is None or c0 <= 0:
            return None, checked
        ret = (c1 / c0 - 1) * 100.0
        checked = d1
        if (direction in ("up", "either") and ret >= threshold) or (direction in ("down", "either") and ret <= -threshold):
            return {"fired_session": d1, "fired_price": None,
                    "reason": (f"{p['index']} {'rose' if ret > 0 else 'fell'} {abs(ret):.2f}% on {_day_text(d1)} "
                               f"(close {c1:,.2f} against {c0:,.2f}; your threshold: {threshold:g}% "
                               f"{'either way' if direction == 'either' else direction})."),
                    "evidence": {"session": d1.isoformat(), "index": p["index"], "close": c1, "prev_close": c0,
                                 "return_pct": round(ret, 2)}}, d1
    return None, checked


# ── writes ───────────────────────────────────────────────────────────────────
async def fire(db, alert: Dict[str, Any], found: Dict[str, Any], now: Optional[datetime] = None
               ) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(the alert as stored afterwards, True when THIS call fired it). Never touches an alert that is not active."""
    stamp = svc._iso(now or svc.utcnow())
    session = found["fired_session"]
    change = {
        "status": "fired",
        "fired_at": stamp,
        "fired_session": session.isoformat() if isinstance(session, date) else session,
        "fired_price": found.get("fired_price"),
        "reason": found.get("reason"),
        "evidence": found.get("evidence"),
        "updated_at": stamp,
    }
    owner = {"_id": alert["_id"], "user_id": alert["user_id"]}
    res = await db[svc.ALERTS].update_one({**owner, "status": "active"}, {"$set": change})
    if res.matched_count:
        return {**alert, **change}, True
    return await db[svc.ALERTS].find_one(owner), False


async def _gather(keys: Iterable[Any], reader) -> Tuple[Dict[Any, List[Dict[str, Any]]], Dict[Any, str]]:
    data: Dict[Any, List[Dict[str, Any]]] = {}
    errors: Dict[Any, str] = {}
    gate = asyncio.Semaphore(svc.FETCH_CONCURRENCY)

    async def one(key: Any) -> None:
        try:
            async with gate:
                data[key] = await reader(key)
        except SourceUnavailable as exc:
            logger.warning("desk_alerts: %r could not be read: %s", key, exc)
            errors[key] = SOURCE_UNAVAILABLE
        except Exception as exc:  # noqa: BLE001 — one source's surprise must not stop every other check
            logger.exception("desk_alerts: reading %r failed: %r", key, exc)
            errors[key] = SOURCE_UNAVAILABLE

    await asyncio.gather(*(one(k) for k in set(keys)))
    return data, errors


async def evaluate(db, alerts: List[Dict[str, Any]], bars: Dict[str, List[Dict[str, Any]]], *,
                   persist: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Check every active alert. `bars` are the end-of-day bars of the bar-based alerts' symbols (read from
    bar_starts). Returns (alerts as they now stand, counts): counts carries `fired` and `already_fired` overall and
    per condition, `checked_through` per alert id and `check_errors` per alert id (a source that could not be read).
    With persist=False nothing is written (the script's dry run)."""
    active = [a for a in alerts if a.get("status") == "active"]
    since = lambda a: svc.ist_date(a["created_at"])  # noqa: E731

    # One read per source key, from the earliest alert date that key needs.
    filing_keys: Dict[Tuple[Optional[str], Optional[str]], date] = {}
    deal_keys: Dict[str, date] = {}
    index_keys: Dict[str, date] = {}
    scanner_syms: Dict[str, date] = {}

    def need(keys: Dict[Any, date], key: Any, day: date) -> None:
        keys[key] = min(keys.get(key, day), day)

    for a in active:
        cond, params = a["condition"], a.get("params") or {}
        if cond == "category" and params.get("category") == "deal":
            need(deal_keys, a["symbol"], since(a))
        elif cond in ("filing", "category"):
            need(filing_keys, (a.get("symbol"), params.get("category")), since(a))
        elif cond == "sector":
            need(index_keys, params["index"], since(a))
        elif cond == "scanner":
            need(scanner_syms, a["symbol"], since(a))

    filings, filing_errors = await _gather(filing_keys, lambda k: read_filings(k[0], k[1], filing_keys[k]))
    deals, deal_errors = await _gather(deal_keys, lambda s: read_deals(s, deal_keys[s]))
    index_rows, index_errors = await _gather(
        index_keys, lambda i: read_index(i, index_keys[i] - timedelta(days=INDEX_LOOKBACK_DAYS)))
    scanner_rows: List[Dict[str, Any]] = []
    scanner_error: Optional[str] = None
    if scanner_syms:
        try:
            scanner_rows = await read_scanner(sorted(scanner_syms), min(scanner_syms.values()))
        except SourceUnavailable as exc:
            logger.warning("desk_alerts: the scanner picks could not be read: %s", exc)
            scanner_error = SOURCE_UNAVAILABLE

    out: List[Dict[str, Any]] = []
    counts: Dict[str, Any] = {"fired": 0, "already_fired": 0, "by_condition": {}, "checked_through": {},
                              "check_errors": {}}
    for alert in alerts:
        if alert.get("status") != "active":
            out.append(alert)
            continue
        cond, sym, params = alert["condition"], alert.get("symbol"), alert.get("params") or {}
        found: Optional[Dict[str, Any]] = None
        checked: Optional[date] = None
        error: Optional[str] = None
        if cond in BAR_CONDITIONS:
            if sym not in bars:
                error = svc.PRICES_UNAVAILABLE
            elif cond in PRICE_CONDITIONS:
                found, checked = price_fire(alert, bars[sym])
            elif cond == "volume":
                found, checked = volume_fire(alert, bars[sym])
            else:
                found, checked = risk_fire(alert, bars[sym])
        elif cond in ("filing", "category") and params.get("category") != "deal":
            key = (sym, params.get("category"))
            if key in filing_errors or key not in filings:
                error = SOURCE_UNAVAILABLE
            else:
                found = filing_fire(alert, filings[key])
        elif cond == "category":
            if sym in deal_errors or sym not in deals:
                error = SOURCE_UNAVAILABLE
            else:
                found = deal_fire(alert, deals[sym])
        elif cond == "sector":
            idx = params["index"]
            if idx in index_errors or idx not in index_rows:
                error = SOURCE_UNAVAILABLE
            else:
                found, checked = sector_fire(alert, index_rows[idx])
        elif cond == "scanner":
            if scanner_error:
                error = scanner_error
            else:
                found = scanner_fire(alert, scanner_rows)
        counts["checked_through"][alert["_id"]] = checked
        if error:
            counts["check_errors"][alert["_id"]] = error
        if found is None:
            out.append(alert)
            continue
        if not persist:
            counts["fired"] += 1
            counts["by_condition"][cond] = counts["by_condition"].get(cond, 0) + 1
            out.append(alert)
            continue
        stored, mine = await fire(db, alert, found)
        if mine:
            counts["fired"] += 1
            counts["by_condition"][cond] = counts["by_condition"].get(cond, 0) + 1
            logger.info("desk_alerts: alert %s (%s %s) fired: %s", alert["_id"], cond, sym or params, found["reason"])
        else:
            counts["already_fired"] += 1
        if stored is not None:
            out.append(stored)
    return out, counts


# ── responses ────────────────────────────────────────────────────────────────
def describe(doc: Dict[str, Any]) -> str:
    """The alert in one plain line, e.g. "RELIANCE: a new exchange filing"."""
    cond, sym, p = doc.get("condition"), doc.get("symbol"), doc.get("params") or {}
    level = doc.get("level")
    if cond in PRICE_CONDITIONS:
        return f"{sym}: price {'at or above' if cond == 'above' else 'at or below'} {_rs(float(level))}" if level is not None else f"{sym}: price {cond}"
    if cond == "filing":
        return f"{sym}: a new exchange filing" + (" rated high impact (AI label)" if p.get("impact") == "high" else "")
    if cond == "category":
        label = CATEGORY_LABEL.get(p.get("category"), p.get("category"))
        return f"{sym}: a new {label.lower()}" if sym else f"Any company: a new {label.lower()} filing"
    if cond == "volume":
        return f"{sym}: volume at {p.get('multiple'):g}× its {VOLUME_BASE_SESSIONS}-session average" if p.get("multiple") else f"{sym}: unusual volume"
    if cond == "scanner":
        stage = p.get("stage")
        return f"{sym}: enters the scanner's picks" + (f" as {stage.replace('_', ' ').lower()}" if stage else "")
    if cond == "sector":
        way = {"up": "rises", "down": "falls", "either": "moves"}[p.get("direction", "either")]
        return f"{p.get('index')}: {way} {p.get('threshold_pct'):g}% or more in a session"
    if cond == "risk":
        return f"{sym}: {ATR_SESSIONS}-session ATR at {float(level):g}% of price or more" if level is not None else f"{sym}: risk"
    return str(cond)


def public_alert(doc: Dict[str, Any], mark: Optional[Dict[str, Any]] = None, mark_error: Optional[str] = None,
                 checked_through: Optional[date] = None, check_error: Optional[str] = None) -> Dict[str, Any]:
    out = svc.public_alert({**doc, "symbol": doc.get("symbol"), "level": doc.get("level")}, mark, mark_error, checked_through)
    is_active = doc.get("status") == "active"
    reason = doc.get("reason")
    if reason is None and doc.get("status") == "fired" and doc.get("condition") in PRICE_CONDITIONS and doc.get("fired_session"):
        # Fired before reasons were stored: the stored session and level say why.
        reason = (f"{doc['symbol']} reached your level of {_rs(float(doc['level']))} on "
                  f"{_day_text(date.fromisoformat(doc['fired_session']))}.")
    out.update({
        "params": doc.get("params") or {},
        "label": describe(doc),
        "rule": RULES.get(doc.get("condition"), ""),
        "reason": reason,
        "evidence": doc.get("evidence"),
        "check_error": check_error if is_active else None,
    })
    if doc.get("condition") not in PRICE_CONDITIONS:
        out["last_close"] = None if doc.get("condition") not in BAR_CONDITIONS else out["last_close"]
    return out


def catalogue() -> Dict[str, Any]:
    """What the client may create: every condition with its rule, and the accepted values."""
    return {
        "conditions": [{"condition": c, "rule": RULES[c]} for c in CONDITIONS],
        "categories": [{"key": k, "label": CATEGORY_LABEL[k]} for k in CATEGORIES],
        "stages": list(SCANNER_STAGES),
        "sector_indices": list(SECTOR_INDEX_NAMES),
        "ranges": {"multiple": list(MULTIPLE_RANGE), "risk_level": list(RISK_RANGE), "threshold_pct": list(THRESHOLD_RANGE)},
        "check_note": CHECK_NOTE,
        "delivery": "in_app",
    }

