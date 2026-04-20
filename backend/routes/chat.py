"""AI Chat routes."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import Optional
from datetime import datetime, timezone
import uuid
import json
import logging

from deps import db, get_current_user, ai_engine
from models import ChatMessageInput
from services import portfolio_intelligence
from services.action_plan_manager import ActionPlanManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_plan_manager = ActionPlanManager()


async def _v2_active_plan_context(user_id: str) -> str:
    """Build a COMPACT, STRICT block describing the user's current V2 active plan.

    This is injected into every chat turn so the AI can ONLY reference V2's
    actions — never invent its own. If there is no active plan we tell the AI
    exactly that, so it stops volunteering recommendations.
    """
    try:
        plan = await _plan_manager.get_active_plan(user_id)
    except Exception as e:
        logger.debug(f"v2 plan context fetch failed: {e}")
        plan = None

    if not plan or not plan.get("actions"):
        return (
            "\n\n── V2 ACTIVE PLAN (SOURCE OF TRUTH) ──\n"
            "No active V2 plan for this user.\n"
            "Rule: Do NOT recommend any actions. Tell the user: 'V2 hasn't flagged "
            "any actions yet. Click Generate New Plan on the Plan Board to run V2.'\n"
        )

    lines = [
        "\n\n── V2 ACTIVE PLAN (SOURCE OF TRUTH) ──",
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

    lines.append("\nActions (use these EXACTLY — do NOT invent new ones):")
    for i, a in enumerate(plan["actions"], 1):
        reasons = " · ".join(a.get("reason_codes") or [])
        ti = a.get("tax_impact") or {}
        tax_str = ""
        if ti.get("tax_impact_pending"):
            tax_str = " [tax pending — buy_date missing]"
        elif ti.get("tax_liability"):
            tax_str = f" · est. tax ₹{ti.get('tax_liability',0):,.0f} ({ti.get('tax_regime','?')})"
        amt = a.get("exit_amount_rs") or a.get("amount_rs") or 0
        lines.append(
            f"  {i}. [{a.get('type')}] {a.get('asset_name','?')[:55]}  "
            f"₹{amt:,.0f} · {reasons}{tax_str}"
        )

    lines.append(
        "\nRule: If the user asks 'what should I do', describe the actions above. "
        "If they ask about a stock/fund that's NOT in this list, respond: 'V2 hasn't "
        "flagged that instrument. Here's what V2 is prioritising instead: …' and list 1-3 "
        "V2 actions from above.\n"
    )
    return "\n".join(lines)



async def _compute_portfolio_intelligence_context(user_id: str) -> str:
    """Generate PG-based Portfolio Intelligence context for AI chat."""
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
        
        # Fund overlap pairs
        if pairs:
            ctx += "\nFund Overlap (Stock-Level):\n"
            for p in pairs[:5]:
                ctx += f"  - {p['a_name']} ↔ {p['b_name']}: {p['overlap_pct']:.1f}% overlap ({p['shared_count']} shared stocks)\n"
                if p.get('reasons'):
                    ctx += f"    Reasons: {', '.join(p['reasons'])}\n"
        
        # Category inefficiency
        if category_ineff:
            ctx += "\nCategory Inefficiency:\n"
            for cat in category_ineff[:3]:
                ctx += f"  - {cat['category']}: {cat['funds_count']} funds, {cat['avg_pair_overlap']:.1f}% avg overlap"
                if cat.get('inefficient'):
                    ctx += " ⚠️ INEFFICIENT\n"
                else:
                    ctx += "\n"
        
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
        return ctx
        
    except Exception as e:
        logger.warning(f"Failed to compute intelligence context: {e}")
        return ""



@router.get("/chat/sessions")
async def list_chat_sessions(request: Request):
    user = await get_current_user(request)
    sessions = await db.chat_sessions.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("updated_at", -1).to_list(50)
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
    return {k: v for k, v in session_doc.items() if k != "_id"}


@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(request: Request, session_id: str):
    user = await get_current_user(request)
    await db.chat_sessions.delete_one({"session_id": session_id, "user_id": user["user_id"]})
    await db.chat_messages.delete_many({"session_id": session_id, "user_id": user["user_id"]})
    return {"message": "Session deleted"}


@router.get("/chat/messages")
async def get_chat_messages(request: Request, session_id: Optional[str] = None):
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if session_id:
        query["session_id"] = session_id
    messages = await db.chat_messages.find(
        query, {"_id": 0}
    ).sort("created_at", 1).to_list(200)
    return messages


@router.post("/chat/send")
async def send_chat(request: Request, msg: ChatMessageInput):
    user = await get_current_user(request)
    user_id = user["user_id"]

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

    # Gather portfolio context
    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(100)
    portfolio_context = ""
    if holdings:
        total_inv = sum(h["quantity"] * h["buy_price"] for h in holdings)
        total_cur = sum(h["quantity"] * h["current_price"] for h in holdings)
        portfolio_context = f"\n\nUser's Portfolio Summary:\n- Total Invested: \u20b9{total_inv:,.0f}\n- Current Value: \u20b9{total_cur:,.0f}\n- Returns: \u20b9{total_cur - total_inv:,.0f} ({((total_cur-total_inv)/total_inv*100) if total_inv > 0 else 0:.1f}%)\n- Holdings ({len(holdings)}):\n"
        for h in holdings:
            inv = h["quantity"] * h["buy_price"]
            cur = h["quantity"] * h["current_price"]
            ret = ((cur - inv) / inv * 100) if inv > 0 else 0
            portfolio_context += f"  - {h['name']} ({h['asset_type']}): {h['quantity']} units @ \u20b9{h['buy_price']} -> \u20b9{h['current_price']} ({ret:.1f}%) | Sector: {h.get('sector','N/A')}\n"

    # Risk profile context
    user_profile = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0})
    risk_context = ""
    if user_profile and user_profile.get("risk_profile"):
        rp = user_profile["risk_profile"]
        risk_context = f"\n\nUser's Risk Profile: {rp.get('category', 'Unknown')} (Score: {rp.get('score', 'N/A')}/100)"

    # Portfolio Intelligence context (PG-based stock-level data)
    intelligence_context = await _compute_portfolio_intelligence_context(user_id)
    # V2 active plan (single source of truth for actions)
    v2_plan_context = await _v2_active_plan_context(user_id)

    # Get recent chat history
    recent_msgs = await db.chat_messages.find(
        {"user_id": user_id, "session_id": session_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(20)
    recent_msgs.reverse()

    try:
        history = []
        if len(recent_msgs) > 1:
            for m in recent_msgs[:-1]:
                history.append({"role": m["role"], "content": m["content"][:500]})

        ai_response = await ai_engine.chat(
            message=msg.message,
            portfolio_context=portfolio_context + risk_context + intelligence_context + v2_plan_context,
            history=history,
            session_id=f"wealth_{user_id}_{session_id}",
        )

    except Exception as e:
        logger.error(f"LLM error: {e}")
        ai_response = "I'm having trouble connecting to my AI engine right now. Please try again in a moment."

    # Save AI response
    ai_msg_doc = {
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
        "session_id": session_id,
        "user_id": user_id,
        "role": "assistant",
        "content": ai_response,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.chat_messages.insert_one(ai_msg_doc)

    return {
        "user_message": {k: v for k, v in user_msg_doc.items() if k != "_id"},
        "ai_message": {k: v for k, v in ai_msg_doc.items() if k != "_id"}
    }


@router.post("/chat/stream")
async def stream_chat(request: Request):
    """Stream AI response token-by-token via SSE."""
    user = await get_current_user(request)
    user_id = user["user_id"]
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

    # Portfolio context
    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(100)
    portfolio_context = ""
    if holdings:
        total_inv = sum(h["quantity"] * h["buy_price"] for h in holdings)
        total_cur = sum(h["quantity"] * h["current_price"] for h in holdings)
        portfolio_context = f"\n\nUser's Portfolio Summary:\n- Total Invested: \u20b9{total_inv:,.0f}\n- Current Value: \u20b9{total_cur:,.0f}\n- Returns: \u20b9{total_cur - total_inv:,.0f} ({((total_cur-total_inv)/total_inv*100) if total_inv > 0 else 0:.1f}%)\n- Holdings ({len(holdings)}):\n"
        for h in holdings[:30]:
            inv = h["quantity"] * h["buy_price"]
            cur = h["quantity"] * h["current_price"]
            ret = ((cur - inv) / inv * 100) if inv > 0 else 0
            portfolio_context += f"  - {h['name']} ({h['asset_type']}): {h['quantity']} units @ \u20b9{h['buy_price']} -> \u20b9{h['current_price']} ({ret:.1f}%)\n"

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
        try:
            # Send metadata first
            meta = {"session_id": session_id, "user_msg_id": user_msg_id, "ai_msg_id": ai_msg_id}
            yield f"data: {json.dumps({'type': 'meta', **meta})}\n\n"

            # Portfolio Intelligence context (PG-based stock-level data)
            intelligence_context = await _compute_portfolio_intelligence_context(user_id)
            v2_plan_context = await _v2_active_plan_context(user_id)
            
            async for token in ai_engine.chat_stream(
                message=message,
                portfolio_context=portfolio_context + intelligence_context + v2_plan_context,
                history=history,
                session_id=f"wealth_{user_id}_{session_id}",
            ):
                full_response += token
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            # Save complete AI response
            ai_msg_doc = {
                "message_id": ai_msg_id,
                "session_id": session_id,
                "user_id": user_id,
                "role": "assistant",
                "content": full_response,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            await db.chat_messages.insert_one(ai_msg_doc)

            yield f"data: {json.dumps({'type': 'done', 'content': full_response})}\n\n"

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
    return {"message": "Chat cleared"}
