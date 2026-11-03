"""Rule evaluators. A rule (catalog.RULES / suggestion_rules) names its evaluator in `trigger`; the evaluator reads only
the inputs the rule declares and returns zero or more candidates:

    {"facts": {...}  values for the rule's `title` / `why` format strings (already formatted text),
     "key":   the part of the dedupe key that tells two candidates of one rule apart (a symbol, a trade, a day),
     "params": the template's parameters ({"symbol": ...}), "symbol": the stock the card is about (icon), or None,
     "subject": what the card is about when the question itself does not say (an index on the F&O list), else the
     symbol; two cards with the same question, parameters and subject are one card,
     "template_id": optional override of the rule's template (an index on the F&O list), "event": True when the
     candidate is an event (stored once in suggestion_events)}

Evaluators are pure: no reads, no writes, no clock (the engine passes `today`). The freshness gate runs before them,
so an evaluator sees only inputs that are current; it still checks that the figure it quotes exists.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from services.copilot_visual.payload import day_text, iso_day, num, price

from .catalog import INDEX_TEMPLATES
from .inputs import Input

Candidate = Dict[str, Any]
Evaluator = Callable[[Dict[str, Any], Dict[str, Input]], List[Candidate]]

PLAN_STATUS_TEXT = {"plan": "setup ready", "wait": "waiting for confirmation", "no_trade": "no setup under the desk's rules",
                    "insufficient_data": "not enough data"}


def _pct(v: float, digits: int = 0) -> str:
    return f"{v:.{digits}f}%"


def _rupees(v: float) -> str:
    return ("−" if v < 0 else "") + f"₹{abs(v):,.2f}"


def source_current(rule: Dict[str, Any], inp: Dict[str, Input]) -> List[Candidate]:
    """One starter while the source is current. `min_count`: no card when the source's own count is below it (a
    question whose answer today is "none met the rule" is not suggested)."""
    i = inp[rule["inputs"][0]]
    need = rule["params"].get("min_count")
    if need is not None and int(i.facts.get("count") or 0) < int(need):
        return []
    facts = {"date": day_text(i.as_of), **i.facts}
    return [{"facts": facts, "key": iso_day(i.as_of)}]


def ai_list_current(rule: Dict[str, Any], inp: Dict[str, Input]) -> List[Candidate]:
    day = inp["ai_watchlist"].value or {}
    cash = [e for e in day.get("cash") or [] if isinstance(e, dict)]
    if not cash:
        return []
    top = cash[:5]
    ready = sum(1 for e in top if e.get("plan_status") == "plan")
    return [{"facts": {"date": day_text(day.get("list_date")), "n": len(top), "ready": ready}, "key": day.get("list_date")}]


def watchlist_on_scanner(rule: Dict[str, Any], inp: Dict[str, Input]) -> List[Candidate]:
    day = inp["ai_watchlist"].value or {}
    mine: Dict[str, str] = inp["user_symbols"].value or {}
    out: List[Candidate] = []
    for e in day.get("cash") or []:
        sym = (e.get("symbol") or "").upper()
        if not sym or sym not in mine:
            continue
        out.append({"facts": {"symbol": sym, "where": "holdings" if mine[sym] == "holdings" else "watchlist",
                              "rank": e.get("rank"), "date": day_text(day.get("list_date")),
                              "status": PLAN_STATUS_TEXT.get(e.get("plan_status") or "", "not recorded")},
                    "key": f"{sym}|{day.get('list_date')}", "params": {"symbol": sym}, "symbol": sym, "event": True})
        if len(out) >= int(rule["params"].get("max") or 3):
            break
    return out


def _insights(inp: Dict[str, Input]) -> List[Dict[str, Any]]:
    return [i for i in inp["portfolio_rules"].value or [] if isinstance(i, dict)]


def _kind(ins: Dict[str, Any]) -> str:
    """Which of the insight route's rules produced this insight (routes/insights._deterministic_insights)."""
    t = (ins.get("title") or "").lower()
    c = ins.get("category")
    if c == "risk" and "sector" in t:
        return "sector"
    if c == "risk" and "amc" in t:
        return "amc"
    if c == "allocation" and "debt" in t:
        return "debt"
    if c == "allocation" and "category" in t:
        return "category"
    if c == "cost":
        return "cost"
    if c == "overlap":
        return "overlap"
    return "other"


def _subject(ins: Dict[str, Any], kind: str) -> str:
    """The sector / AMC the insight names: its title is "Reduce <X> sector exposure" / "Reduce <X> AMC concentration"."""
    t = ins.get("title") or ""
    for lead, tail in (("Reduce ", " sector exposure"), ("Reduce ", " AMC concentration")):
        if t.startswith(lead) and t.endswith(tail):
            return t[len(lead):-len(tail)]
    return kind


def portfolio_review(rule: Dict[str, Any], inp: Dict[str, Input]) -> List[Candidate]:
    flagged = [i for i in _insights(inp) if i.get("type") in ("warning", "opportunity")]
    if not flagged:
        return []
    names = {"sector": "sector", "amc": "fund house", "debt": "allocation", "category": "fund category",
             "cost": "costs", "overlap": "overlap", "other": "other"}
    topics = sorted({names[_kind(i)] for i in flagged})
    return [{"facts": {"count": len(flagged), "topics": ", ".join(topics), "date": day_text(inp["holdings"].as_of)},
             "key": iso_day(inp["holdings"].as_of), "event": True}]


def portfolio_insight(rule: Dict[str, Any], inp: Dict[str, Input]) -> List[Candidate]:
    want = rule["params"].get("kind")
    for ins in _insights(inp):
        if _kind(ins) != want or not ins.get("current_value"):
            continue
        subject = _subject(ins, want)
        return [{"facts": {"subject": subject, "current": ins.get("current_value"), "target": ins.get("target_value") or "the rule's",
                           "date": day_text(inp["holdings"].as_of)},
                 "key": f"{subject}|{iso_day(inp['holdings'].as_of)}", "event": True}]
    return []


def fund_overlap(rule: Dict[str, Any], inp: Dict[str, Input]) -> List[Candidate]:
    ctx = inp["portfolio_facts"].value or {}
    top = num(ctx.get("max_overlap_pct"))
    if top is None or top < float(rule["params"].get("min_pct") or 40) or not num(ctx.get("total_value")):
        return []
    return [{"facts": {"pct": _pct(top), "date": day_text(inp["holdings"].as_of)},
             "key": f"{round(top)}|{iso_day(inp['holdings'].as_of)}", "event": True}]


def open_trades(rule: Dict[str, Any], inp: Dict[str, Input]) -> List[Candidate]:
    trades = [t for t in inp["paper_trades"].value or [] if not t.get("exited")]
    if not trades:
        return []
    i = inp["paper_trades"]
    return [{"facts": {"count": len(trades), "date": day_text(i.as_of)}, "key": iso_day(i.as_of)}]


def trade_near_level(rule: Dict[str, Any], inp: Dict[str, Input]) -> List[Candidate]:
    """How far the last close has travelled from the entry towards the trade's own stop (or target): 0 at the entry,
    1 at the level. Works for a long (stop below entry) and a short (stop above). A trade not yet entered, already
    past its exit, or without a current mark is skipped."""
    which = rule["params"].get("level", "stop")
    need = float(rule["params"].get("min_fraction") or 0.7)
    mark_day = iso_day(inp["paper_trades"].as_of)
    out: List[Candidate] = []
    for t in inp["paper_trades"].value or []:
        lvl = t.get(which)
        if lvl is None or t.get("last") is None or not t.get("entered") or t.get("exited") or t.get("last_date") != mark_day:
            continue
        span = lvl - t["entry"]
        if span == 0:
            continue
        frac = (t["last"] - t["entry"]) / span
        if frac < need or frac >= 1:
            continue
        away = abs(lvl - t["last"]) / t["last"] * 100 if t["last"] else None
        out.append({"facts": {"symbol": t["symbol"], "last": price(t["last"]), "date": day_text(t["last_date"]),
                              "level_price": price(lvl), "distance": _pct(away, 2) if away is not None else "a short way"},
                    "key": f"{t['trade_id']}", "params": {"symbol": t["symbol"]}, "symbol": t["symbol"], "event": True})
    return out


def loss_limit_use(rule: Dict[str, Any], inp: Dict[str, Input]) -> List[Candidate]:
    book = inp["risk_book"].value or {}
    day = book.get("day") or {}
    pnl, start = num(day.get("pnl_rs")), num(day.get("start_equity_rs"))
    limit = num(((book.get("profile") or {}).get("limits") or {}).get("daily_loss_pct"))
    if pnl is None or not start or not limit or pnl >= 0:
        return []
    used = -pnl / start * 100 / limit * 100
    if used < float(rule["params"].get("min_used_pct") or 50):
        return []
    return [{"facts": {"used": _pct(min(used, 999)), "pnl": _rupees(pnl), "limit": _pct(limit, 1),
                       "date": day_text(inp["risk_book"].as_of)},
             "key": day.get("start") or iso_day(inp["risk_book"].as_of), "event": True}]


def always(rule: Dict[str, Any], inp: Dict[str, Input]) -> List[Candidate]:
    return [{"facts": {}, "key": "starter"}]


def fno_list_current(rule: Dict[str, Any], inp: Dict[str, Input]) -> List[Candidate]:
    day = inp["ai_watchlist"].value or {}
    fno = [e for e in day.get("fno") or [] if isinstance(e, dict)]
    if not fno or (day.get("notes") or {}).get("fno_staleness"):
        return []
    return [{"facts": {"date": day_text(day.get("list_date")), "n": len(fno)}, "key": day.get("list_date")}]


def fno_list_signals(rule: Dict[str, Any], inp: Dict[str, Input]) -> List[Candidate]:
    """The top instruments of the F&O list. Refused as a whole when the list says its chain data is stale (the build
    job's own `fno_staleness` note): a stale chain is never a signal."""
    day = inp["ai_watchlist"].value or {}
    if (day.get("notes") or {}).get("fno_staleness"):
        return []
    out: List[Candidate] = []
    for e in sorted((e for e in day.get("fno") or [] if isinstance(e, dict)), key=lambda e: e.get("rank") or 99):
        und = (e.get("underlying") or "").upper()
        if not und or not e.get("name"):
            continue
        fit = num((e.get("fit") or {}).get("score"))
        index = INDEX_TEMPLATES.get(und)
        out.append({"facts": {"underlying": und, "structure": e.get("name"), "rank": e.get("rank"),
                              "date": day_text(day.get("list_date")), "fit": f"{fit:g}" if fit is not None else "not recorded"},
                    "key": f"{und}|{day.get('list_date')}", "params": {} if index else {"symbol": und},
                    "symbol": None if index else und, "subject": und, "template_id": index, "event": True})
        if len(out) >= int(rule["params"].get("max") or 3):
            break
    return out


EVALUATORS: Dict[str, Evaluator] = {
    "source_current": source_current,
    "ai_list_current": ai_list_current,
    "watchlist_on_scanner": watchlist_on_scanner,
    "portfolio_review": portfolio_review,
    "portfolio_insight": portfolio_insight,
    "fund_overlap": fund_overlap,
    "open_trades": open_trades,
    "trade_near_level": trade_near_level,
    "loss_limit_use": loss_limit_use,
    "always": always,
    "fno_list_current": fno_list_current,
    "fno_list_signals": fno_list_signals,
}

