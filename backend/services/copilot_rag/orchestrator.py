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
import os
from typing import Any, Dict, List, Optional

from . import retrievers as R
from . import chart_specs as C
from .intent_router import Intent, classify_intent
from services.copilot_tools import technical as T
from services.copilot_tools import fundamental as F
from services.copilot_tools import mf as MF
from services.copilot_tools import portfolio as PORT
from services.copilot_tools import company_financials as CF

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
        elif intent.name == "fd_comparison":
            xirr = r.get("portfolio_xirr_pct")
            fd_gross = r.get("fd_gross_pct")
            fd_net = r.get("fd_post_tax_pct")
            diff = r.get("outperformance_gross_pp")
            verdict = r.get("verdict", "")
            label = r.get("label", "FD")
            xirr_part = f" portfolio_xirr={xirr:+.1f}%" if xirr is not None else ""
            fd_part = f" fd_gross={fd_gross:.1f}% fd_post_tax={fd_net:.1f}%" if fd_gross else ""
            diff_part = f" diff={diff:+.1f}pp" if diff is not None else ""
            lines.append(f"  - {label}:{xirr_part}{fd_part}{diff_part} [{verdict}]")
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
        elif intent.name == "tax_timing":
            name = r.get("name", "")
            days = r.get("days_to_ltcg", 0)
            saving = r.get("tax_saving_if_wait_rs", 0)
            gain = r.get("gain_rs", 0)
            is_ltcg = r.get("is_ltcg", False)
            status = "LTCG" if is_ltcg else f"STCG→LTCG in {days}d"
            saving_part = f" tax-saving-if-wait=₹{saving:,.0f}" if saving > 0 else ""
            lines.append(f"  - {name}: {status} gain=₹{gain:+,.0f}{saving_part}")
        elif intent.name == "company_financials":
            if r.get("_type") == "shareholding":
                p = r.get("period", "")
                fii = r.get("fii_pct"); dii = r.get("dii_pct")
                prom = r.get("promoter_pct"); pledge = r.get("promoter_pledged_pct")
                lines.append(
                    f"  - SH {p}: promoter={prom or 0:.1f}% fii={fii or 0:.1f}% "
                    f"dii={dii or 0:.1f}% pledge={pledge or 0:.1f}%"
                )
            else:
                q = r.get("quarter", "")
                rev = r.get("revenue_cr"); pat = r.get("pat_cr")
                rev_yoy = r.get("revenue_yoy_pct"); pat_yoy = r.get("pat_yoy_pct")
                margin = r.get("ebitda_margin_pct")
                rev_part = f" rev=₹{rev:,.0f}cr" if rev else ""
                pat_part = f" PAT=₹{pat:,.0f}cr" if pat else ""
                yoy_part = (
                    f" rev_yoy={rev_yoy:+.1f}%" if rev_yoy is not None else ""
                ) + (
                    f" pat_yoy={pat_yoy:+.1f}%" if pat_yoy is not None else ""
                )
                margin_part = f" ebitda_margin={margin:.1f}%" if margin is not None else ""
                lines.append(f"  - {q}:{rev_part}{pat_part}{yoy_part}{margin_part}")
        elif intent.name == "shareholding":
            p = r.get("period", "")
            fii = r.get("fii_pct"); dii = r.get("dii_pct")
            prom = r.get("promoter_pct"); pledge = r.get("promoter_pledged_pct")
            fii_chg = r.get("fii_change_qoq")
            chg_part = f" fii_chg={fii_chg:+.2f}pp" if fii_chg is not None else ""
            lines.append(
                f"  - {p}: promoter={prom or 0:.1f}% fii={fii or 0:.1f}% "
                f"dii={dii or 0:.1f}% pledge={pledge or 0:.1f}%{chg_part}"
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

    if intent.name == "company_financials":
        symbols = (intent.extras or {}).get("symbols", [])
        if not symbols:
            return R.Retrieval(
                ok=False,
                summary="Please specify a stock symbol (e.g. RELIANCE, TCS) for company financials.",
                rows=[],
                reason="no_symbol",
            )
        sym = symbols[0]
        result = await CF.get_company_overview(sym)
        return R.Retrieval(
            ok=result.ok,
            summary=result.summary,
            rows=result.rows[:8],
            reason=result.error,
            extras=result.data,
        )

    if intent.name == "shareholding":
        symbols = (intent.extras or {}).get("symbols", [])
        if not symbols:
            return R.Retrieval(
                ok=False,
                summary="Please specify a stock symbol for shareholding analysis.",
                rows=[],
                reason="no_symbol",
            )
        result = await CF.get_shareholding_analysis(symbols[0])
        return R.Retrieval(
            ok=result.ok,
            summary=result.summary,
            rows=result.rows,
            reason=result.error,
            extras=result.data,
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
        extras = intent.extras or {}
        scenario = extras.get("scenario", "covid_2020")
        custom_equity_drop = extras.get("custom_equity_drop")
        result = await PORT.run_stress_test(
            user_id,
            scenario=scenario,
            custom_equity_drop=custom_equity_drop,
        )
        return R.Retrieval(
            ok=result.ok,
            summary=result.summary,
            rows=result.rows,
            reason=result.error,
            extras=result.data,
        )

    if intent.name == "fd_comparison":
        result = await PORT.get_fd_comparison(user_id)
        return R.Retrieval(
            ok=result.ok,
            summary=result.summary,
            rows=result.rows,
            reason=result.error,
            extras=result.data,
        )

    if intent.name == "tax_timing":
        result = await PORT.get_tax_timing_advice(user_id)
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
            model=os.environ.get("COPILOT_LLM_MODEL", "gpt-5"),
            messages=messages,
            max_tokens=400,        # tight — answers are short
            temperature=0.2,       # deterministic-ish
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("RAG LLM call failed: %s", e)
        return f"(Copilot temporarily unavailable: {e})"


# ── Insight-card widget envelope wiring ────────────────────────────
#
# Selected intents map to a tool we already build a `WidgetEnvelope`
# for. When matched, we run that tool's data-builder + insight_card
# transformer and attach the envelope to the chat response. The chat
# route persists it on the assistant message so the frontend's
# WidgetRenderer can paint the unified card alongside the prose.
#
# Disabled by default so existing chat-text-only behaviour is unchanged;
# set COPILOT_INSIGHT_CARD_CHAT=true to turn it on globally. Per-intent
# wiring lives in `_intent_to_envelope` — adding a new intent is one
# entry there plus a builder import.

_INSIGHT_CARD_ENABLED = (os.environ.get("COPILOT_INSIGHT_CARD_CHAT", "true").lower() == "true")


async def _intent_to_envelope(
    intent: Intent,
    user_id: str,
    retrieval: Optional["R.Retrieval"] = None,
) -> Optional[Dict[str, Any]]:
    """Map an Intent to a fully-formed insight_card WidgetEnvelope dict
    by calling the matching widget builder + transformer.

    `retrieval` is the result of the orchestrator's own `_retrieve()`
    call — passed in so retrieval-only intents (concentration, goals,
    health, invest_fresh, ranking, mf_analysis) can reuse the rows
    instead of running the query twice. Optional so this function is
    still callable standalone (in which case retrieval-only intents
    return None).

    Returns None when the intent has no widget mapping (chat falls back
    to prose-only as it does today). Any failure logs and returns None
    — chat must never 500 because the optional card couldn't build."""
    try:
        from services.copilot_tools import widget_builders as WB
        from services.copilot_tools import insight_card_transformers as TR
        from models_copilot_widgets import (
            WidgetEnvelope, FreshnessChip, AgentInfo,
        )
        from datetime import datetime, timezone

        def _now_iso() -> str:
            return datetime.now(timezone.utc).isoformat()

        name = intent.name

        if name == "stress_test":
            scenario = intent.extras.get("scenario", "covid_2020")
            custom_drop = intent.extras.get("custom_equity_drop")
            data, scen = await WB.build_stress_test_data(
                user_id=user_id, scenario=scenario, custom_drop_pct=custom_drop,
            )
            card = TR.stress_to_insight_card(data)
            env = WidgetEnvelope(
                kind="insight_card", title=scen["name"],
                freshness=FreshnessChip(state="cached", last_updated=_now_iso(),
                                          source=["portfolio_holdings", "nidp.scenarios"]),
                agent=AgentInfo(id="market_strategist", label="Market Strategist",
                                 version="v1", confidence=82),
                data=card.model_dump(),
                primary_cta={"label": "Run custom scenario", "action": "custom_stress"},
                suggestions=["Compare with 2008 GFC", "How to reduce drawdown?", "Hedge strategies"],
            )
            return env.model_dump()

        if name == "overlap":
            data = await WB.build_overlap_data(user_id=user_id)
            if not data.funds:
                return None
            card = TR.overlap_to_insight_card(data)
            env = WidgetEnvelope(
                kind="insight_card",
                title=f"Overlap · {' vs '.join(data.funds[:2]) if len(data.funds) >= 2 else 'Portfolio funds'}",
                freshness=FreshnessChip(state="cached", last_updated=_now_iso(),
                                          source=["mf_master"]),
                agent=AgentInfo(id="mf_research", label="Mutual Fund Research",
                                 version="v1", confidence=78),
                data=card.model_dump(),
                primary_cta={"label": "Find alternatives with less overlap",
                              "action": "reduce_overlap"},
                suggestions=["Cheaper alternatives", "Compare returns", "Remove a fund"],
            )
            return env.model_dump()

        if name == "tax":
            data = await WB.build_tax_harvest_data(user_id=user_id)
            card = TR.tax_harvest_to_insight_card(data)
            env = WidgetEnvelope(
                kind="insight_card", title=f"Tax Harvest Plan · {data.fy}",
                freshness=FreshnessChip(state="cached", last_updated=_now_iso(),
                                          source=["portfolio_holdings", "capital_gains_summary"]),
                agent=AgentInfo(id="tax_agent", label="Tax Agent",
                                 version="v1", confidence=85),
                data=card.model_dump(),
                primary_cta={"label": "Simulate harvest", "action": "simulate_harvest"},
                suggestions=["Plan switch", "Show STCG separately", "Generate gains statement"],
            )
            return env.model_dump()

        if name in ("plan", "drift"):
            data = await WB.build_rebalance_data(user_id=user_id)
            card = TR.rebalance_to_insight_card(data)
            env = WidgetEnvelope(
                kind="insight_card", title="Rebalance Plan",
                freshness=FreshnessChip(state="cached", last_updated=_now_iso(),
                                          source=["portfolio_holdings"]),
                agent=AgentInfo(id="portfolio_analyzer", label="Portfolio Analyzer",
                                 version="v1", confidence=80),
                data=card.model_dump(),
                primary_cta={"label": "Execute plan", "action": "execute_rebalance"},
                suggestions=["Simulate tax impact", "Show only equity changes", "Compare with my goals"],
            )
            return env.model_dump()

        # ── Retrieval-only intents (no dedicated widget endpoint) ───
        # These intents already have a retriever the orchestrator
        # invokes for the prose answer; we reuse that data to populate
        # the card. The retrieval object is threaded in by `answer()`
        # — if it's missing (e.g. _intent_to_envelope was called
        # standalone), we skip the card rather than re-running the DB
        # query.
        if name in ("concentration", "goals", "health", "invest_fresh",
                     "ranking", "mf_analysis"):
            if retrieval is None or not retrieval.ok:
                return None
            extras = dict(intent.extras or {})
            extras.setdefault("grouping", intent.grouping)
            extras.setdefault("metric", intent.metric)
            card = TR.retrieval_to_insight_card(name, extras, retrieval)
            if card is None:
                return None
            title_map = {
                "concentration":  "Concentration breakdown",
                "goals":          "Goal progress",
                "health":         "Portfolio Health",
                "invest_fresh":   "Deploy fresh capital",
                "ranking":        f"Top by {intent.metric or 'profit'}",
                "mf_analysis":    "Mutual Fund analysis",
            }
            agent_map = {
                "concentration":  ("portfolio_analyzer", "Portfolio Analyzer"),
                "goals":          ("goal_planner", "Goal Planner"),
                "health":         ("portfolio_analyzer", "Portfolio Analyzer"),
                "invest_fresh":   ("portfolio_analyzer", "Portfolio Analyzer"),
                "ranking":        ("portfolio_analyzer", "Portfolio Analyzer"),
                "mf_analysis":    ("mf_research", "Mutual Fund Research"),
            }
            aid, alabel = agent_map[name]
            env = WidgetEnvelope(
                kind="insight_card", title=title_map[name],
                freshness=FreshnessChip(state="cached", last_updated=_now_iso(),
                                          source=["portfolio_holdings"]),
                agent=AgentInfo(id=aid, label=alabel, version="v1", confidence=80),
                data=card.model_dump(),
                suggestions=[],
            )
            return env.model_dump()

        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("insight_card envelope build failed for intent=%s: %s", intent.name, e)
        return None


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

    # Optional insight_card envelope alongside the prose.
    widget_envelope: Optional[Dict[str, Any]] = None
    if _INSIGHT_CARD_ENABLED:
        widget_envelope = await _intent_to_envelope(intent, user_id, retrieval=retrieval)

    return {
        "prose": prose,
        "chart_spec": retrieval.chart_spec,
        "widget": widget_envelope,
        "intent": intent.name,
        "retrieval_ok": retrieval.ok,
        "retrieval_reason": retrieval.reason or None,
        "retrieval_summary": retrieval.summary,
        "rows": retrieval.rows,
        "_payload_chars": len(payload_text),  # for telemetry
    }
