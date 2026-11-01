"""The `screen_stocks` visual answer (1 Nov 2026, docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md slice W4).

    "Screen large cap stocks with ROE over 20 and debt to equity under 0.5"
      ─► screen_spec.parse      the rules, and every word that was not used
      ─► readers.screen_run     the Screener's own screen (services/screener_run.py), on the day's stock features
      ─► payload                the rules as understood FIRST, then what was not used, then the matches

The model never sees a result and never runs anything: it explains the payload's figures like every other visual answer. The
answer says "stocks that match your filters": a screen is a filter, not a ranking of picks. Nothing here writes.

Failure is not "no match": a screen that could not run says so and shows no figure (the page's rule too). A rule on a metric
the day's data does not carry is named, because no stock can pass it.
"""
from __future__ import annotations

from typing import Any, Dict, List

from . import readers as rd
from . import screen_spec as ss
from .intents import Intent
from .payload import Sources, assemble, block, follow, iso_day, notice, num, short_day, why

SRC_SCREEN = "Stock screener · the day's stock features (nidp.stock_features_daily)"
SHOWN = 25                                   # rows in the answer; the Screener page shows the rest
MAX_METRIC_COLUMNS = 4
_WHOLE = frozenset({"rsi", "momentum", "accumulation", "liquidity", "earningsConsistency"})
_TWO = frozenset({"de", "beta", "peVsSector"})


async def _try(coro):
    try:
        return await coro, None
    except Exception as e:  # noqa: BLE001 — a failed read is recorded by the caller, never raised into the answer
        return None, e


def indian(n: float) -> str:
    """7,68,844 — the product's grouping for rupee amounts (the column header says ₹Cr)."""
    s = f"{abs(int(round(n))):d}"
    if len(s) > 3:
        head, tail, groups = s[:-3], s[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + groups + [tail])
    return ("−" if n < 0 else "") + s


def _cell(key: str, v: Any):
    n = num(v)
    if n is None:
        return None
    if key == "mcap":
        return indian(n)
    digits = 0 if key in _WHOLE else 2 if key in _TWO else 1
    return f"{n:.{digits}f}"


def _action(spec: ss.ScreenSpec) -> Dict[str, Any]:
    return {"kind": "open_screener", "label": "Open in Screener ›", "query": ss.query_string(spec)}


def _read_notice(spec: ss.ScreenSpec, labels: Dict[str, str]) -> Dict[str, Any]:
    n = notice(f"I read this as: {ss.words(spec, labels)}.", "info", "read")
    n["actions"] = [_action(spec)]
    return n


def _not_used_notice(spec: ss.ScreenSpec) -> Dict[str, Any]:
    listed = ", ".join(spec.not_used)
    n = notice(f"Not used: {listed}. Nothing in your sentence matched a screening rule for these, so they did not narrow the screen. "
               "A rule is a metric, over or under, and a number.", "warn", "not_used")
    return n


async def screen_stocks(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    follow_ups = follow("Which stocks have unusual volume?", "Which breakouts are confirmed?", "Where is smart money moving?",
                        "What is the market view today?")
    title = "Stock screen"
    spec = ss.parse(ctx.get("message") or "", rd.screen_vocabulary())
    try:
        labels = rd.screen_labels()
    except Exception:  # noqa: BLE001 — the labels only word the sentence; the keys do as well
        labels = {}

    if not spec.has_rules:
        blocks: List[Dict[str, Any]] = [
            notice("I could not read a screening rule in that. A rule is a metric, over or under, and a number: for example "
                   "“large cap stocks with ROE over 20 and debt to equity under 0.5”. You can also build the screen on the Screener page.",
                   "info", "norules")]
        blocks[0]["actions"] = [_action(spec)]
        if spec.not_used:
            blocks.append(_not_used_notice(spec))
        return assemble("screen_stocks", title, None, None, "neutral", blocks, src, follow_ups, now=ctx.get("now"))

    lead: List[Dict[str, Any]] = [_read_notice(spec, labels)]
    if spec.not_used:
        lead.append(_not_used_notice(spec))

    res, err = await _try(rd.screen_run(spec.request()))
    if err is not None or not isinstance(res, dict) or not res.get("ok"):
        src.miss(SRC_SCREEN, why(err) if err is not None else "the stock data source did not answer")
        lead.append(notice("The screen did not run, so there is no result. That is not “no stock matches”: try again in a moment, "
                           "or run it on the Screener page.", "warn", "failed"))
        return assemble("screen_stocks", title, None, None, "neutral", lead, src, follow_ups, now=ctx.get("now"))

    as_of = iso_day(res.get("as_of_date"))
    src.add(SRC_SCREEN, as_of)
    widget = res.get("widget") or {}
    universe = [r for r in widget.get("universe") or [] if isinstance(r, dict)]
    coverage = res.get("coverage") or {}
    matched = int(res.get("matched") or 0)
    rule_keys = list(dict.fromkeys(c["key"] for c in spec.conditions))
    day_total = max([0] + [int(c.get("total") or 0) for c in coverage.values() if isinstance(c, dict)])
    empty_metrics = [k for k in rule_keys if (coverage.get(k) or {}).get("filled") == 0]
    size_missing = bool(spec.bucket) and (coverage.get("bucket") or {}).get("filled") == 0

    kpis = [{"label": "Matched", "value": f"{matched:,}", "sub": f"of {day_total:,} stocks screened" if day_total else None},
            {"label": "Data as of", "value": short_day(as_of) if as_of else "not reported", "sub": "end of day"}]
    blocks = lead + [block("kpis", "summary", "The screen", None, items=kpis)]

    if not res.get("universe_complete", True):
        blocks.append(notice(f"Only the first {day_total:,} stocks of the day were screened; later ones were not read.", "warn", "partial"))
    gaps = [labels.get(k, k) for k in empty_metrics] + (["market-cap size"] if size_missing else [])
    if matched == 0 and day_total == 0:
        blocks.append(notice("There was no stock data to screen. That is a gap in the data, not a result.", "warn", "nodata"))
    elif matched == 0 and gaps:
        blocks.append(notice(f"The latest screening data has no values for {', '.join(gaps)}, so no stock can pass a rule on it and this screen "
                             "matches nothing. That is a gap in the data, not a verdict on any stock.", "warn", "gap"))
    elif matched == 0:
        blocks.append(notice("No stock passes every rule. The data has what these rules need, but no stock passes all of them together: "
                             "loosen a threshold or remove a rule.", "info", "nomatch"))
    elif gaps:
        blocks.append(notice(f"The latest screening data has no values for {', '.join(gaps)}; that part of the screen could not narrow anything.",
                             "warn", "gap"))

    head = None
    if matched:
        shown = min(len(universe), SHOWN)
        metric_keys = (rule_keys or ["pe", "roe"])[:MAX_METRIC_COLUMNS]
        columns = [{"key": "rank", "label": "#", "align": "right", "format": "int"},
                   {"key": "symbol", "label": "Stock", "align": "left", "format": "text"},
                   {"key": "sector", "label": "Sector", "align": "left", "format": "text"},
                   {"key": "mcap", "label": "Mkt cap ₹Cr", "align": "right", "format": "text"}]
        columns += [{"key": k, "label": labels.get(k, k), "align": "right", "format": "text"} for k in metric_keys if k != "mcap"]
        rows = []
        for i, r in enumerate(universe[:SHOWN], start=1):
            sym = str(r.get("ticker") or r.get("symbol") or "")
            if not sym:
                continue
            cells: Dict[str, Any] = {"rank": i, "symbol": sym, "sector": r.get("sector") or None, "mcap": _cell("mcap", r.get("mcap"))}
            for k in metric_keys:
                if k != "mcap":
                    cells[k] = _cell(k, r.get(k))
            rows.append({"symbol": sym, "ask": f"Trade plan for {sym}", "cells": cells})
        count = (f"Showing {shown} of {matched:,} matching stocks, largest companies first." if matched > shown
                 else f"{matched:,} {'stock matches' if matched == 1 else 'stocks match'}, largest companies first.")
        blocks.append(block("ranked", "matches", f"Stocks that match your filters · {short_day(as_of)}",
                            f"{count} These are stocks that match the rules above, not recommendations. A stock with no value for a metric "
                            "shows — and cannot pass a rule on it. The Screener page has every match and more columns.",
                            columns=columns, rows=rows))
        head = f"{matched:,} {'stock matches' if matched == 1 else 'stocks match'} your filters."
    return assemble("screen_stocks", title, as_of, head, "neutral", blocks, src, follow_ups, now=ctx.get("now"))


BUILDERS = {"screen_stocks": screen_stocks}
