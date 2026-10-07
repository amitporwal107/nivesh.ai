"""Filing insights from the corporate-event AI analysis (Mongo event_ai_analysis), for filings the stage-7
filing_insights generator has not covered.

Why: stage 7 (nidp/services/filing_insights, gpt-4o-mini) has written almost nothing since 2026-09-18 (OpenAI
account out of credit), so the Research page's "Read for you" cards and drawer had no insight at all. The research
pipeline (research/event_direction/ai_analysis/, owner's master + filter prompts, claude-sonnet-5, tools off) already
analyses the same filings (same 40-char announcement_id) and posts them to Mongo. This module shapes those documents
into the insight dict routes/filings.py already renders — no frontend change.

Rules:
  - only analyses run tools-off and isolated;
  - the full impact analysis wins; otherwise the importance filter's own verdict (title + reason) is used, and a
    filing the filter dropped says so ("Assessed as routine"), so it never reads as important;
  - research inputs (document text, Trendlyne material) never leave the backend;
  - a Mongo failure returns {} — insights are additive, the feed still renders.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

COLLECTION = "event_ai_analysis"
ISOLATED = "tools_off+isolated"
MODEL_LABEL = "claude-sonnet-5 (corporate-event analysis)"

BAND_TEXT = {
    "extremely_positive": "extremely positive", "strongly_positive": "strongly positive",
    "moderately_positive": "moderately positive", "slightly_positive": "slightly positive",
    "neutral_mixed": "neutral or mixed", "slightly_negative": "slightly negative",
    "moderately_negative": "moderately negative", "strongly_negative": "strongly negative",
    "extremely_negative": "extremely negative",
}
UNIT_TEXT = {"cr": "₹ cr", "usd_mn": "USD mn", "pct": "%", "shares": "shares"}


def _is_analysis(d: dict) -> bool:
    m = d.get("mode") or ""
    return m.endswith("_compact") or m == "single_full"


def _when(d: dict) -> datetime:
    t = d.get("analyzed_at")
    if isinstance(t, datetime):
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _iso(d: dict) -> Optional[str]:
    t = _when(d)
    return None if t.year == 1 else t.isoformat()


def _sentiment(net: Any) -> Optional[str]:
    if not isinstance(net, (int, float)):
        return None
    return "positive" if net >= 10 else "negative" if net <= -10 else "neutral"


def _metric(amts: Any) -> Optional[Dict[str, Any]]:
    for a in amts or []:
        if isinstance(a, dict) and isinstance(a.get("v"), (int, float)) and a.get("what"):
            return {"label": str(a["what"]).replace("_", " ").capitalize(), "value": f"{a['v']:,.2f}".rstrip("0").rstrip("."),
                    "unit": UNIT_TEXT.get(a.get("u"), a.get("u") or "")}
    return None


def _sec(tab: str, h: str, items: List[str]) -> Optional[Dict[str, Any]]:
    items = [i for i in items if isinstance(i, str) and i.strip()]
    return {"tab": tab, "h": h, "items": items} if items else None


def from_analysis(a: dict) -> Dict[str, Any]:
    an = a.get("analysis") or {}
    band = BAND_TEXT.get(a.get("net_band") or "", None)
    pf = [x[0] for x in an.get("pf") or [] if isinstance(x, (list, tuple)) and x and isinstance(x[0], str)]
    nf = [x[0] for x in an.get("nf") or [] if isinstance(x, (list, tuple)) and x and isinstance(x[0], str)]
    kind = " · ".join(x for x in (str(a.get("event_type") or "").title(), a.get("event_subtype")) if x)
    reading = [f"Reads {band} for the company (net impact {a.get('net_impact_score')}, materiality {a.get('materiality_score')}/100)."] if band else []
    if a.get("event_certainty") and a.get("event_certainty") != "unknown":
        reading.append(f"Certainty: {str(a['event_certainty']).replace('_', ' ')}.")
    secs = [
        _sec("Quick Summary", kind or "What the filing says", [an.get("sum")]),
        _sec("Sentiment", "How it bears on the business", reading + [f"+ {x}" for x in pf] + [f"− {x}" for x in nf]),
        _sec("Potential Risks", "Not yet known", list(an.get("unk") or [])),
    ]
    conf = a.get("confidence_score")
    return {"one": an.get("sum"), "period": None, "metric": _metric(an.get("amt")),
            "sentiment": _sentiment(a.get("net_impact_score")),
            "confidence": conf / 100 if isinstance(conf, (int, float)) else None,
            "docType": None, "sourceUrl": None, "sections": [s for s in secs if s],
            "model": MODEL_LABEL, "generatedAt": _iso(a), "source": "event_ai_analysis"}


def from_filter(f: dict, kept: bool) -> Dict[str, Any]:
    r = f.get("analysis") or {}
    imp = f.get("event_importance_score")
    title, why = r.get("title"), r.get("why")
    if kept:
        one = title or why
        head = f"Flagged as important (importance {imp}/100); full analysis pending."
    else:
        one = f"Assessed as routine (importance {imp}/100): {why or title}" if (why or title) else None
        head = "The importance check judged this filing routine."
    secs = [
        _sec("Quick Summary", head, [title, why] if kept else [why or title]),
        _sec("Business Outlook", "Possible catalysts", list(r.get("cats") or [])) if kept else None,
        _sec("Potential Risks", "Risks named in the filing", list(r.get("risks") or [])) if kept else None,
    ]
    pos, neg = f.get("positive_impact_score"), f.get("negative_impact_score")
    net = pos - neg if isinstance(pos, (int, float)) and isinstance(neg, (int, float)) else None
    return {"one": one, "period": None, "metric": None, "sentiment": _sentiment(net) if kept else "neutral",
            "confidence": {"HIGH": 0.85, "MEDIUM": 0.6, "LOW": 0.3}.get(f.get("evidence_confidence")),
            "docType": None, "sourceUrl": None, "sections": [s for s in secs if s],
            "model": MODEL_LABEL, "generatedAt": _iso(f), "source": "event_ai_analysis"}


def build(docs: Iterable[dict]) -> Dict[str, Dict[str, Any]]:
    """{announcement_id: insight} from one batch of Mongo documents."""
    by: Dict[str, List[dict]] = {}
    for d in docs:
        if d.get("tool_isolation") == ISOLATED and d.get("announcement_id"):
            by.setdefault(d["announcement_id"], []).append(d)
    out: Dict[str, Dict[str, Any]] = {}
    for aid, ds in by.items():
        full = [d for d in ds if _is_analysis(d) and (d.get("analysis") or {}).get("sum")]
        if full:
            out[aid] = from_analysis(max(full, key=_when))
            continue
        filt = [d for d in ds if d.get("mode") in ("filter_v1", "filter_v1_second")]
        if not filt:
            continue
        keep = [d for d in filt if d.get("include")]
        pick = max(keep or filt, key=_when)
        ins = from_filter(pick, kept=bool(keep))
        if ins["one"]:
            out[aid] = ins
    return out


async def insights_for(db, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not ids:
        return {}
    try:
        cur = db[COLLECTION].find({"announcement_id": {"$in": list(ids)}, "tool_isolation": ISOLATED}, {"input": 0})
        return build(await cur.to_list(length=20 * len(ids)))
    except Exception as e:  # additive: the feed renders without it
        logger.warning("event_ai insight lookup failed: %s", e)
        return {}
