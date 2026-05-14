"""Goal Copilot — natural-language what-if for Goal-Based Investment Planning.

Converts user questions like "Can I retire 5 years earlier?" into parameters
the goal_engine understands, runs the simulation, and returns a concise
plain-English narrative alongside the structured result.

Flow (2 LLM hops, each ~1s on gpt-4o-mini):
   1. `extract_params`  — the LLM parses the user's natural-language query +
      current goal snapshot into a strict JSON object {horizon_years,
      monthly_sip_rs, allocation_override, target_amount_rs, question_intent}.
   2. `narrate_result`  — the LLM takes the computed engine output and
      produces a short human-readable explanation citing numbers.

Chat history is stored in Postgres `goal_copilot_messages` (PKey goal_id +
turn_idx) so follow-up questions retain context ("what if I increase by 5k
more").
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from services import goal_engine, pg_client

logger = logging.getLogger(__name__)

_MODEL_PROVIDER = "openai"
_MODEL_NAME = "gpt-4o-mini"
_SYSTEM_EXTRACT = """You are an assistant that maps user questions about a financial goal into a strict JSON object.

You receive a user question + the goal context. Output ONLY valid JSON (no prose, no code fences) with these keys:
  horizon_years         (number or null — override horizon if mentioned)
  monthly_sip_rs        (number or null — override monthly SIP)
  target_amount_rs      (number or null — override target)
  allocation_override   (object {equity, debt, hybrid} summing to 100, or null)
  question_intent       (one of: "faster_goal", "bigger_goal", "affordability", "risk_adjust",
                         "sip_bump", "general")

Rules:
  * If the user says "retire 5 years earlier" and current horizon is 20, set horizon_years = 15.
  * If they say "increase SIP by 5k" and current SIP is 25000, set monthly_sip_rs = 30000.
  * Interpret lakh = 1e5, crore = 1e7 in target_amount_rs when user mentions rupee amounts.
  * For risk adjust, map "aggressive" → {equity:80,debt:10,hybrid:10},
    "moderate" → {equity:60,debt:30,hybrid:10}, "conservative" → {equity:30,debt:60,hybrid:10}.
  * If no parameter change is requested, all override fields should be null.
  * NEVER invent numbers; only extract what the user literally said or logically implied.
"""

_SYSTEM_NARRATE = """You explain a financial simulation result in 2-3 short sentences of plain English.

You receive:
  - The user's original question
  - Their current goal baseline (horizon, SIP, on-track %)
  - The simulated scenario (what changed + the engine output)

Write like a financial coach — direct, specific with numbers, no fluff. Format rupees as
"₹X Cr", "₹Y L", or "₹Z" when < 1 lakh. Use the Monte-Carlo probability as the success metric.
End with a single concrete recommendation. Do NOT produce bullet points or headers — one
paragraph only. Do NOT add disclaimers.
"""


async def _llm_call(
    system_message: str,
    session_id: str,
    user_text: str,
    *,
    timeout_s: int = 12,
) -> Optional[str]:
    """Fresh LlmChat per request (stateless — we manage history in PG)."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        logger.warning("EMERGENT_LLM_KEY missing — copilot disabled")
        return None
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(
        api_key=api_key,
        session_id=session_id,
        system_message=system_message,
    ).with_model(_MODEL_PROVIDER, _MODEL_NAME)
    task = asyncio.create_task(chat.send_message(UserMessage(text=user_text)))
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
        return None


def _parse_json_loose(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    s = raw.strip()
    # Strip code fences (``` or ```json) if present
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


# ── Persistence ────────────────────────────────────────────────────────
async def _ensure_schema() -> None:
    pool = await pg_client.get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS goal_copilot_messages (
                id BIGSERIAL PRIMARY KEY,
                goal_id UUID NOT NULL,
                user_id UUID NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                extracted_params JSONB,
                engine_output JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_copilot_goal "
            "ON goal_copilot_messages(goal_id, created_at)"
        )


async def load_history(goal_id: str, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    await _ensure_schema()
    pool = await pg_client.get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content, extracted_params, engine_output, created_at "
            "FROM goal_copilot_messages WHERE goal_id = $1 AND user_id = $2 "
            "ORDER BY created_at ASC LIMIT $3",
            uuid.UUID(goal_id), uuid.UUID(user_id), limit,
        )
    out = []
    for r in rows:
        d = dict(r)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        if isinstance(d.get("extracted_params"), str):
            try:
                d["extracted_params"] = json.loads(d["extracted_params"])
            except json.JSONDecodeError:
                pass
        if isinstance(d.get("engine_output"), str):
            try:
                d["engine_output"] = json.loads(d["engine_output"])
            except json.JSONDecodeError:
                pass
        out.append(d)
    return out


async def _save_message(
    goal_id: str, user_id: str, role: str, content: str,
    extracted_params: Optional[Dict[str, Any]] = None,
    engine_output: Optional[Dict[str, Any]] = None,
) -> None:
    pool = await pg_client.get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO goal_copilot_messages "
            "(goal_id, user_id, role, content, extracted_params, engine_output) "
            "VALUES ($1,$2,$3,$4,$5,$6)",
            uuid.UUID(goal_id), uuid.UUID(user_id), role, content,
            json.dumps(extracted_params) if extracted_params else None,
            json.dumps(engine_output) if engine_output else None,
        )


# ── Public entry-point ─────────────────────────────────────────────────
async def ask(
    *,
    goal: Dict[str, Any],
    user_id: str,
    user_query: str,
    risk_profile: str = "moderate",
) -> Dict[str, Any]:
    """Process a single copilot turn.

    Returns:
      {
        "user_query":     str,
        "interpretation": str,
        "extracted_params": {...},
        "engine_output":  {...}   (goal_engine.evaluate_goal().to_dict())
        "narrative":      str      (LLM explanation)
        "baseline_on_track": float (for delta comparison)
      }
    """
    goal_id = str(goal["goal_id"])
    await _ensure_schema()

    # Build the extraction prompt
    baseline = {
        "goal_name": goal.get("goal_name"),
        "goal_type": goal.get("goal_type"),
        "target_amount_rs": goal.get("target_amount_rs"),
        "horizon_years": goal.get("horizon_years"),
        "current_corpus_rs": goal.get("current_corpus_rs"),
        "monthly_sip_rs": goal.get("monthly_sip_rs"),
        "allocation": goal.get("allocation"),
        "on_track_pct": goal.get("on_track_pct"),
    }

    # Multi-turn: include last 3 exchanges for follow-up context
    history = await load_history(goal_id, user_id, limit=6)
    history_prompt = ""
    for h in history[-6:]:
        history_prompt += f"\n{h['role'].upper()}: {h['content']}"

    extract_prompt = (
        f"GOAL:\n{json.dumps(baseline, indent=2)}\n\n"
        + (f"PREVIOUS TURNS:{history_prompt}\n\n" if history_prompt else "")
        + f"USER QUESTION: {user_query}\n\nReturn JSON only."
    )

    raw_extraction = await _llm_call(_SYSTEM_EXTRACT, f"gbipe-extract-{goal_id}", extract_prompt)
    params = _parse_json_loose(raw_extraction)

    # Convert extracted params → evaluate_goal args (with safe fallbacks)
    horizon = params.get("horizon_years") or baseline["horizon_years"] or 10
    sip = params.get("monthly_sip_rs")
    if sip is None:
        sip = baseline["monthly_sip_rs"] or 0
    target = params.get("target_amount_rs") or baseline["target_amount_rs"] or 0
    allocation = params.get("allocation_override") or baseline["allocation"]

    try:
        ev = goal_engine.evaluate_goal(
            target_today_rs=float(target),
            horizon_years=float(horizon),
            starting_corpus_rs=float(baseline["current_corpus_rs"] or 0),
            monthly_sip_rs=float(sip),
            risk_profile=risk_profile,
            inflation_pct=float(goal.get("inflation_pct") or 6.0),
            allocation_override=allocation,
            n_mc_runs=500,   # lighter for copilot; full runs at /simulate
        )
        engine_output = ev.to_dict()
    except Exception as e:  # noqa: BLE001
        logger.exception("copilot engine eval failed")
        engine_output = {"error": str(e)[:200]}

    # Narration hop
    narrate_prompt = (
        f"USER ASKED: {user_query}\n\n"
        f"BASELINE:\n{json.dumps(baseline, default=str, indent=2)}\n\n"
        f"WHAT CHANGED (extracted overrides): {json.dumps(params, default=str)}\n\n"
        f"ENGINE RESULT:\n{json.dumps(engine_output, default=str, indent=2)}\n\n"
        "Explain in 2-3 sentences, end with one concrete recommendation."
    )
    narrative = await _llm_call(_SYSTEM_NARRATE, f"gbipe-narrate-{goal_id}", narrate_prompt)
    if not narrative:
        narrative = _fallback_narrative(baseline, params, engine_output)

    # Persist turn
    await _save_message(goal_id, user_id, "user", user_query)
    await _save_message(
        goal_id, user_id, "assistant", narrative,
        extracted_params=params, engine_output=engine_output,
    )

    return {
        "user_query": user_query,
        "interpretation": params.get("question_intent") or "general",
        "extracted_params": params,
        "engine_output": engine_output,
        "narrative": narrative,
        "baseline_on_track": baseline.get("on_track_pct"),
    }


def _fallback_narrative(baseline: Dict[str, Any], params: Dict[str, Any], eo: Dict[str, Any]) -> str:
    """Deterministic text when LLM is unreachable / disabled."""
    if eo.get("error"):
        return f"Could not simulate: {eo['error']}."
    mc = (eo.get("monte_carlo") or {})
    ot = eo.get("on_track_pct")
    prob = mc.get("prob_success_pct")
    req = eo.get("required_sip_rs")
    bits = [f"With those changes, you'd be on-track for {ot:.0f}%"]
    if prob is not None:
        bits.append(f"(Monte-Carlo success probability {prob:.0f}%)")
    if req and baseline.get("monthly_sip_rs") and req > baseline["monthly_sip_rs"]:
        gap = req - baseline["monthly_sip_rs"]
        bits.append(f"to fully meet this target you'd need to add ₹{int(gap):,}/month")
    return ". ".join(bits) + "."


async def clear_history(goal_id: str, user_id: str) -> int:
    pool = await pg_client.get_pool()
    if pool is None:
        return 0
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM goal_copilot_messages WHERE goal_id = $1 AND user_id = $2",
            uuid.UUID(goal_id), uuid.UUID(user_id),
        )
    # asyncpg returns "DELETE N"
    try:
        return int(res.split()[-1])
    except (ValueError, IndexError):
        return 0
