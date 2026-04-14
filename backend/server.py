from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import httpx
import json
import io
import csv
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from emergentintegrations.llm.chat import LlmChat, UserMessage

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# LLM Key
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')

app = FastAPI()
api_router = APIRouter(prefix="/api")

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== MODELS ====================

class UserProfile(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = ""
    created_at: str

class HoldingCreate(BaseModel):
    name: str
    ticker: Optional[str] = ""
    asset_type: str  # equity, mutual_fund, etf, bond, gold, fd, other
    quantity: float
    buy_price: float
    current_price: float
    sector: Optional[str] = "Other"
    buy_date: Optional[str] = ""

class HoldingUpdate(BaseModel):
    name: Optional[str] = None
    ticker: Optional[str] = None
    asset_type: Optional[str] = None
    quantity: Optional[float] = None
    buy_price: Optional[float] = None
    current_price: Optional[float] = None
    sector: Optional[str] = None
    buy_date: Optional[str] = None

class ChatMessage(BaseModel):
    message: str

# ==================== AUTH HELPERS ====================

async def get_current_user(request: Request) -> dict:
    session_token = request.cookies.get("session_token")
    if not session_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header.split(" ")[1]
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    session_doc = await db.user_sessions.find_one({"session_token": session_token}, {"_id": 0})
    if not session_doc:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    expires_at = session_doc["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")
    
    user_doc = await db.users.find_one({"user_id": session_doc["user_id"]}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    return user_doc

# ==================== AUTH ROUTES ====================

@api_router.post("/auth/session")
async def exchange_session(request: Request, response: Response):
    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.get(
            "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
            headers={"X-Session-ID": session_id}
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session_id")
    
    user_data = resp.json()
    email = user_data["email"]
    name = user_data.get("name", "")
    picture = user_data.get("picture", "")
    session_token = user_data.get("session_token", str(uuid.uuid4()))
    
    existing_user = await db.users.find_one({"email": email}, {"_id": 0})
    if existing_user:
        user_id = existing_user["user_id"]
        await db.users.update_one({"email": email}, {"$set": {"name": name, "picture": picture}})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
    
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=7 * 24 * 3600
    )
    
    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return user_doc

@api_router.get("/auth/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    return user

@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    if session_token:
        await db.user_sessions.delete_many({"session_token": session_token})
    response.delete_cookie(key="session_token", path="/", samesite="none", secure=True)
    return {"message": "Logged out"}

# ==================== PORTFOLIO ROUTES ====================

@api_router.get("/portfolio/holdings")
async def get_holdings(request: Request):
    user = await get_current_user(request)
    holdings = await db.holdings.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(1000)
    return holdings

@api_router.post("/portfolio/holdings")
async def add_holding(request: Request, holding: HoldingCreate):
    user = await get_current_user(request)
    holding_doc = {
        "holding_id": f"hold_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "name": holding.name,
        "ticker": holding.ticker,
        "asset_type": holding.asset_type,
        "quantity": holding.quantity,
        "buy_price": holding.buy_price,
        "current_price": holding.current_price,
        "sector": holding.sector or "Other",
        "buy_date": holding.buy_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.holdings.insert_one(holding_doc)
    result = await db.holdings.find_one({"holding_id": holding_doc["holding_id"]}, {"_id": 0})
    return result

@api_router.put("/portfolio/holdings/{holding_id}")
async def update_holding(request: Request, holding_id: str, holding: HoldingUpdate):
    user = await get_current_user(request)
    update_data = {k: v for k, v in holding.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    await db.holdings.update_one(
        {"holding_id": holding_id, "user_id": user["user_id"]},
        {"$set": update_data}
    )
    result = await db.holdings.find_one({"holding_id": holding_id}, {"_id": 0})
    if not result:
        raise HTTPException(status_code=404, detail="Holding not found")
    return result

@api_router.delete("/portfolio/holdings/{holding_id}")
async def delete_holding(request: Request, holding_id: str):
    user = await get_current_user(request)
    result = await db.holdings.delete_one({"holding_id": holding_id, "user_id": user["user_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Holding not found")
    return {"message": "Holding deleted"}

@api_router.post("/portfolio/upload-csv")
async def upload_csv(request: Request, file: UploadFile = File(...)):
    user = await get_current_user(request)
    content = await file.read()
    text = content.decode("utf-8")
    
    reader = csv.DictReader(io.StringIO(text))
    holdings_added = []
    
    for row in reader:
        name = row.get("name") or row.get("Name") or row.get("STOCK") or row.get("stock") or ""
        if not name:
            continue
        holding_doc = {
            "holding_id": f"hold_{uuid.uuid4().hex[:12]}",
            "user_id": user["user_id"],
            "name": name.strip(),
            "ticker": (row.get("ticker") or row.get("Ticker") or row.get("SYMBOL") or row.get("symbol") or "").strip(),
            "asset_type": (row.get("asset_type") or row.get("Type") or row.get("type") or "equity").strip().lower(),
            "quantity": float(row.get("quantity") or row.get("Quantity") or row.get("QTY") or row.get("qty") or 0),
            "buy_price": float(row.get("buy_price") or row.get("Buy Price") or row.get("avg_price") or row.get("cost") or 0),
            "current_price": float(row.get("current_price") or row.get("Current Price") or row.get("ltp") or row.get("cmp") or 0),
            "sector": (row.get("sector") or row.get("Sector") or "Other").strip(),
            "buy_date": (row.get("buy_date") or row.get("Buy Date") or row.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip(),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.holdings.insert_one(holding_doc)
        holdings_added.append(holding_doc["holding_id"])
    
    return {"message": f"{len(holdings_added)} holdings imported", "count": len(holdings_added)}

@api_router.get("/portfolio/analytics")
async def get_analytics(request: Request):
    user = await get_current_user(request)
    holdings = await db.holdings.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(1000)
    
    if not holdings:
        return {
            "total_invested": 0, "current_value": 0, "total_returns": 0,
            "returns_pct": 0, "asset_allocation": [], "sector_exposure": [],
            "risk_score": 0, "risk_label": "N/A", "holdings_count": 0,
            "top_gainers": [], "top_losers": []
        }
    
    total_invested = 0
    current_value = 0
    asset_map = {}
    sector_map = {}
    holding_perf = []
    
    for h in holdings:
        inv = h["quantity"] * h["buy_price"]
        cur = h["quantity"] * h["current_price"]
        total_invested += inv
        current_value += cur
        
        at = h.get("asset_type", "other")
        asset_map[at] = asset_map.get(at, 0) + cur
        
        sec = h.get("sector", "Other")
        sector_map[sec] = sector_map.get(sec, 0) + cur
        
        pct_change = ((cur - inv) / inv * 100) if inv > 0 else 0
        holding_perf.append({"name": h["name"], "pct_change": round(pct_change, 2), "value": cur})
    
    total_returns = current_value - total_invested
    returns_pct = (total_returns / total_invested * 100) if total_invested > 0 else 0
    
    asset_allocation = [{"name": k, "value": round(v, 2)} for k, v in asset_map.items()]
    sector_exposure = [{"name": k, "value": round(v, 2)} for k, v in sector_map.items()]
    
    # Risk scoring: based on concentration and diversification
    risk_score = 0
    if len(holdings) < 3:
        risk_score += 30
    elif len(holdings) < 5:
        risk_score += 15
    
    if asset_allocation:
        max_asset_pct = max(a["value"] for a in asset_allocation) / current_value * 100 if current_value > 0 else 0
        if max_asset_pct > 80:
            risk_score += 30
        elif max_asset_pct > 60:
            risk_score += 20
        elif max_asset_pct > 40:
            risk_score += 10
    
    if sector_exposure:
        max_sector_pct = max(s["value"] for s in sector_exposure) / current_value * 100 if current_value > 0 else 0
        if max_sector_pct > 50:
            risk_score += 25
        elif max_sector_pct > 30:
            risk_score += 15
    
    equity_pct = asset_map.get("equity", 0) / current_value * 100 if current_value > 0 else 0
    if equity_pct > 80:
        risk_score += 15
    
    risk_score = min(risk_score, 100)
    risk_label = "Low" if risk_score < 30 else "Moderate" if risk_score < 60 else "High"
    
    holding_perf.sort(key=lambda x: x["pct_change"], reverse=True)
    top_gainers = holding_perf[:3]
    top_losers = holding_perf[-3:][::-1] if len(holding_perf) > 3 else []
    
    return {
        "total_invested": round(total_invested, 2),
        "current_value": round(current_value, 2),
        "total_returns": round(total_returns, 2),
        "returns_pct": round(returns_pct, 2),
        "asset_allocation": asset_allocation,
        "sector_exposure": sector_exposure,
        "risk_score": risk_score,
        "risk_label": risk_label,
        "holdings_count": len(holdings),
        "top_gainers": top_gainers,
        "top_losers": top_losers
    }

# ==================== AI CHAT ROUTES ====================

@api_router.get("/chat/messages")
async def get_chat_messages(request: Request):
    user = await get_current_user(request)
    messages = await db.chat_messages.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", 1).to_list(200)
    return messages

@api_router.post("/chat/send")
async def send_chat(request: Request, msg: ChatMessage):
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    # Save user message
    user_msg_doc = {
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "role": "user",
        "content": msg.message,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.chat_messages.insert_one(user_msg_doc)
    
    # Gather portfolio context
    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(100)
    portfolio_context = ""
    if holdings:
        total_inv = sum(h["quantity"] * h["buy_price"] for h in holdings)
        total_cur = sum(h["quantity"] * h["current_price"] for h in holdings)
        portfolio_context = f"\n\nUser's Portfolio Summary:\n- Total Invested: ₹{total_inv:,.0f}\n- Current Value: ₹{total_cur:,.0f}\n- Returns: ₹{total_cur - total_inv:,.0f} ({((total_cur-total_inv)/total_inv*100) if total_inv > 0 else 0:.1f}%)\n- Holdings ({len(holdings)}):\n"
        for h in holdings:
            inv = h["quantity"] * h["buy_price"]
            cur = h["quantity"] * h["current_price"]
            ret = ((cur - inv) / inv * 100) if inv > 0 else 0
            portfolio_context += f"  - {h['name']} ({h['asset_type']}): {h['quantity']} units @ ₹{h['buy_price']} → ₹{h['current_price']} ({ret:.1f}%) | Sector: {h.get('sector','N/A')}\n"
    
    system_message = f"""You are an expert AI Financial Advisor for Indian retail investors. You provide personalized, data-driven financial guidance.

Your capabilities:
- Portfolio analysis and optimization
- Risk assessment and management
- Investment recommendations (stocks, mutual funds, ETFs, bonds, gold)
- Tax planning and optimization (Indian tax laws)
- Goal-based financial planning (retirement, education, wealth growth)
- Market intelligence and trends

Guidelines:
- Always use ₹ (INR) for currency
- Reference Indian markets (NSE/BSE), SEBI regulations
- Be specific with actionable recommendations
- Explain reasoning clearly
- Include disclaimers for investment advice
- Be conversational and friendly, not robotic
- Use data from the user's portfolio when available
{portfolio_context}

Disclaimer: This is AI-generated guidance for educational purposes. Always consult a SEBI-registered advisor before making investment decisions."""
    
    # Get recent chat history for context
    recent_msgs = await db.chat_messages.find(
        {"user_id": user_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(20)
    recent_msgs.reverse()
    
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"wealth_{user_id}_{uuid.uuid4().hex[:6]}",
            system_message=system_message
        )
        chat.with_model("openai", "gpt-5.2")
        
        # Add conversation history
        for m in recent_msgs[:-1]:  # Exclude the just-added user message
            if m["role"] == "user":
                user_message = UserMessage(text=m["content"])
                await chat.send_message(user_message)
        
        # Send current message
        user_message = UserMessage(text=msg.message)
        ai_response = await chat.send_message(user_message)
        
    except Exception as e:
        logger.error(f"LLM error: {e}")
        ai_response = "I'm having trouble connecting to my AI engine right now. Please try again in a moment."
    
    # Save AI response
    ai_msg_doc = {
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
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

@api_router.delete("/chat/clear")
async def clear_chat(request: Request):
    user = await get_current_user(request)
    await db.chat_messages.delete_many({"user_id": user["user_id"]})
    return {"message": "Chat cleared"}

# ==================== AI INSIGHTS ROUTES ====================

@api_router.get("/insights")
async def get_insights(request: Request):
    user = await get_current_user(request)
    insights = await db.ai_insights.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(20)
    return insights

@api_router.post("/insights/generate")
async def generate_insights(request: Request):
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(100)
    if not holdings:
        return {"insights": [], "message": "Add holdings to generate insights"}
    
    total_inv = sum(h["quantity"] * h["buy_price"] for h in holdings)
    total_cur = sum(h["quantity"] * h["current_price"] for h in holdings)
    
    portfolio_text = f"Portfolio: ₹{total_inv:,.0f} invested, ₹{total_cur:,.0f} current value.\nHoldings:\n"
    for h in holdings:
        ret_pct = ((h["current_price"] - h["buy_price"]) / h["buy_price"] * 100) if h["buy_price"] > 0 else 0
        portfolio_text += f"- {h['name']} ({h['asset_type']}, {h.get('sector','N/A')}): {h['quantity']} units, ₹{h['buy_price']}→₹{h['current_price']} ({ret_pct:.1f}%)\n"
    
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"insights_{user_id}_{uuid.uuid4().hex[:6]}",
            system_message="""You are an expert Indian financial advisor. Analyze the user's portfolio and provide exactly 4 actionable insights.
Return ONLY a valid JSON array with exactly 4 objects, each with these fields:
- "title": short insight title (max 8 words)
- "description": detailed explanation (2-3 sentences)
- "type": one of "warning", "opportunity", "info", "action"
- "priority": one of "high", "medium", "low"

Example: [{"title":"High Sector Concentration","description":"Your portfolio is 70% in IT...","type":"warning","priority":"high"}]"""
        )
        chat.with_model("openai", "gpt-5.2")
        
        user_message = UserMessage(text=f"Analyze this portfolio:\n{portfolio_text}")
        response = await chat.send_message(user_message)
        
        # Parse JSON from response
        clean_response = response.strip()
        if clean_response.startswith("```"):
            clean_response = clean_response.split("```")[1]
            if clean_response.startswith("json"):
                clean_response = clean_response[4:]
        
        insights_data = json.loads(clean_response)
        
    except Exception as e:
        logger.error(f"Insights generation error: {e}")
        insights_data = [
            {"title": "Portfolio Review Needed", "description": "We couldn't generate AI insights right now. Please try again.", "type": "info", "priority": "medium"}
        ]
    
    # Delete old insights and save new
    await db.ai_insights.delete_many({"user_id": user_id})
    saved_insights = []
    for insight in insights_data:
        doc = {
            "insight_id": f"ins_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "title": insight.get("title", ""),
            "description": insight.get("description", ""),
            "type": insight.get("type", "info"),
            "priority": insight.get("priority", "medium"),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.ai_insights.insert_one(doc)
        saved_insights.append({k: v for k, v in doc.items() if k != "_id"})
    
    return {"insights": saved_insights}

# ==================== ROOT ====================

@api_router.get("/")
async def root():
    return {"message": "Agentic Wealth System API"}

# Include router and CORS
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
