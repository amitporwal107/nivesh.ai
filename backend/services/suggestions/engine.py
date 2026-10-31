"""Evaluate the rules for one user and rank what they produce.

    rules (store.rules) ─► inputs (market cached, personal per user) ─► freshness gate ─► evaluators (rules.py)
      ─► cards (template query, title/why from facts, class wording) ─► feedback suppression + cooldowns
      ─► rank (class urgency, priority, evidence freshness, audience, feedback) ─► dedupe across tabs
      ─► persist instances + events ─► the requested tab, with notices for every source that was stale or missing

FRESHNESS (owner rule): a rule whose input is stale, missing or unreadable produces nothing; the tab says which source
and why ("prices stale", "broker disconnected") instead. "session" = today's or the previous NSE session's data
(services/market_freshness.window); "days" = not older than N calendar days (the user's holdings).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.copilot_visual.payload import day_text, iso_day

from . import catalog, inputs, store
from .inputs import MARKET, Input
from .rules import EVALUATORS

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
PER_TAB = 8
MEMO_SECONDS = 60
STARTER_TTL_HOURS = 24
EVENT_TTL_HOURS = 72
FEEDBACK_DAYS = 30
RULE_FEEDBACK_DAYS = 7

_memo: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}


def forget(user_id: str) -> None:
    for k in [k for k in _memo if k[0] == user_id]:
        _memo.pop(k, None)


class _Facts(dict):
    def __missing__(self, key: str) -> str:
        raise KeyError(key)


def _fmt(text: str, facts: Dict[str, Any]) -> Optional[str]:
    try:
        return text.format_map(_Facts({k: v for k, v in facts.items() if v is not None}))
    except (KeyError, ValueError, IndexError):
        return None


def _status(inp: Input, spec: Dict[str, Any], window: Any, today: date) -> str:
    if inp.error:
        return "missing"
    if inp.empty:
        return "empty"
    if spec.get("kind") == "none":
        return "fresh"
    d = iso_day(inp.as_of)
    if not d:
        return "missing"
    if spec.get("kind") == "days":
        return "fresh" if date.fromisoformat(d) >= today - timedelta(days=int(spec.get("days") or 7)) else "stale"
    return "fresh" if window.current(d) else "stale"


def _freshness_bonus(as_of: Optional[str], today: date) -> int:
    d = iso_day(as_of)
    if not d:
        return 0
    age = (today - date.fromisoformat(d)).days
    return 20 if age <= 0 else 10 if age <= 3 else 5


def _notice(name: str, inp: Input, status: str, window: Any) -> Dict[str, Any]:
    day = day_text(inp.as_of) or "an unknown date"
    if status == "stale" and name == "holdings":
        text = (f"Your holdings were last updated on {day}. Suggestions about them are paused until they are refreshed: "
                "upload a newer statement or sync a broker.")
        return {"kind": "stale", "source": inp.label, "as_of": iso_day(inp.as_of), "text": text, "action": "refresh_holdings"}
    if status == "stale" and name in ("paper_trades", "risk_book"):
        text = (f"Prices stale: your paper trades are marked at the close of {day}, older than the previous session "
                f"({day_text(window.floor)}). No trade alert is shown until the marks are current.")
        return {"kind": "stale", "source": inp.label, "as_of": iso_day(inp.as_of), "text": text}
    if status == "stale":
        text = (f"{inp.label}: the newest data is from {day}, older than the previous session ({day_text(window.floor)}). "
                "Nothing is suggested from it today.")
        return {"kind": "stale", "source": inp.label, "as_of": iso_day(inp.as_of), "text": text}
    why = f" ({inp.error})" if inp.error else " (no date on the data)"
    return {"kind": "missing", "source": inp.label, "as_of": None,
            "text": f"{inp.label} could not be read just now{why}. Nothing is suggested from it."}


def _public(card: Dict[str, Any]) -> Dict[str, Any]:
    keep = ("tab", "class", "class_label", "title", "why", "footer", "query", "intent", "template_id", "rule_id", "symbol",
            "as_of", "inputs", "state")
    return {"id": card["_id"], **{k: card.get(k) for k in keep}}


async def evaluate(db: Any, user: Dict[str, Any], *, request: Any, mode: Optional[str] = None,
                   now: Optional[datetime] = None, fresh_read: bool = False, persist: bool = True) -> Dict[str, Any]:
    """Every tab for this user: {window, cards (all tabs, ranked), notices (per tab), counts}. Memoised per user and
    mode for MEMO_SECONDS unless `fresh_read`."""
    uid = user["user_id"]
    mode = mode if mode in catalog.AUDIENCES else "investor"
    memo_key = (uid, mode)
    hit = _memo.get(memo_key)
    if hit and not fresh_read and hit[0] > time.monotonic():
        return hit[1]

    from services import market_freshness
    moment = now or datetime.now(timezone.utc)
    today = moment.astimezone(IST).date()
    window = await market_freshness.window(moment)
    all_rules = [r for r in await store.rules(db) if r.get("enabled", True) and r.get("trigger") in EVALUATORS]
    tmpls = await store.templates(db)
    names = sorted({n for r in all_rules for n in r.get("inputs") or [] if n in MARKET})
    market = await inputs.market(request, names, fresh_read=fresh_read)
    personal = await inputs.personal(db, uid)
    brokers = personal.pop("brokers", [])
    inp: Dict[str, Input] = {**market, **personal}
    since = (moment - timedelta(days=FEEDBACK_DAYS)).isoformat()
    feedback = [f for f in await store.latest_feedback(db, uid) if str(f.get("at") or "") >= since]

    # The newest SUPPRESSING feedback per card: a later "useful" does not lift a dismissal before its cooldown.
    latest_by_key: Dict[str, Dict[str, Any]] = {}
    for f in feedback:                                   # newest first
        if f.get("action") in ("dismissed", "not_relevant", "completed"):
            latest_by_key.setdefault(f["dedupe_key"], f)
    rule_since = (moment - timedelta(days=RULE_FEEDBACK_DAYS)).isoformat()
    rule_adjust: Dict[str, int] = {}
    for f in feedback:
        if str(f.get("at") or "") < rule_since:
            continue
        if f["action"] == "not_relevant":
            rule_adjust[f["rule_id"]] = rule_adjust.get(f["rule_id"], 0) - 40
        elif f["action"] == "useful":
            rule_adjust[f["rule_id"]] = rule_adjust.get(f["rule_id"], 0) + 10

    blocked: Dict[str, Dict[str, Any]] = {}
    cards: List[Dict[str, Any]] = []
    suppressed = 0
    for r in all_rules:
        spec = r.get("freshness") or {"kind": "session"}
        statuses = {n: _status(inp[n], spec, window, today) for n in r.get("inputs") or [] if n in inp}
        if any(n not in inp for n in r.get("inputs") or []):
            continue
        bad = {n: s for n, s in statuses.items() if s != "fresh"}
        if bad:
            for n, s in bad.items():
                if s in ("stale", "missing"):
                    blocked.setdefault(n, {"status": s, "tabs": set()})["tabs"].add(r["tab"])
            continue
        try:
            found = EVALUATORS[r["trigger"]](r, inp)
        except Exception:  # noqa: BLE001 — one rule's failure never hides the others
            logger.exception("suggestions: rule %s failed", r.get("_id"))
            continue
        for c in found:
            tmpl = tmpls.get(c.get("template_id") or r["template_id"])
            if not tmpl:
                continue
            params = c.get("params") or {}
            if any(p not in params for p in tmpl.get("params") or []):
                continue
            query = _fmt(tmpl["query"], params)
            facts = c.get("facts") or {}
            title, why = _fmt(r["title"], facts), _fmt(r["why"], facts)
            if not (query and title and why):
                logger.info("suggestions: rule %s left out a figure its text needs", r["_id"])
                continue
            cls = catalog.CLASSES[r["class"]]
            used = [{"name": n, "label": inp[n].label, "as_of": inp[n].as_of, "status": statuses[n]}
                    for n in r.get("inputs") or []]
            data_days = [iso_day(u["as_of"]) for u in used if u["name"] != "user_symbols" and iso_day(u["as_of"])]
            as_of = max(data_days) if data_days else None
            dedupe_key = f"{r['_id']}|{c.get('key')}"
            last = latest_by_key.get(dedupe_key)
            if last:
                until = datetime.fromisoformat(last["at"]) + timedelta(hours=float(r.get("cooldown_hours") or 24))
                if until > moment:
                    suppressed += 1
                    continue
            score = (cls["weight"] + int(r.get("priority") or 0) + _freshness_bonus(as_of, today)
                     + (15 if mode in (r.get("audience") or []) else 0) + rule_adjust.get(r["_id"], 0))
            ttl = EVENT_TTL_HOURS if c.get("event") else STARTER_TTL_HOURS
            cards.append({
                "_id": store.instance_id(uid, dedupe_key), "user_id": uid, "dedupe_key": dedupe_key, "rule_id": r["_id"],
                "tab": r["tab"], "class": r["class"], "class_label": cls["label"], "title": title, "why": why,
                "footer": _fmt(cls["footer"], {"date": facts.get("date") or "its list date"}),
                "query": query, "intent": tmpl.get("intent"), "template_id": tmpl["_id"], "params": params,
                "symbol": c.get("symbol"), "subject": c.get("subject") or c.get("symbol"), "as_of": as_of, "inputs": used, "facts": facts, "score": score,
                "event": bool(c.get("event")), "state": "active", "seq": len(cards),
                "expires_at": moment + timedelta(hours=ttl),
            })

    # One card per (question, parameters, subject) across all tabs: the higher-ranked one stays. Equal scores keep the
    # order the rules produced them in (catalog order, then the source's own rank, e.g. the scanner list's).
    cards.sort(key=lambda c: (-c["score"], c["seq"]))
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for c in cards:
        k = (c["template_id"], json.dumps(c["params"], sort_keys=True), c["subject"])
        if k in seen:
            continue
        seen.add(k)
        unique.append(c)
    per_tab: Dict[str, List[Dict[str, Any]]] = {t: [] for t in catalog.TAB_KEYS}
    for c in unique:
        if len(per_tab[c["tab"]]) < PER_TAB:
            per_tab[c["tab"]].append(c)

    notices: Dict[str, List[Dict[str, Any]]] = {t: [] for t in catalog.TAB_KEYS}
    for name, b in sorted(blocked.items()):
        n = _notice(name, inp[name], b["status"], window)
        for t in sorted(b["tabs"]):
            if all(x["source"] != n["source"] for x in notices[t]):
                notices[t].append(n)
    if inp["holdings"].empty:
        notices["for_you"].insert(0, {"kind": "no_portfolio", "source": inp["holdings"].label, "as_of": None,
                                      "text": "Connect or import a portfolio to get suggestions about your holdings.",
                                      "action": "connect"})
    for b in brokers:
        if b.get("needs_reconnect"):
            synced = day_text(b.get("last_sync_at"))
            notices["for_you"].append({
                "kind": "disconnected", "source": f"{b.get('name') or 'Broker'} connection", "as_of": iso_day(b.get("last_sync_at")),
                "text": (f"Broker disconnected: your {b.get('name') or 'broker'} connection has ended, so its holdings are as of "
                         f"{'the last sync on ' + synced if synced else 'the last sync'}. Reconnect to refresh them."),
                "action": "brokers"})

    if persist:
        await store.ensure_indexes(db)
        for c in (c for tab in per_tab.values() for c in tab):
            if c["event"]:
                await store.record_event(db, uid, dedupe_key=c["dedupe_key"], rule_id=c["rule_id"], facts=c["facts"],
                                         inputs=c["inputs"], now=moment)
            await store.upsert_instance(db, {k: v for k, v in c.items() if k not in ("score", "event", "seq")}, now=moment)

    result = {"window": {"today": today.isoformat(), "previous_session": window.floor.isoformat()},
              "generated_at": moment.isoformat(), "mode": mode, "per_tab": per_tab, "notices": notices,
              "suppressed": suppressed, "inputs": {k: v.public() for k, v in inp.items()}}
    _memo[memo_key] = (time.monotonic() + MEMO_SECONDS, result)
    return result


def tab_view(result: Dict[str, Any], tab: str) -> Dict[str, Any]:
    return {
        "schema": catalog.SCHEMA, "tab": tab, "mode": result["mode"], "generated_at": result["generated_at"],
        "window": result["window"],
        "tabs": [{**t, "count": len(result["per_tab"][t["key"]])} for t in catalog.TABS],
        "suggestions": [_public(c) for c in result["per_tab"][tab]],
        "notices": result["notices"][tab],
    }


def why(inst: Dict[str, Any], rule: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    r = rule or {}
    return {
        "id": inst["_id"], "title": inst.get("title"), "why": inst.get("why"), "class": inst.get("class"),
        "class_label": inst.get("class_label"), "footer": inst.get("footer"), "tab": inst.get("tab"),
        "query": inst.get("query"), "intent": inst.get("intent"), "template_id": inst.get("template_id"),
        "rule": {"id": inst.get("rule_id"), "name": r.get("name"), "description": r.get("description"),
                 "trigger": r.get("trigger"), "params": r.get("params") or {}, "freshness": r.get("freshness"),
                 "cooldown_hours": r.get("cooldown_hours")},
        "inputs": inst.get("inputs") or [], "as_of": inst.get("as_of"),
        "evaluated_at": inst.get("updated_at"), "first_seen_at": inst.get("created_at"), "state": inst.get("state"),
    }


async def scheduled_pass(db: Any, *, user_ids: List[str], now: Optional[datetime] = None) -> Dict[str, Any]:
    """The pre-open / post-close pass: re-read the market sources once, then evaluate (and store) every listed user's
    suggestions, each as that user (deps.system_caller) with an internal request. Not scheduled by itself."""
    from deps import system_caller
    from services.ai_watchlist_build import internal_request
    inputs.clear_market_cache()
    done, failed = 0, 0
    for uid in user_ids:
        user = {"user_id": uid, "role": "user", "is_admin": False}
        try:
            with system_caller(user):
                await evaluate(db, user, request=internal_request(), now=now, fresh_read=False)
            done += 1
        except Exception:  # noqa: BLE001 — one user's failure does not stop the pass
            logger.exception("suggestions: scheduled pass failed for one user")
            failed += 1
    return {"users": len(user_ids), "evaluated": done, "failed": failed}
