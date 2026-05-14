"""AI narration on top of portfolio_intelligence metrics.

Feeds computed metrics into GPT-4o-mini (via OpenAI or Emergent LLM key) to
produce specific, one-line actionable insights. Graceful fallback to
deterministic templates when the LLM is unavailable.
"""
from __future__ import annotations
import json
import logging
import time
from typing import Any, Dict, List, Optional

from helpers import secrets as _secrets

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a SEBI-registered portfolio analyst writing terse,
evidence-based insights for an Indian mutual-fund investor. Every insight
must cite a specific ₹ amount, %, or fund name from the data. Never use
hedge words like "may" or "could". Maximum 2 lines per insight. Output
strict JSON per the schema in the user prompt."""

# ── Circuit breaker ──────────────────────────────────────────────────────
# The Emergent LLM upstream endpoint has been unresponsive (requests block
# the event loop for 60+s despite asyncio.wait_for + shield). For now the
# circuit stays permanently OPEN by default; admin can re-enable LLM via
# POST /api/admin/ai/circuit/reset once upstream is healthy again. The
# deterministic fallback produces high-quality insights that cite real
# ₹ amounts + % directly from computed metrics.
_CB_COOLDOWN_S = 300
import time as _time_mod
_LLM_CB_UNTIL = _time_mod.time() + 365 * 24 * 3600  # tripped indefinitely


def _llm_circuit_open() -> bool:
    return time.time() < _LLM_CB_UNTIL


def _llm_circuit_trip() -> None:
    global _LLM_CB_UNTIL
    _LLM_CB_UNTIL = time.time() + _CB_COOLDOWN_S
    logger.warning("LLM circuit tripped for %ss", _CB_COOLDOWN_S)


def llm_circuit_reset() -> None:
    global _LLM_CB_UNTIL
    _LLM_CB_UNTIL = 0.0
    logger.info("LLM circuit manually reset")


def llm_circuit_status() -> Dict[str, Any]:
    return {
        "open": _llm_circuit_open(),
        "opens_until": _LLM_CB_UNTIL,
        "seconds_remaining": max(0, int(_LLM_CB_UNTIL - time.time())),
    }


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
    """Deterministic insights — NO LLM invents numbers here.

    Data-accuracy rule: every ₹ and % comes from the metrics dict which is
    computed from real holdings. Letting the LLM invent numbers produced the
    "Banking 773% / Pharma 818%" garbage users flagged.
    """
    insights: List[Dict[str, str]] = []
    n = m.get("narrative") or {}
    c = m.get("compression") or {}
    top = m.get("top_stocks") or []
    pairs = m.get("pairwise_overlap") or []
    cats = m.get("category_inefficiency") or []
    sectors = m.get("sector_exposure") or []
    rd = m.get("redundancy_suggestions") or []
    mfs = m.get("mf_investments") or []

    # 1. Compression
    if n.get("total_invested_rs") and c.get("score"):
        insights.append({
            "type": "compression",
            "headline": f"Your ₹{_fmt(n['total_invested_rs'])} portfolio behaves like ₹{_fmt(n['behaves_like_rs'])} due to overlap.",
            "detail": f"Effective {c.get('effective_stocks')} unique stocks out of {c.get('unique_stocks')}.",
        })

    # 2. Top stock concentration
    if top and (top[0].get("exposure_pct") or 0) >= 5:
        s = top[0]
        insights.append({
            "type": "top_stock",
            "headline": f"{s['name']} is {s['exposure_pct']:.1f}% of your portfolio via {s['fund_count']} funds.",
            "detail": f"₹{_fmt(s['exposure_rs'])} concentrated in this single stock.",
        })

    # 3. MF category concentration (NEW — user flagged Mid Cap exposure)
    #    Flag when a single MF category > 35% of total MF AUM.
    total_mf = sum((mf.get("amount_rs") or 0) for mf in mfs)
    if total_mf > 0:
        from collections import defaultdict as _dd
        cat_totals = _dd(float)
        for mf in mfs:
            cname = (mf.get("category") or "Uncategorised").strip() or "Uncategorised"
            cat_totals[cname] += (mf.get("amount_rs") or 0)
        flagged = sorted(
            [(cn, v / total_mf * 100) for cn, v in cat_totals.items() if cn != "Uncategorised"],
            key=lambda x: -x[1],
        )
        if flagged and flagged[0][1] >= 35.0:
            cat_name, cat_pct = flagged[0]
            insights.append({
                "type": "category_concentration",
                "headline": f"{cat_name} is {cat_pct:.0f}% of your MF corpus — above the 35% guardrail.",
                "detail": (
                    f"₹{_fmt(total_mf * cat_pct / 100)} sits in {cat_name}. "
                    "Concentration in one category amplifies drawdown risk — consider trimming."
                ),
            })

    # 4. Category inefficiency
    for cat in cats[:1]:
        if cat.get("inefficient"):
            insights.append({
                "type": "category_inefficiency",
                "headline": f"{cat['funds_count']} {cat['category']} funds with {cat['avg_pair_overlap']}% average overlap.",
                "detail": f"₹{_fmt(cat['invested_rs'])} split across near-identical strategies.",
            })

    # 5. Pairwise duplication
    for p in pairs[:1]:
        if (p.get("overlap_pct") or 0) >= 50:
            insights.append({
                "type": "duplication",
                "headline": f"{p['a_name']} and {p['b_name']} overlap {p['overlap_pct']:.0f}%.",
                "detail": "; ".join(p.get("reasons", [])) or "Strong strategy duplication.",
            })

    # 6. Sector concentration — clamp to [0, 100] so we never leak bad data to UI
    for s in sectors[:1]:
        sec_pct = max(0.0, min(100.0, float(s.get("pct") or 0)))
        if sec_pct >= 30:
            insights.append({
                "type": "sector_concentration",
                "headline": f"{s.get('sector','?')} is {sec_pct:.0f}% of your equity exposure.",
                "detail": f"₹{_fmt(s.get('rs', 0))} tilted to {s.get('sector','?')} — consider diversifying.",
            })

    # 7. Redundancy suggestion
    if rd:
        r = rd[0]
        if (r.get("overlap_reduced_pp") or 0) > 3:
            insights.append({
                "type": "redundancy",
                "headline": f"Removing {r['remove_name']} cuts overlap by {r['overlap_reduced_pp']} pp.",
                "detail": f"Sector drift only {r['sector_l1_drift_pct']}%.",
            })

    return insights[:6]


def _fmt(n: float) -> str:
    if n is None:
        return "—"
    if n >= 10_00_000:
        return f"{n/1_00_000:.2f}L"
    if n >= 1_000:
        return f"{n/1000:.1f}K"
    return f"{int(n)}"


async def _call_llm_with_timeout(chat, user_text: str, timeout_s: int = 10) -> Optional[str]:
    """Run an LlmChat.send_message in a background task with hard timeout.

    Litellm retries internally and ignores asyncio cancellation, so we run
    it in a separate task and abandon if it exceeds the timeout. Returns
    raw response text or None on timeout/error.
    """
    import asyncio
    from emergentintegrations.llm.chat import UserMessage
    task = asyncio.create_task(chat.send_message(UserMessage(text=user_text)))
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()  # Fire-and-forget; task may continue but we won't wait.
        return None


async def generate_insights(metrics: Dict[str, Any]) -> List[Dict[str, str]]:
    """Generate portfolio insights.

    Data-accuracy policy (v2.5): insights are ALWAYS produced from pre-computed
    metrics — never from LLM output — because the LLM was hallucinating
    percentages (e.g. "Banking 773%") that broke user trust. The LLM path is
    kept only behind an opt-in flag for a narrative-rewrite pass in future.
    """
    if metrics.get("empty"):
        return []
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
    if not key or not out or _llm_circuit_open():
        out.sort(key=lambda x: (x["rating"], -x["invested_rs"]))
        return out
    try:
        from emergentintegrations.llm.chat import LlmChat
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
        raw = await _call_llm_with_timeout(chat, json.dumps(compact), timeout_s=10)
        if raw is None:
            _llm_circuit_trip()
            out.sort(key=lambda x: (x["rating"], -x["invested_rs"]))
            return out
        data = _parse_json_loose(raw)
        updates = {u.get("category"): u.get("reason")
                   for u in (data.get("updates") or [])
                   if isinstance(u, dict)}
        for o in out:
            if o["category"] in updates and updates[o["category"]]:
                o["reason"] = str(updates[o["category"]])[:300]
    except Exception as e:  # noqa: BLE001
        _llm_circuit_trip()
        logger.info("category AI reason-upgrade skipped: %s", e)

    out.sort(key=lambda x: (x["rating"], -x["invested_rs"]))
    return out


# ── MF AI rating (on-demand) ─────────────────────────────────────────────
async def rate_fund(fund_detail: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a 1-5 rating + reasoning for a single MF."""
    key = _secrets.get("EMERGENT_LLM_KEY") or _secrets.get("OPENAI_API_KEY")
    if not key:
        return {"rating": None, "reason": "LLM not configured"}
    if _llm_circuit_open():
        return {"rating": None, "reason": "LLM temporarily unavailable"}
    try:
        from emergentintegrations.llm.chat import LlmChat
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
        raw = await _call_llm_with_timeout(
            chat, f"Rate this fund:\n{json.dumps(compact, default=str)}", timeout_s=10
        )
        if raw is None:
            _llm_circuit_trip()
            return {"rating": None, "reason": "LLM timeout"}
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
        _llm_circuit_trip()
        logger.warning("AI rate_fund failed: %s", e)
        return {"rating": None, "reason": f"LLM error: {e}"}
