"""Scanner event ingest (PRD §6.2; Workflow §4.2 steps 7–9, §4.4, §4.5, §5.2 steps 1–4).

A list mark (services/scan_builder/signals.record: {id, widget_id, widget_title, symbol, first_seen, entry, direction, ...})
or a strong signal (signals.record_strong: {symbol, score_at, parts_at, lists_at, first_strong, entry, stop_loss, ...})
becomes ONE immutable event in `spt_signal_events` with the PRD §6.2 fields plus the normalized ones (normalize.py):

    signal_id / _id     sig:<day>:<widget>:<SYMBOL> (list mark) · sig:<day>:strong:<SYMBOL> (strong signal)
    detected_at         the mark's `first_seen` / the strong record's `first_strong`, as UTC ISO (the raw IST string stays in
                        supporting_metrics); detected_price = its `entry` (the live price then)
    scanner_score       strong: `score_at`. List mark: the stock's strength score from the day's scores doc
                        (signals.load_scores) ONLY when that doc was saved at or after the detection and at most
                        SCORE_MATCH_S later. The scan round that records a mark scores the stock and saves the doc with the
                        same timestamp afterwards; a doc saved before the detection predates the mark (a stock new to the
                        lists is not in it) and one saved much later is not the score at detection → null with
                        scanner_score_note. Never invented.
    supporting_metrics  the raw record exactly as the scan stored it
    market_regime       null at ingest (the validation records the regime it read, with its date)
    expiry_at           the end of the signal's consolidation window (clock.window_until)
    status              "normalized", or "quarantined" with quarantine_reasons (Workflow §4.4):
                            missing_mapping    the widget is not in normalize.LIST_MAP (strong: none of its lists is)
                            invalid_symbol     not an NSE trading symbol (A–Z, 0–9, & and -; at most 20)
                            missing_price      no positive detection price
                            invalid_timestamp  no parseable, timezone-aware time, or its IST day is not the record's day
                            outside_session    detected outside 09:15–15:30 IST on a weekday
                            stale              received more than STALE_GRACE_S after its expiry_at (an expired signal
                                               delivered late; PRD §23.3 scenario 12): stored for the record and for
                                               outcomes, never consolidated. The grace covers the hook's own delay for a
                                               mark recorded in the session's last seconds.
                        A quarantined event is still stored (Workflow §4.5: the original event is preserved).
    outcome_eligible    symbol, price and time are valid (the signal can be measured even when it was received late)

Duplicates are no-ops: the `_id` exists, nothing is written and no event is emitted (Workflow §20.2).
Events (events.py, DESIGN.md §7): SCANNER_SIGNAL_RECEIVED for every stored event (key `sig:<id>:received`) and
SCANNER_SIGNAL_NORMALIZED for a normalized one (key `sig:<id>:normalized`).
"""
from __future__ import annotations

import copy
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .. import constants as C
from .. import events
from . import clock, normalize, store

logger = logging.getLogger(__name__)

SOURCE = "spt-signal-ingest"
SCORE_MATCH_S = 120
STALE_GRACE_S = 120
SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
OUTCOME_BLOCKERS = {"invalid_symbol", "missing_price", "invalid_timestamp"}
SCAN_SOURCE = "Scan dashboard signals (services/scan_builder/signals.py, Redis)"
REGIME_NOTE = "not read at ingest; the opportunity's validation records the regime it read, with its date"

EXPLAIN = {
    "missing_mapping": "The list is not in the SPT list map ({wid}), so its category and horizon are unknown.",
    "invalid_symbol": "The symbol {sym!r} is not an NSE trading symbol.",
    "missing_price": "The record has no price at detection.",
    "invalid_timestamp": "The detection time {ts!r} is missing, unparseable, without a timezone, or not on {day}.",
    "outside_session": "Detected at {ts}, outside the 09:15–15:30 IST weekday session.",
    "stale": "Received at {now}, more than " + str(STALE_GRACE_S) + " s after the signal's expiry ({exp}): an expired "
             "signal delivered late.",
}


def list_signal_id(day: str, widget_id: str, symbol: str) -> str:
    return f"sig:{day}:{widget_id}:{symbol}"


def strong_signal_id(day: str, symbol: str) -> str:
    return f"sig:{day}:strong:{symbol}"


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _score_from_doc(symbol: str, detected: Optional[datetime], scores_doc: Optional[Dict[str, Any]]):
    """(score, score_as_of, note) for a list mark from the day's scores doc (see the module docstring)."""
    doc = scores_doc or {}
    as_of = clock.parse_ts(doc.get("as_of"))
    if detected is None:
        return None, None, "no valid detection time to match a score to"
    if as_of is None:
        return None, None, "no scores doc for the day"
    lag = (as_of - detected).total_seconds()
    if lag < 0 or lag > SCORE_MATCH_S:
        return None, clock.utc_iso(as_of), (f"the day's scores are as of {doc.get('as_of')}, {lag:+.0f} s from the "
                                            f"detection (match window 0 to +{SCORE_MATCH_S} s): not the score at detection")
    rec = (doc.get("scores") or {}).get(symbol) or {}
    sc = rec.get("score")
    if not isinstance(sc, (int, float)) or isinstance(sc, bool):
        why = rec.get("note") or "the stock is not in the day's scores yet"
        return None, clock.utc_iso(as_of), f"no score for the stock at detection ({why})"
    return sc, clock.utc_iso(as_of), None


def _checks(*, mapped: bool, symbol: Any, price: Optional[float], detected: Optional[datetime], day: str,
            expiry: Optional[datetime], now: datetime) -> List[str]:
    reasons: List[str] = []
    if not mapped:
        reasons.append("missing_mapping")
    if not isinstance(symbol, str) or not SYMBOL_RE.match(symbol):
        reasons.append("invalid_symbol")
    if price is None or price <= 0:
        reasons.append("missing_price")
    if detected is None or clock.ist_day(detected).isoformat() != day:
        reasons.append("invalid_timestamp")
    elif not clock.in_session(detected):
        reasons.append("outside_session")
    if expiry is not None and (now - expiry).total_seconds() > STALE_GRACE_S:
        reasons.append("stale")
    return reasons


def _explain(reasons: Sequence[str], **kw: Any) -> List[str]:
    out = []
    for r in reasons:
        try:
            out.append(EXPLAIN[r].format(**kw))
        except (KeyError, IndexError):
            out.append(r)
    return out


def _event(*, kind: str, signal_id: str, day: str, raw: Dict[str, Any], norm: Dict[str, Any], scanner_id: str,
           scanner_name: Any, symbol: Any, ts_raw: Any, price_raw: Any, score: Any, score_version: Optional[str],
           score_as_of: Optional[str], score_note: Optional[str], now: datetime, via: str, key: Optional[str],
           window_sessions: int) -> Dict[str, Any]:
    detected = clock.parse_ts(ts_raw)
    price = _num(price_raw)
    expiry = None
    if detected is not None and norm.get("horizon"):
        expiry = clock.window_until(clock.ist_day(detected), norm["horizon"], window_sessions)
    reasons = _checks(mapped=norm["mapped"], symbol=symbol, price=price, detected=detected, day=day, expiry=expiry, now=now)
    status = "quarantined" if reasons else "normalized"
    return {
        "_id": signal_id, "signal_id": signal_id, "kind": kind, "day": day,
        "scanner_id": scanner_id, "scanner_name": scanner_name,
        "instrument_id": symbol, "symbol": symbol, "exchange": "NSE", "segment": "Equity",
        "direction": norm.get("direction"), "bias": norm.get("bias"), "timeframe": norm.get("timeframe"),
        "horizon": norm.get("horizon"), "category": norm.get("category"), "signal_type": norm.get("category"),
        "family": norm.get("family"),
        "detected_at": clock.utc_iso(detected) if detected else None,
        "detected_price": round(price, 2) if price is not None else None,
        "scanner_score": score, "score_version": score_version if score is not None else None,
        "score_as_of": score_as_of, "scanner_score_note": score_note,
        "supporting_metrics": copy.deepcopy(raw),
        "market_regime": None, "market_regime_note": REGIME_NOTE,
        "expiry_at": clock.utc_iso(expiry) if expiry else None,
        "status": status, "quarantine_reasons": reasons,
        "explanations": _explain(reasons, wid=scanner_id, sym=symbol, ts=ts_raw, day=day, now=clock.utc_iso(now),
                                 exp=clock.utc_iso(expiry) if expiry else None),
        "outcome_eligible": not (set(reasons) & OUTCOME_BLOCKERS),
        "source": {"store": SCAN_SOURCE, "key": key, "rules": raw.get("rules"), "via": via},
        "normalizer_version": C.NORMALIZER_VERSION,
        "received_at": clock.utc_iso(now),
    }


def list_event(entry: Dict[str, Any], *, day: str, scores_doc: Optional[Dict[str, Any]], now: datetime,
               via: str = "hook", window_sessions: Optional[int] = None) -> Dict[str, Any]:
    """The event of one list mark (pure)."""
    wid, sym = entry.get("widget_id"), entry.get("symbol")
    norm = normalize.for_list(wid, entry.get("direction"))
    detected = clock.parse_ts(entry.get("first_seen"))
    score, as_of, note = _score_from_doc(sym, detected, scores_doc) if isinstance(sym, str) else (None, None, "no symbol")
    key = f"nivesh:sb:signals:{day}:s:{wid}:{sym}"
    return _event(kind="list", signal_id=list_signal_id(day, str(wid), str(sym)), day=day, raw=entry, norm=norm,
                  scanner_id=str(wid), scanner_name=entry.get("widget_title") or wid, symbol=sym,
                  ts_raw=entry.get("first_seen"), price_raw=entry.get("entry"), score=score,
                  score_version=normalize.SCORE_VERSION, score_as_of=as_of, score_note=note, now=now, via=via, key=key,
                  window_sessions=window_sessions or clock.window_sessions())


def strong_event(rec: Dict[str, Any], *, day: str, now: datetime, via: str = "hook",
                 window_sessions: Optional[int] = None) -> Dict[str, Any]:
    """The event of one strong signal (pure). Its score is the frozen `score_at`."""
    sym = rec.get("symbol")
    norm = normalize.for_strong(rec)
    sc = rec.get("score_at")
    score = sc if isinstance(sc, (int, float)) and not isinstance(sc, bool) else None
    key = f"nivesh:sb:signals:{day}:g:{sym}"
    return _event(kind="strong", signal_id=strong_signal_id(day, str(sym)), day=day, raw=rec, norm=norm,
                  scanner_id=normalize.STRONG_SCANNER_ID, scanner_name=normalize.STRONG_SCANNER_NAME, symbol=sym,
                  ts_raw=rec.get("first_strong"), price_raw=rec.get("entry"), score=score,
                  score_version=normalize.SCORE_VERSION, score_as_of=None,
                  score_note=None if score is not None else "the strong record has no score_at",
                  now=now, via=via, key=key, window_sessions=window_sessions or clock.window_sessions())


async def _emit(db, doc: Dict[str, Any]) -> None:
    sid = doc["signal_id"]
    await events.emit(db, "SCANNER_SIGNAL_RECEIVED", idempotency_key=f"sig:{sid}:received", source_service=SOURCE,
                      occurred_at=doc["received_at"], instrument_id=doc.get("symbol") if isinstance(doc.get("symbol"), str) else None,
                      correlation_id=sid,
                      payload={"signal_id": sid, "kind": doc["kind"], "scanner_id": doc["scanner_id"],
                               "symbol": doc["symbol"], "detected_at": doc["detected_at"],
                               "detected_price": doc["detected_price"], "scanner_score": doc["scanner_score"],
                               "status": doc["status"], "quarantine_reasons": doc["quarantine_reasons"]})
    if doc["status"] == "normalized":
        await events.emit(db, "SCANNER_SIGNAL_NORMALIZED", idempotency_key=f"sig:{sid}:normalized", source_service=SOURCE,
                          occurred_at=doc["received_at"], instrument_id=doc["symbol"], correlation_id=sid,
                          payload={"signal_id": sid, "category": doc["category"], "family": doc["family"],
                                   "timeframe": doc["timeframe"], "horizon": doc["horizon"], "direction": doc["direction"],
                                   "expiry_at": doc["expiry_at"], "normalizer_version": doc["normalizer_version"]})


def _counts() -> Dict[str, Any]:
    return {"seen": 0, "inserted": 0, "duplicate": 0, "normalized": 0, "quarantined": 0, "errors": 0, "reasons": {}}


async def store_events(db, docs: Iterable[Dict[str, Any]], counts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Insert each event (a duplicate is a no-op) and emit its events. One failing insert is counted and logged; the rest
    go on."""
    counts = counts if counts is not None else _counts()
    for doc in docs:
        counts["seen"] += 1
        try:
            stored = await store.insert(db, doc)
        except Exception as e:  # noqa: BLE001 — the next catch-up round inserts it again (idempotent)
            counts["errors"] += 1
            logger.warning("spt ingest: %s not stored (%s)", doc.get("signal_id"), type(e).__name__)
            continue
        if not stored:
            counts["duplicate"] += 1
            continue
        counts["inserted"] += 1
        counts[doc["status"]] += 1
        for r in doc["quarantine_reasons"]:
            counts["reasons"][r] = counts["reasons"].get(r, 0) + 1
        await _emit(db, doc)
    return counts


async def ingest(db, *, day: str, marks: Sequence[Dict[str, Any]] = (), strong: Sequence[Dict[str, Any]] = (),
                 scores_doc: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None, via: str = "hook",
                 skip_ids: Optional[set] = None) -> Dict[str, Any]:
    """Build and store the events of `marks` (list marks) and `strong` (strong records) of IST `day`. `skip_ids`: ids known
    to be stored already (not rebuilt). Returns counts {seen, inserted, duplicate, normalized, quarantined, errors, reasons}."""
    now = now or datetime.now(timezone.utc)
    skip = skip_ids or set()
    n = clock.window_sessions()
    docs: List[Dict[str, Any]] = []
    for m in marks:
        if not isinstance(m, dict):
            continue
        sid = list_signal_id(day, str(m.get("widget_id")), str(m.get("symbol")))
        if sid not in skip:
            docs.append(list_event(m, day=day, scores_doc=scores_doc, now=now, via=via, window_sessions=n))
    for r in strong:
        if not isinstance(r, dict):
            continue
        sid = strong_signal_id(day, str(r.get("symbol")))
        if sid not in skip:
            docs.append(strong_event(r, day=day, now=now, via=via, window_sessions=n))
    docs.sort(key=lambda d: d.get("detected_at") or "")
    return await store_events(db, docs)
