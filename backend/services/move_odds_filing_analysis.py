"""Filing analysis for the Move odds stock view: the corporate-event AI analyses of a company's own exchange filings.

Source: Mongo `event_ai_analysis`, written by the research pipeline (research/event_direction/ai_analysis/, owner's
master prompts, claude-sonnet-5 run tool-less) through /api/internal/event-ai-analysis/bulk. Several documents exist
per filing, one per stage:
    filter_v1           importance filter, first pass (include, event_importance_score, resolution_status)
    filter_v1_second    same-model second opinion on filings the first pass dropped
    resolution_v1       resolution of LOW-confidence verdicts (resolution_status CONFIRMED / PARTIALLY_CONFIRMED / ...)
    batch*_compact, single_full   the impact analysis itself (summary, net impact, materiality, certainty)

Rules (test_reports/move_odds_filing_analysis_20260930.md):
  - only analyses run with tools off and isolated; the ones flagged NOT_ISOLATED are never shown;
  - a filing the importance filter dropped is not shown (owner: analyse and surface only important events);
  - research inputs (document text, Trendlyne material) never leave the backend.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

COLLECTION = "event_ai_analysis"
ISOLATED = "tools_off+isolated"
WINDOW_DAYS = 30
MAX_ROWS = 5
KEEP_IMPORTANCE = 60
KEPT_BY_RESOLUTION = ("CONFIRMED", "PARTIALLY_CONFIRMED")


def _is_analysis(d: dict) -> bool:
    m = d.get("mode") or ""
    return m.endswith("_compact") or m == "single_full"


def _ts(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def _iso(v: Any) -> Optional[str]:
    t = _ts(v)
    return t.isoformat() if t else None


def _factors(xs: Any) -> List[str]:
    out = []
    for x in xs or []:
        if isinstance(x, (list, tuple)) and x and isinstance(x[0], str):
            out.append(x[0])
    return out[:3]


def _kept(filters: List[dict], second: List[dict], resolution: List[dict]) -> bool:
    """No filter verdict at all (analysed before the filter existed) counts as kept; otherwise any pass may keep it."""
    if not filters and not second and not resolution:
        return True
    if any(d.get("include") for d in filters + second):
        return True
    return any(d.get("resolution_status") in KEPT_BY_RESOLUTION and (d.get("event_importance_score") or 0) >= KEEP_IMPORTANCE
               for d in resolution)


def select(docs: Iterable[dict], now: datetime, window_days: int = WINDOW_DAYS, limit: int = MAX_ROWS) -> Dict[str, Any]:
    """Group one symbol's documents by filing and return the rows the stock view shows, newest filing first."""
    since = now - timedelta(days=window_days)
    by: Dict[str, Dict[str, List[dict]]] = {}
    for d in docs:
        if d.get("tool_isolation") != ISOLATED:
            continue
        key = f"{d.get('source')}:{d.get('announcement_id')}"
        g = by.setdefault(key, {"analysis": [], "filter_v1": [], "filter_v1_second": [], "resolution_v1": []})
        mode = d.get("mode")
        if _is_analysis(d):
            g["analysis"].append(d)
        elif mode in g:
            g[mode].append(d)
    rows = []
    for g in by.values():
        if not g["analysis"]:
            continue
        a = max(g["analysis"], key=lambda d: _ts(d.get("analyzed_at")) or datetime.min.replace(tzinfo=timezone.utc))
        filed = _ts(a.get("event_ts"))
        if filed is None or filed < since:
            continue
        if not _kept(g["filter_v1"], g["filter_v1_second"], g["resolution_v1"]):
            continue
        res = g["resolution_v1"][0] if g["resolution_v1"] else None
        flt = g["filter_v1"][0] if g["filter_v1"] else None
        evidence = (res or flt or {}).get("resolution_status") or "NOT_CHECKED"
        imps = [d.get("event_importance_score") for d in g["filter_v1"] + g["filter_v1_second"] + g["resolution_v1"]]
        imps = [i for i in imps if isinstance(i, (int, float))]
        an = a.get("analysis") or {}
        rows.append({
            "announcement_id": a.get("announcement_id"),
            "exchange": "NSE" if str(a.get("source", "")).startswith("NSE") else "BSE",
            "filed_at": filed.isoformat(),
            "exchange_category": a.get("exchange_category"),
            "event_type": a.get("event_type"),
            "event_subtype": a.get("event_subtype"),
            "certainty": a.get("event_certainty"),
            "summary": an.get("sum"),
            "impact_band": a.get("net_band"),
            "net_impact_score": a.get("net_impact_score"),
            "materiality_score": a.get("materiality_score"),
            "confidence_score": a.get("confidence_score"),
            "importance_score": max(imps) if imps else None,
            "evidence_status": evidence,
            "positive_factors": _factors(an.get("pf")),
            "negative_factors": _factors(an.get("nf")),
            "unknowns": [u for u in (an.get("unk") or []) if isinstance(u, str)][:5],
            "model": a.get("model_tag"),
            "analyzed_at": _iso(a.get("analyzed_at")),
        })
    rows.sort(key=lambda r: r["filed_at"], reverse=True)
    return {"window_days": window_days, "rows": rows[:limit], "more": max(0, len(rows) - limit)}


async def filing_analysis(db, symbol: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=WINDOW_DAYS)
    cur = db[COLLECTION].find({"symbol": symbol, "event_ts": {"$gte": since}}, {"input": 0})
    docs = await cur.to_list(length=500)
    out = select(docs, now)
    out["symbol"] = symbol
    return out
