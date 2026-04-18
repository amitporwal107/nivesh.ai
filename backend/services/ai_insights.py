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
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=key,
            session_id="nivesh-insights",
            system_message=SYSTEM_PROMPT,
        ).with_model("openai", "gpt-4o-mini")
        user_prompt = (
            "Using the metrics below, return STRICT JSON ONLY (no markdown, no prose) "
            "with key 'insights' containing 3-5 objects {type, headline, detail}. "
            "Types must be from [compression, top_stock, duplication, "
            "category_inefficiency, redundancy, sector_concentration, risk_adjusted]. "
            "Headlines MUST cite exact ₹ or %. "
            "No advice to BUY; only diagnose or suggest REDUCE/REMOVE.\n\n"
            f"METRICS:\n{json.dumps(payload, default=str)}"
        )
        raw = await chat.send_message(UserMessage(text=user_prompt))
        data = _parse_json_loose(raw)
        out = (data or {}).get("insights") or []
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


def _parse_json_loose(raw: str) -> Dict[str, Any]:
    """Tolerant JSON parser for LLM output that may have code fences or prose."""
    if not raw:
        return {}
    s = raw.strip()
    # Strip markdown code fences
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip().rstrip("`").strip()
    # Find the outermost {...}
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        s = s[i:j + 1]
    try:
        return json.loads(s)
    except ValueError:
        return {}


# ── Category-level AI rating ─────────────────────────────────────────────
async def rate_portfolio_categories(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """For each category in a user's portfolio, return a 1-5 rating + rationale.

    Heuristic baseline (always computed): category rating = a function of:
      - funds_count (more = worse if overlap is high)
      - avg_pair_overlap (lower = better)
      - invested_rs share of portfolio (sanity anchor)
    AI-enhanced reason string if LLM is available.
    """
    cats = metrics.get("category_inefficiency") or []
    mf_invs = metrics.get("mf_investments") or []
    total_invested = sum(m.get("amount_rs", 0) for m in mf_invs) or 1.0
    out: List[Dict[str, Any]] = []

    # First pass: deterministic rating
    by_cat: Dict[str, Dict[str, Any]] = {}
    for m in mf_invs:
        c = m.get("category")
        if not c:
            continue
        by_cat.setdefault(c, {"funds": [], "rs": 0.0})
        by_cat[c]["funds"].append(m)
        by_cat[c]["rs"] += m.get("amount_rs", 0)

    cat_ov = {c["category"]: c["avg_pair_overlap"] for c in cats}

    for cat_name, info in by_cat.items():
        n = len(info["funds"])
        rs = info["rs"]
        ov = cat_ov.get(cat_name)
        # Deterministic rating:
        if n == 1:
            rating = 4   # single fund in category — clean
            reason = f"Single fund (₹{_fmt(rs)}) in {cat_name} — no internal overlap."
        else:
            if ov is None:
                rating = 3
                reason = f"{n} funds in {cat_name} (overlap data not yet available)."
            elif ov >= 70:
                rating = 1
                reason = f"{n} funds in {cat_name} overlap {ov}% on average — near-identical portfolios."
            elif ov >= 50:
                rating = 2
                reason = f"{n} funds in {cat_name} overlap {ov}% — clear consolidation opportunity."
            elif ov >= 30:
                rating = 3
                reason = f"{n} funds in {cat_name} overlap {ov}% — moderate duplication."
            elif ov >= 15:
                rating = 4
                reason = f"{n} funds in {cat_name} with only {ov}% overlap — well diversified."
            else:
                rating = 5
                reason = f"{n} funds in {cat_name} with minimal {ov}% overlap — highly diversified."
        out.append({
            "category": cat_name,
            "funds_count": n,
            "invested_rs": round(rs, 2),
            "invested_pct": round(rs / total_invested * 100, 2),
            "avg_pair_overlap": ov,
            "rating": rating,
            "reason": reason,
        })

    # Second pass: upgrade reason with LLM if key present (best-effort)
    key = _secrets.get("EMERGENT_LLM_KEY") or _secrets.get("OPENAI_API_KEY")
    if not key or not out:
        out.sort(key=lambda x: (x["rating"], -x["invested_rs"]))
        return out
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=key,
            session_id="nivesh-category-ratings",
            system_message=(
                "You are rating category-level diversification quality of an Indian MF portfolio. "
                "Given existing ratings/reasons, return STRICT JSON {'updates':[{category, reason}]} "
                "with at most 40-word punchier reasons that call out fund consolidation action. "
                "Keep numbers from input intact. No generic phrases."
            ),
        ).with_model("openai", "gpt-4o-mini")
        compact = [
            {"category": o["category"], "rating": o["rating"], "reason": o["reason"],
             "funds_count": o["funds_count"], "invested_rs": o["invested_rs"]}
            for o in out
        ]
        raw = await chat.send_message(UserMessage(text=json.dumps(compact)))
        data = _parse_json_loose(raw)
        updates = {u.get("category"): u.get("reason")
                   for u in (data.get("updates") or [])
                   if isinstance(u, dict)}
        for o in out:
            if o["category"] in updates and updates[o["category"]]:
                o["reason"] = str(updates[o["category"]])[:300]
    except Exception as e:  # noqa: BLE001
        logger.info(f"category AI reason-upgrade skipped: {e}")

    out.sort(key=lambda x: (x["rating"], -x["invested_rs"]))
    return out


# ── MF AI rating (on-demand) ─────────────────────────────────────────────
async def rate_fund(fund_detail: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a 1-5 rating + reasoning for a single MF."""
    key = _secrets.get("EMERGENT_LLM_KEY") or _secrets.get("OPENAI_API_KEY")
    if not key:
        return {"rating": None, "reason": "LLM not configured"}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=key,
            session_id="nivesh-mf-rating",
            system_message=(
                "You rate Indian mutual funds 1-5 stars based on risk-adjusted "
                "returns, expense, and portfolio quality. Return STRICT JSON "
                "{rating: int 1-5, reason: 2-sentence string}."
            ),
        ).with_model("openai", "gpt-4o-mini")
        compact = {
            "name": fund_detail.get("scheme_name")
                    or fund_detail.get("instrument", {}).get("instrument_name"),
            "metadata": fund_detail.get("metadata"),
            "ratios": (fund_detail.get("ratios_history") or [{}])[0]
                      if fund_detail.get("ratios_history") else fund_detail.get("ratios"),
            "top_holdings": (fund_detail.get("holdings") or [])[:10],
        }
        raw = await chat.send_message(UserMessage(
            text=f"Rate this fund:\n{json.dumps(compact, default=str)}"
        ))
        data = _parse_json_loose(raw)
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
