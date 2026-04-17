"""AI Chat routes."""
from fastapi import APIRouter, HTTPException, Request
from typing import Optional
from datetime import datetime, timezone
import uuid
import logging

from deps import db, get_current_user, ai_engine
from models import ChatMessageInput

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


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
            portfolio_context=portfolio_context,
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
