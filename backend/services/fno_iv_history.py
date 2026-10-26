"""Daily ATM implied volatility per F&O underlying (Mongo `fno_iv_history`), and IV rank / IV percentile over it.

One document per underlying and session, `_id` "<UNDERLYING>:<YYYY-MM-DD>" (an upsert by that key: running the
recorder twice for a session leaves one document). The figures are worked out by routes/fno.py :: session_iv, the
chain route's own model (Black-76 on the forward, services/option_pricing) on that session's NSE F&O bhavcopy rows,
read from the data platform (DaaS /v1/fno/{symbol}?on=<day>, nidp.fno_bhavcopy). The bhavcopy is an end-of-day
file, so a session worked out later from the stored file gives the figures the recorder would have written that
night; `method` says which happened first ("recorded" by the nightly run, or "backfill" from the stored file).

    {
      "_id": "NIFTY:2026-10-23", "underlying": "NIFTY", "date": "2026-10-23",
      "as_of": "2026-10-23",            the day the data platform answered for (a row is written only when it is `date`)
      "calc_version": CALC_VERSION, "source": SOURCE, "rate_pct": 5.75 (option_pricing.RISK_FREE_RATE),
      "buckets": {
        "near_month": {expiry, days_to_expiry, atm_strike, spot, future_settle, forward, forward_basis,
                       call_iv, call_iv_price, put_iv, put_iv_price, atm_iv, reason},
        "next_month": {...}
      },
      "method": "recorded" | "backfill", "recorded_at": first write (UTC), "computed_at": latest write (UTC)
    }

A session the data platform has no rows for (a holiday, a day not loaded) or could not be read for has no document:
nothing is interpolated or carried over. A session that was read but whose ATM IV cannot be worked out keeps a
document with `atm_iv` null and the `reason`, so the gap is visible; it never counts as a value.

IV rank and IV percentile (`iv_rank`, `iv_percentile`), over a window of daily ATM IVs, oldest first, whose last
value is the current session's:

    IV rank        (current − lowest) ÷ (highest − lowest) × 100, over the whole window (current included):
                   where the current IV sits between the window's extremes. Undefined when highest = lowest.
    IV percentile  the share of the window's EARLIER sessions whose IV is strictly below the current IV, × 100:
                   how often the IV was lower than it is now.

    Worked by hand (tests/test_fno_iv_history.py uses it), window 10, 30, 12, 14, 11, 13 (current 13):
        lowest 10, highest 30            rank = (13 − 10) ÷ (30 − 10) × 100 = 3 ÷ 20 × 100 = 15.0
        earlier sessions 10 30 12 14 11  below 13: 10, 12, 11 = 3 of 5   percentile = 3 ÷ 5 × 100 = 60.0
    The one spike to 30 squeezes the rank; the percentile is not moved by how far the spike went.

The route reports both only with MIN_SESSIONS (252, about a year of NSE sessions) recorded sessions that have an IV
of the current CALC_VERSION, over the latest 252 of them; otherwise both are null and `reason` says how many exist.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

COLLECTION = "fno_iv_history"
CALC_VERSION = "fno-atm-iv-v1"
SOURCE = ("NSE F&O bhavcopy (nidp.fno_bhavcopy) via DaaS /v1/fno/{symbol}?on=<day>; ATM IV by the chain route's "
          "model (routes/fno.py session_iv: Black-76 on the forward, services/option_pricing)")
BUCKETS = ("near_month", "next_month")
METHODS = ("recorded", "backfill")
MIN_SESSIONS = 252
DEFAULT_DAYS = 252
MAX_DAYS = 1000
READ_LIMIT = 5000           # sessions read per underlying (about twenty years): every row the route counts

# What one point of the route's series carries from its bucket and its document.
_POINT_BUCKET_FIELDS = ("atm_iv", "call_iv", "put_iv", "expiry", "days_to_expiry", "atm_strike", "spot",
                        "future_settle", "forward", "forward_basis", "reason")


def doc_id(underlying: str, day: str) -> str:
    return f"{underlying}:{day}"


def build_doc(underlying: str, day: str, buckets: Dict[str, Dict[str, Any]], rate_pct: float) -> Dict[str, Any]:
    """The stored document without its timestamps and `method` (upsert sets those)."""
    return {
        "_id": doc_id(underlying, day), "underlying": underlying, "date": day, "as_of": day,
        "calc_version": CALC_VERSION, "source": SOURCE, "rate_pct": rate_pct,
        "buckets": {name: dict(buckets.get(name) or {}) for name in BUCKETS},
    }


async def upsert(db, doc: Dict[str, Any], method: str, now: Optional[datetime] = None) -> bool:
    """Write the session's document by its `_id`. The figures are replaced (the same session's file gives the same
    figures); `method` and `recorded_at` keep their first value. True when the document was new."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}, not {method!r}")
    at = now or datetime.now(timezone.utc)
    body = {k: v for k, v in doc.items() if k != "_id"}
    res = await db[COLLECTION].update_one(
        {"_id": doc["_id"]},
        {"$set": {**body, "computed_at": at}, "$setOnInsert": {"method": method, "recorded_at": at}},
        upsert=True,
    )
    return res.upserted_id is not None


async def ensure_indexes(db) -> None:
    await db[COLLECTION].create_index([("underlying", 1), ("date", -1)])


async def recorded_days(db, underlying: str, version: str = CALC_VERSION) -> set:
    """The sessions already stored for the underlying with this calculation version."""
    cur = db[COLLECTION].find({"underlying": underlying, "calc_version": version}, {"_id": 0, "date": 1})
    return {d["date"] async for d in cur if isinstance(d.get("date"), str)}


async def read_rows(db, underlying: str) -> List[Dict[str, Any]]:
    """Every stored session of the underlying, oldest first. Raises when the store cannot be read."""
    cur = db[COLLECTION].find({"underlying": underlying}, {"_id": 0}).sort("date", 1).limit(READ_LIMIT)
    return [d async for d in cur]


# ── IV rank and IV percentile ────────────────────────────────────────────────

def _iv(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
        return None
    return float(v)


def iv_rank(window: Sequence[float]) -> Optional[float]:
    """(current − lowest) ÷ (highest − lowest) × 100 over the window (oldest first, the last value current),
    to one decimal. None for an empty window or one whose highest equals its lowest."""
    if not window:
        return None
    lo, hi, cur = min(window), max(window), window[-1]
    if hi == lo:
        return None
    return round((cur - lo) / (hi - lo) * 100.0, 1)


def iv_percentile(window: Sequence[float]) -> Optional[float]:
    """Share of the window's earlier sessions with an IV strictly below the current (last) one, × 100, to one
    decimal. None without at least one earlier session."""
    if len(window) < 2:
        return None
    cur, earlier = window[-1], window[:-1]
    return round(sum(1 for v in earlier if v < cur) / len(earlier) * 100.0, 1)


# ── the route's answer ───────────────────────────────────────────────────────

def _point(doc: Dict[str, Any], bucket: str) -> Dict[str, Any]:
    b = (doc.get("buckets") or {}).get(bucket) or {}
    p = {"date": doc.get("date")}
    p.update({k: b.get(k) for k in _POINT_BUCKET_FIELDS})
    p["atm_iv"] = _iv(p["atm_iv"])
    if p["atm_iv"] is None and not p["reason"]:
        p["reason"] = f"no {bucket} ATM IV stored for this session"
    p.update(rate_pct=doc.get("rate_pct"), calc_version=doc.get("calc_version"), method=doc.get("method"))
    return p


def history_answer(underlying: str, docs: Iterable[Dict[str, Any]], bucket: str, days: int,
                   min_sessions: int = MIN_SESSIONS) -> Dict[str, Any]:
    """The route's body from the stored documents. Only stored sessions appear; none is estimated."""
    points = sorted((_point(d, bucket) for d in docs if isinstance(d, dict) and isinstance(d.get("date"), str)),
                    key=lambda p: p["date"])
    usable = [p for p in points if p["atm_iv"] is not None and p["calc_version"] == CALC_VERSION]
    current = points[-1] if points else None
    out: Dict[str, Any] = {
        "symbol": underlying, "bucket": bucket, "calc_version": CALC_VERSION, "source": SOURCE,
        "series": points[-days:], "requested_days": days,
        "sessions": len(usable), "sessions_without_iv": sum(1 for p in points if p["atm_iv"] is None),
        "sessions_other_version": sum(1 for p in points if p["atm_iv"] is not None and p["calc_version"] != CALC_VERSION),
        "first_session": points[0]["date"] if points else None, "last_session": current["date"] if current else None,
        "methods": {m: sum(1 for p in points if p["method"] == m) for m in METHODS},
        "current": current, "min_sessions": min_sessions,
        "iv_rank": None, "iv_percentile": None, "window": None, "reason": None,
        "note": "Only recorded sessions are listed; a session that was not recorded is absent, never estimated.",
        "read_only": True,
    }
    if current is None:
        out["reason"] = (f"No IV history is recorded for {underlying}. The nightly recorder (scripts/record_iv_history.py) "
                         f"writes one row per session; past sessions exist only once its backfill has read them from the "
                         f"data platform's stored bhavcopy.")
        return out
    if current["atm_iv"] is None or current["calc_version"] != CALC_VERSION:
        out["reason"] = (f"The latest recorded session ({current['date']}) has no {bucket} ATM IV "
                         f"({current['reason'] or 'another calculation version'}), so IV rank and IV percentile are not worked out.")
        return out
    if len(usable) < min_sessions:
        out["reason"] = (f"{len(usable)} sessions with a {bucket} ATM IV are recorded for {underlying}; IV rank and IV "
                         f"percentile need {min_sessions} (about one year of sessions).")
        return out
    win = usable[-min_sessions:]
    values = [p["atm_iv"] for p in win]
    first, last = win[0]["date"], win[-1]["date"]
    out["window"] = {"sessions": len(win), "from": first, "to": last, "min": min(values), "max": max(values),
                     "calendar_days": (date.fromisoformat(last) - date.fromisoformat(first)).days}
    out["iv_rank"], out["iv_percentile"] = iv_rank(values), iv_percentile(values)
    if out["iv_rank"] is None:
        out["reason"] = "The ATM IV did not change over the window, so IV rank is undefined."
    return out
