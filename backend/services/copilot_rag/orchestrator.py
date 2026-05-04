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
    if intent.name == "tax":
        # Tax retrieval not yet implemented — surface a typed reason so
        # the LLM tells the user what's coming, doesn't fabricate.
        return R.Retrieval(ok=False, reason="tax_retriever_pending",
                           summary="tax retrieval is not yet wired (LTCG/STCG split coming)")
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
