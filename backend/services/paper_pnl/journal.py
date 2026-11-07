"""Signals at entry for one paper share trade (docs/paper_pnl_dashboard/DESIGN.md "v2", GET /api/desk/pnl/journal/{trade_id}).

The Scan dashboard keeps each day's signals in Redis for 3 days (services/scan_builder/signals.py, TTL_S): the strong record of a
stock that reached score 70 that day (its score, five parts, reasons and the positional plan frozen then) and the day's stored
scores. This reads them for the trade's stock on its SIGNAL day — the trade's own `source.signal_date` when it names one, else
the IST day the trade was recorded (a conditional entry may fill days later; the signal it came from is the recording day's).
Read-only: nothing is written, here or in the store.

Paper share trades only. A structure (no single stock), a broker position (no entry signal is recorded) or a trade that is not
the user's answers `None`, which the route turns into 404 journal_not_available.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from services.kite_live_feed import config as cfg

from .book import Book

logger = logging.getLogger(__name__)

KEPT_DAYS = 3
_PART_KEYS = ("quality", "trend", "reason", "size", "participation", "penalty")


def _ist_day(stamp: Any) -> Optional[str]:
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return str(stamp)[:10] if len(str(stamp)) >= 10 else None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(cfg.IST).date().isoformat()


def _when(day: str) -> str:
    try:
        return date.fromisoformat(day).strftime("%-d %b")
    except ValueError:
        return day


def _parts(p: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(p, dict):
        return None
    return {k: p.get(k) for k in _PART_KEYS}


def _lists(raw: Any) -> List[Dict[str, Any]]:
    out = []
    for x in raw or []:
        if isinstance(x, dict) and x.get("id"):
            out.append({"id": str(x["id"]), "title": x.get("title") or str(x["id"])})
    return out


def find_trade(book: Book, trade_id: str):
    """The user's paper SHARE trade (open or closed) with this id, or None."""
    for item in list(book.open) + list(book.closed):
        if item.trade_id == trade_id:
            return item if item.kind == "cash" else None
    return None


async def journal(book: Book, trade_id: str, *, now: Optional[datetime] = None, store: Any = None) -> Optional[Dict[str, Any]]:
    """The journal body for `trade_id`, or None when it is not one of the user's paper share trades."""
    from services.scan_builder import signals as sig

    item = find_trade(book, trade_id)
    if item is None:
        return None
    pub = item.public
    sym = str(pub.get("symbol") or (item.legs[0].symbol if item.legs else "")).upper()
    source = pub.get("source") if isinstance(pub.get("source"), dict) else None
    day = (source or {}).get("signal_date") or _ist_day(pub.get("opened_at")) or item.entry_session
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(cfg.IST).date()
    trade = {"source": source, "rationale": pub.get("rationale"), "note": pub.get("note"), "opened_at": pub.get("opened_at"),
             "entry_rule": pub.get("entry_rule"), "entry_session": item.entry_session}
    body: Dict[str, Any] = {"trade_id": trade_id, "symbol": sym, "entry_day": day, "found": False, "why": None, "signal": None,
                            "trade": trade}
    if not day or not sym:
        body["why"] = "The trade records no day or stock to look its signal up by."
        return body
    store = store or sig.get_store()
    signal: Optional[Dict[str, Any]] = None
    unreadable = False
    try:
        index, _ = sig._strong_keys(day)
        for raw in await store.read(index, sig.MAX_STRONG):
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if str(rec.get("symbol") or "").upper() == sym:
                signal = {"kind": "strong", "first_strong": rec.get("first_strong"), "score": rec.get("score_at"),
                          "parts": _parts(rec.get("parts_at")), "reasons": list(rec.get("reasons_at") or []),
                          "penalties": list(rec.get("penalties_at") or []), "lists": _lists(rec.get("lists_at")),
                          **{k: rec.get(k) for k in ("entry", "stop_loss", "target_1", "target_2", "rr_1", "rr_2", "trend_exit",
                                                      "plan_ok", "plan_note", "rules")}}
                break
    except Exception as e:  # noqa: BLE001 — answered as "could not be read", never as "no signal"
        logger.warning("paper_pnl journal: strong signals unreadable (%s)", type(e).__name__)
        unreadable = True
    if signal is None:
        try:
            doc = await sig.load_scores(day, store=store)
            sc = (doc.get("scores") or {}).get(sym)
        except Exception as e:  # noqa: BLE001
            logger.warning("paper_pnl journal: day scores unreadable (%s)", type(e).__name__)
            sc, unreadable = None, True
        if isinstance(sc, dict) and sc.get("score") is not None:
            lists: List[Dict[str, Any]] = []
            try:
                seen = set()
                for m in await sig.day_marks(day, store=store):
                    if str(m.get("symbol") or "").upper() == sym and m.get("widget_id") and m["widget_id"] not in seen:
                        seen.add(m["widget_id"])
                        lists.append({"id": str(m["widget_id"]), "title": m.get("widget_title") or str(m["widget_id"])})
            except Exception as e:  # noqa: BLE001 — the score stands without its lists
                logger.warning("paper_pnl journal: day marks unreadable (%s)", type(e).__name__)
            signal = {"kind": "scored", "first_strong": None, "score": sc.get("score"), "parts": _parts(sc.get("parts")),
                      "reasons": list(sc.get("reasons") or []), "penalties": list(sc.get("penalties") or []), "lists": lists,
                      "entry": None, "stop_loss": None, "target_1": None, "target_2": None, "rr_1": None, "rr_2": None,
                      "trend_exit": None, "plan_ok": False,
                      "plan_note": sc.get("note") or "Below the strong threshold (70) that day: no plan was frozen.",
                      "rules": None}
    if signal is not None:
        body.update(found=True, signal=signal)
        return body
    try:
        age = (today - date.fromisoformat(day)).days
    except ValueError:
        age = 0
    if unreadable:
        body["why"] = "The Scan dashboard's signal store could not be read just now."
    elif age > KEPT_DAYS:
        body["why"] = f"Scan signals are kept {KEPT_DAYS} days; this trade's signal day was {_when(day)}."
    else:
        body["why"] = f"No scan signal for {sym} on {_when(day)}."
    return body
