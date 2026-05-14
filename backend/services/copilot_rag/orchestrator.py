"""Orchestrates intent → retrieval → small LLM context → prose answer.

Public API: `answer(user_id, message, history=None)` returns
    {
        "prose": "<assistant text>",
        "chart_spec": {...} | None,
        "intent": "ranking" | "concentration" | ... ,
        "retrieval_summary": "<one-liner>",
        "rows": [...],   # the structured data backing the answer
    }

The LLM call is intentionally minimal — a 200-token system prompt + the
retrieval payload formatted as bullet points + the user's question. No
holdings dumps, no kitchen-sink intel block.
"""
from __future__ import annotations
import json
import logging
from typing import Any, Dict, List, Optional

from . import retrievers as R
from . import chart_specs as C
from .intent_router import Intent, classify_intent
from services.copilot_tools import technical as T
from services.copilot_tools import fundamental as F
from services.copilot_tools import mf as MF
from services.copilot_tools import portfolio as PORT

logger = logging.getLogger(__name__)


# Tight system prompt — only ~150 tokens. Easier for the model to follow
# than the 5000-char monster we used before.
_SYSTEM = (
    "You are nivesh.ai's investment Copilot for Indian retail investors. "
    "You will receive a STRUCTURED PAYLOAD with the user's actual data "
    "(retrieved server-side from Postgres / Mongo). Rules:\n"
    "1. Use ONLY names, numbers, and percentages from the payload — never "
    "invent fund names, stock names, or amounts.\n"
    "2. Answer in ≤80 words, plain prose, no bullet points unless asked.\n"
    "3. End with one concrete next step ONLY if the payload includes "
    "actionable data; otherwise end with a clean period.\n"
    "4. If the payload says no_data / unavailable, say so plainly — never "
    "fabricate to fill the gap.\n"
    "5. Currency is ₹ INR. Percentages keep their sign.\n"
    "6. Never include disclaimers in the body — the API adds one."
)


def _format_rows_for_llm(retrieval: R.Retrieval, intent: Intent) -> str:
    """Render the retrieval payload as a tight bullet list for the LLM.
    Stays under ~400 chars for a 5-row result so the model's attention
    isn't diluted."""
    if not retrieval.ok:
        return f"NO_DATA reason={retrieval.reason}: {retrieval.summary}"

    header = f"INTENT={intent.name} · {retrieval.summary}"
    lines: List[str] = [header]
    for r in retrieval.rows[:8]:  # cap at 8 even if retriever returned more
        if intent.name == "ranking":
            lines.append(
                f"  {r['rank']}. {r['name']} [{r.get('asset_type')}] · "
                f"₹{r['current_value_rs']:,.0f} · "
                f"profit ₹{r['profit_rs']:+,.0f} · return {r['return_pct']:+.1f}%"
            )
        elif intent.name == "concentration":
            lines.append(
                f"  - {r['label']}: {r['value']:.1f}% (₹{r['amount_rs']:,.0f})"
            )
        elif intent.name == "overlap":
            ts = ", ".join(r.get("top_shared", [])[:3])
            extra = f" [shared: {ts}]" if ts else ""
            lines.append(
                f"  {r['rank']}. {r['fund_a']} ↔ {r['fund_b']}: "
                f"{r['overlap_pct']:.0f}% overlap ({r['shared_count']} stocks){extra}"
            )
        elif intent.name == "goals":
            lines.append(
                f"  - {r['name']} ({r['priority']}): target ₹{r['target_rs']:,.0f} "
                f"in {r['horizon_years']:.0f}y · on-track {r['on_track_pct']:.0f}%"
            )
        elif intent.name == "health":
            lines.append(f"  - {r['component']}: {r['score']:.0f}/100")
        elif intent.name == "drift":
            note = f" — {r.get('note')}" if r.get("note") else ""
            lines.append(
                f"  - {r['asset']}: cur {r['current_pct']:.1f}% / tgt {r['target_pct']:.1f}% "
                f"= {r['deviation_pp']:+.1f}pp ({r['direction']}, {r['trigger']}){note}"
            )
        elif intent.name == "invest_fresh":
            amt = r.get("suggested_amount_rs")
            amt_part = f" → ₹{amt:,.0f}" if amt else ""
            lines.append(
                f"  - {r['bucket']}: cur {r['current_pct']:.1f}% / tgt {r['target_pct']:.1f}% "
                f"({r['deviation_pp']:+.1f}pp) — share {r['share_of_fresh_pct']:.0f}%{amt_part} "
                f"· suggest: {r['fund_class']}"
            )
        elif intent.name == "mf_analysis":
            r1y = r.get("return_1y")
            r3y = r.get("return_3y")
            sh = r.get("sharpe_1y")
            mdd = r.get("max_drawdown_1y")
            ter = r.get("ter")
            rank = r.get("composite_rank")
            name = r.get("scheme_name") or r["scheme_code"]
            r1y_str = f" ret_1y={r1y:+.1f}%" if r1y is not None else ""
            r3y_str = f" ret_3y={r3y:+.1f}%" if r3y is not None else ""
            sh_str = f" sharpe={sh:.2f}" if sh is not None else ""
            mdd_str = f" maxdd={mdd:.1f}%" if mdd is not None else ""
            ter_str = f" TER={ter:.2f}%" if ter is not None else ""
            rank_str = f" rank=#{rank}" if rank is not None else ""
            lines.append(
                f"  - {name}:{r1y_str}{r3y_str}{sh_str}{mdd_str}{ter_str}{rank_str}"
            )
        elif intent.name == "fundamental_analysis":
            pe = r.get("pe_ttm")
            roe = r.get("roe_pct")
            de = r.get("debt_to_equity")
            ps = r.get("piotroski_score")
            az = r.get("altman_z_score")
            val = r.get("valuation_signal") or "unknown"
            rev_g = r.get("revenue_growth_yoy_pct")
            pat_g = r.get("pat_growth_yoy_pct")
            pe_part = f" PE={pe:.1f}x" if pe is not None else " PE=N/A"
            roe_part = f" ROE={roe:.1f}%" if roe is not None else ""
            de_part = f" D/E={de:.2f}" if de is not None else ""
            ps_part = f" Piotroski={ps}/9" if ps is not None else ""
            az_part = f" AltmanZ={az:.2f}" if az is not None else ""
            g_part = f" rev_g={rev_g:+.1f}% pat_g={pat_g:+.1f}%" if rev_g is not None and pat_g is not None else ""
            lines.append(
                f"  - {r['symbol']}:{pe_part}{roe_part}{de_part}{g_part}{ps_part}{az_part} "
                f"valuation={val} — {r.get('summary', '')}"
            )
        elif intent.name == "technical_analysis":
            sig_str = "; ".join((r.get("signals") or [])[:3])
            rsi = r.get("rsi14")
            macd_val = r.get("macd")
            rsi_part = f" RSI={rsi:.0f}" if rsi is not None else ""
            macd_part = f" MACD={macd_val:.2f}" if macd_val is not None else ""
            ret = r.get("return_20d_pct")
            ret_part = f" ret20d={ret:+.1f}%" if ret is not None else ""
            lines.append(
                f"  - {r['symbol']}:{rsi_part}{macd_part}{ret_part} — {r.get('summary', '')} [{sig_str}]"
            )
        elif intent.name == "plan":
            rc = ",".join((r.get("reason_codes") or [])[:3])
            rt = (r.get("reason_text") or "").strip()
            tax = r.get("tax_impact_rs")
            tax_part = f" · tax ₹{tax:+,.0f}" if tax not in (None, 0) else ""
            reason_part = f" — {rt[:160]}" if rt else ""
            lines.append(
                f"  - {r['action_type']} {r['asset_name']} "
                f"₹{r['amount_rs']:,.0f} [{rc}]{tax_part}{reason_part}"
            )
        elif intent.name == "portfolio_perf":
            xirr = r.get("xirr_pct")
            ret = r.get("return_pct")
            xirr_part = f" XIRR={xirr:+.1f}%" if xirr is not None else ""
            ret_part = f" abs_ret={ret:+.1f}%" if ret is not None else ""
            inv = r.get("invested_rs")
            cur = r.get("current_rs")
            inv_part = f" invested=₹{inv:,.0f}" if inv is not None else ""
            cur_part = f" current=₹{cur:,.0f}" if cur is not None else ""
            lines.append(
                f"  - {r.get('name', 'Portfolio')}:{xirr_part}{ret_part}{inv_part}{cur_part}"
            )
        elif intent.name == "stress_test":
            drop = r.get("drop_pct")
            loss = r.get("loss_rs")
            curr = r.get("current_rs")
            drop_part = f" drop={drop:+.0f}%" if drop is not None else ""
            loss_part = f" loss=₹{loss:,.0f}" if loss is not None else ""
            curr_part = f" now=₹{curr:,.0f}" if curr is not None else ""
            lines.append(f"  - {r.get('name', '')}:{drop_part}{loss_part}{curr_part}")
        elif intent.name == "tax":
            gain = r.get("capital_gain", r.get("gain_rs", 0))
            tax  = r.get("tax_if_sold", 0)
            gt   = r.get("gain_type", "")
            days = r.get("holding_days", 0)
            cat  = r.get("asset_category", r.get("asset_type", ""))
            grandf = " [grandfathered]" if r.get("is_grandfathered") else ""
            exempt = " [EXEMPT]" if r.get("is_exempt") else ""
            harvest = r.get("tax_saved_if_harvested", 0)
            harvest_part = f" harvest-saving=₹{harvest:,.0f}" if harvest > 0 else ""
            lines.append(
                f"  - {r.get('name', '')} [{gt}/{cat}] "
                f"gain=₹{gain:+,.0f} tax-if-sold=₹{tax:,.0f} "
                f"held={days}d{grandf}{exempt}{harvest_part}"
            )
        elif intent.name == "rebalance":
            amt = r.get("amount_rs")
            amt_part = f" ₹{amt:,.0f}" if amt else ""
            lines.append(
                f"  - {r.get('action', '')} {r.get('asset', '')}{amt_part} "
                f"({r.get('current_pct', 0):.0f}%→{r.get('target_pct', 0):.0f}%): "
                f"{r.get('reason', '')}"
            )
        else:
            lines.append(f"  - {json.dumps(r, default=str)[:200]}")

    # extras give the model context for one-step framing (totals,
    # thresholds, grades) without dumping the entire structure.
    if retrieval.extras:
        useful = {k: v for k, v in retrieval.extras.items()
                  if not isinstance(v, (list, dict))}
        if useful:
            lines.append(
                "  meta: "
                + ", ".join(f"{k}={v}" for k, v in list(useful.items())[:6])
            )
    return "\n".join(lines)


async def _retrieve(intent: Intent, user_id: str) -> R.Retrieval:
    """Dispatch to the right retriever based on intent."""
    if intent.name == "ranking":
        # MF-only when the user asks "top funds"; equity-only for "top stocks";
        # otherwise both. Crude but matches user intent in practice.
        msg_l = (intent.raw or "").lower()
        if "fund" in msg_l and "stock" not in msg_l:
            atype = "mutual_fund"
        elif "stock" in msg_l or "equity" in msg_l or "compan" in msg_l:
            atype = "equity"
        else:
            atype = None
        return await R.top_n_by_metric(user_id, intent.metric or "profit",
                                       n=intent.n, asset_type=atype)
    if intent.name == "concentration":
        if intent.grouping == "amc":
            return await R.amc_concentration(user_id)
        if intent.grouping == "sector":
            return await R.sector_concentration(user_id)
        if intent.grouping == "category":
            return await R.category_mix(user_id)
        if intent.grouping == "asset_class":
            return await R.asset_class_breakdown(user_id)
        if intent.grouping == "company":
            return await R.company_concentration(user_id)
        return await R.amc_concentration(user_id)  # default to AMC
    if intent.name == "overlap":
        return await R.top_overlap_pairs(user_id)
    if intent.name == "drift":
        return await R.allocation_drift(user_id)
    if intent.name == "invest_fresh":
        return await R.invest_fresh_money(
            user_id,
            amount_rs=(intent.extras or {}).get("amount_rs"),
        )
    if intent.name == "rebalance":
        return await R.rebalance_suggestions(user_id)
    if intent.name == "goals":
        return await R.goals_status(user_id)
    if intent.name == "health":
        return await R.health_scorecard(user_id)
    if intent.name == "plan":
        plan = await R.active_plan_actions(user_id)
        # Fall back to fresh decision-engine suggestions when there's
        # no saved plan — so a user asking "fix my portfolio" gets
        # something concrete even before they hit "Generate Plan".
        if not plan.ok and plan.reason in ("no_active_plan", "all_actions_done"):
            fresh = await R.rebalance_suggestions(user_id)
            if fresh.ok:
                # Annotate the summary so the LLM knows these are
                # newly synthesised, not from a saved plan.
                fresh.summary = "no saved plan — fresh suggestions: " + fresh.summary
                return fresh
        return plan
    if intent.name == "mf_analysis":
        # MF queries: if scheme codes detected use them; otherwise route to
        # the category leaderboard based on keywords in the message.
        msg_l = (intent.raw or "").lower()
        symbols = (intent.extras or {}).get("symbols", [])

        # Detect category from message
        cat = None
        if "large cap" in msg_l or "largecap" in msg_l:
            cat = "Large Cap"
        elif "mid cap" in msg_l or "midcap" in msg_l:
            cat = "Mid Cap"
        elif "small cap" in msg_l or "smallcap" in msg_l:
            cat = "Small Cap"
        elif "flexi" in msg_l or "multi cap" in msg_l:
            cat = "Flexi Cap"
        elif "debt" in msg_l or "bond" in msg_l:
            cat = "Debt"
        elif "hybrid" in msg_l or "balanced" in msg_l:
            cat = "Hybrid"
        elif "index" in msg_l or "etf" in msg_l:
            cat = "Index"

        # Detect preferred metric
        metric = "composite_rank"
        if "sharpe" in msg_l:
            metric = "sharpe_1y"
        elif "return" in msg_l or "performance" in msg_l:
            metric = "return_1y"
        elif "3 year" in msg_l or "3y" in msg_l or "three year" in msg_l:
            metric = "return_3y"

        if cat:
            top_funds = await MF.get_top_funds(cat, metric=metric, limit=5)
            rows = [
                {
                    "scheme_code": r.scheme_code,
                    "scheme_name": r.data.get("scheme_name"),
                    "category": r.data.get("category"),
                    "return_1y": r.data.get("return_1y"),
                    "return_3y": r.data.get("return_3y"),
                    "sharpe_1y": r.data.get("sharpe_1y"),
                    "max_drawdown_1y": r.data.get("max_drawdown_1y"),
                    "composite_rank": r.data.get("composite_rank"),
                    "ter": r.data.get("ter"),
                    "summary": r.summary,
                    "signals": r.signals,
                }
                for r in top_funds if r.ok
            ]
            ok_count = len(rows)
            summary = f"Top {cat} funds by {metric} — {ok_count} results"
        else:
            rows = []
            summary = "MF query — no category identified; please specify (large cap, debt, hybrid, etc.)"

        return R.Retrieval(
            ok=bool(rows),
            summary=summary,
            rows=rows,
            reason="no_category" if not rows else None,
        )

    if intent.name == "fundamental_analysis":
        symbols = (intent.extras or {}).get("symbols", [])
        if symbols:
            results = await F.get_fundamental_comparison(symbols[:3])
            rows = [
                {
                    "symbol": r.symbol,
                    "ok": r.ok,
                    "summary": r.summary,
                    "signals": r.signals,
                    "pe_ttm": r.data.get("pe_ttm"),
                    "pb": r.data.get("pb"),
                    "roe_pct": r.data.get("roe_pct"),
                    "debt_to_equity": r.data.get("debt_to_equity"),
                    "revenue_growth_yoy_pct": r.data.get("revenue_growth_yoy_pct"),
                    "pat_growth_yoy_pct": r.data.get("pat_growth_yoy_pct"),
                    "piotroski_score": r.data.get("piotroski_score"),
                    "altman_z_score": r.data.get("altman_z_score"),
                    "valuation_signal": r.data.get("valuation_signal"),
                    "sector": r.data.get("sector"),
                    "sector_median_pe": r.data.get("sector_median_pe"),
                    "promoter_pct": r.data.get("promoter_pct"),
                    "fii_pct_change_qoq": r.data.get("fii_pct_change_qoq"),
                }
                for r in results
            ]
            ok_count = sum(1 for r in results if r.ok)
            summary = f"Fundamental analysis for {', '.join(symbols[:3])} — {ok_count}/{len(results)} with data"
        else:
            rows = []
            summary = "fundamental query but no symbol identified — please specify a stock name"
        return R.Retrieval(
            ok=bool(rows and any(r["ok"] for r in rows)),
            summary=summary,
            rows=rows,
            reason="no_symbol" if not rows else None,
        )

    if intent.name == "technical_analysis":
        symbols = (intent.extras or {}).get("symbols", [])
        if symbols:
            results = await T.get_technical_comparison(symbols[:3])  # cap at 3 symbols
            rows = [
                {
                    "symbol": r.symbol,
                    "ok": r.ok,
                    "summary": r.summary,
                    "signals": r.signals,
                    "rsi14": r.data.get("rsi14"),
                    "macd": r.data.get("macd"),
                    "close": r.data.get("close"),
                    "sma20": r.data.get("sma20"),
                    "sma50": r.data.get("sma50"),
                    "return_20d_pct": r.data.get("return_20d_pct"),
                    "vol_z20": r.data.get("vol_z20"),
                }
                for r in results
            ]
            ok_count = sum(1 for r in results if r.ok)
            summary = f"Technical analysis for {', '.join(symbols[:3])} — {ok_count}/{len(results)} with data"
        else:
            # No symbol extracted — ask user to specify
            rows = []
            summary = "technical query but no symbol identified"
        return R.Retrieval(
            ok=bool(rows and any(r["ok"] for r in rows)),
            summary=summary,
            rows=rows,
            reason="no_symbol" if not rows else None,
        )
    if intent.name == "tax":
        # Use full report for complete picture; harvest candidates for harvest-specific queries
        tax_kws = ("harvest", "loss", "sell for tax", "save tax")
        is_harvest_query = any(kw in (intent.raw or "").lower() for kw in tax_kws)
        if is_harvest_query:
            result = await PORT.get_tax_harvest_candidates(user_id)
        else:
            result = await PORT.get_full_tax_report(user_id)
        return R.Retrieval(
            ok=result.ok,
            summary=result.summary,
            rows=result.rows,
            reason=result.error,
            extras=result.data,
        )

    if intent.name == "portfolio_perf":
        result = await PORT.get_portfolio_xirr(user_id)
        return R.Retrieval(
            ok=result.ok,
            summary=result.summary,
            rows=result.rows,
            reason=result.error,
            extras=result.data,
        )

    if intent.name == "stress_test":
        scenario = (intent.extras or {}).get("scenario", "covid_2020")
        result = await PORT.run_stress_test(user_id, scenario=scenario)
        return R.Retrieval(
            ok=result.ok,
            summary=result.summary,
            rows=result.rows,
            reason=result.error,
            extras=result.data,
        )

    if intent.name == "rebalance":
        result = await PORT.get_rebalance_plan(user_id)
        return R.Retrieval(
            ok=result.ok,
            summary=result.summary,
            rows=result.rows,
            reason=result.error,
            extras=result.data,
        )

    # generic / fallback
    return await R.portfolio_summary(user_id)


def _attach_chart(retrieval: R.Retrieval, intent: Intent) -> None:
    """Mutates retrieval.chart_spec when a chart makes sense for the intent
    and the data supports it (≥2 rows)."""
    if not retrieval.ok or len(retrieval.rows) < 2:
        return
    if intent.name == "concentration":
        retrieval.chart_spec = C.for_concentration(
            retrieval.rows, intent.grouping or "amc",
            highlight_threshold_pct=float(
                retrieval.extras.get("highlight_threshold_pct") or 15.0
            ),
        )
        return
    if intent.name == "ranking" and intent.chart_requested:
        retrieval.chart_spec = C.for_ranking(retrieval.rows, intent.metric or "profit")
        return
    if intent.name == "health" and intent.chart_requested:
        retrieval.chart_spec = C.for_health(retrieval.rows)
        return
    if intent.name == "goals" and intent.chart_requested:
        retrieval.chart_spec = C.for_goals(retrieval.rows)
        return
    if intent.name == "drift":
        retrieval.chart_spec = C.for_drift(retrieval.rows)


async def _llm_prose(
    payload_text: str,
    user_message: str,
    history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Single small LLM call. We don't reuse ai_engine.chat — that one
    builds a giant context-stuffed prompt; here we want the OPPOSITE."""
    from deps import ai_engine  # has the OpenAI client + key
    user_prompt = (
        f"STRUCTURED PAYLOAD (server-retrieved, this is the ground truth):\n"
        f"{payload_text}\n\n"
        f"USER QUESTION: {user_message}\n\n"
        "Answer using ONLY the payload above."
    )
    messages = [{"role": "system", "content": _SYSTEM}]
    if history:
        for m in history[-4:]:  # tiny history window — RAG context already self-sufficient
            messages.append({"role": m["role"], "content": (m.get("content") or "")[:300]})
    messages.append({"role": "user", "content": user_prompt})
    try:
        resp = await ai_engine.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=400,        # tight — answers are short
            temperature=0.2,       # deterministic-ish
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("RAG LLM call failed: %s", e)
        return f"(Copilot temporarily unavailable: {e})"


async def answer(
    user_id: str,
    message: str,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Top-level RAG entry point. Returns prose + chart_spec + metadata."""
    intent = classify_intent(message)
    retrieval = await _retrieve(intent, user_id)
    _attach_chart(retrieval, intent)
    payload_text = _format_rows_for_llm(retrieval, intent)

    # Inject live market + portfolio context when NIDP_COPILOT_ENABLED=true (fails open)
    try:
        from services.nidp_context import get_market_context, get_portfolio_context
        import asyncio as _asyncio

        # Look up user email so we can fetch their NIDP portfolio intelligence
        user_email: Optional[str] = None
        try:
            from deps import db as _db
            _udoc = await _db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1})
            user_email = (_udoc or {}).get("email")
        except Exception:
            pass

        market_ctx, portfolio_ctx = await _asyncio.gather(
            get_market_context(),
            get_portfolio_context(user_email or ""),
            return_exceptions=True,
        )
        if isinstance(market_ctx, Exception):
            market_ctx = ""
        if isinstance(portfolio_ctx, Exception):
            portfolio_ctx = ""

        if market_ctx:
            payload_text = payload_text + "\n\n" + market_ctx
        if portfolio_ctx:
            payload_text = payload_text + "\n\n" + portfolio_ctx
    except Exception as _nidp_exc:
        logger.debug("NIDP context injection skipped: %s", _nidp_exc)

    prose = await _llm_prose(payload_text, message, history)
    return {
        "prose": prose,
        "chart_spec": retrieval.chart_spec,
        "intent": intent.name,
        "retrieval_ok": retrieval.ok,
        "retrieval_reason": retrieval.reason or None,
        "retrieval_summary": retrieval.summary,
        "rows": retrieval.rows,
        "_payload_chars": len(payload_text),  # for telemetry
    }
