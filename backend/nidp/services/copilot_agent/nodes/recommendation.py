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

from .._llm import ANTI_HALLUCINATION_RULES, COPILOT_LLM_MODEL, get_openai_api_key, temperature_for
from ..persona_framing import frame_for_persona
from ..schemas import AgentName, AgentResponse, CopilotState, ToolResult, WidgetType

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Recommendation Engine for Nivesh AI, an Indian investment platform.

You surface actionable investment ideas grounded in screener data in TOOL_DATA.
Always cite specific data points (RSI, PE ratio, Piotroski score, Sharpe ratio).

Style:
- ≤ 300 words, plain text (no markdown)
- Stocks: table — Symbol | Score/10 | Signal | RSI | PE | Key Reason
- Funds:  table — Fund | Category | 3Y CAGR | Sharpe | TER | Reason
- Max 5 picks; bold the top pick
- Note the user's risk profile if mentioned
- Do NOT append any SEBI disclaimer — the UI renders one canonical disclaimer below the chat input.
""" + ANTI_HALLUCINATION_RULES


import re

# Metric synonyms → widget filter key (used by the stock-screener NL parser).
# Order matters: longer / more-specific phrases first so e.g. "sales growth yoy"
# is not eaten by "sales growth". Keys match the NIDP-backed primitive catalog
# in services/copilot_tools/stock_intelligence.py (_SCREENER_PRIMITIVES).
_SCREEN_METRICS = [
    # Valuation
    ("evEbitda",     r"ev\s*/?\s*ebitda|enterprise value"),
    ("peVsSector",   r"p\s*/?\s*e\s+vs\s+sector|pe\s+vs\s+sector"),
    ("pe",           r"p\s*/?\s*e(?:\s+ratio)?|price[\s-]+to[\s-]+earnings"),
    ("pb",           r"p\s*/?\s*b(?:\s+ratio)?|price[\s-]+to[\s-]+book"),
    ("divYield",     r"dividend\s+yield|div\s+yield|dividend"),
    # Profitability
    ("roce",         r"roce|return on capital(?: employed)?"),
    ("roe",          r"roe|return on equity"),
    ("profitMargin", r"net\s+(?:profit\s+)?margin|profit\s+margin|net\s+margin"),
    ("interestCoverage", r"interest\s+cover(?:age)?"),
    ("earningsConsistency", r"earnings\s+consistency"),
    # Growth
    ("salesGyoy",    r"sales\s+growth\s+yoy|revenue\s+growth\s+yoy|sales\s+yoy|revenue\s+yoy"),
    ("profitGyoy",   r"profit\s+growth\s+yoy|pat\s+growth\s+yoy|profit\s+yoy|pat\s+yoy"),
    ("epsGyoy",      r"eps\s+growth\s+yoy|eps\s+yoy"),
    ("salesG",       r"sales\s+growth|revenue\s+growth|topline\s+growth"),
    ("profitG",      r"profit\s+growth|earnings\s+growth|eps\s+growth|pat\s+growth"),
    ("marginTrend",  r"margin\s+trend"),
    # Financial health
    ("de",           r"debt[\s-]+to[\s-]+equity|debt\s*/\s*equity|d\s*/\s*e"),
    ("debtTrend",    r"debt\s+trend"),
    ("liquidity",    r"liquidity(?:\s+score)?"),
    # Size
    ("mcap",         r"market\s+cap(?:italisation|italization)?|mcap"),
    # Price / technical
    ("return1y",     r"1\s*y(?:ea)?r?\s+return|one\s+year\s+return|return\s+1y|annual\s+return"),
    ("volatility",   r"volatility"),
    ("beta",         r"beta"),
    ("maxDrawdown",  r"max(?:imum)?\s+drawdown|drawdown"),
    ("rsi",          r"rsi(?:\s*14)?"),
    ("momentum",     r"momentum(?:\s+score)?"),
    ("accumulation", r"accumulation(?:\s+score)?"),
    # Ownership / smart money
    ("promoterPledge", r"promoter\s+pledge|pledged?\s+(?:shares|holding)?"),
    ("promoterChange", r"promoter\s+(?:holding\s+)?change"),
    ("promoter",     r"promoter(?:\s+holding)?"),
    ("fiiChange",    r"fii\s+change"),
    ("fii",          r"fii(?:\s+holding)?|foreign\s+(?:institutional|holding)"),
    ("dii",          r"dii(?:\s+holding)?|domestic\s+institutional"),
]
_MIN_WORDS = r"over|above|greater than|more than|at least|min(?:imum)?|higher than|>"
_MAX_WORDS = r"under|below|less than|at most|max(?:imum)?|lower than|<"


def _parse_screen_filters(text: str) -> dict:
    """Parse a natural-language screen ("ROE over 18, P/E under -20, low debt")
    into widget filter keys + server-side kwargs. Forward phrasing only.

    Matched spans are masked as they're consumed so a generic synonym
    ("promoter") can't re-match inside an already-claimed phrase
    ("promoter pledge"). Negative thresholds are supported (e.g. down-20 screens)."""
    tl = text.lower()           # for qualitative + cap-bucket detection
    t = tl                      # working copy that gets masked as metrics are claimed
    num = r"(-?[\d]+(?:\.[\d]+)?)"
    client: dict = {}
    for key, syn in _SCREEN_METRICS:
        for words, suffix in ((_MIN_WORDS, "min"), (_MAX_WORDS, "max")):
            m = re.search(rf"(?:{syn})[^\d-]{{0,12}}?(?:{words})\s*{num}", t)
            if m:
                client[f"{key}_{suffix}"] = float(m.group(1))
                t = t[:m.start()] + " " * (m.end() - m.start()) + t[m.end():]
    # Qualitative shortcuts
    if re.search(r"debt[\s-]*free|no\s+debt|zero\s+debt", tl):
        client["de_max"] = min(client.get("de_max", 0.1), 0.1)
    elif re.search(r"low\s+debt", tl) and "de_max" not in client:
        client["de_max"] = 0.5

    market_cap = None
    if re.search(r"large[\s-]*cap", tl):     market_cap = "LARGE_CAP"
    elif re.search(r"mid[\s-]*cap", tl):     market_cap = "MID_CAP"
    elif re.search(r"small[\s-]*cap", tl):   market_cap = "SMALL_CAP"
    elif re.search(r"micro[\s-]*cap", tl):   market_cap = "MICRO_CAP"

    # Only the params the /v1/stocks/screener endpoint supports go server-side;
    # every other parsed filter rides along as a client_filter (the widget
    # applies it over the returned rows).
    server = {
        "min_roe": client.get("roe_min"),
        "max_de": client.get("de_max"),
        "min_sales_cagr_3y": client.get("salesG_min"),
        "min_profit_cagr_3y": client.get("profitG_min"),
        "max_rsi": client.get("rsi_max"),
        "min_rsi": client.get("rsi_min"),
        "max_pe_vs_sector": client.get("peVsSector_max"),
        "market_cap": market_cap,
    }
    if client.get("roe_min") is not None:
        server["sort_by"] = "roe_pct"
    elif client.get("salesG_min") is not None:
        server["sort_by"] = "revenue_growth_3y_cagr_pct"
    elif client.get("profitG_min") is not None:
        server["sort_by"] = "eps_growth_3y_cagr_pct"
    else:
        server["sort_by"] = "market_cap_cr"

    # Human title from the parsed constraints (covers the full primitive catalog).
    _lbl = {
        "pe": "P/E", "pb": "P/B", "evEbitda": "EV/EBITDA", "peVsSector": "P/E vs sector",
        "divYield": "Div Yield", "roe": "ROE", "roce": "ROCE", "profitMargin": "Net margin",
        "interestCoverage": "Int cover", "earningsConsistency": "Earnings consistency",
        "salesG": "Sales 3Y", "profitG": "Profit 3Y", "salesGyoy": "Sales YoY",
        "profitGyoy": "Profit YoY", "epsGyoy": "EPS YoY", "marginTrend": "Margin trend",
        "de": "D/E", "debtTrend": "Debt trend", "liquidity": "Liquidity", "mcap": "Mkt Cap",
        "return1y": "1Y return", "volatility": "Volatility", "beta": "Beta",
        "maxDrawdown": "Max drawdown", "rsi": "RSI", "momentum": "Momentum",
        "accumulation": "Accumulation", "promoter": "Promoter %", "promoterPledge": "Pledge",
        "fii": "FII %", "dii": "DII %", "fiiChange": "FII Δ", "promoterChange": "Promoter Δ",
    }
    bits = []
    if market_cap:
        bits.append(market_cap.replace("_", "-").title())
    for key, _ in _SCREEN_METRICS:
        if f"{key}_min" in client: bits.append(f"{_lbl[key]} > {client[f'{key}_min']:g}")
        if f"{key}_max" in client: bits.append(f"{_lbl[key]} < {client[f'{key}_max']:g}")
    title = " · ".join(bits) if bits else "Stock screen"

    return {"client_filters": client, "server": server, "title": title}


# "Build me a portfolio" launches the in-chat builder wizard instead of the
# screener. Kept independent of intent._P_BUILDER to avoid a cross-node import;
# the wizard self-drives the risk chat + /portfolio-builder endpoints client-side.
_P_BUILD_PORTFOLIO = re.compile(
    r"\b(?:build|create|design|set\s*up|make|start|begin)\s+(?:me\s+)?(?:a\s+|my\s+|my\s+first\s+|an?\s+)?"
    r"(?:portfolio|investment\s+plan|investing)\b"
    r"|\bportfolio\s+builder\b"
    r"|\bhelp\s+me\s+(?:build|create|start)\s+(?:a\s+)?(?:portfolio|investing|investment\s+plan)\b"
    r"|\binvest\s+from\s+scratch\b",
    re.IGNORECASE,
)

_BUILDER_INTRO = (
    "Let's build your portfolio. Pick a goal and I'll shape a real, ranked mix "
    "to your risk profile — every fund scored on live V3 quality, not samples."
)

# "Build a strategy" / "strategy lab" launches the in-chat Strategy Lab — an
# interactive 5-step equity workbench (universe → screen → backtest → export).
# Kept independent of intent._P_STRATEGY_LAB to avoid a cross-node import.
_P_STRATEGY_LAB = re.compile(
    r"\b(?:build|create|design|make|start|open|launch)\s+(?:me\s+)?(?:a\s+|an?\s+|my\s+)?"
    r"(?:[a-z]+\s+){0,2}strateg(?:y|ies)\b"
    r"|\bstrateg(?:y|ies)\s+(?:lab|builder|workbench)\b"
    r"|\bstrategy\s+lab\b",
    re.IGNORECASE,
)

_STRATEGY_LAB_INTRO = (
    "Opening the Strategy Lab. Pick a universe, choose a factor template, then "
    "screen and backtest it on live, corp-action-adjusted data — right here in chat."
)


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

        # ── Stock screener (real NIDP feature-store universe) ───────────────────
        else:
            intel_mod = importlib.import_module("services.copilot_tools.stock_intelligence")
            parsed = _parse_screen_filters(user_msg)

            fetched = await intel_mod.nidp_stock_screener(
                limit=60, **{k: v for k, v in parsed["server"].items() if v is not None},
            )
            fetch_ok = fetched.get("ok", True)   # False only when the source is unreachable
            raw_rows = fetched.get("rows", [])

            widget_data = intel_mod.build_stock_screener_widget(
                raw_rows,
                title=parsed["title"],
                initial_filters=parsed["client_filters"],
                as_of_date=fetched.get("as_of_date"),
            )
            if fetch_ok and not raw_rows:
                widget_data["note"] = "No stocks matched these filters — loosen a threshold and try again."

            # Ground the LLM narrative in the actual top names (the widget itself
            # is deterministic; the LLM only writes the explanation). Without real
            # symbols + metrics here the anti-hallucination rules force a
            # "data unavailable" answer.
            pick_lines = []
            for r in (widget_data.get("universe") or [])[:5]:
                bits = [str(r.get("ticker") or r.get("name") or "?")]
                metric_bits = []
                if r.get("roe") is not None:  metric_bits.append(f"ROE {float(r['roe']):.0f}%")
                if r.get("pe") is not None:   metric_bits.append(f"PE {float(r['pe']):.1f}")
                if r.get("de") is not None:   metric_bits.append(f"D/E {float(r['de']):.2f}")
                if metric_bits:
                    bits.append("(" + " ".join(metric_bits) + ")")
                pick_lines.append(" ".join(bits))
            picks_str = "; ".join(pick_lines)
            count = widget_data.get("count", 0)

            if not fetch_ok:
                # Source unreachable → no widget; LLM emits the "couldn't retrieve" line.
                summary = f"Stock screen ({parsed['title']}): screener data source unavailable"
            elif count == 0:
                # Valid empty result — a real answer, not a failure. Emit the widget
                # (empty-state note) and let the LLM say "no stocks matched".
                summary = f"Stock screen ({parsed['title']}): 0 stocks matched the filters"
            else:
                summary = (
                    f"Stock screen ({parsed['title']}): {count} matches"
                    + (f" — {picks_str}" if picks_str else "")
                    + (f" [as of {fetched.get('as_of_date')}]" if fetched.get("as_of_date") else "")
                )

            results.append(ToolResult(
                ok=fetch_ok,                       # True even for 0 matches → widget still renders
                tool_name="stock_screener",
                summary=summary,
                data=widget_data,
                rows=widget_data.get("universe", []),
                widget_type=WidgetType.STOCK_SCREENER,
            ))

    except Exception as exc:
        logger.warning("recommendation data fetch failed: %s", exc)
        results.append(ToolResult(
            ok=False, tool_name="recommendation_tools",
            summary="Recommendation data unavailable", error=str(exc),
        ))

    return results


async def recommendation_node(state: CopilotState) -> dict:
    # ── Builder short-circuit ───────────────────────────────────────────────
    # "Build me a portfolio" → emit the interactive builder seed widget (the
    # wizard self-drives the risk chat + /portfolio-builder endpoints). Static
    # intro, no LLM call — deterministic, nothing to hallucinate.
    _builder_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "",
    )
    # Strategy Lab short-circuit — checked before the portfolio builder so
    # "build a strategy" opens the equity workbench (the widget self-drives the
    # /strategy-builder endpoints). Static intro, no LLM call.
    if _P_STRATEGY_LAB.search(_builder_msg or ""):
        from .._stream import emit_widget
        seed = {"universe": {"type": "index", "ref": "NIFTY500"}}
        await emit_widget(WidgetType.STRATEGY_LAB, seed)
        response = AgentResponse(
            agent=AgentName.RECOMMENDATION,
            text=_STRATEGY_LAB_INTRO,
            widget_type=WidgetType.STRATEGY_LAB,
            widget_data=seed,
            tool_results=[],
        )
        return {
            "tool_results": [],
            "response":     response,
            "messages":     [AIMessage(content=_STRATEGY_LAB_INTRO)],
        }

    if _P_BUILD_PORTFOLIO.search(_builder_msg or ""):
        from .._stream import emit_widget
        seed = {"has_risk_profile": False}
        await emit_widget(WidgetType.PORTFOLIO_BUILDER, seed)
        response = AgentResponse(
            agent=AgentName.RECOMMENDATION,
            text=_BUILDER_INTRO,
            widget_type=WidgetType.PORTFOLIO_BUILDER,
            widget_data=seed,
            tool_results=[],
        )
        return {
            "tool_results": [],
            "response":     response,
            "messages":     [AIMessage(content=_BUILDER_INTRO)],
        }

    tool_results = await _fetch_recommendation_data(state)
    tool_context  = "TOOL_DATA:\n" + "\n".join(
        f"  [{tr.tool_name}] {tr.as_llm_context()}" for tr in tool_results
    )

    user_msg = next(
        (m.content for m in reversed(state.messages) if hasattr(m, "type") and m.type == "human"),
        "What should I invest in?",
    )

    llm = ChatOpenAI(
        model=COPILOT_LLM_MODEL,
        temperature=temperature_for(0.2),
        api_key=get_openai_api_key(),
    )
    resp = await llm.ainvoke([
        {"role": "system", "content": frame_for_persona(state.persona) + "\n\n" + _SYSTEM + "\n\n" + tool_context},
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
