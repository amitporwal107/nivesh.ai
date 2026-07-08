"""MFD Copilot — CIO-assistant layer.

Provides three endpoints in Pass 1:
  - POST /api/copilot/explain         → portfolio explanation in CIO tone
  - POST /api/copilot/client-message  → ready-to-send WhatsApp / Email draft
  - POST /api/copilot/ask             → free-form Q&A with context

All endpoints accept a `model` string ("gemini" | "claude" | "gpt") so the
MFD can trade cost vs. quality per-call. Default is `gemini` (cheapest).

Responses cached 24h in `copilot_cache` (keyed by SHA1 of model + prompt +
context snapshot) to avoid re-billing identical calls.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deps import db, get_current_user
from services.copilot_charts import (
    CHART_PROTOCOL, validate_chart_blocks, log_invalid_chart_specs,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/copilot", tags=["copilot"])

def _get_openai_key() -> str:
    """Resolve OPENAI_API_KEY at call time. Order:
       1. Google Secret Manager (prod source of truth — rotates without restart)
       2. DB-backed admin override (helpers.secrets)
       3. Env var (local dev)
    """
    try:
        from helpers import gsm as _gsm
        key = _gsm.get("OPENAI_API_KEY")
        if key:
            return key
    except Exception:  # noqa: BLE001
        pass
    try:
        from helpers import secrets as _secrets
        key = _secrets.get("OPENAI_API_KEY")
        if key:
            return key
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("OPENAI_API_KEY", "")


MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "gpt-4o": {
        "model": "gpt-4o",
        "label": "GPT-4o",
        "tier": "Best · recommended",
        "price_hint": "~₹0.40 / call",
    },
    "gpt-4o-mini": {
        "model": "gpt-4o-mini",
        "label": "GPT-4o Mini",
        "tier": "Cheapest · fast",
        "price_hint": "~₹0.04 / call",
    },
    # Legacy aliases so existing callers sending "gemini"/"claude"/"gpt" still work
    "gemini": {"model": "gpt-4o-mini", "label": "GPT-4o Mini", "tier": "Fast", "price_hint": "~₹0.04 / call"},
    "claude": {"model": "gpt-4o",      "label": "GPT-4o",      "tier": "Best", "price_hint": "~₹0.40 / call"},
    "gpt":    {"model": "gpt-4o",      "label": "GPT-4o",      "tier": "Best", "price_hint": "~₹0.40 / call"},
}
DEFAULT_MODEL_KEY = "gpt-4o"


# ── Caching helpers ────────────────────────────────────────────────────
def _cache_key(model: str, prompt_name: str, context: Dict[str, Any],
               user_prompt: str = "") -> str:
    payload = json.dumps(
        {"m": model, "p": prompt_name, "c": context, "u": user_prompt},
        sort_keys=True, default=str,
    )
    return hashlib.sha1(payload.encode()).hexdigest()


async def _cache_get(key: str) -> Optional[str]:
    doc = await db.copilot_cache.find_one({"_id": key}, {"_id": 0, "response": 1, "expires_at": 1})
    if not doc:
        return None
    try:
        if datetime.fromisoformat(doc["expires_at"]) < datetime.now(timezone.utc):
            return None
    except Exception:  # noqa: BLE001
        return None
    return doc.get("response")


async def _cache_put(key: str, response: str, ttl_hours: int = 24) -> None:
    await db.copilot_cache.update_one(
        {"_id": key},
        {"$set": {
            "response": response,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat(),
        }},
        upsert=True,
    )


# ── Prompt builder ─────────────────────────────────────────────────────
def _portfolio_context_block(ctx: Dict[str, Any]) -> str:
    """Formats the client's portfolio data into a terse block the LLM can
    reason about. Keeps it <800 tokens — we don't want latency blowout."""
    lines = []
    if ctx.get("client_name"):
        lines.append(f"CLIENT: {ctx['client_name']}")
    if ctx.get("wealth_tier"):
        lines.append(f"TIER: {ctx['wealth_tier']}")
    if ctx.get("aum_rs"):
        lines.append(f"AUM: ₹{ctx['aum_rs']:,.0f}")
    if ctx.get("invested_rs"):
        lines.append(f"INVESTED: ₹{ctx['invested_rs']:,.0f}")
    if ctx.get("return_pct") is not None:
        lines.append(f"RETURN_SO_FAR: {ctx['return_pct']:+.1f}%")
    if ctx.get("health_score") is not None:
        lines.append(f"HEALTH: {ctx['health_score']:.0f}/100 (grade {ctx.get('grade', '?')})")
    if ctx.get("components"):
        parts = [f"{k}={v:.0f}" for k, v in ctx["components"].items()]
        lines.append("COMPONENTS: " + ", ".join(parts))
    if ctx.get("top_issues"):
        lines.append("TOP ISSUES:")
        for i, iss in enumerate(ctx["top_issues"][:3], 1):
            lines.append(f"  {i}. {iss.get('label')} — {iss.get('detail', '')}"[:180])
    if ctx.get("open_actions"):
        lines.append(f"OPEN_ACTIONS ({len(ctx['open_actions'])} total):")
        for a in ctx["open_actions"][:5]:
            amt = f" ₹{a['amount']:,.0f}" if a.get("amount") else ""
            lines.append(f"  - {a.get('type', '')}{amt} · {a.get('asset_name', '')} — {a.get('reason_text', '')[:120]}")
    if ctx.get("tax"):
        t = ctx["tax"]
        lines.append(f"TAX: unrealized ₹{t.get('total_unrealized_rs', 0):,.0f} "
                     f"(STCG ₹{t.get('stcg_rs', 0):,.0f} / LTCG ₹{t.get('ltcg_rs', 0):,.0f})")
    if ctx.get("goals"):
        lines.append(f"GOALS ({len(ctx['goals'])}):")
        for g in ctx["goals"][:3]:
            lines.append(f"  - {g.get('goal_name')} · target ₹{g.get('target_amount_rs', 0):,.0f} · "
                         f"{g.get('on_track_pct', 0):.0f}% on track")
    return "\n".join(lines)


# ── LLM call ───────────────────────────────────────────────────────────
async def _llm_call(
    model_key: str, system: str, user_prompt: str, session_id: str,
) -> str:
    """Single-shot chat completion via OpenAI SDK."""
    key = _get_openai_key()
    if not key:
        raise HTTPException(500, "OPENAI_API_KEY is not configured")
    meta = MODEL_REGISTRY.get(model_key) or MODEL_REGISTRY[DEFAULT_MODEL_KEY]
    import openai
    client = openai.AsyncOpenAI(api_key=key)
    try:
        completion = await client.chat.completions.create(
            model=meta["model"],
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=600,
        )
        return (completion.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.exception("copilot llm call failed: model=%s", model_key)
        raise HTTPException(502, f"Copilot ({meta['label']}) failed: {exc}") from exc


# ── Context hydrator ───────────────────────────────────────────────────
async def _build_context(user_id: str) -> Dict[str, Any]:
    """Pulls together everything Copilot needs about the current user /
    impersonated client in a single dict. Intentionally cheap reads — all
    data already exists in Mongo."""
    ctx: Dict[str, Any] = {}

    # Client profile (when impersonating, `active_profile_id` points to
    # the profiles doc; name + AUM live there).
    from services import mfd_workspace as _ws
    try:
        # Find which profile this shadow-user maps to.
        prof = await db.profiles.find_one({"shadow_user_id": user_id}, {"_id": 0})
        if prof:
            ctx["client_name"]  = prof.get("name")
            ctx["aum_rs"]       = prof.get("aum_rs")
    except Exception:  # noqa: BLE001
        pass

    # Portfolio health (same service the dashboard uses)
    try:
        from services import portfolio_health as _ph
        hr = await _ph.build_portfolio_health(user_id)
        if hr and hr.health_score is not None:
            ctx["health_score"] = float(hr.health_score)
            ctx["grade"] = hr.grade
            ctx["components"] = {c.name: float(c.score) for c in (hr.components or {}).values()}
            ctx["top_issues"] = [
                {"label": d.label, "detail": d.detail}
                for d in (hr.risk_drivers or [])[:3]
            ]
            ctx["summary"] = hr.summary
    except Exception:  # noqa: BLE001
        logger.debug("copilot: health fetch failed for %s", user_id, exc_info=True)

    # Open action plan
    try:
        plan = await db.action_plans.find_one(
            {"user_id": user_id, "status": {"$ne": "archived"}},
            {"_id": 0, "actions": 1},
            sort=[("created_at", -1)],
        )
        actions = [
            a for a in (plan or {}).get("actions", [])
            if (a.get("status") or "").upper() not in ("COMPLETED", "SKIPPED")
        ]
        ctx["open_actions"] = actions[:10]
    except Exception:  # noqa: BLE001
        ctx["open_actions"] = []

    # Portfolio value + invested
    try:
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$group": {
                "_id": None,
                "current":  {"$sum": {"$multiply": [{"$ifNull": ["$quantity", 0]}, {"$ifNull": ["$current_price", 0]}]}},
                "invested": {"$sum": {"$multiply": [{"$ifNull": ["$quantity", 0]}, {"$ifNull": ["$buy_price", 0]}]}},
            }},
        ]
        async for row in db.holdings.aggregate(pipeline):
            ctx["aum_rs"] = float(row.get("current") or ctx.get("aum_rs") or 0)
            ctx["invested_rs"] = float(row.get("invested") or 0)
            if ctx["invested_rs"] > 0:
                ctx["return_pct"] = (ctx["aum_rs"] - ctx["invested_rs"]) / ctx["invested_rs"] * 100
    except Exception:  # noqa: BLE001
        pass

    return ctx


async def _is_advisor_caller(session_user_id: str, active_profile_id: Optional[str]) -> bool:
    """True if the caller owns an ADVISORY workspace AND is viewing the
    workspace root — i.e. is NOT currently impersonating any client profile.
    Mirrors the detection in /copilot/suggested-prompts so prompt suggestions
    and ask-context stay in sync.

    Impersonation is detected via the session's ``active_profile_id``, NOT by
    comparing user-ids: an advisor who is *their own client* opens a SELF
    profile whose ``shadow_user_id`` equals their own ``user_id``, so an
    id-comparison would wrongly read as "not impersonating" and keep the
    cross-client copilot active. ``active_profile_id`` flips SELF and CLIENT
    profiles alike to the personal/client copilot."""
    if active_profile_id:
        return False
    try:
        ws = await db.workspaces.find_one(
            {"owner_user_id": session_user_id}, {"_id": 0, "type": 1},
        )
    except Exception:  # noqa: BLE001
        return False
    return bool(ws and (ws.get("type") or "").upper() == "ADVISORY")


# ── Mode-agnostic research tools ─────────────────────────────────────────
# The Chat surface exposes four launchers — Research a stock, Research a
# fund, Build a portfolio, Stocks Screener — that ask about an instrument
# or run a tool and DO NOT depend on the advisor's client book. They must
# return identical results whether the caller is in advisor (cross-client)
# mode or client mode. So in advisor mode these bypass the book-summary
# path and run the normal investor (LangGraph) engine.
_RESEARCH_INTENT_RE = re.compile(
    r"(?:"
    r"\btell\s+me\s+about\b|"                                  # "Research a stock/fund" chip prefill
    r"\bresearch\s+(?:the\s+)?(?:stock|fund|mutual\s+fund|company|scheme)\b|"
    r"\banalys[ez]e?\s+(?:the\s+)?(?:stock|fund|mutual\s+fund|scheme)\b|"
    r"\bbuild\s+(?:me\s+)?(?:a\s+|my\s+)?portfolio\b|"         # "Build a portfolio" chip
    r"\bscreen\s+(?:stocks?|for|where)\b|\bstocks?\s+screener\b|"  # "Stocks Screener" chip
    # Strategy Lab — mode-agnostic equity workbench, same as the screener/builder.
    r"\bbuild\s+(?:me\s+)?(?:a\s+|an?\s+|my\s+)?(?:[a-z]+\s+){0,2}strateg(?:y|ies)\b|"
    r"\bstrateg(?:y|ies)\s+(?:lab|builder|workbench)\b|\bstrategy\s+lab\b|"
    # Tier-A conversational tools — render the investor widget even in advisor mode
    # (they are mode-agnostic tools, not cross-client book questions).
    r"\bcapital\s+gains?\b|\bcg\s+statement\b|\breali[sz]ed?\s+(?:capital\s+)?gains?\b|\b(?:stcg|ltcg)\b|"
    r"\bwhich\s+funds?\b|\bfund\s+basket\b|\bfunds?\s+for\s+(?:this|my|the)\s+goal\b"
    r")",
    re.IGNORECASE,
)

# Cross-client book questions always stay on the advisor book path, even
# when they contain a research-ish verb (e.g. "tell me about my top
# client"). This guard takes priority over the research gate so the
# advisor book experience (and its regression test) is never hijacked.
_ADVISOR_BOOK_INTENT_RE = re.compile(
    r"\b(clients?|client\s+book|my\s+book|across\s+(?:my\s+)?clients|"
    r"aum|assets?\s+under\s+management|workspace|advisory|"
    r"which\s+(?:of\s+my\s+)?clients?)\b",
    re.IGNORECASE,
)


def _is_research_tool_intent(message: str) -> bool:
    """True when an advisor-mode message is one of the four mode-agnostic
    research tools (stock/fund research, portfolio builder, stock
    screener) and should therefore run the investor engine so the answer
    matches client mode. Cross-client book questions are excluded."""
    m = message or ""
    if _ADVISOR_BOOK_INTENT_RE.search(m):
        return False
    return bool(_RESEARCH_INTENT_RE.search(m))


async def _advisor_book_block(owner_user_id: str) -> str:
    """Compact advisor-book summary fed to the LLM: one line per client
    with name, AUM, return %, top issue. Sorted by AUM desc; capped at
    100 clients so we never blow the context budget."""
    profs = await db.profiles.find(
        {"workspace_id": {"$exists": True}},
        {"_id": 0, "profile_id": 1, "name": 1, "shadow_user_id": 1,
         "workspace_id": 1, "aum_rs": 1, "type": 1},
    ).to_list(500)
    # Filter to profiles owned by this advisor
    ws_ids = {w["workspace_id"] async for w in db.workspaces.find(
        {"owner_user_id": owner_user_id}, {"_id": 0, "workspace_id": 1},
    )}
    profs = [p for p in profs if p.get("workspace_id") in ws_ids and p.get("type") == "CLIENT"]
    if not profs:
        return "No clients linked to this advisory workspace yet."
    rows: List[Dict[str, Any]] = []
    for p in profs:
        suid = p.get("shadow_user_id")
        if not suid:
            rows.append({"name": p.get("name") or "—", "aum": float(p.get("aum_rs") or 0)})
            continue
        # Aggregate live AUM + invested from holdings
        try:
            agg = db.holdings.aggregate([
                {"$match": {"user_id": suid}},
                {"$group": {
                    "_id": None,
                    "current": {"$sum": {"$multiply": [{"$ifNull": ["$quantity", 0]}, {"$ifNull": ["$current_price", 0]}]}},
                    "invested": {"$sum": {"$multiply": [{"$ifNull": ["$quantity", 0]}, {"$ifNull": ["$buy_price", 0]}]}},
                    "n": {"$sum": 1},
                }},
            ])
            cur, inv, n = 0.0, 0.0, 0
            async for r in agg:
                cur = float(r.get("current") or 0)
                inv = float(r.get("invested") or 0)
                n = int(r.get("n") or 0)
        except Exception:  # noqa: BLE001
            cur, inv, n = float(p.get("aum_rs") or 0), 0.0, 0
        # Pick up cached health + recent action count
        cached = await db.mfd_profile_signal_cache.find_one(
            {"user_id": suid}, {"_id": 0, "portfolio_score": 1, "ai_summary": 1, "recommendations": 1},
        )
        rows.append({
            "name": p.get("name") or "—",
            "aum": cur if cur > 0 else float(p.get("aum_rs") or 0),
            "invested": inv,
            "ret_pct": ((cur - inv) / inv * 100) if inv > 0 else None,
            "holdings": n,
            "score": (cached or {}).get("portfolio_score"),
            "summary": ((cached or {}).get("ai_summary") or "")[:120],
            "actions": len((cached or {}).get("recommendations") or []),
        })
    rows.sort(key=lambda r: r["aum"] or 0, reverse=True)
    rows = rows[:100]
    lines = [f"TOTAL CLIENTS: {len(rows)}", "RANKED BY AUM (desc):"]
    for i, r in enumerate(rows, 1):
        ret = f"{r['ret_pct']:+.1f}%" if r["ret_pct"] is not None else "—"
        score = f"{int(r['score'])}/100" if r["score"] is not None else "—"
        lines.append(
            f"{i}. {r['name']} · AUM ₹{r['aum']:,.0f} · ret {ret} · "
            f"holdings {r['holdings']} · health {score} · actions {r['actions']}"
            + (f" · {r['summary']}" if r['summary'] else "")
        )
    return "\n".join(lines)


# ── Endpoints ──────────────────────────────────────────────────────────
@router.get("/models")
async def list_models(request: Request):
    """Surfaces the 3 model options + default to the UI so the MFD can
    choose cost vs. quality per-call."""
    await get_current_user(request)
    return {
        "default": DEFAULT_MODEL_KEY,
        "models": [
            {"key": k, **{x: v[x] for x in ("label", "tier", "price_hint")}}
            for k, v in MODEL_REGISTRY.items()
        ],
    }


class ExplainRequest(BaseModel):
    model: str = Field(default=DEFAULT_MODEL_KEY)
    focus: Optional[str] = Field(default=None, max_length=200)  # "risk" | "tax" | "performance"


@router.post("/explain")
async def explain(payload: ExplainRequest, request: Request):
    user = await get_current_user(request)
    uid = user["user_id"] if isinstance(user, dict) else user.user_id
    ctx = await _build_context(uid)
    key = _cache_key(payload.model, f"explain:{payload.focus or 'general'}", ctx)
    hit = await _cache_get(key)
    if hit:
        return {"response": hit, "cached": True, "model": payload.model}

    system = (
        "You are a senior investment advisor (CIO) writing for a mutual-fund "
        "distributor (MFD) in India. Style: crisp, specific, professional, "
        "≤ 60 words, no filler, no disclaimers. Use concrete numbers from "
        "the portfolio context. Never fabricate data. End with ONE decisive "
        "line on what to prioritise."
    )
    focus_clause = {
        "risk":        "Focus on risk concentration, drawdown exposure, volatility.",
        "tax":         "Focus on tax efficiency, STCG/LTCG timing, direct-vs-regular savings.",
        "performance": "Focus on returns, benchmark comparison, alpha.",
    }.get(payload.focus or "", "Balanced view across structure, performance, and risk.")

    user_prompt = (
        f"PORTFOLIO CONTEXT:\n{_portfolio_context_block(ctx)}\n\n"
        f"TASK: Explain this portfolio to the advisor. {focus_clause}\n"
        "Return 3-4 short sentences, plain prose. No bullets."
    )
    resp = await _llm_call(payload.model, system, user_prompt, session_id=f"explain-{uid}")
    await _cache_put(key, resp)
    return {"response": resp, "cached": False, "model": payload.model}


class ClientMessageRequest(BaseModel):
    model: str = Field(default=DEFAULT_MODEL_KEY)
    channel: str = Field(default="whatsapp")  # "whatsapp" | "email"
    tone: str = Field(default="warm_professional")  # "warm_professional" | "formal" | "concise"
    additional_note: Optional[str] = Field(default=None, max_length=400)


@router.post("/client-message")
async def client_message(payload: ClientMessageRequest, request: Request):
    user = await get_current_user(request)
    uid = user["user_id"] if isinstance(user, dict) else user.user_id
    ctx = await _build_context(uid)
    cache_ctx = {**ctx, "__channel": payload.channel, "__tone": payload.tone}
    key = _cache_key(payload.model, "client-message", cache_ctx, payload.additional_note or "")
    hit = await _cache_get(key)
    if hit:
        return {"response": hit, "cached": True, "model": payload.model}

    system = (
        "You are drafting a short, client-ready portfolio update for a mutual-fund "
        "distributor in India to send to their client. Style rules: "
        "(1) use the client's first name; "
        "(2) mention 1-2 concrete things you noticed in plain English — NO jargon like 'alpha', 'drawdown'; "
        "(3) end with a light CTA to discuss; "
        "(4) do NOT make promises about returns; "
        "(5) do NOT reveal internal scores or numbers the client wouldn't understand; "
        "(6) never fabricate data."
    )
    length_clause = "WhatsApp — 4-6 short lines." if payload.channel == "whatsapp" \
        else "Email — subject line + 3 short paragraphs."
    tone_clause = {
        "warm_professional": "Warm, professional, first-person plural (we).",
        "formal":           "Formal, deferential, third-person where possible.",
        "concise":          "Direct, bulleted, no pleasantries.",
    }.get(payload.tone, "Warm, professional.")
    extra = f"\nADVISOR NOTE: {payload.additional_note}" if payload.additional_note else ""
    user_prompt = (
        f"CLIENT CONTEXT:\n{_portfolio_context_block(ctx)}{extra}\n\n"
        f"TASK: Draft the message. {length_clause} {tone_clause} "
        "Output ONLY the message body (and subject on line 1 if email)."
    )
    resp = await _llm_call(payload.model, system, user_prompt, session_id=f"msg-{uid}")
    await _cache_put(key, resp, ttl_hours=6)  # shorter TTL — tone variations likely
    return {"response": resp, "cached": False, "model": payload.model}


class AskRequest(BaseModel):
    model: str = Field(default=DEFAULT_MODEL_KEY)
    question: str = Field(min_length=2, max_length=800)
    history: Optional[List[Dict[str, str]]] = None  # [{role, content}, ...]


@router.post("/ask")
async def ask(payload: AskRequest, request: Request):
    """Free-form Q&A with the client's full portfolio context. Not cached
    (questions are unique by definition). History is optional — if
    provided, included inline in the user prompt so the LLM sees continuity
    without us needing a server-side session store in Pass 1."""
    user = await get_current_user(request)
    uid = user["user_id"] if isinstance(user, dict) else user.user_id
    session_uid = user.get("_session_user_id") if isinstance(user, dict) else None
    session_uid = session_uid or uid
    advisor_mode = await _is_advisor_caller(session_uid, user.get("_active_profile_id") if isinstance(user, dict) else None)
    ctx = await _build_context(uid)
    base_system = (
        "You are the advisor's cross-client AI copilot. You have access to "
        "the entire client book provided below. Answer crisply (≤ 200 words), "
        "ground every claim in the numbers. When the user asks for clients "
        "matching a condition, return a Markdown table with name, AUM and the "
        "specific number that triggered the match. End with one concrete next "
        "step. Never speculate beyond the data."
    ) if advisor_mode else (
        "You are the user's personal investment AI copilot — a senior analyst "
        "with access to their full portfolio context. Answer crisply (≤ 120 "
        "words), grounded in the numbers provided. If the question can't be "
        "answered from the context, say so — don't speculate. End with a "
        "clear next step when relevant."
    )
    system = base_system + CHART_PROTOCOL
    history_block = ""
    if payload.history:
        turns = []
        for h in payload.history[-6:]:
            role = h.get("role", "user").upper()
            content = (h.get("content") or "")[:400]
            turns.append(f"{role}: {content}")
        history_block = "\nCONVERSATION SO FAR:\n" + "\n".join(turns) + "\n"

    if advisor_mode:
        book_block = await _advisor_book_block(session_uid)
        user_prompt = (
            f"ADVISOR CLIENT BOOK:\n{book_block}\n"
            f"{history_block}\n"
            f"QUESTION: {payload.question}"
        )
    else:
        user_prompt = (
            f"PORTFOLIO CONTEXT:\n{_portfolio_context_block(ctx)}"
            f"{history_block}\n"
            f"QUESTION: {payload.question}"
        )
    resp = await _llm_call(payload.model, system, user_prompt, session_id=f"ask-{uid}")
    validated = validate_chart_blocks(resp)
    await log_invalid_chart_specs(db, uid, payload.model, "copilot/ask", validated["invalid_specs"])
    return {
        "response": validated["clean_text"],
        "model": payload.model,
        "mode": "advisor" if advisor_mode else "investor",
        "chart_count": validated["valid_count"],
    }


# ── Bundled brief: single LLM call → 4 section narratives ──────────────
class BriefRequest(BaseModel):
    model: str = Field(default=DEFAULT_MODEL_KEY)


@router.post("/brief")
async def brief(payload: BriefRequest, request: Request):
    """One-shot CIO brief — returns {summary, risk, tax, performance, priority}
    in a single LLM call. Cached 24h. Use this for the Client 360 panel
    instead of calling /explain four times."""
    user = await get_current_user(request)
    uid = user["user_id"] if isinstance(user, dict) else user.user_id
    ctx = await _build_context(uid)
    key = _cache_key(payload.model, "brief:v1", ctx)
    hit = await _cache_get(key)
    if hit:
        try:
            return {"brief": json.loads(hit), "cached": True, "model": payload.model}
        except Exception:  # noqa: BLE001
            pass  # fall through to regenerate

    system = (
        "You are a senior CIO writing a structured client brief for a mutual-fund "
        "distributor (MFD) in India. Output STRICT JSON with 5 keys: "
        "summary (≤ 40 words, plain prose on overall shape), "
        "risk (≤ 30 words, top concentration/drawdown risk), "
        "tax (≤ 30 words, STCG/LTCG efficiency or cost leak), "
        "performance (≤ 30 words, return quality), "
        "priority (≤ 20 words, ONE decisive next action). "
        "Use concrete numbers from context. Never fabricate. No filler. "
        "Return ONLY the JSON object, no markdown fences."
    )
    user_prompt = (
        f"PORTFOLIO CONTEXT:\n{_portfolio_context_block(ctx)}\n\n"
        "TASK: Produce the JSON brief now."
    )
    raw = await _llm_call(payload.model, system, user_prompt, session_id=f"brief-{uid}")

    # Strip ```json fences if the model adds them
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()
    try:
        parsed = json.loads(cleaned)
    except Exception:  # noqa: BLE001
        # Fallback: wrap raw text as summary so UI still renders something
        parsed = {"summary": raw, "risk": "", "tax": "", "performance": "", "priority": ""}

    await _cache_put(key, json.dumps(parsed), ttl_hours=24)
    return {"brief": parsed, "cached": False, "model": payload.model}
