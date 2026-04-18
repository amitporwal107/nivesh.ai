"""AI narration on top of portfolio_intelligence metrics.

Feeds computed metrics into GPT-4o-mini (via OpenAI or Emergent LLM key) to
produce specific, one-line actionable insights. Graceful fallback to
deterministic templates when the LLM is unavailable.
"""
from __future__ import annotations
import json
import logging
from typing import Any, Dict, List, Optional

from helpers import secrets as _secrets

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a SEBI-registered portfolio analyst writing terse,
evidence-based insights for an Indian mutual-fund investor. Every insight
must cite a specific ₹ amount, %, or fund name from the data. Never use
hedge words like "may" or "could". Maximum 2 lines per insight. Output
strict JSON per the schema in the user prompt."""


def _truncate(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Trim to keep the prompt small."""
    return {
        "narrative": metrics.get("narrative"),
        "compression": metrics.get("compression"),
        "top_stocks": metrics.get("top_stocks", [])[:8],
        "pairwise_overlap": [
            {k: v for k, v in p.items() if k != "top_shared"}
            for p in metrics.get("pairwise_overlap", [])[:8]
        ],
        "category_inefficiency": metrics.get("category_inefficiency", []),
        "sector_exposure": metrics.get("sector_exposure", [])[:6],
        "redundancy_suggestions": metrics.get("redundancy_suggestions", [])[:3],
    }


def _fallback_insights(m: Dict[str, Any]) -> List[Dict[str, str]]:
    insights: List[Dict[str, str]] = []
    n = m.get("narrative") or {}
    c = m.get("compression") or {}
    top = m.get("top_stocks") or []
    pairs = m.get("pairwise_overlap") or []
    cats = m.get("category_inefficiency") or []
    rd = m.get("redundancy_suggestions") or []
    if n.get("total_invested_rs") and c.get("score"):
        insights.append({
            "type": "compression",
            "headline": f"Your ₹{_fmt(n['total_invested_rs'])} portfolio behaves like ₹{_fmt(n['behaves_like_rs'])} due to overlap.",
            "detail": f"Effective {c.get('effective_stocks')} unique stocks out of {c.get('unique_stocks')}.",
        })
    if top and top[0]["exposure_pct"] >= 5:
        s = top[0]
        insights.append({
            "type": "top_stock",
            "headline": f"{s['name']} is {s['exposure_pct']}% of your portfolio via {s['fund_count']} funds.",
            "detail": f"₹{_fmt(s['exposure_rs'])} concentrated in this single stock.",
        })
    for cat in cats[:1]:
        if cat["inefficient"]:
            insights.append({
                "type": "category_inefficiency",
                "headline": f"{cat['funds_count']} {cat['category']} funds with {cat['avg_pair_overlap']}% average overlap.",
                "detail": f"₹{_fmt(cat['invested_rs'])} split across near-identical strategies.",
            })
    for p in pairs[:1]:
        if p["overlap_pct"] >= 50:
            insights.append({
                "type": "duplication",
                "headline": f"{p['a_name']} and {p['b_name']} overlap {p['overlap_pct']}%.",
                "detail": "; ".join(p.get("reasons", [])) or "Strong strategy duplication.",
            })
    if rd:
        r = rd[0]
        if r["overlap_reduced_pp"] > 3:
            insights.append({
                "type": "redundancy",
                "headline": f"Removing {r['remove_name']} cuts overlap by {r['overlap_reduced_pp']} pp.",
                "detail": f"Sector drift only {r['sector_l1_drift_pct']}%.",
            })
    return insights


def _fmt(n: float) -> str:
    if n is None:
        return "—"
    if n >= 10_00_000:
        return f"{n/1_00_000:.2f}L"
    if n >= 1_000:
        return f"{n/1000:.1f}K"
    return f"{int(n)}"


async def generate_insights(metrics: Dict[str, Any]) -> List[Dict[str, str]]:
    if metrics.get("empty"):
        return []
    payload = _truncate(metrics)
    key = _secrets.get("EMERGENT_LLM_KEY") or _secrets.get("OPENAI_API_KEY")
    if not key:
        return _fallback_insights(metrics)
    try:
        from openai import OpenAI
        emergent = bool(_secrets.get("EMERGENT_LLM_KEY")) and not _secrets.get("OPENAI_API_KEY")
        base_url = "https://integrations.emergentagent.com/openai" if emergent else None
        client = OpenAI(api_key=key, base_url=base_url) if base_url else OpenAI(api_key=key)
        user_prompt = (
            "Using the metrics below, return a JSON object with key 'insights' "
            "containing 3-5 objects {type, headline, detail}. Types must be from "
            "[compression, top_stock, duplication, category_inefficiency, redundancy, "
            "sector_concentration, risk_adjusted]. Headlines cite exact ₹ or %. "
            "No advice to BUY; only diagnose or suggest REDUCE/REMOVE.\n\n"
            f"METRICS:\n{json.dumps(payload, default=str)}"
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=700,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        out = data.get("insights") or []
        if not isinstance(out, list) or not out:
            return _fallback_insights(metrics)
        return [
            {
                "type": str(x.get("type", ""))[:40],
                "headline": str(x.get("headline", ""))[:200],
                "detail": str(x.get("detail", ""))[:300],
            }
            for x in out[:6]
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"AI insights failed, falling back: {e}")
        return _fallback_insights(metrics)


# ── MF AI rating (on-demand) ─────────────────────────────────────────────
async def rate_fund(fund_detail: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a 1-5 rating + reasoning for a single MF."""
    key = _secrets.get("EMERGENT_LLM_KEY") or _secrets.get("OPENAI_API_KEY")
    if not key:
        return {"rating": None, "reason": "LLM not configured"}
    try:
        from openai import OpenAI
        emergent = bool(_secrets.get("EMERGENT_LLM_KEY")) and not _secrets.get("OPENAI_API_KEY")
        base_url = "https://integrations.emergentagent.com/openai" if emergent else None
        client = OpenAI(api_key=key, base_url=base_url) if base_url else OpenAI(api_key=key)
        compact = {
            "name": fund_detail.get("scheme_name") or fund_detail.get("instrument", {}).get("instrument_name"),
            "metadata": fund_detail.get("metadata"),
            "ratios": (fund_detail.get("ratios_history") or [{}])[0] if fund_detail.get("ratios_history") else fund_detail.get("ratios"),
            "top_holdings": (fund_detail.get("holdings") or [])[:10],
        }
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content":
                    "You rate Indian mutual funds 1-5 stars based on risk-adjusted "
                    "returns, expense, and portfolio quality. Return JSON "
                    "{rating: int 1-5, reason: 2-sentence string}."},
                {"role": "user", "content":
                    f"Rate this fund:\n{json.dumps(compact, default=str)}"},
            ],
            temperature=0.2,
            max_tokens=200,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        rating = data.get("rating")
        try:
            rating = int(rating) if rating is not None else None
            if rating is not None:
                rating = max(1, min(5, rating))
        except (TypeError, ValueError):
            rating = None
        return {"rating": rating, "reason": str(data.get("reason", ""))[:400]}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"AI rate_fund failed: {e}")
        return {"rating": None, "reason": f"LLM error: {e}"}
