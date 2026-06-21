"""AI Chat routes."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import os
import uuid
import json
import logging

from deps import db, get_current_user, ai_engine
from models import ChatMessageInput
from services import portfolio_intelligence
from services.action_plan_manager import ActionPlanManager
from routes.copilot import _advisor_book_block, _is_advisor_caller
from services.copilot_charts import (
    CHART_PROTOCOL, validate_chart_blocks, log_invalid_chart_specs,
)

logger = logging.getLogger(__name__)

# Always attempt to import the LangGraph copilot agent at startup.
# _lg_available tracks whether imports succeeded; the actual routing
# decision is made per-request from the DB-backed feature flag
# "copilot_engine_nidp" (admin default: everyone → NIDP engine).
_lg_available = False
_get_copilot_graph = None
_HumanMessage = None
_AIMessage = None

_load_persona_context = None

try:
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from nidp.services.copilot_agent.graph import get_graph as _get_copilot_graph
    from nidp.services.copilot_agent.persona_loader import load_persona_context as _load_persona_context
    from langchain_core.messages import HumanMessage as _HumanMessage
    from langchain_core.messages import AIMessage as _AIMessage
    _lg_available = True
    logger.info("LangGraph copilot agent available (routing controlled by 'copilot_engine_nidp' flag)")
except Exception as _lg_err:
    logger.warning("LangGraph import failed (%s) — NIDP engine unavailable, V3 RAG will be used", _lg_err)
router = APIRouter(prefix="/api")

_plan_manager = ActionPlanManager()


# Advisor-mode system prompt — replaces FINANCIAL_ADVISOR_SYSTEM (which is
# tuned for a single user's portfolio + Plan Board) when the caller is an
# advisor asking cross-client questions. Mirrors the contract used in
# /copilot/ask so advisor experience stays consistent across surfaces.
_ADVISOR_CHAT_SYSTEM = """You are the advisor's cross-client AI copilot for nivesh.ai.
You have access to the entire client book provided below.

Style: crisp, ≤ 250 words, ground every claim in the numbers in the book.
When the user asks for clients matching a condition (top AUM, underperformers,
needing rebalance, etc.), return a Markdown table with name, AUM and the
specific number that triggered the match. End with one concrete next step.
Never speculate beyond the data in the book. If the book has zero clients,
say so and suggest adding a client profile.

{portfolio_context}

DISCLAIMER: AI-generated guidance for educational purposes. Always consult a SEBI-registered advisor."""


async def _active_plan_context(user_id: str) -> str:
    """Build a COMPACT block describing the user's current active action plan,
    if any. The system prompt's rules tell the AI how to behave when this
    block is empty (answer factual questions from intelligence data, redirect
    specific recommendations to a fresh Plan Board run).

    Each action now carries a CP3-* block so the LLM can answer the
    five mandatory questions (§10.13 CP-3) when the user asks for an
    explanation of any recommendation.
    """
    try:
        plan = await _plan_manager.get_active_plan(user_id)
    except Exception as e:
        logger.debug(f"active plan context fetch failed: {e}")
        plan = None

    if not plan or not plan.get("actions"):
        return (
            "\n\n── ACTIVE ACTION PLAN ──\n"
            "No active action plan exists for this user yet.\n"
            "For SPECIFIC recommendations (which fund to exit, tax-aware moves, "
            "fresh fund picks) suggest a Plan Board run. Factual questions about "
            "overlap, allocation, exposure, etc. are still answerable from the "
            "PORTFOLIO INTELLIGENCE block above.\n"
        )

    lines = [
        "\n\n── ACTIVE ACTION PLAN (USE FOR SPECIFIC RECOMMENDATIONS) ──",
        f"Plan ID: {plan.get('plan_id')} · Status: {plan.get('status')} · "
        f"Generated: {str(plan.get('created_at',''))[:10]}",
        f"Total actions: {len(plan['actions'])} · "
        f"Completed: {plan.get('completed_actions', 0)} · "
        f"Pending: {plan.get('pending_actions', len(plan['actions']))}",
    ]

    tti = plan.get("total_tax_impact") or plan.get("tax_impact") or {}
    if tti:
        lines.append(
            f"Plan tax: total_liability=₹{tti.get('total_tax_liability') or tti.get('total_tax') or 0:,.0f} "
            f"(equity LTCG ₹{tti.get('equity_ltcg',0):,.0f}, equity STCG ₹{tti.get('equity_stcg',0):,.0f})"
        )

    # Plan-level simulation block (populated by SimulationEngine when enabled)
    simulation = plan.get("simulation")

    try:
        from services.recommendation_engine.cp3_narrator import narrate_action as _cp3_narrate
        _cp3_available = True
    except Exception:
        _cp3_available = False

    lines.append("\nActions (recommend these EXACTLY for action-shaped questions):")
    for i, a in enumerate(plan["actions"], 1):
        reasons = " · ".join(a.get("reason_codes") or [])
        ti = a.get("tax_impact") or {}
        tax_str = ""
        if ti.get("tax_impact_pending"):
            tax_str = " [tax pending — buy_date missing]"
        elif ti.get("tax_liability"):
            tax_str = f" · est. tax ₹{ti.get('tax_liability',0):,.0f} ({ti.get('tax_regime','?')})"
        amt = a.get("exit_amount_rs") or a.get("amount_rs") or a.get("amount") or 0
        lines.append(
            f"  {i}. [{a.get('type')}] {a.get('asset_name','?')[:55]}  "
            f"₹{amt:,.0f} · {reasons}{tax_str}"
        )
        # CP-3: inject structured 5-question narration below each action
        if _cp3_available:
            try:
                lines.append(_cp3_narrate(a, simulation))
            except Exception as _cp3_err:
                logger.debug("CP3 narration failed for action %s: %s", a.get("action_id"), _cp3_err)

    return "\n".join(lines)


# Keywords that signal the user is asking for an action recommendation
# (sell/exit/switch/add/buy/rebalance/optimise) rather than a factual lookup.
# When present AND the user has no active plan, we auto-generate one before
# the LLM call so the answer can cite real plan actions instead of refusing.
_ACTIONABLE_KEYWORDS = (
    "should i sell", "should i exit", "should i remove", "should i trim",
    "should i buy", "should i add", "should i switch", "should i rebalance",
    "exit ", "sell ", "trim ", "remove with", "switch to", "switch from",
    "rebalance", "fix my", "fix overlap", "clean up my", "clean up portfolio",
    "tax-smart", "tax smart", "tax-loss harvest", "tax loss harvest",
    "harvest loss", "optimise tax", "optimize tax", "minimise tax", "minimize tax",
    "where should i invest", "where to invest",
    "what should i do", "next action", "next step",
    "minimal tax impact", "with minimum tax",
)


def _is_actionable_question(message: str) -> bool:
    """Cheap heuristic — returns True when the user's message looks like it
    expects a specific action recommendation rather than a factual answer."""
    m = (message or "").lower()
    return any(kw in m for kw in _ACTIONABLE_KEYWORDS)


async def _ensure_plan_for_actionable_question(user_id: str, message: str) -> None:
    """If the user asks an actionable question but has no active plan, run a
    Plan Board generation in-line so the LLM can cite real actions. Best-effort:
    swallows errors so a slow generation never breaks the chat reply.

    Skips when:
      - the user already has an active plan (no need to regenerate),
      - the question is purely factual (no need for a plan),
      - the user has no holdings (nothing to plan against)."""
    if not _is_actionable_question(message):
        return
    try:
        existing = await _plan_manager.get_active_plan(user_id)
        if existing and existing.get("actions"):
            return
        holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
        if not holdings:
            return
        intelligence = await portfolio_intelligence.compute_portfolio_intelligence(user_id)
        plan = await _plan_manager.generate_plan(user_id, intelligence, holdings)
        # generate_plan returns a "preview" plan; activate it so get_active_plan picks it up.
        plan["status"] = "active"
        await _plan_manager.create_plan(plan)
        logger.info(f"chat: auto-generated action plan for {user_id} (actions={len(plan.get('actions') or [])})")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"chat auto-plan-gen failed for {user_id}: {e}")



_KNOWN_AMCS = {
    "HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "NIPPON", "FRANKLIN",
    "TEMPLETON", "MIRAE", "DSP", "TATA", "UTI", "INVESCO", "HSBC",
    "IDFC", "SUNDARAM", "MOTILAL", "EDELWEISS", "BARODA", "CANARA",
    "BANDHAN", "UNION", "BOI", "QUANTUM",
}
_MULTI_WORD_AMCS = [("ADITYA", "BIRLA"), ("PARAG", "PARIKH")]


def _extract_amc(name: str) -> Optional[str]:
    if not name:
        return None
    words = name.upper().split()
    word_set = set(words)
    for a, b in _MULTI_WORD_AMCS:
        if a in word_set and b in word_set:
            return f"{a} {b}"
    for w in words:
        if w in _KNOWN_AMCS:
            return w
    return words[0] if words else None  # fallback: first word


def _amc_concentration_block(mf_investments: list) -> str:
    """Bucket MF investments by extracted AMC and return a sorted markdown
    block. Empty string when there are no MFs to bucket."""
    if not mf_investments:
        return ""
    totals: Dict[str, float] = {}
    grand = 0.0
    for m in mf_investments:
        amt = float(m.get("amount_rs") or 0)
        if amt <= 0:
            continue
        amc = _extract_amc(m.get("scheme_name", ""))
        if not amc:
            continue
        totals[amc] = totals.get(amc, 0.0) + amt
        grand += amt
    if grand <= 0:
        return ""
    rows = sorted(
        [(amc, val, val / grand * 100) for amc, val in totals.items()],
        key=lambda r: r[1], reverse=True,
    )[:8]
    out = "\nAMC Concentration (% of MF AUM):\n"
    for amc, val, pct in rows:
        out += f"  - {amc}: {pct:.1f}% (₹{val:,.0f})\n"
    return out


_EMPTY_HOLDINGS_BLOCK = (
    "\n\n=== USER PORTFOLIO HOLDINGS ===\n"
    "NO HOLDINGS RECORDED for this user. The user has not uploaded a CAS, "
    "imported via Connect, or added holdings manually. When asked about "
    "holdings, top funds, top stocks, returns, profit, performance, "
    "allocation, sectors, or anything that requires holdings, you MUST "
    "tell the user plainly: 'You don't have any holdings recorded yet — "
    "upload your CAS or connect your portfolio to get started.' "
    "DO NOT invent holding names, funds, stocks, percentages, or returns — "
    "fabricating data here is a critical failure.\n"
)


def _render_portfolio_block(holdings: list) -> str:
    """Holdings summary with EXPLICIT per-holding profit + return so the
    LLM can answer 'top funds by return / profit' factually without
    re-doing math. Also includes a pre-sorted top-by-return and
    top-by-profit ranking so the model just reads the answer off.

    Cost-basis sanity check: if buy_price == current_price AND there's
    no buy_date, treat as a placeholder fill (CAS rebuild defaults to
    cmp when avg cost can't be derived). Such holdings are listed
    separately under "Holdings with unknown cost basis" and excluded
    from any profit-based ranking — the AI is told upfront which
    holdings can vs cannot be ranked.

    Empty holdings → returns the explicit `_EMPTY_HOLDINGS_BLOCK`
    instead of "" so the LLM can't silently confabulate.
    """
    if not holdings:
        return _EMPTY_HOLDINGS_BLOCK
    enriched = []
    for h in holdings:
        qty = float(h.get("quantity") or 0)
        bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        inv = qty * bp
        cur = qty * cp
        profit = cur - inv
        ret = (profit / inv * 100) if inv > 0 else 0.0
        # Cost-basis confidence flag (see docstring).
        has_buy_date = bool(h.get("buy_date"))
        prices_match = abs(bp - cp) < 0.005
        cost_basis_known = (bp > 0) and not (prices_match and not has_buy_date)
        enriched.append({
            "name": h.get("name", "Unknown"),
            "type": h.get("asset_type", ""),
            "sector": h.get("sector") or "N/A",
            "qty": qty, "buy_price": bp, "current_price": cp,
            "invested": inv, "current": cur,
            "profit": profit, "ret_pct": ret,
            "cost_basis_known": cost_basis_known,
        })
    # Totals — invested only counts holdings with known cost basis so the
    # portfolio-level return % isn't dragged to 0% by placeholder rows.
    ranked = [e for e in enriched if e["cost_basis_known"]]
    total_inv = sum(e["invested"] for e in ranked)
    total_cur = sum(e["current"] for e in ranked)
    total_profit = total_cur - total_inv
    total_ret = (total_profit / total_inv * 100) if total_inv > 0 else 0.0

    unknown_basis = [e for e in enriched if not e["cost_basis_known"]]
    out = (
        "\n\n=== USER PORTFOLIO HOLDINGS ===\n"
        f"Holdings with KNOWN cost basis: {len(ranked)} · "
        f"invested ₹{total_inv:,.0f} · current ₹{total_cur:,.0f} · "
        f"profit ₹{total_profit:+,.0f} · return {total_ret:+.1f}%\n"
    )
    if unknown_basis:
        out += (
            f"Holdings with UNKNOWN cost basis: {len(unknown_basis)} "
            f"(buy_price was a placeholder; profit/return cannot be computed for these — "
            f"they are excluded from rankings below but their CMP value is still tracked)\n"
        )
    out += f"\nAll Holdings ({len(enriched)}):\n"
    for e in enriched:
        if e["cost_basis_known"]:
            out += (
                f"  - {e['name']} [{e['type']}]: qty {e['qty']:g} · "
                f"invested ₹{e['invested']:,.0f} · current ₹{e['current']:,.0f} · "
                f"profit ₹{e['profit']:+,.0f} · return {e['ret_pct']:+.1f}% · "
                f"sector {e['sector']}\n"
            )
        else:
            out += (
                f"  - {e['name']} [{e['type']}]: qty {e['qty']:g} · "
                f"current ₹{e['current']:,.0f} · cost basis UNKNOWN · "
                f"sector {e['sector']}\n"
            )

    # Pre-sorted leaderboards — the AI cites these verbatim for "top N
    # funds by return / by profit / by loss" questions, eliminating the
    # "I don't have performance data" failure mode where the model
    # refuses to compute these from the rows above. Only holdings with
    # known cost basis enter rankings.
    only_funds = [e for e in ranked if (e["type"] or "").lower() in ("mutual_fund", "mf", "equity")]
    if len(only_funds) >= 2:
        by_ret = sorted(only_funds, key=lambda x: x["ret_pct"], reverse=True)[:5]
        by_profit = sorted(only_funds, key=lambda x: x["profit"], reverse=True)[:5]
        worst_ret = sorted(only_funds, key=lambda x: x["ret_pct"])[:3]
        out += "\nTop holdings by RETURN %:\n"
        for i, e in enumerate(by_ret, 1):
            out += f"  {i}. {e['name']}: {e['ret_pct']:+.1f}% (profit ₹{e['profit']:+,.0f})\n"
        out += "Top holdings by ABSOLUTE PROFIT (₹):\n"
        for i, e in enumerate(by_profit, 1):
            out += f"  {i}. {e['name']}: ₹{e['profit']:+,.0f} ({e['ret_pct']:+.1f}%)\n"
        if worst_ret and worst_ret[0]["ret_pct"] < 0:
            out += "Worst-performing holdings (by return %):\n"
            for i, e in enumerate(worst_ret, 1):
                if e["ret_pct"] >= 0:
                    break
                out += f"  {i}. {e['name']}: {e['ret_pct']:+.1f}% (loss ₹{e['profit']:+,.0f})\n"

    # Per-sector breakdown — direct equity holdings only, and only those
    # with known cost basis. Excluding placeholder-basis rows means the
    # ranking actually reflects performance instead of being skewed by
    # 0% rows. (For MF look-through stocks see the PORTFOLIO INTELLIGENCE
    # block — sector exposure + top-stock exposure but no per-stock profit.)
    direct_equities = [e for e in ranked if (e["type"] or "").lower() == "equity"]
    by_sector: Dict[str, list] = {}
    for e in direct_equities:
        by_sector.setdefault(e["sector"] or "Unknown", []).append(e)
    multi_sector = {s: rows for s, rows in by_sector.items() if rows}
    if len(multi_sector) >= 1 and any(len(r) >= 1 for r in multi_sector.values()):
        # Sort sectors by total ₹ profit desc so the most material
        # sectors come first.
        sector_order = sorted(
            multi_sector.items(),
            key=lambda kv: sum(r["profit"] for r in kv[1]),
            reverse=True,
        )
        out += "\nTop equities BY SECTOR (direct holdings only, ranked within each sector):\n"
        for sector, rows in sector_order:
            top_in_sector = sorted(rows, key=lambda x: x["ret_pct"], reverse=True)[:3]
            sector_total_profit = sum(r["profit"] for r in rows)
            out += f"  Sector: {sector} ({len(rows)} holdings · sector profit ₹{sector_total_profit:+,.0f})\n"
            for i, e in enumerate(top_in_sector, 1):
                out += (
                    f"    {i}. {e['name']}: return {e['ret_pct']:+.1f}% · "
                    f"profit ₹{e['profit']:+,.0f}\n"
                )
    return out


async def _compute_goals_context(user_id: str) -> str:
    """User's financial goals from user_goals (PG). Includes both planned
    on-track % and actual on-track % (reconciled against recent SIP from
    CAS) so the AI can flag plan-vs-execution gaps without asking the
    user. Returns empty string when PG is down or there are no goals."""
    try:
        from services import pg_client as _pg
        pool = await _pg.get_pool()
        if pool is None:
            return ""
        import uuid as _uuid
        try:
            uid = _uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except Exception:  # noqa: BLE001
            uid = _uuid.uuid5(_uuid.NAMESPACE_DNS, f"nivesh:user:{user_id}")
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT goal_id, goal_type, goal_name, target_amount_rs, "
                "horizon_years, current_corpus_rs, monthly_sip_rs, "
                "expected_return_pct, on_track_pct, priority, status "
                "FROM user_goals WHERE user_id = $1 AND COALESCE(status,'') <> 'archived' "
                "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
                "created_at DESC LIMIT 8",
                uid,
            )
        if not rows:
            return (
                "\n\n=== USER GOALS ===\n"
                "NO GOALS RECORDED. The user has not created any financial "
                "goals yet. When asked about goals or being on track, say "
                "so plainly — DO NOT invent goal names or targets.\n"
            )
        # Reconcile actual vs planned SIP for the gap line.
        actual_sip = 0.0
        try:
            from services import cas_snapshot_engine as _eng
            stats = await _eng.actual_monthly_sip_rate(user_id, lookback_months=6)
            actual_sip = float(stats.get("avg_monthly_rs") or 0)
        except Exception:  # noqa: BLE001
            pass
        out = "\n\n=== USER GOALS ===\n"
        out += f"Total goals: {len(rows)} · Actual recent SIP: ₹{actual_sip:,.0f}/mo (last 6 months)\n"
        for r in rows:
            target = float(r["target_amount_rs"] or 0)
            horizon = float(r["horizon_years"] or 0)
            sip = float(r["monthly_sip_rs"] or 0)
            corpus = float(r["current_corpus_rs"] or 0)
            on_track = float(r["on_track_pct"] or 0)
            gap_line = ""
            if sip > 0 and actual_sip + 1 < sip:
                gap_line = f" · ⚠ SIP gap ₹{sip - actual_sip:,.0f}/mo"
            out += (
                f"  - {r['goal_name']} ({r['goal_type']}, {r['priority']}): "
                f"target ₹{target:,.0f} in {horizon:.0f}y · "
                f"corpus ₹{corpus:,.0f} · plan SIP ₹{sip:,.0f}/mo · "
                f"{on_track:.0f}% on track{gap_line}\n"
            )
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("goals context build failed for %s: %s", user_id, e)
        return ""


async def _compute_health_context(user_id: str) -> str:
    """Portfolio Health scorecard — score/grade plus the top 3 risk drivers.
    Different from the intelligence block: health is the holistic scorecard
    the dashboard shows; intelligence is the analytic detail. Both inform
    chat answers."""
    try:
        from services import portfolio_health as _ph
        hr = await _ph.build_portfolio_health(user_id)
        # Empty-portfolio sentinel: build_portfolio_health returns a
        # 0/F result with a "no holdings on file" summary when the user
        # has nothing to score. Treat that the same as "no health score"
        # so the AI doesn't broadcast a misleading 0/100 grade.
        is_empty_state = (
            not hr or hr.health_score is None or
            (hr.health_score == 0 and "no holdings" in (hr.summary or "").lower())
        )
        if is_empty_state:
            return (
                "\n\n=== PORTFOLIO HEALTH SCORECARD ===\n"
                "NO HEALTH SCORE AVAILABLE (no portfolio yet, or scoring "
                "pipeline hasn't run). DO NOT invent a score or grade.\n"
            )
        out = "\n\n=== PORTFOLIO HEALTH SCORECARD ===\n"
        out += f"Health: {hr.health_score:.0f}/100 (Grade {hr.grade})"
        if hr.low_confidence:
            out += " · low-confidence (some sub-scores were heuristic)"
        out += "\n"
        if hr.summary:
            out += f"Summary: {hr.summary}\n"
        if hr.components:
            comp_line = " · ".join(
                f"{c.name}={c.score:.0f}" for c in hr.components.values()
            )
            out += f"Components: {comp_line}\n"
        drivers = (hr.risk_drivers or [])[:3]
        if drivers:
            out += "Top risk drivers:\n"
            for d in drivers:
                label = d.get("label") or d.get("title") or d.get("kind", "")
                detail = d.get("detail") or d.get("note") or ""
                out += f"  - {label}: {detail[:160]}\n"
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("health context build failed for %s: %s", user_id, e)
        return ""


async def _compute_snapshot_context(user_id: str) -> str:
    """Financial snapshot — income / expenses / corpus / liabilities — so
    the AI can reason about affordability and savings rate. Returns empty
    when no snapshot exists yet (user hasn't filled in goals onboarding)."""
    try:
        from services import pg_client as _pg
        pool = await _pg.get_pool()
        if pool is None:
            return ""
        import uuid as _uuid
        try:
            uid = _uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except Exception:  # noqa: BLE001
            uid = _uuid.uuid5(_uuid.NAMESPACE_DNS, f"nivesh:user:{user_id}")
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT monthly_income_rs, monthly_expenses_rs, current_corpus_rs, "
                "total_liabilities_rs, income_growth_pct, inflation_pct, behavior_score "
                "FROM user_financial_snapshots WHERE user_id = $1",
                uid,
            )
        if not row:
            return (
                "\n\n=== FINANCIAL SNAPSHOT ===\n"
                "NO FINANCIAL SNAPSHOT RECORDED. The user hasn't filled in "
                "income/expenses/corpus yet. DO NOT invent these figures.\n"
            )
        out = "\n\n=== FINANCIAL SNAPSHOT ===\n"
        income = float(row["monthly_income_rs"] or 0)
        expenses = float(row["monthly_expenses_rs"] or 0)
        savings = max(0.0, income - expenses)
        savings_rate = (savings / income * 100) if income > 0 else 0.0
        out += f"Monthly income: ₹{income:,.0f} · expenses: ₹{expenses:,.0f} · "
        out += f"savings capacity: ₹{savings:,.0f}/mo ({savings_rate:.0f}%)\n"
        out += f"Current corpus: ₹{float(row['current_corpus_rs'] or 0):,.0f} · "
        out += f"liabilities: ₹{float(row['total_liabilities_rs'] or 0):,.0f}\n"
        if row.get("behavior_score") is not None:
            out += f"Behavior score: {float(row['behavior_score']):.0f}/100\n"
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("snapshot context build failed for %s: %s", user_id, e)
        return ""


# Redis-backed warmup cache for the assembled intelligence-context string.
# `compute_portfolio_intelligence` is the heaviest call in the chat path
# (PG joins + look-through across all MFs), so we cache the rendered
# string for a few minutes — invalidated implicitly when the TTL expires.
# Key namespace lives under nivesh:cache:chat_ctx:intel:* via redis_client.
_INTEL_CTX_TTL_S = 300


async def _compute_portfolio_intelligence_context(user_id: str,
                                                   *, use_cache: bool = True) -> str:
    """Generate PG-based Portfolio Intelligence context for AI chat.

    `use_cache=True` (default) checks Redis for a recent rendered copy
    first; misses fall through to a fresh compute and re-populate. The
    `/chat/warmup` endpoint always passes `use_cache=False` so the first
    request after drawer-open primes the cache instead of returning a
    stale value.
    """
    if use_cache:
        try:
            from services import redis_client as _redis
            cached = await _redis.cache_get(f"chat_ctx:intel:{user_id}")
            if isinstance(cached, str):
                return cached
        except Exception:  # noqa: BLE001
            pass  # cache is best-effort
    try:
        metrics = await portfolio_intelligence.compute_portfolio_intelligence(user_id)

        if metrics.get("empty"):
            return ""

        # Build intelligence summary for AI context
        narrative = metrics.get("narrative", {})
        compression = metrics.get("compression", {})
        top_stocks = metrics.get("top_stocks", [])
        pairs = metrics.get("pairwise_overlap", [])
        category_ineff = metrics.get("category_inefficiency", [])
        sector_exp = metrics.get("sector_exposure", [])
        redundancy = metrics.get("redundancy_suggestions", [])
        mf_investments = metrics.get("mf_investments", [])
        
        ctx = "\n\n=== PORTFOLIO INTELLIGENCE (Real Stock-Level Analysis) ===\n"
        
        # Compression summary
        ctx += f"\nCompression Score: {compression.get('score', 0):.1f}/100 "
        ctx += f"(Portfolio behaves like ₹{narrative.get('behaves_like_rs', 0):,.0f} due to overlap)\n"
        ctx += f"- Unique stocks held: {narrative.get('unique_stocks', 0)}\n"
        ctx += f"- Effective stocks (risk-weighted): {compression.get('effective_stocks', 0)}\n"
        ctx += f"- Top 10 stocks exposure: {compression.get('top_10_exposure_pct', 0):.1f}%\n"
        ctx += f"- Top 20 stocks exposure: {compression.get('top_20_exposure_pct', 0):.1f}%\n"
        
        # Top stock exposures
        if top_stocks:
            ctx += "\nTop Stock Exposures (look-through across all MFs):\n"
            for i, s in enumerate(top_stocks[:10], 1):
                ctx += f"  {i}. {s['name']} ({s.get('sector', 'N/A')}): {s['exposure_pct']:.2f}% (₹{s['exposure_rs']:,.0f}) via {s['fund_count']} funds\n"
        
        # Fund overlap pairs (with the actual shared companies per pair so
        # the AI can name them when asked "which companies are overlapping?")
        if pairs:
            ctx += "\nFund Overlap (Stock-Level):\n"
            for p in pairs[:5]:
                ctx += f"  - {p['a_name']} ↔ {p['b_name']}: {p['overlap_pct']:.1f}% overlap ({p['shared_count']} shared stocks)\n"
                if p.get('reasons'):
                    ctx += f"    Reasons: {', '.join(p['reasons'])}\n"
                top_shared = p.get('top_shared') or []
                if top_shared:
                    parts = []
                    for s in top_shared[:6]:
                        # `key` is a slug like 'hdfc-bank' or a lowercased name; humanise it
                        raw = (s.get('key') or '').replace('-', ' ').strip()
                        name = raw.title() if raw else 'Unknown'
                        parts.append(
                            f"{name} ({s.get('w_a', 0):.1f}% in A · {s.get('w_b', 0):.1f}% in B)"
                        )
                    ctx += "    Shared companies: " + "; ".join(parts) + "\n"
        
        # Category inefficiency
        if category_ineff:
            ctx += "\nCategory Inefficiency:\n"
            for cat in category_ineff[:3]:
                ctx += f"  - {cat['category']}: {cat['funds_count']} funds, {cat['avg_pair_overlap']:.1f}% avg overlap"
                if cat.get('inefficient'):
                    ctx += " ⚠️ INEFFICIENT\n"
                else:
                    ctx += "\n"
        
        # AMC concentration — bucket MF investments by fund-house name.
        ctx += _amc_concentration_block(mf_investments)

        # Sector exposure
        if sector_exp:
            ctx += "\nSector Exposure (look-through):\n"
            for s in sector_exp[:8]:
                ctx += f"  - {s['sector']}: {s['pct']:.1f}% (₹{s['rs']:,.0f})\n"
        
        # Redundancy suggestions
        if redundancy:
            ctx += "\nRedundancy Removal Suggestions:\n"
            for r in redundancy[:3]:
                ctx += f"  - Remove '{r['remove_name']}' (₹{r['remove_amount_rs']:,.0f}): "
                ctx += f"Would reduce overlap by {r['overlap_reduced_pp']:.1f}pp, "
                ctx += f"sector drift {r['sector_l1_drift_pct']:.1f}%\n"
        
        ctx += "\n(Use this intelligence data to provide accurate, data-driven advice)\n"

        # Best-effort write-through cache. Failure here never blocks the
        # response — the chat just stays uncached and recomputes next time.
        try:
            from services import redis_client as _redis
            await _redis.cache_set(f"chat_ctx:intel:{user_id}", ctx, ttl_s=_INTEL_CTX_TTL_S)
        except Exception:  # noqa: BLE001
            pass
        return ctx

    except Exception as e:
        logger.warning(f"Failed to compute intelligence context: {e}")
        return ""



# ── Per-user chat-history cache (Redis) ────────────────────────────────────
# Chat history is read on every session open / post-send refetch. Cache the
# session list and per-session message list in Redis, namespaced per user, and
# bust on every write so a just-sent message can never be hidden by a stale
# read. The TTL is only a safety net — explicit busts are the real invalidator.
_CHAT_CACHE_TTL_S = 6 * 3600


def _sessions_key(user_id: str) -> str:
    return f"chat:sessions:{user_id}"


def _messages_key(user_id: str, session_id: str) -> str:
    return f"chat:msgs:{user_id}:{session_id}"


async def _bust_chat_cache(user_id: str, session_id: Optional[str] = None) -> None:
    """Drop a user's session-list cache and (optionally) one session's messages."""
    try:
        from services import redis_client as _redis
        await _redis.cache_del(_sessions_key(user_id))
        if session_id:
            await _redis.cache_del(_messages_key(user_id, session_id))
    except Exception:  # noqa: BLE001 — cache is best-effort; never break a write
        pass


# Cached full equity universe for autocomplete — refreshed hourly so we don't hit
# the NIDP screener on every keystroke. Shared across requests in this process.
_STOCK_UNIVERSE: Dict[str, Any] = {"ts": 0.0, "rows": []}
_STOCK_UNIVERSE_TTL = 3600.0


async def _stock_universe() -> List[Dict[str, Any]]:
    import time
    now = time.time()
    if _STOCK_UNIVERSE["rows"] and (now - _STOCK_UNIVERSE["ts"]) < _STOCK_UNIVERSE_TTL:
        return _STOCK_UNIVERSE["rows"]
    try:
        from services.copilot_tools import daas_client
        rows = await daas_client.list_stock_universe(limit=800)
    except Exception as exc:  # noqa: BLE001
        logger.debug("_stock_universe load failed: %s", exc)
        rows = []
    if rows:
        _STOCK_UNIVERSE["rows"] = rows
        _STOCK_UNIVERSE["ts"] = now
    return _STOCK_UNIVERSE["rows"]


@router.get("/chat/instrument-search")
async def chat_instrument_search(q: str = "", limit: int = 6):
    """Typeahead for the chat composer — matching stocks (curated equity universe)
    and mutual funds (live NIDP scheme master). Read-only; degrades to empty lists
    if DaaS is unavailable. Fund rows are deduped to one per fund family (plan
    variants collapsed, Growth/Regular preferred)."""
    term = (q or "").strip()
    if len(term) < 2:
        return {"stocks": [], "funds": []}
    ql = term.lower()
    limit = max(1, min(int(limit or 6), 10))

    # Stocks — substring match on the full V3 equity universe (cached), ranked by
    # quality. Falls back to the curated list if NIDP is unavailable.
    stocks: List[Dict[str, Any]] = []
    universe = await _stock_universe()
    for r in universe:
        sym = (r.get("symbol") or "").strip()
        if not sym:
            continue
        name = (r.get("company_name") or r.get("name") or "").strip()
        if ql in sym.lower() or (name and ql in name.lower()):
            stocks.append({"symbol": sym, "name": name or sym, "sector": r.get("sector") or r.get("industry")})
        if len(stocks) >= limit:
            break
    if not stocks:
        from instruments_data import INDIAN_INSTRUMENTS
        for inst in INDIAN_INSTRUMENTS:
            if inst.get("type") != "equity":
                continue
            if ql in inst["name"].lower() or ql in inst["ticker"].lower():
                stocks.append({"symbol": inst["ticker"], "name": inst["name"], "sector": inst.get("sector")})
            if len(stocks) >= limit:
                break

    # Funds — live scheme search, collapsed to one row per fund family.
    funds: List[Dict[str, Any]] = []
    try:
        import re as _re
        from services.copilot_tools import daas_client
        from services.copilot_tools.mf_cards import _clean_name, _fund_key, _peer_pref
        # _fund_key collapses plan/option variants (Direct/Regular/Growth/IDCW);
        # also strip share-class words so "X", "X - Retail", "X - Wholesale" collapse.
        _share = _re.compile(r"\b(retail|wholesale|institutional|inst|super)\b")
        def _fam(nm: str) -> str:
            return _re.sub(r"\s+", " ", _share.sub(" ", _fund_key(nm))).strip()
        def _disp(nm: str) -> str:
            d = _clean_name(nm)
            d = _re.sub(r"\s*[-–]\s*(?:retail|wholesale|institutional|super\s+institutional)\b.*$", "", d, flags=_re.I)
            return d.strip()
        raw = await daas_client.search_mf_schemes(term, limit=max(limit * 5, 30))
        best: Dict[str, Dict[str, Any]] = {}
        for r in raw:
            fam = _fam(r.get("scheme_name") or "")
            if not fam:
                continue
            prev = best.get(fam)
            if prev is None or _peer_pref(r) < _peer_pref(prev):
                best[fam] = r
        for r in list(best.values())[:limit]:
            funds.append({
                "name": _disp(r.get("scheme_name") or ""),
                "amc": r.get("amc_name"),
                "category": r.get("scheme_category"),
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("chat_instrument_search funds(%r): %s", term[:40], exc)

    return {"stocks": stocks, "funds": funds}


@router.get("/chat/sessions")
async def list_chat_sessions(request: Request):
    user = await get_current_user(request)
    uid = user["user_id"]
    try:
        from services import redis_client as _redis
        cached = await _redis.cache_get(_sessions_key(uid))
        if isinstance(cached, list):
            return cached
    except Exception:  # noqa: BLE001
        pass
    sessions = await db.chat_sessions.find(
        {"user_id": uid}, {"_id": 0}
    ).sort("updated_at", -1).to_list(50)
    try:
        from services import redis_client as _redis
        await _redis.cache_set(_sessions_key(uid), sessions, ttl_s=_CHAT_CACHE_TTL_S)
    except Exception:  # noqa: BLE001
        pass
    return sessions


@router.post("/chat/sessions")
async def create_chat_session(request: Request):
    user = await get_current_user(request)
    session_doc = {
        "session_id": f"sess_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "title": "New Conversation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.chat_sessions.insert_one(session_doc)
    await _bust_chat_cache(user["user_id"])
    return {k: v for k, v in session_doc.items() if k != "_id"}


# NOTE: /chat/rag and the V3 RAG orchestration path are decommissioned.
# Copilot now runs exclusively on the NIDP LangGraph engine, which has
# canonical intent coverage and emits insight_card envelopes directly.
# The /chat/rag endpoint stays only to return a clean 410 Gone so any
# stale clients fail loudly instead of silently degrading.

class RAGRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: Optional[List[Dict[str, str]]] = None


@router.post("/chat/rag")
async def rag_chat(request: Request, payload: RAGRequest):
    """Retired — Copilot is NIDP-only. Use /chat/send or /chat/stream."""
    raise HTTPException(
        status_code=410,
        detail="The V3 RAG endpoint has been retired. Use /chat/stream or /chat/send (both run on the NIDP engine).",
    )


@router.post("/chat/warmup")
async def warmup_chat_context(request: Request):
    """Fire-and-forget context preload.

    Called by the frontend when the Nivesh Copilot drawer first opens.
    Triggers a fresh compute of the heaviest pieces of the chat context
    (portfolio intelligence including AMC concentration, sector exposure,
    overlap, etc.) and caches the rendered string in Redis. Subsequent
    `/chat/send` and `/chat/stream` calls within the TTL window read
    straight from the cache, so the user sees first-token latency
    measured in hundreds of ms instead of seconds.

    Advisor mode skips intelligence (uses the cross-client book instead),
    so warmup is a no-op for that path.
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    session_user_id = user.get("_session_user_id") or user_id
    advisor_mode = await _is_advisor_caller(session_user_id, user_id)
    if advisor_mode:
        return {"ok": True, "warmed": False, "reason": "advisor_mode"}
    # Warm all five context pieces in parallel. Intelligence is the only
    # one with its own Redis-write (heaviest); the other four are cheap
    # but hitting them now guarantees the first /chat/send doesn't pay
    # any cold-start cost.
    import asyncio as _asyncio
    try:
        intel, plan, goals, health, snapshot = await _asyncio.gather(
            _compute_portfolio_intelligence_context(user_id, use_cache=False),
            _active_plan_context(user_id),
            _compute_goals_context(user_id),
            _compute_health_context(user_id),
            _compute_snapshot_context(user_id),
            return_exceptions=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("chat warmup failed for %s: %s", user_id, e)
        return {"ok": False, "warmed": False, "reason": str(e)[:120]}

    def _len_safe(x):
        return len(x) if isinstance(x, str) else 0

    return {
        "ok": True,
        "warmed": True,
        "ttl_s": _INTEL_CTX_TTL_S,
        "blocks": {
            "intelligence": _len_safe(intel),
            "active_plan":  _len_safe(plan),
            "goals":        _len_safe(goals),
            "health":       _len_safe(health),
            "snapshot":     _len_safe(snapshot),
        },
    }


@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(request: Request, session_id: str):
    user = await get_current_user(request)
    await db.chat_sessions.delete_one({"session_id": session_id, "user_id": user["user_id"]})
    await db.chat_messages.delete_many({"session_id": session_id, "user_id": user["user_id"]})
    await _bust_chat_cache(user["user_id"], session_id)
    return {"message": "Session deleted"}


@router.get("/chat/messages")
async def get_chat_messages(request: Request, session_id: Optional[str] = None):
    user = await get_current_user(request)
    uid = user["user_id"]
    # Cache only the common per-session read (the cross-session case is rare).
    if session_id:
        try:
            from services import redis_client as _redis
            cached = await _redis.cache_get(_messages_key(uid, session_id))
            if isinstance(cached, list):
                return cached
        except Exception:  # noqa: BLE001
            pass
    query = {"user_id": uid}
    if session_id:
        query["session_id"] = session_id
    messages = await db.chat_messages.find(
        query, {"_id": 0}
    ).sort("created_at", 1).to_list(200)
    if session_id:
        try:
            from services import redis_client as _redis
            await _redis.cache_set(_messages_key(uid, session_id), messages, ttl_s=_CHAT_CACHE_TTL_S)
        except Exception:  # noqa: BLE001
            pass
    return messages


@router.post("/chat/send")
async def send_chat(request: Request, msg: ChatMessageInput):
    user = await get_current_user(request)
    user_id = user["user_id"]
    session_user_id = user.get("_session_user_id") or user_id
    advisor_mode = await _is_advisor_caller(session_user_id, user_id)

    session_id = msg.session_id
    if not session_id:
        existing = await db.chat_sessions.find_one(
            {"user_id": user_id}, {"_id": 0}, sort=[("updated_at", -1)]
        )
        if existing:
            session_id = existing["session_id"]
        else:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"
            await db.chat_sessions.insert_one({
                "session_id": session_id,
                "user_id": user_id,
                "title": "New Conversation",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })

    # Save user message
    user_msg_doc = {
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
        "session_id": session_id,
        "user_id": user_id,
        "role": "user",
        "content": msg.message,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.chat_messages.insert_one(user_msg_doc)
    await _bust_chat_cache(user_id, session_id)

    # Auto-title session
    session_msgs_count = await db.chat_messages.count_documents({"session_id": session_id, "role": "user"})
    if session_msgs_count == 1:
        title = msg.message[:50] + ("..." if len(msg.message) > 50 else "")
        await db.chat_sessions.update_one(
            {"session_id": session_id},
            {"$set": {"title": title}}
        )

    await db.chat_sessions.update_one(
        {"session_id": session_id},
        {"$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
    )

    # Gather recent chat history (used by both paths below).
    recent_msgs = await db.chat_messages.find(
        {"user_id": user_id, "session_id": session_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(20)
    recent_msgs.reverse()
    history: List[Dict[str, str]] = []
    if len(recent_msgs) > 1:
        for m in recent_msgs[:-1]:
            history.append({"role": m["role"], "content": m["content"][:500]})

    # insight_card envelope — populated only on the V3 RAG path when the
    # intent maps to a known widget tool. Other paths leave it None so
    # the frontend renders prose as today.
    widget_envelope: Optional[Dict[str, Any]] = None

    # ── Single-portfolio (investor) path ─────────────────────────────
    # Copilot is NIDP-only — V3 RAG retired. If LangGraph deps failed
    # to import at startup, surface a clean error rather than silently
    # degrading.
    if not advisor_mode:
        if not _lg_available:
            ai_response = (
                "Copilot is currently unavailable — the LangGraph engine "
                "failed to load. Please try again shortly."
            )
        else:
            try:
                await _ensure_plan_for_actionable_question(user_id, msg.message)
                graph = _get_copilot_graph()
                lg_config = {"configurable": {"thread_id": session_id}}
                lg_messages = []
                for m in history[-20:]:
                    if m["role"] == "user":
                        lg_messages.append(_HumanMessage(content=m["content"]))
                    elif m["role"] == "assistant":
                        lg_messages.append(_AIMessage(content=m["content"]))
                # Page-aware grounding: when the question comes from the global
                # Copilot dock on a specific dashboard, prefix a light context
                # hint so "explain this" / "why is this high?" resolve to the
                # screen in view. Stored user message (above) stays clean.
                current_message = msg.message
                if msg.page:
                    page_label = msg.page.strip()[:60]
                    if page_label:
                        current_message = (
                            f"[Context: I'm currently viewing the {page_label} "
                            f"dashboard.]\n\n{msg.message}"
                        )
                lg_messages.append(_HumanMessage(content=current_message))
                persona_ctx = await _load_persona_context(db, user_id) if _load_persona_context else {}
                result = await graph.ainvoke(
                    {
                        "messages": lg_messages,
                        "user_id": user_id,
                        "session_id": session_id,
                        **persona_ctx,
                    },
                    config=lg_config,
                )
                resp = result.get("response")
                prose = (getattr(resp, "text", None) or "") if resp else ""
                wt = getattr(resp, "widget_type", None)
                wt_str = wt.value if hasattr(wt, "value") else (str(wt) if wt else None)
                wd = getattr(resp, "widget_data", None)
                if wt_str and wt_str != "none" and wd:
                    agent_val = getattr(resp, "agent", None)
                    agent_id = agent_val.value if hasattr(agent_val, "value") else agent_val
                    freshness = {
                        "state": "cached",
                        "last_updated": datetime.now(timezone.utc).isoformat(),
                        "source": ["NIDP", "portfolio_holdings"],
                    }
                    agent_block = {"id": agent_id or "risk_analyst", "confidence": 85}
                    # Structured V5-native widgets pass through verbatim — no
                    # insight_card transform.
                    if wt_str in ("fund_consolidation", "fund_overlap", "overlap_severity", "risk_overview", "cap_education", "concentration", "allocation_review", "risk_assessment", "instrument_detail", "goal_simulation", "stock_screener"):
                        widget_envelope = {
                            "widget_type": wt_str, "data": wd,
                            "freshness": freshness, "agent": agent_block,
                        }
                    else:
                        try:
                            from services.copilot_tools.insight_card_transformers import (
                                nidp_widget_to_insight_card,
                            )
                            unified = nidp_widget_to_insight_card(wt, wd)
                        except Exception:
                            unified = None
                        if unified is not None:
                            widget_envelope = {
                                "widget_type": "insight_card",
                                "data":        unified.model_dump(),
                                "freshness":   freshness,
                                "agent":       agent_block,
                            }
                        else:
                            widget_envelope = {
                                "widget_type": wt_str,
                                "data":        wd,
                                "freshness":   freshness,
                                "agent":       agent_block,
                            }
                validated = validate_chart_blocks(prose)
                ai_response = validated["clean_text"]
                await log_invalid_chart_specs(
                    db, user_id,
                    model="langgraph_nidp",
                    route="chat/send/nidp",
                    invalid=validated["invalid_specs"],
                )
            except Exception as e:  # noqa: BLE001
                logger.error("NIDP LangGraph send error: %s", e, exc_info=True)
                ai_response = (
                    "I'm having trouble connecting to my AI engine right now. "
                    "Please try again in a moment."
                )
    else:
        # Advisor (cross-client) mode still uses the legacy path \u2014 its
        # context shape (cross-client book) hasn't been ported to RAG yet.
        book = await _advisor_book_block(session_user_id)
        portfolio_context = f"\n\nADVISOR CLIENT BOOK:\n{book}\n"
        try:
            system_override = _ADVISOR_CHAT_SYSTEM.format(
                portfolio_context=portfolio_context
            ) + CHART_PROTOCOL
            ai_response = await ai_engine.chat(
                message=msg.message,
                portfolio_context=portfolio_context,
                history=history,
                session_id=f"wealth_{user_id}_{session_id}",
                system_override=system_override,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"LLM error (advisor): {e}")
            ai_response = "I'm having trouble connecting to my AI engine right now. Please try again in a moment."
        validated = validate_chart_blocks(ai_response)
        ai_response = validated["clean_text"]
        await log_invalid_chart_specs(
            db, user_id,
            model="ai_engine",
            route="chat/send/advisor",
            invalid=validated["invalid_specs"],
        )

    # Save AI response (plus the insight_card envelope if one was built).
    ai_msg_doc = {
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
        "session_id": session_id,
        "user_id": user_id,
        "role": "assistant",
        "content": ai_response,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    if widget_envelope:
        ai_msg_doc["widget"] = widget_envelope
    await db.chat_messages.insert_one(ai_msg_doc)
    await _bust_chat_cache(user_id, session_id)

    return {
        "user_message": {k: v for k, v in user_msg_doc.items() if k != "_id"},
        "ai_message": {k: v for k, v in ai_msg_doc.items() if k != "_id"}
    }


def _widget_envelope(wt: Optional[str], wd: Optional[Dict[str, Any]],
                     agent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Build the SSE widget envelope from a (widget_type, widget_data) pair.
    V5-native widgets pass through verbatim; legacy ones become the unified
    insight_card. Returns None when there's no widget. Shared by the early
    custom-event emit and the final on_chain_end emit."""
    if not (wt and wt != "none" and wd):
        return None
    title_map = {
        "stress_test": (wd.get("scenario_name") or "Portfolio Stress Test"),
        "rebalance_plan": "Rebalance Plan", "tax_harvest": "Tax Harvest Plan",
        "sip_plan": "SIP Plan", "overlap_reveal": "Fund Overlap",
        "sector_rotation": "Sector Rotation", "fund_comparison": "Fund Comparison",
        "portfolio_overview": "Portfolio Overview", "goal_tracker": "Goal Tracker",
        "stock_screener": "Stock Screener",
    }
    title = title_map.get(wt, "Insight")
    freshness = {"state": "cached", "last_updated": datetime.now(timezone.utc).isoformat(),
                 "source": ["NIDP", "portfolio_holdings"]}
    agent = {"id": agent_id or "portfolio_analyst", "confidence": 90}
    unified = None
    # V5-native widgets render with their own component — never insight_card-ify.
    if wt not in ("instrument_detail", "stock_screener"):
        try:
            from services.copilot_tools.insight_card_transformers import nidp_widget_to_insight_card
            unified = nidp_widget_to_insight_card(wt, wd)
        except Exception:  # noqa: BLE001
            unified = None
    if unified is not None:
        return {"widget_type": "insight_card", "data": unified.model_dump(),
                "title": title, "freshness": freshness, "agent": agent}
    return {"widget_type": wt, "data": wd, "title": title, "freshness": freshness, "agent": agent}


@router.post("/chat/stream")
async def stream_chat(request: Request):
    """Stream AI response token-by-token via SSE."""
    user = await get_current_user(request)
    user_id = user["user_id"]
    session_user_id = user.get("_session_user_id") or user_id
    advisor_mode = await _is_advisor_caller(session_user_id, user_id)
    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id")

    if not message:
        raise HTTPException(status_code=400, detail="Message required")

    # Resolve or create session
    if not session_id:
        existing = await db.chat_sessions.find_one(
            {"user_id": user_id}, {"_id": 0}, sort=[("updated_at", -1)]
        )
        if existing:
            session_id = existing["session_id"]
        else:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"
            await db.chat_sessions.insert_one({
                "session_id": session_id,
                "user_id": user_id,
                "title": "New Conversation",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })

    # Save user message
    user_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    user_msg_doc = {
        "message_id": user_msg_id,
        "session_id": session_id,
        "user_id": user_id,
        "role": "user",
        "content": message,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.chat_messages.insert_one(user_msg_doc)
    await _bust_chat_cache(user_id, session_id)

    # Auto-title
    session_msgs_count = await db.chat_messages.count_documents({"session_id": session_id, "role": "user"})
    if session_msgs_count == 1:
        title = message[:50] + ("..." if len(message) > 50 else "")
        await db.chat_sessions.update_one(
            {"session_id": session_id},
            {"$set": {"title": title}}
        )

    await db.chat_sessions.update_one(
        {"session_id": session_id},
        {"$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
    )

    # Portfolio context \u2014 advisor mode swaps to the cross-client book.
    portfolio_context = ""
    risk_context = ""
    if advisor_mode:
        book = await _advisor_book_block(session_user_id)
        portfolio_context = f"\n\nADVISOR CLIENT BOOK:\n{book}\n"
    else:
        holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(100)
        if holdings:
            portfolio_context = _render_portfolio_block(holdings)
        # Risk profile
        user_profile = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0})
        if user_profile and user_profile.get("risk_profile"):
            rp = user_profile["risk_profile"]
            risk_context = f"\n\nUser's Risk Profile: {rp.get('category', 'Unknown')} (Score: {rp.get('score', 'N/A')}/100)"

    # Chat history
    recent_msgs = await db.chat_messages.find(
        {"user_id": user_id, "session_id": session_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(20)
    recent_msgs.reverse()
    history = []
    if len(recent_msgs) > 1:
        for m in recent_msgs[:-1]:
            history.append({"role": m["role"], "content": m["content"][:500]})

    ai_msg_id = f"msg_{uuid.uuid4().hex[:12]}"

    async def event_generator():
        full_response = ""
        follow_ups: list = []
        # insight_card / widget envelope, set by the RAG (or NIDP) branch
        # when an intent matches a known widget tool. Persisted onto
        # ai_msg_doc so the chat-history GET returns it on reload.
        pending_widget: Optional[Dict[str, Any]] = None
        try:
            # Send metadata first
            meta = {"session_id": session_id, "user_msg_id": user_msg_id, "ai_msg_id": ai_msg_id}
            yield f"data: {json.dumps({'type': 'meta', **meta})}\n\n"

            # ── Single-portfolio (investor) path ─────────────────────────────
            if not advisor_mode:
                await _ensure_plan_for_actionable_question(user_id, message)

                # Per-request engine selection: NIDP (LangGraph) when the
                # "copilot_engine_nidp" feature flag is on for this user AND
                # the LangGraph deps imported successfully at startup.
                # Copilot is NIDP-only — V3 RAG retired. If the LangGraph
                # engine isn't available, fail loud rather than silently fall back.
                if not _lg_available:
                    yield f"data: {json.dumps({'type': 'token', 'content': 'Copilot is currently unavailable — the LangGraph engine failed to load. Please try again shortly.'})}\n\n"
                    full_response = "Copilot is currently unavailable."
                else:
                    # ── LangGraph multi-agent path ──────────────────────────
                    graph = _get_copilot_graph()
                    lg_config = {"configurable": {"thread_id": session_id}}

                    # Inject conversation history so context survives server
                    # restarts — MemorySaver is in-process only; MongoDB is
                    # the authoritative store.  We pre-populate the LangGraph
                    # messages list with the last 10 turns (20 messages) from
                    # the DB, then append the new human message.
                    lg_messages = []
                    for m in history[-20:]:
                        if m["role"] == "user":
                            lg_messages.append(_HumanMessage(content=m["content"]))
                        elif m["role"] == "assistant":
                            lg_messages.append(_AIMessage(content=m["content"]))
                    lg_messages.append(_HumanMessage(content=message))

                    persona_ctx = await _load_persona_context(db, user_id) if _load_persona_context else {}
                    lg_input = {
                        "messages": lg_messages,
                        "user_id": user_id,
                        "session_id": session_id,
                        **persona_ctx,
                    }
                    prose = ""
                    streamed_any = False  # True once real LLM tokens are emitted
                    widget_streamed = False  # True once a widget frame is emitted (early or final)
                    widget_envelope: Optional[Dict] = None
                    async for event in graph.astream_events(lg_input, config=lg_config, version="v2"):
                        kind = event.get("event", "")
                        if kind == "on_custom_event" and event.get("name") == "copilot_widget":
                            # A node pushed its widget early (data ready, before
                            # the narrative). Emit it now so the client renders
                            # the widget first and streams the text underneath.
                            cdata = event.get("data") or {}
                            env = _widget_envelope(cdata.get("widget_type"), cdata.get("widget_data"))
                            if env and not widget_streamed:
                                widget_envelope = env
                                widget_streamed = True
                                yield f"data: {json.dumps({'type': 'widget', **env})}\n\n"
                        elif kind == "on_tool_start":
                            tool_name = event.get("name") or event.get("data", {}).get("input", {}).get("name", "tool")
                            yield f"data: {json.dumps({'type': 'thinking', 'tool': tool_name, 'status': 'start'})}\n\n"
                        elif kind == "on_tool_end":
                            tool_name = event.get("name") or "tool"
                            yield f"data: {json.dumps({'type': 'thinking', 'tool': tool_name, 'status': 'end'})}\n\n"
                        elif kind == "on_chat_model_stream":
                            tags = event.get("tags") or []
                            if "intent_internal" in tags:
                                continue
                            chunk = event.get("data", {}).get("chunk")
                            if chunk and hasattr(chunk, "content") and chunk.content:
                                prose += chunk.content
                                streamed_any = True
                                yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"
                        elif kind == "on_chain_end" and event.get("name") == "intent_node":
                            output = event.get("data", {}).get("output", {})
                            intent = output.get("intent") if isinstance(output, dict) else None
                            if intent is not None:
                                agent_val = getattr(intent, "agent", None)
                                agent_id = agent_val.value if hasattr(agent_val, "value") else agent_val
                                route_payload = {
                                    "type": "route",
                                    "agent": agent_id,
                                    "confidence": float(getattr(intent, "confidence", 0.0)),
                                    "symbol": getattr(intent, "symbol", None),
                                    "scheme_code": getattr(intent, "scheme_code", None),
                                }
                                yield f"data: {json.dumps(route_payload)}\n\n"
                        elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                            output = event.get("data", {}).get("output", {})
                            final_resp = output.get("response")
                            if final_resp:
                                if not prose:
                                    prose = getattr(final_resp, "text", "") or str(final_resp)
                                wt = getattr(final_resp, "widget_type", None)
                                wd = getattr(final_resp, "widget_data", None)
                                wt_s = wt.value if hasattr(wt, "value") else (str(wt) if wt else None)
                                if wt_s and wt_s != "none" and wd:
                                    agent_val = getattr(final_resp, "agent", None)
                                    agent_id = agent_val.value if hasattr(agent_val, "value") else agent_val
                                    # Same envelope the node already emitted early
                                    # — kept here for the DB save (and as a fallback
                                    # if the early custom event didn't fire).
                                    env = _widget_envelope(wt_s, wd, agent_id)
                                    if env:
                                        widget_envelope = env
                                fu = getattr(final_resp, "follow_ups", None) or []
                                if fu:
                                    follow_ups = list(fu)[:3]

                    # Only chunk-emit the final prose when NOTHING was streamed
                    # live (e.g. a node returned text without token events).
                    # When real tokens already streamed, re-emitting here would
                    # DOUBLE the answer in the client.
                    if prose and not streamed_any:
                        CHUNK = 24
                        for i in range(0, len(prose), CHUNK):
                            tok = prose[i:i + CHUNK]
                            full_response += tok
                            yield f"data: {json.dumps({'type': 'token', 'content': tok})}\n\n"
                    else:
                        full_response = prose

                    if widget_envelope:
                        pending_widget = widget_envelope  # always persist for the DB save
                        # Only emit here if the node didn't already stream it early.
                        if not widget_streamed:
                            widget_streamed = True
                            yield f"data: {json.dumps({'type': 'widget', **widget_envelope})}\n\n"
            else:
                # Advisor (cross-client) mode — legacy book-block path.
                full_context = portfolio_context
                system_override = _ADVISOR_CHAT_SYSTEM.format(
                    portfolio_context=portfolio_context
                ) + CHART_PROTOCOL
                async for token in ai_engine.chat_stream(
                    message=message,
                    portfolio_context=full_context,
                    history=history,
                    session_id=f"wealth_{user_id}_{session_id}",
                    system_override=system_override,
                ):
                    full_response += token
                    yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            # Validate + sanitise the full response post-stream.
            validated = validate_chart_blocks(full_response)
            full_response = validated["clean_text"]
            await log_invalid_chart_specs(
                db, user_id,
                model="copilot_rag" if not advisor_mode else "ai_engine",
                route=f"chat/stream/{'advisor' if advisor_mode else 'investor'}",
                invalid=validated["invalid_specs"],
            )

            # Save complete AI response (plus widget envelope if one was emitted)
            ai_msg_doc = {
                "message_id": ai_msg_id,
                "session_id": session_id,
                "user_id": user_id,
                "role": "assistant",
                "content": full_response,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            if pending_widget:
                ai_msg_doc["widget"] = pending_widget
            await db.chat_messages.insert_one(ai_msg_doc)
            await _bust_chat_cache(user_id, session_id)

            done_payload = {
                "type": "done",
                "content": full_response,
                "chart_count": validated["valid_count"],
            }
            if follow_ups:
                done_payload["follow_ups"] = follow_ups
            yield f"data: {json.dumps(done_payload)}\n\n"

        except Exception as e:
            logger.error(f"Stream error: {e}")
            error_msg = "I'm having trouble connecting right now. Please try again."
            # Save error response
            ai_msg_doc = {
                "message_id": ai_msg_id,
                "session_id": session_id,
                "user_id": user_id,
                "role": "assistant",
                "content": error_msg,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            await db.chat_messages.insert_one(ai_msg_doc)
            await _bust_chat_cache(user_id, session_id)
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.delete("/chat/clear")
async def clear_chat(request: Request, session_id: Optional[str] = None):
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if session_id:
        query["session_id"] = session_id
    await db.chat_messages.delete_many(query)
    if session_id:
        await db.chat_sessions.delete_one({"session_id": session_id, "user_id": user["user_id"]})
    else:
        await db.chat_sessions.delete_many({"user_id": user["user_id"]})
    await _bust_chat_cache(user["user_id"], session_id)
    return {"message": "Chat cleared"}
