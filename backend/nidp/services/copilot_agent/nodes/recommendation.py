"""Recommendation agent node.

Handles: stock screener, fund recommendations, fresh investment ideas.
Tools:  services.copilot_tools.recommendation (composite scorer, screener, MF recommender)
"""
from __future__ import annotations

import logging
import os
from typing import List

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Recommendation Engine for Nivesh AI, an Indian investment platform.

You surface actionable investment ideas grounded in screener data in TOOL_DATA.
Always cite specific data points (RSI, PE ratio, Piotroski score, Sharpe ratio).

Style:
- ≤ 300 words, markdown
- Stocks: table — Symbol | Score/10 | Signal | RSI | PE | Key Reason
- Funds:  table — Fund | Category | 3Y CAGR | Sharpe | TER | Reason
- Max 5 picks; bold the top pick
- Note the user's risk profile if mentioned
- End with: DISCLAIMER: AI-generated screening output. Not SEBI-registered investment advice. Do your own research."""


def _infer_risk_band(user_msg: str) -> str:
    msg = user_msg.lower()
    if any(w in msg for w in ("conservative", "safe", "low risk", "capital protection")):
        return "conservative"
    if any(w in msg for w in ("aggressive", "high risk", "high return", "growth", "small cap", "mid cap")):
        return "aggressive"
    return "moderate"


def _infer_mf_category(user_msg: str) -> str | None:
    msg = user_msg.lower()
    if "large cap" in msg or "largecap" in msg:
        return "Large Cap"
    if "mid cap" in msg or "midcap" in msg:
        return "Mid Cap"
    if "small cap" in msg or "smallcap" in msg:
        return "Small Cap"
    if "flexi cap" in msg or "flexicap" in msg:
        return "Flexi Cap"
    if "debt" in msg or "bond" in msg:
        return "Corporate Bond"
    if "liquid" in msg:
        return "Liquid"
    if "index" in msg:
        return "Index"
    if "balanced" in msg or "hybrid" in msg:
        return "Balanced Advantage"
    return None


async def _fetch_recommendation_data(state: CopilotState) -> List[ToolResult]:
    results: List[ToolResult] = []
    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "",
    )
    msg_lower = user_msg.lower()
    risk_band = _infer_risk_band(user_msg)

    try:
        import importlib
        rec_mod  = importlib.import_module("services.copilot_tools.recommendation")
        port_mod = importlib.import_module("services.copilot_tools.portfolio")

        # ── Portfolio context (sector weights, equity %, for portfolio fit scorer) ──
        portfolio_data: dict = {}
        try:
            ps = await port_mod.get_portfolio_summary(state.user_id)
            if ps.ok:
                portfolio_data = ps.data
                results.append(ToolResult(
                    ok=True, tool_name="get_portfolio_summary",
                    summary=ps.summary, data=ps.data, rows=[],
                ))
        except Exception:
            pass

        # ── MF recommendations ─────────────────────────────────────────────────
        if any(kw in msg_lower for kw in ("fund", "mf", "mutual", "sip", "invest in")):
            category = _infer_mf_category(user_msg)

            # Try NIDP composite-score screener first
            nidp_rows: list = []
            try:
                intel_mod = importlib.import_module("services.copilot_tools.mf_intelligence")
                max_ter    = 0.5 if risk_band == "conservative" else None
                min_comp   = 70.0 if risk_band == "conservative" else 60.0
                nidp_rows  = await intel_mod.get_mf_screener(
                    category=category,
                    sort_by="composite_score",
                    min_composite=min_comp,
                    max_ter=max_ter,
                    limit=8,
                )
            except Exception:
                pass

            if nidp_rows:
                results.append(ToolResult(
                    ok=True,
                    tool_name="mf_composite_screener",
                    summary=(
                        f"NIDP composite screener: {len(nidp_rows)} funds"
                        f"{' in ' + category if category else ''}"
                        f", min_score={min_comp}"
                    ),
                    data={
                        "risk_band":     risk_band,
                        "category_used": category or "all",
                        "count":         len(nidp_rows),
                        "source":        "nidp_composite_scorecard",
                    },
                    rows=nidp_rows,
                    widget_type=WidgetType.FUND_COMPARISON,
                ))
            else:
                # Fallback to legacy recommender
                mf_rec = await rec_mod.recommend_mf(
                    category=category,
                    risk_band=risk_band,
                )
                results.append(ToolResult(
                    ok=mf_rec.ok,
                    tool_name="recommend_mf",
                    summary=mf_rec.summary,
                    data={
                        "risk_band":     mf_rec.risk_band,
                        "category_used": mf_rec.category_used,
                        "count":         len(mf_rec.rows),
                    },
                    rows=mf_rec.rows,
                    widget_type=WidgetType.FUND_COMPARISON,
                    error=mf_rec.error,
                ))

        # ── Stock screener + composite scoring ─────────────────────────────────
        else:
            max_pe    = 30.0 if any(w in msg_lower for w in ("value", "undervalued")) else None
            min_piotr = 6    if any(w in msg_lower for w in ("quality", "strong fundamental")) else None
            valuation = "undervalued" if "undervalued" in msg_lower else None

            screener = await rec_mod.screen_stocks(
                rsi_max=65.0,
                max_pe=max_pe,
                min_piotroski=min_piotr,
                valuation=valuation,
                limit=20,
            )

            if screener.ok and screener.rows:
                symbols = [r["symbol"] for r in screener.rows if r.get("symbol")]
                scored  = await rec_mod.composite_score_batch(
                    symbols,
                    user_risk_profile=risk_band,
                    portfolio_data=portfolio_data,
                    top_n=5,
                )
                rows = [
                    {
                        "symbol":    s.symbol,
                        "score":     s.total_score,
                        "signal":    s.signal,
                        "rsi14":     s.data.get("rsi14"),
                        "pe_ttm":    s.data.get("pe_ttm"),
                        "piotroski": s.data.get("piotroski_score"),
                        "sector":    s.data.get("sector"),
                        "reason":    s.reasons[0] if s.reasons else "",
                    }
                    for s in scored
                ]
            else:
                rows = []

            results.append(ToolResult(
                ok=screener.ok,
                tool_name="stock_screener",
                summary=(
                    f"Screener ({screener.filter_summary}): "
                    f"{screener.total_scanned} scanned, {len(rows)} top picks"
                ),
                data={
                    "filter_summary":  screener.filter_summary,
                    "total_scanned":   screener.total_scanned,
                    "top_picks_count": len(rows),
                    "risk_band":       risk_band,
                },
                rows=rows,
                widget_type=WidgetType.STOCK_SCREENER,
                error=screener.error,
            ))

    except Exception as exc:
        logger.warning("recommendation data fetch failed: %s", exc)
        results.append(ToolResult(
            ok=False, tool_name="recommendation_tools",
            summary="Recommendation data unavailable", error=str(exc),
        ))

    return results


async def recommendation_node(state: CopilotState) -> dict:
    tool_results = await _fetch_recommendation_data(state)
    tool_context  = "TOOL_DATA:\n" + "\n".join(
        f"  [{tr.tool_name}] {tr.as_llm_context()}" for tr in tool_results
    )

    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "What should I invest in?",
    )

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.2,
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
    resp = await llm.ainvoke([
        {"role": "system", "content": _SYSTEM + "\n\n" + tool_context},
        {"role": "user", "content": user_msg},
    ])
    answer_text = resp.content

    widget_tr = next(
        (r for r in tool_results if r.widget_type not in (WidgetType.NONE, None) and r.ok),
        None,
    )
    response = AgentResponse(
        agent=AgentName.RECOMMENDATION,
        text=answer_text,
        widget_type=widget_tr.widget_type if widget_tr else WidgetType.NONE,
        widget_data={"rows": widget_tr.rows, **widget_tr.data} if widget_tr else {},
        tool_results=tool_results,
    )
    return {
        "tool_results": tool_results,
        "response":     response,
        "messages":     [AIMessage(content=answer_text)],
    }
