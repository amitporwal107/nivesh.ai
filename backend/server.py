from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, UploadFile, File, BackgroundTasks
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
import asyncio
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from emergentintegrations.llm.chat import LlmChat, UserMessage

# Local modules
from models import PortfolioCreate, HoldingCreate, HoldingUpdate, ChatMessageInput, AssetType
from repository import UserRepository, SessionRepository, PortfolioRepository, HoldingRepository
from services import compute_health_score, compute_risk_analysis, generate_recommendations
from services.ai_engine import AIEngine
from services.amfi_nav import fetch_nav_data, update_holdings_nav, lookup_nav
from services.fund_performance import compute_benchmark_ratings
from middleware import RateLimitMiddleware, validate_env

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Validate env on startup
validate_env()

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# LLM Key
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')

# Initialize layers
user_repo = UserRepository(db)
session_repo = SessionRepository(db)
portfolio_repo = PortfolioRepository(db)
holding_repo = HoldingRepository(db)
ai_engine = AIEngine(EMERGENT_LLM_KEY)

app = FastAPI(title="nivesh.ai API", version="2.0")
api_router = APIRouter(prefix="/api")

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

# ==================== PORTFOLIO MANAGEMENT ROUTES ====================

@api_router.get("/portfolios")
async def list_portfolios(request: Request):
    user = await get_current_user(request)
    portfolios = await db.portfolios.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(50)
    # Add holdings count per portfolio
    for p in portfolios:
        count = await db.holdings.count_documents({"user_id": user["user_id"], "portfolio_id": p["portfolio_id"]})
        p["holdings_count"] = count
    return portfolios

@api_router.post("/portfolios")
async def create_portfolio(request: Request, data: PortfolioCreate):
    user = await get_current_user(request)
    doc = {
        "portfolio_id": f"pf_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "name": data.name,
        "member_name": data.member_name,
        "relationship": data.relationship,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.portfolios.insert_one(doc)
    result = await db.portfolios.find_one({"portfolio_id": doc["portfolio_id"]}, {"_id": 0})
    return result

@api_router.delete("/portfolios/{portfolio_id}")
async def delete_portfolio(request: Request, portfolio_id: str):
    user = await get_current_user(request)
    result = await db.portfolios.delete_one({"portfolio_id": portfolio_id, "user_id": user["user_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    # Cascade delete holdings
    deleted = await db.holdings.delete_many({"user_id": user["user_id"], "portfolio_id": portfolio_id})
    return {"message": f"Portfolio deleted with {deleted.deleted_count} holdings"}

# ==================== INSTRUMENT SEARCH / AUTOCOMPLETE ====================

@api_router.get("/search/instruments")
async def search_instruments(q: str = ""):
    from instruments_data import INDIAN_INSTRUMENTS
    if not q or len(q) < 2:
        return []
    q_lower = q.lower()
    results = []
    for inst in INDIAN_INSTRUMENTS:
        if q_lower in inst["name"].lower() or q_lower in inst["ticker"].lower():
            results.append(inst)
        if len(results) >= 15:
            break
    return results

# ==================== HOLDINGS ROUTES ====================

@api_router.get("/portfolio/holdings")
async def get_holdings(request: Request, portfolio_id: str = "", asset_type: str = ""):
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    if asset_type:
        query["asset_type"] = asset_type
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)
    return holdings

@api_router.post("/portfolio/holdings")
async def add_holding(request: Request, holding: HoldingCreate):
    user = await get_current_user(request)
    holding_doc = {
        "holding_id": f"hold_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "portfolio_id": holding.portfolio_id or "",
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

async def parse_csv_holdings(content: bytes) -> list:
    """Parse CSV/Excel files into holding rows."""
    holdings = []
    # Try UTF-8, then latin-1
    for encoding in ["utf-8", "latin-1", "cp1252"]:
        try:
            text = content.decode(encoding)
            break
        except (UnicodeDecodeError, Exception):
            continue
    else:
        raise HTTPException(status_code=400, detail="Could not decode file. Please use UTF-8 encoding.")
    
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        name = row.get("name") or row.get("Name") or row.get("STOCK") or row.get("stock") or row.get("Scheme Name") or row.get("scheme_name") or row.get("Fund") or ""
        if not name.strip():
            continue
        holdings.append({
            "name": name.strip(),
            "ticker": (row.get("ticker") or row.get("Ticker") or row.get("SYMBOL") or row.get("symbol") or row.get("ISIN") or "").strip(),
            "asset_type": (row.get("asset_type") or row.get("Type") or row.get("type") or row.get("Asset Type") or "equity").strip().lower(),
            "quantity": float(row.get("quantity") or row.get("Quantity") or row.get("QTY") or row.get("qty") or row.get("Units") or row.get("units") or row.get("Balance Units") or 0),
            "buy_price": float(row.get("buy_price") or row.get("Buy Price") or row.get("avg_price") or row.get("cost") or row.get("Avg. Cost") or row.get("NAV") or 0),
            "current_price": float(row.get("current_price") or row.get("Current Price") or row.get("ltp") or row.get("cmp") or row.get("Current NAV") or row.get("Market Value") or 0),
            "sector": (row.get("sector") or row.get("Sector") or "Other").strip(),
            "buy_date": (row.get("buy_date") or row.get("Buy Date") or row.get("date") or row.get("Date") or "").strip(),
        })
    return holdings

async def parse_excel_holdings(content: bytes) -> list:
    """Parse Excel (.xlsx) files into holding rows."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    
    headers = [str(h).strip().lower() if h else "" for h in rows[0]]
    holdings = []
    
    def col(names):
        for n in names:
            if n.lower() in headers:
                return headers.index(n.lower())
        return None
    
    name_i = col(["name", "scheme name", "fund", "stock", "scheme"])
    qty_i = col(["quantity", "qty", "units", "balance units"])
    buy_i = col(["buy price", "buy_price", "avg price", "avg. cost", "nav", "cost"])
    cur_i = col(["current price", "current_price", "ltp", "cmp", "current nav", "market value"])
    type_i = col(["asset_type", "type", "asset type"])
    sector_i = col(["sector"])
    ticker_i = col(["ticker", "symbol", "isin"])
    date_i = col(["buy_date", "buy date", "date"])
    
    for row in rows[1:]:
        if not row or name_i is None or name_i >= len(row) or not row[name_i]:
            continue
        name = str(row[name_i]).strip()
        if not name:
            continue
        holdings.append({
            "name": name,
            "ticker": str(row[ticker_i]).strip() if ticker_i is not None and ticker_i < len(row) and row[ticker_i] else "",
            "asset_type": str(row[type_i]).strip().lower() if type_i is not None and type_i < len(row) and row[type_i] else "equity",
            "quantity": float(row[qty_i]) if qty_i is not None and qty_i < len(row) and row[qty_i] else 0,
            "buy_price": float(row[buy_i]) if buy_i is not None and buy_i < len(row) and row[buy_i] else 0,
            "current_price": float(row[cur_i]) if cur_i is not None and cur_i < len(row) and row[cur_i] else 0,
            "sector": str(row[sector_i]).strip() if sector_i is not None and sector_i < len(row) and row[sector_i] else "Other",
            "buy_date": str(row[date_i]).strip() if date_i is not None and date_i < len(row) and row[date_i] else "",
        })
    wb.close()
    return holdings

async def parse_cas_pdf(content: bytes, password: str = "") -> list:
    """Parse CAS (Consolidated Account Statement) PDF using AI with direct PDF upload."""
    from emergentintegrations.llm.chat import FileContent
    import base64
    
    cas_system_message = """You are a CAS (Consolidated Account Statement) parser for Indian mutual funds and investments.
Extract ALL investment holdings from the CAS data provided.

Return ONLY a valid JSON array. Each object must have:
- "name": scheme/fund name (string, clean and readable)
- "ticker": ISIN code if found (string, empty if not found)
- "asset_type": one of "mutual_fund", "equity", "etf", "bond", "gold", "fd", "other"
- "quantity": number of units/shares (float)
- "buy_price": average cost per unit (float, 0 if unknown)
- "current_price": current NAV or market price per unit (float, 0 if unknown)
- "sector": category like "Large Cap", "Mid Cap", "Small Cap", "Flexi Cap", "Multi Cap", "Balanced", "Debt", "ELSS", "Index", "Gold", "Banking", "IT", "Other" (string)

IMPORTANT RULES:
- If same fund appears with different folios, keep them SEPARATE (don't combine)
- For mutual funds, use the NAV as current_price and avg cost as buy_price
- For equities, use market price as current_price
- For ETFs, classify as "etf" not "mutual_fund"
- For Sovereign Gold Bonds, use asset_type "gold"
- Extract ALL holdings, don't skip any
- Return ONLY the JSON array, no explanation"""

    # Try text extraction first (works for text-based PDFs)
    text = ""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            if not password:
                raise HTTPException(status_code=400, detail="PDF is password-protected. Please provide the password.")
            if not reader.decrypt(password):
                raise HTTPException(status_code=400, detail="Incorrect PDF password. Please try again.")
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"PyPDF2 text extraction failed: {e}")

    if text.strip() and len(text.strip()) > 200:
        text = text[:12000]
        try:
            chat = LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"cas_txt_{uuid.uuid4().hex[:8]}",
                system_message=cas_system_message
            )
            chat.with_model("openai", "gpt-5.2")
            user_message = UserMessage(text=f"Parse this CAS statement and extract ALL holdings:\n\n{text}")
            response = await chat.send_message(user_message)
            return _parse_json_response(response)
        except Exception as e:
            logger.error(f"CAS text parsing error: {e}")
            raise HTTPException(status_code=422, detail=f"Could not parse CAS text. Error: {str(e)}")
    
    # Image-based PDF — get page count reliably using pdf2image/poppler
    logger.info(f"CAS PDF is image-based, processing in page batches (password={'yes' if password else 'no'})")
    try:
        from pdf2image import pdfinfo_from_bytes
        from PyPDF2 import PdfReader as PdfReader2, PdfWriter
        
        # Use poppler (pdfinfo) for reliable page count — pass password if available
        try:
            pdfinfo_kwargs = {}
            if password:
                pdfinfo_kwargs["userpw"] = password
            info = pdfinfo_from_bytes(content, **pdfinfo_kwargs)
            total_pages = info.get("Pages", 0)
            logger.info(f"pdf2image detected {total_pages} pages")
        except Exception as e:
            logger.warning(f"pdfinfo failed: {e}")
            total_pages = 0
        
        # Fallback: try PyPDF2 with strict=False and decrypt
        if total_pages == 0:
            try:
                fallback_reader = PdfReader2(io.BytesIO(content), strict=False)
                if fallback_reader.is_encrypted and password:
                    fallback_reader.decrypt(password)
                total_pages = len(fallback_reader.pages)
                logger.info(f"PyPDF2 strict=False detected {total_pages} pages")
            except Exception as e:
                logger.warning(f"PyPDF2 fallback failed: {e}")
        
        if total_pages == 0:
            detail = "Could not read PDF."
            if password:
                detail += " The password may be incorrect."
            else:
                detail += " The file may be password-protected — please provide the password."
            raise HTTPException(status_code=400, detail=detail)
        
        all_holdings = []
        
        # Re-read with strict=False and decrypt for page extraction
        pdf_reader = None
        try:
            pdf_reader = PdfReader2(io.BytesIO(content), strict=False)
            if pdf_reader.is_encrypted and password:
                pdf_reader.decrypt(password)
            # Test if we can actually access pages after decryption
            _ = len(pdf_reader.pages)
        except Exception as e:
            logger.warning(f"PyPDF2 reader init failed: {e}")
            pdf_reader = None
        
        # Process in batches of 3 pages
        for start_idx in range(0, total_pages, 3):
            end_idx = min(start_idx + 3, total_pages)
            
            # Try to create chunk PDF from pages
            chunk_bytes = None
            if pdf_reader and len(pdf_reader.pages) >= end_idx:
                try:
                    writer = PdfWriter()
                    for i in range(start_idx, end_idx):
                        writer.add_page(pdf_reader.pages[i])
                    buf = io.BytesIO()
                    writer.write(buf)
                    chunk_bytes = buf.getvalue()
                except Exception as e:
                    logger.warning(f"PyPDF2 page split failed for pages {start_idx+1}-{end_idx}: {e}")
            
            # Fallback: use pdf2image to extract pages as a new PDF via poppler
            if not chunk_bytes or len(chunk_bytes) < 1000:
                try:
                    from pdf2image import convert_from_bytes
                    from PIL import Image
                    
                    convert_kwargs = {"first_page": start_idx+1, "last_page": end_idx, "dpi": 150}
                    if password:
                        convert_kwargs["userpw"] = password
                    images = convert_from_bytes(content, **convert_kwargs)
                    if images:
                        # Convert images back to a PDF
                        img_buf = io.BytesIO()
                        rgb_images = [img.convert('RGB') for img in images]
                        rgb_images[0].save(img_buf, format='PDF', save_all=True, append_images=rgb_images[1:])
                        chunk_bytes = img_buf.getvalue()
                        logger.info(f"Used pdf2image fallback for pages {start_idx+1}-{end_idx}")
                except Exception as e:
                    logger.warning(f"pdf2image fallback failed for pages {start_idx+1}-{end_idx}: {e}")
                    continue
            
            if not chunk_bytes or len(chunk_bytes) < 1000:
                continue
            
            pdf_base64 = base64.b64encode(chunk_bytes).decode("utf-8")
            
            file_content = FileContent(
                content_type="application/pdf",
                file_content_base64=pdf_base64
            )
            
            chat = LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"cas_p{start_idx}_{uuid.uuid4().hex[:6]}",
                system_message=cas_system_message
            )
            chat.with_model("openai", "gpt-5.2")
            
            user_message = UserMessage(
                text=f"These are pages {start_idx+1}-{end_idx} of a CAS (Consolidated Account Statement) from NSDL/CDSL India. Extract ALL investment holdings visible on these pages (mutual funds, equities, ETFs, gold bonds). If no holdings on these pages, return []. Return ONLY a JSON array.",
                file_contents=[file_content]
            )
            
            try:
                response = await chat.send_message(user_message)
                page_holdings = _parse_json_response(response)
                if page_holdings:
                    all_holdings.extend(page_holdings)
                    logger.info(f"Extracted {len(page_holdings)} holdings from pages {start_idx+1}-{end_idx}")
            except Exception as page_err:
                logger.warning(f"Failed to parse pages {start_idx+1}-{end_idx}: {page_err}")
                continue
        
        # Deduplicate by name+quantity+current_price
        seen = set()
        unique_holdings = []
        for h in all_holdings:
            key = f"{h.get('name','').strip()}__{h.get('quantity',0)}__{h.get('current_price',0)}"
            if key not in seen:
                seen.add(key)
                unique_holdings.append(h)
        
        logger.info(f"Total unique holdings from CAS: {len(unique_holdings)}")
        
        if not unique_holdings:
            raise HTTPException(status_code=422, detail="Could not extract any holdings from the CAS PDF. Please ensure the file contains valid CAS data.")
        
        return unique_holdings
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CAS PDF parsing error: {e}")
        raise HTTPException(status_code=422, detail=f"Could not parse CAS PDF. Error: {str(e)}")

def _parse_json_response(response: str) -> list:
    """Parse JSON array from LLM response, handling markdown code blocks."""
    clean = response.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        start = 1
        end = len(lines) - 1
        if lines[0].startswith("```json"):
            start = 1
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        clean = "\n".join(lines[start:end])
    try:
        result = json.loads(clean.strip())
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        import re
        match = re.search(r'\[[\s\S]*\]', clean)
        if match:
            try:
                result = json.loads(match.group())
                return result if isinstance(result, list) else []
            except json.JSONDecodeError:
                pass
        return []

def _parse_json_response_obj(response: str) -> dict:
    """Parse JSON object from LLM response."""
    clean = response.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        start = 1
        end = len(lines) - 1
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        clean = "\n".join(lines[start:end])
    try:
        result = json.loads(clean.strip())
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{[\s\S]*\}', clean)
        if match:
            try:
                result = json.loads(match.group())
                return result if isinstance(result, dict) else {}
            except json.JSONDecodeError:
                pass
        return {}

async def _save_holdings(user_id: str, parsed: list, file_type: str, task_id: str = None, portfolio_id: str = ""):
    """Save parsed holdings to DB and optionally update task status."""
    holdings_added = []
    for h in parsed:
        asset_type = h.get("asset_type", "equity")
        if asset_type not in ["equity", "mutual_fund", "etf", "bond", "gold", "fd", "other"]:
            asset_type = "mutual_fund" if "fund" in h.get("name", "").lower() else "equity"
        
        holding_doc = {
            "holding_id": f"hold_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "portfolio_id": portfolio_id,
            "name": h.get("name", "Unknown"),
            "ticker": h.get("ticker", ""),
            "asset_type": asset_type,
            "quantity": float(h.get("quantity", 0)),
            "buy_price": float(h.get("buy_price", 0)),
            "current_price": float(h.get("current_price", 0)),
            "sector": h.get("sector", "Other"),
            "buy_date": h.get("buy_date", "") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.holdings.insert_one(holding_doc)
        holdings_added.append({
            "holding_id": holding_doc["holding_id"],
            "name": holding_doc["name"],
            "asset_type": holding_doc["asset_type"],
            "quantity": holding_doc["quantity"],
        })
    
    if task_id:
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {
                "status": "completed",
                "message": f"{len(holdings_added)} holdings imported from {file_type}",
                "count": len(holdings_added),
                "holdings": holdings_added,
                "completed_at": datetime.now(timezone.utc).isoformat()
            }}
        )
    
    return holdings_added

async def _process_cas_background(content: bytes, user_id: str, task_id: str, portfolio_id: str = "", password: str = ""):
    """Background task for CAS PDF processing."""
    try:
        logger.info(f"Background CAS task {task_id}: password={'provided' if password else 'none'}, size={len(content)}")
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "processing", "message": "Parsing CAS PDF with AI..."}}
        )
        parsed = await parse_cas_pdf(content, password=password)
        if not parsed:
            await db.upload_tasks.update_one(
                {"task_id": task_id},
                {"$set": {"status": "completed", "message": "No holdings found in CAS PDF", "count": 0, "holdings": []}}
            )
            return
        await _save_holdings(user_id, parsed, "CAS PDF", task_id, portfolio_id)
    except Exception as e:
        logger.error(f"Background CAS processing error: {e}")
        error_msg = str(e)
        if "password" in error_msg.lower() or "decrypt" in error_msg.lower():
            error_msg = "PDF is password-protected. Please provide the correct password."
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "error", "message": f"Failed to parse CAS: {error_msg}", "count": 0, "holdings": []}}
        )

@api_router.post("/portfolio/upload")
async def upload_portfolio(request: Request, file: UploadFile = File(...)):
    """Upload portfolio file - supports CSV, Excel (.xlsx), and CAS PDF."""
    user = await get_current_user(request)
    filename = (file.filename or "").lower()
    user_id = user["user_id"]
    
    # Read file synchronously via underlying SpooledTemporaryFile (faster than async read for large files)
    content = file.file.read()
    
    # For PDF files, process asynchronously (can take 1-3 minutes)
    if filename.endswith(".pdf"):
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        await db.upload_tasks.insert_one({
            "task_id": task_id,
            "user_id": user_id,
            "status": "processing",
            "message": "CAS PDF received, AI parsing started...",
            "count": 0,
            "holdings": [],
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"CAS PDF received: {len(content)} bytes, task {task_id}")
        asyncio.create_task(_process_cas_background(content, user_id, task_id))
        return {
            "task_id": task_id,
            "status": "processing",
            "message": "CAS PDF is being processed by AI. This may take 1-2 minutes.",
            "count": 0,
            "holdings": []
        }
    
    # For CSV/Excel, process synchronously
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        parsed = await parse_excel_holdings(content)
        file_type = "Excel"
    elif filename.endswith(".csv"):
        parsed = await parse_csv_holdings(content)
        file_type = "CSV"
    else:
        try:
            parsed = await parse_csv_holdings(content)
            file_type = "CSV"
        except Exception:
            raise HTTPException(status_code=400, detail="Unsupported file format. Please upload CSV, Excel (.xlsx), or CAS PDF.")
    
    if not parsed:
        return {"message": "No holdings found in the uploaded file", "count": 0, "holdings": []}
    
    holdings_added = await _save_holdings(user_id, parsed, file_type)
    return {
        "message": f"{len(holdings_added)} holdings imported from {file_type}",
        "count": len(holdings_added),
        "holdings": holdings_added
    }

@api_router.post("/portfolio/upload-raw")
async def upload_portfolio_raw(request: Request):
    """Raw upload endpoint for large files - avoids multipart parsing overhead.
    Send file as raw body with X-Filename, X-Portfolio-Id, X-Password headers."""
    user = await get_current_user(request)
    filename = request.headers.get("X-Filename", "upload.pdf").lower()
    portfolio_id = request.headers.get("X-Portfolio-Id", "")
    pdf_password = request.headers.get("X-Password", "")
    user_id = user["user_id"]
    
    # Stream the body directly
    body_chunks = []
    async for chunk in request.stream():
        body_chunks.append(chunk)
    content = b"".join(body_chunks)
    
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    
    logger.info(f"Raw upload received: {len(content)} bytes, filename: {filename}, password={'yes' if pdf_password else 'no'}, portfolio: {portfolio_id}")
    
    if filename.endswith(".pdf"):
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        await db.upload_tasks.insert_one({
            "task_id": task_id,
            "user_id": user_id,
            "status": "processing",
            "message": "CAS PDF received, AI parsing started...",
            "count": 0,
            "holdings": [],
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        asyncio.create_task(_process_cas_background(content, user_id, task_id, portfolio_id, pdf_password))
        return {
            "task_id": task_id,
            "status": "processing",
            "message": "CAS PDF is being processed by AI. This may take 1-2 minutes.",
            "count": 0,
            "holdings": []
        }
    
    # CSV/Excel via raw
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        parsed = await parse_excel_holdings(content)
        file_type = "Excel"
    elif filename.endswith(".csv"):
        parsed = await parse_csv_holdings(content)
        file_type = "CSV"
    else:
        raise HTTPException(status_code=400, detail="Unsupported format")
    
    if not parsed:
        return {"message": "No holdings found", "count": 0, "holdings": []}
    holdings_added = await _save_holdings(user_id, parsed, file_type, portfolio_id=portfolio_id)
    return {"message": f"{len(holdings_added)} holdings imported from {file_type}", "count": len(holdings_added), "holdings": holdings_added}

@api_router.get("/portfolio/upload-status/{task_id}")
async def get_upload_status(request: Request, task_id: str):
    """Poll the status of a CAS PDF upload task."""
    user = await get_current_user(request)
    task = await db.upload_tasks.find_one(
        {"task_id": task_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not task:
        raise HTTPException(status_code=404, detail="Upload task not found")
    return task

@api_router.get("/portfolio/upload-latest-task")
async def get_latest_upload_task(request: Request):
    """Get the most recent upload task for the user (for timeout recovery)."""
    user = await get_current_user(request)
    task = await db.upload_tasks.find_one(
        {"user_id": user["user_id"]},
        {"_id": 0},
        sort=[("created_at", -1)]
    )
    if not task:
        raise HTTPException(status_code=404, detail="No upload tasks found")
    return task

# Keep old endpoint for backward compatibility
@api_router.post("/portfolio/upload-csv")
async def upload_csv_legacy(request: Request, file: UploadFile = File(...)):
    return await upload_portfolio(request, file)

@api_router.get("/portfolio/analytics")
async def get_analytics(request: Request, portfolio_id: str = ""):
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)
    
    # Update mutual fund holdings with live NAV from AMFI
    holdings = await update_holdings_nav(holdings)
    # Persist updated NAV prices back to DB
    for h in holdings:
        if h.get("nav_source") == "AMFI" and h.get("holding_id"):
            await db.holdings.update_one(
                {"holding_id": h["holding_id"]},
                {"$set": {"current_price": h["current_price"], "nav_date": h.get("nav_date", ""), "nav_source": "AMFI"}}
            )
    
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
    top_gainers = holding_perf[:5]
    top_losers = list(reversed(holding_perf[-5:])) if len(holding_perf) > 5 else []
    
    # Heatmap data: all holdings with value and return info for treemap
    heatmap_data = []
    for h in holdings:
        inv = h["quantity"] * h["buy_price"]
        cur = h["quantity"] * h["current_price"]
        pct = ((cur - inv) / inv * 100) if inv > 0 else 0
        if cur > 0:
            heatmap_data.append({
                "name": h["name"][:30],
                "ticker": h.get("ticker", ""),
                "value": round(cur, 2),
                "invested": round(inv, 2),
                "return_pct": round(pct, 1),
                "asset_type": h.get("asset_type", "other"),
                "sector": h.get("sector", "Other"),
            })
    heatmap_data.sort(key=lambda x: x["value"], reverse=True)
    
    # Performance trend: simulated 30-day portfolio value based on current data
    import random
    random.seed(42)
    trend = []
    base = total_invested
    daily_return = (returns_pct / 100) / 365
    for i in range(30):
        day_offset = 29 - i
        d = datetime.now(timezone.utc) - timedelta(days=day_offset)
        # Simulate path from invested to current with some noise
        progress = (30 - day_offset) / 30
        simulated = base + (total_returns * progress) + (random.uniform(-0.015, 0.015) * current_value)
        trend.append({
            "date": d.strftime("%b %d"),
            "value": round(max(simulated, base * 0.85), 0),
        })
    # Ensure last point matches current value
    if trend:
        trend[-1]["value"] = round(current_value, 0)
    
    # Day change (simulated)
    day_change = round(current_value * random.uniform(-0.008, 0.012), 2)
    day_change_pct = round((day_change / current_value * 100) if current_value > 0 else 0, 2)
    
    return {
        "total_invested": round(total_invested, 2),
        "current_value": round(current_value, 2),
        "total_returns": round(total_returns, 2),
        "returns_pct": round(returns_pct, 2),
        "day_change": day_change,
        "day_change_pct": day_change_pct,
        "asset_allocation": asset_allocation,
        "sector_exposure": sector_exposure,
        "risk_score": risk_score,
        "risk_label": risk_label,
        "holdings_count": len(holdings),
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "heatmap_data": heatmap_data[:40],
        "performance_trend": trend,
        # ── Product Intelligence ──
        "health_score": compute_health_score(holdings, total_invested, current_value),
        "risk_analysis": compute_risk_analysis(holdings, current_value),
        "recommendations": generate_recommendations(holdings, current_value, total_invested),
    }

# ==================== NAV & DEEP ANALYTICS ROUTES ====================

@api_router.post("/nav/refresh")
async def refresh_nav(request: Request):
    """Manually refresh AMFI NAV cache and update all MF holdings."""
    user = await get_current_user(request)
    nav_map = await fetch_nav_data()
    holdings = await db.holdings.find({"user_id": user["user_id"], "asset_type": "mutual_fund"}, {"_id": 0}).to_list(2000)
    updated_count = 0
    for h in holdings:
        isin = (h.get("ticker") or "").upper().strip()
        name = h.get("name", "")
        nav_entry = None
        if isin and isin in nav_map:
            nav_entry = nav_map[isin]
        elif name:
            nav_entry = await lookup_nav(name=name)
        if nav_entry:
            await db.holdings.update_one(
                {"holding_id": h["holding_id"]},
                {"$set": {"current_price": nav_entry["nav"], "nav_date": nav_entry["date"], "nav_source": "AMFI"}}
            )
            updated_count += 1
    return {"updated": updated_count, "total_mf": len(holdings), "nav_entries": len(nav_map)}


@api_router.get("/portfolio/fund-performance")
async def get_fund_performance(request: Request, portfolio_id: str = ""):
    """Get MF benchmark ratings, performance distribution, and category overlap."""
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)

    if not holdings:
        return {"fund_ratings": [], "performance_distribution": {}, "category_overlap": [], "summary": {}}

    # Get the AMFI NAV cache for scheme code matching
    nav_cache = await fetch_nav_data()

    # Compute benchmark ratings using mfapi.in historical data
    result = await compute_benchmark_ratings(holdings, nav_cache)
    return result


@api_router.get("/portfolio/deep-analytics")
async def get_deep_analytics(request: Request, portfolio_id: str = ""):
    """Advanced analytics: overexposure, fund overlap, performance cards."""
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)

    if not holdings:
        return {"overexposure": {}, "overlap_matrix": [], "performance_cards": []}

    total_value = sum(h["quantity"] * h["current_price"] for h in holdings)
    if total_value == 0:
        return {"overexposure": {}, "overlap_matrix": [], "performance_cards": []}

    # ── 1. Overexposure Analysis ──
    # Fund house / AMC concentration
    fund_house_map = {}
    sector_concentration = {}
    asset_type_values = {}

    for h in holdings:
        val = h["quantity"] * h["current_price"]
        name = h.get("name", "")
        sector = h.get("sector", "Other")
        asset_type = h.get("asset_type", "other")

        # Extract fund house from mutual fund name
        if asset_type == "mutual_fund":
            fund_house = _extract_fund_house(name)
            fund_house_map.setdefault(fund_house, {"value": 0, "count": 0, "funds": []})
            fund_house_map[fund_house]["value"] += val
            fund_house_map[fund_house]["count"] += 1
            fund_house_map[fund_house]["funds"].append(name[:50])

        sector_concentration.setdefault(sector, {"value": 0, "count": 0, "holdings": []})
        sector_concentration[sector]["value"] += val
        sector_concentration[sector]["count"] += 1
        sector_concentration[sector]["holdings"].append(name[:40])

        asset_type_values[asset_type] = asset_type_values.get(asset_type, 0) + val

    # Build overexposure data
    fund_house_data = []
    for fh, data in sorted(fund_house_map.items(), key=lambda x: x[1]["value"], reverse=True):
        pct = (data["value"] / total_value * 100) if total_value > 0 else 0
        fund_house_data.append({
            "name": fh,
            "value": round(data["value"], 2),
            "pct": round(pct, 1),
            "count": data["count"],
            "funds": data["funds"][:5],
            "risk_level": "high" if pct > 40 else "medium" if pct > 25 else "low"
        })

    sector_data = []
    for sec, data in sorted(sector_concentration.items(), key=lambda x: x[1]["value"], reverse=True):
        pct = (data["value"] / total_value * 100) if total_value > 0 else 0
        sector_data.append({
            "name": sec,
            "value": round(data["value"], 2),
            "pct": round(pct, 1),
            "count": data["count"],
            "holdings": data["holdings"][:5],
            "risk_level": "high" if pct > 40 else "medium" if pct > 25 else "low"
        })

    # ── 2. Fund Overlap Matrix ──
    mf_holdings = [h for h in holdings if h.get("asset_type") == "mutual_fund"]
    overlap_matrix = []

    if len(mf_holdings) >= 2:
        # Group MFs by category/sector for overlap
        for i in range(len(mf_holdings)):
            for j in range(i + 1, len(mf_holdings)):
                f_a = mf_holdings[i]
                f_b = mf_holdings[j]
                overlap = _compute_fund_overlap(f_a, f_b)
                if overlap["overlap_pct"] > 0:
                    overlap_matrix.append(overlap)

        overlap_matrix.sort(key=lambda x: x["overlap_pct"], reverse=True)
        overlap_matrix = overlap_matrix[:15]  # Top 15 overlaps

    # ── 3. Performance Cards ──
    performance_cards = []
    for h in holdings:
        inv = h["quantity"] * h["buy_price"]
        cur = h["quantity"] * h["current_price"]
        abs_return = cur - inv
        pct_return = ((cur - inv) / inv * 100) if inv > 0 else 0
        weight = (cur / total_value * 100) if total_value > 0 else 0

        # Estimate CAGR if buy_date available
        cagr = None
        if h.get("buy_date") and inv > 0 and cur > 0:
            try:
                from dateutil.parser import parse as parse_date
                buy_dt = parse_date(h["buy_date"])
                now_dt = datetime.now(timezone.utc)
                years = max((now_dt - buy_dt.replace(tzinfo=timezone.utc)).days / 365.25, 0.1)
                cagr = round(((cur / inv) ** (1 / years) - 1) * 100, 1)
            except Exception:
                pass

        performance_cards.append({
            "name": h["name"][:50],
            "ticker": h.get("ticker", ""),
            "asset_type": h.get("asset_type", "other"),
            "sector": h.get("sector", "Other"),
            "quantity": h["quantity"],
            "buy_price": round(h["buy_price"], 2),
            "current_price": round(h["current_price"], 2),
            "invested": round(inv, 2),
            "current_value": round(cur, 2),
            "abs_return": round(abs_return, 2),
            "pct_return": round(pct_return, 1),
            "weight": round(weight, 1),
            "cagr": cagr,
            "nav_source": h.get("nav_source", ""),
            "nav_date": h.get("nav_date", ""),
        })

    performance_cards.sort(key=lambda x: x["pct_return"], reverse=True)

    return {
        "overexposure": {
            "fund_house": fund_house_data,
            "sector": sector_data[:15],
            "total_value": round(total_value, 2),
        },
        "overlap_matrix": overlap_matrix,
        "performance_cards": performance_cards,
    }


def _extract_fund_house(fund_name: str) -> str:
    """Extract AMC/fund house name from a mutual fund name."""
    known_houses = [
        "HDFC", "ICICI Prudential", "ICICI", "SBI", "Axis", "Kotak",
        "Aditya Birla Sun Life", "Aditya Birla", "Nippon India", "Nippon",
        "UTI", "DSP", "Mirae Asset", "Mirae", "Tata", "Canara Robeco",
        "HSBC", "Franklin Templeton", "Franklin", "Motilal Oswal", "Motilal",
        "Parag Parikh", "PPFAS", "Quant", "Bandhan", "Edelweiss",
        "Invesco", "Sundaram", "PGIM", "Baroda BNP", "Baroda",
        "JM Financial", "JM", "WhiteOak", "Navi", "Groww", "ITI",
        "360 ONE", "Bank of India", "BOI", "LIC", "Mahindra Manulife",
    ]
    name_lower = fund_name.lower()
    for house in known_houses:
        if house.lower() in name_lower:
            return house
    # Fallback: first word(s) before common keywords
    for kw in ["mutual fund", "fund", "flexi", "large", "mid", "small", "multi", "balanced", "liquid", "overnight", "debt", "index"]:
        idx = name_lower.find(kw)
        if idx > 2:
            return fund_name[:idx].strip().rstrip("-").strip()
    return fund_name.split(" ")[0] if fund_name else "Unknown"


def _compute_fund_overlap(fund_a: dict, fund_b: dict) -> dict:
    """Compute overlap between two mutual funds based on sector and category similarity."""
    name_a = fund_a.get("name", "")
    name_b = fund_b.get("name", "")
    sector_a = fund_a.get("sector", "Other").lower()
    sector_b = fund_b.get("sector", "Other").lower()

    overlap_score = 0
    reasons = []

    # Same sector = high overlap
    if sector_a == sector_b and sector_a != "other":
        overlap_score += 50
        reasons.append(f"Same category: {fund_a.get('sector', 'Other')}")

    # Extract category keywords
    categories = ["large cap", "mid cap", "small cap", "flexi cap", "multi cap",
                   "balanced", "hybrid", "debt", "liquid", "elss", "index",
                   "nifty", "sensex", "banking", "it", "pharma", "infrastructure"]

    cats_a = set(c for c in categories if c in name_a.lower())
    cats_b = set(c for c in categories if c in name_b.lower())

    shared_cats = cats_a & cats_b
    if shared_cats:
        overlap_score += min(len(shared_cats) * 25, 40)
        reasons.append(f"Shared mandate: {', '.join(shared_cats)}")

    # Same fund house = minor overlap
    house_a = _extract_fund_house(name_a)
    house_b = _extract_fund_house(name_b)
    if house_a == house_b:
        overlap_score += 10
        reasons.append(f"Same AMC: {house_a}")

    overlap_score = min(overlap_score, 95)

    return {
        "fund_a": name_a[:50],
        "fund_b": name_b[:50],
        "overlap_pct": overlap_score,
        "reasons": reasons,
        "sector_a": fund_a.get("sector", "Other"),
        "sector_b": fund_b.get("sector", "Other"),
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
async def send_chat(request: Request, msg: ChatMessageInput):
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
    
    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    if not holdings:
        return {"insights": [], "message": "Add holdings to generate insights"}
    
    total_inv = sum(h["quantity"] * h["buy_price"] for h in holdings)
    total_cur = sum(h["quantity"] * h["current_price"] for h in holdings)
    
    # Build portfolio summary for AI
    asset_map = {}
    sector_map = {}
    mf_names = []
    for h in holdings:
        cur = h["quantity"] * h["current_price"]
        at = h.get("asset_type", "other")
        asset_map[at] = asset_map.get(at, 0) + cur
        sec = h.get("sector", "Other")
        sector_map[sec] = sector_map.get(sec, 0) + cur
        if at == "mutual_fund":
            mf_names.append(h["name"])
    
    portfolio_text = f"Portfolio: ₹{total_inv:,.0f} invested, ₹{total_cur:,.0f} current ({((total_cur-total_inv)/total_inv*100) if total_inv > 0 else 0:.1f}% returns).\n"
    portfolio_text += f"Asset split: {', '.join(f'{k}={v/total_cur*100:.1f}%' for k,v in asset_map.items() if total_cur > 0)}\n"
    portfolio_text += f"Sectors: {', '.join(f'{k}={v/total_cur*100:.1f}%' for k,v in list(sector_map.items())[:10] if total_cur > 0)}\n"
    portfolio_text += f"Holdings ({len(holdings)}):\n"
    for h in holdings[:60]:
        ret_pct = ((h["current_price"] - h["buy_price"]) / h["buy_price"] * 100) if h["buy_price"] > 0 else 0
        portfolio_text += f"- {h['name']} ({h['asset_type']}, {h.get('sector','N/A')}): qty={h['quantity']}, ₹{h['buy_price']}→₹{h['current_price']} ({ret_pct:.1f}%)\n"
    
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"insights_{user_id}_{uuid.uuid4().hex[:6]}",
            system_message="""You are an expert Indian financial advisor. Analyze the portfolio and return a comprehensive JSON analysis.

Return ONLY valid JSON with this exact structure:
{
  "insights": [
    {"title":"...", "description":"2-3 sentences", "type":"warning|opportunity|info|action", "impact":"high|medium|low", "effort":"high|medium|low", "category":"risk|allocation|cost|redundancy|opportunity", "current_value":"e.g. 18%", "target_value":"e.g. 10%", "progress": 30}
  ],
  "problem_distribution": [
    {"name":"High Risk", "value": 35, "color":"#EF4444"},
    {"name":"Allocation Issues", "value": 25, "color":"#F59E0B"},
    {"name":"Cost Inefficiency", "value": 20, "color":"#3B82F6"},
    {"name":"Redundancy", "value": 20, "color":"#10B981"}
  ],
  "before_after": {
    "before": {"return_pct": 6.5, "risk_label":"High", "risk_score": 75, "expense_ratio": 1.8},
    "after": {"return_pct": 8.2, "risk_label":"Moderate", "risk_score": 45, "expense_ratio": 0.5}
  },
  "action_funnel": [
    {"step":1, "title":"Remove High Risk Stocks", "status":"critical", "detail":"Sell Vodafone, penny stocks"},
    {"step":2, "title":"Shift to Direct Plans", "status":"important", "detail":"Switch 5 regular plans to direct"},
    {"step":3, "title":"Consolidate Overlapping Funds", "status":"moderate", "detail":"Merge 3 similar large-cap funds"},
    {"step":4, "title":"Rebalance Asset Allocation", "status":"recommended", "detail":"Increase debt to 15%, reduce equity"}
  ],
  "overlap_pairs": [
    {"fund_a":"Fund A Name", "fund_b":"Fund B Name", "overlap_pct": 80},
    {"fund_a":"Fund C Name", "fund_b":"Fund D Name", "overlap_pct": 65}
  ],
  "cost_leakage": {"annual_loss": 32000, "total_invested": 500000, "loss_pct": 1.2, "detail":"Regular plans vs Direct plans"},
  "risk_gauge": {"current": 75, "target": 45, "current_label":"High", "target_label":"Moderate"}
}

Rules:
- Provide 6-8 insights covering risk, allocation, cost, redundancy, opportunities
- problem_distribution percentages must sum to 100
- before_after should show realistic improvements
- overlap_pairs: identify mutual funds with similar mandates (large cap overlap etc)
- cost_leakage: estimate commission drag from regular plans
- Be specific with fund names and numbers from the portfolio
- All values must be realistic and based on the actual portfolio data"""
        )
        chat.with_model("openai", "gpt-5.2")
        
        user_message = UserMessage(text=f"Analyze:\n{portfolio_text}")
        response = await chat.send_message(user_message)
        
        analysis = _parse_json_response_obj(response)
        
    except Exception as e:
        logger.error(f"Insights generation error: {e}")
        analysis = {
            "insights": [{"title": "Analysis Error", "description": "Could not generate insights. Try again.", "type": "info", "impact": "medium", "effort": "low", "category": "info", "current_value": "", "target_value": "", "progress": 0}],
            "problem_distribution": [],
            "before_after": {"before": {"return_pct": 0, "risk_label": "N/A", "risk_score": 0, "expense_ratio": 0}, "after": {"return_pct": 0, "risk_label": "N/A", "risk_score": 0, "expense_ratio": 0}},
            "action_funnel": [],
            "overlap_pairs": [],
            "cost_leakage": {"annual_loss": 0, "total_invested": 0, "loss_pct": 0, "detail": ""},
            "risk_gauge": {"current": 0, "target": 0, "current_label": "N/A", "target_label": "N/A"}
        }
    
    # Save insights
    await db.ai_insights.delete_many({"user_id": user_id})
    saved_insights = []
    for insight in analysis.get("insights", []):
        doc = {
            "insight_id": f"ins_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "title": insight.get("title", ""),
            "description": insight.get("description", ""),
            "type": insight.get("type", "info"),
            "priority": insight.get("impact", "medium"),
            "impact": insight.get("impact", "medium"),
            "effort": insight.get("effort", "medium"),
            "category": insight.get("category", "info"),
            "current_value": insight.get("current_value", ""),
            "target_value": insight.get("target_value", ""),
            "progress": insight.get("progress", 0),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.ai_insights.insert_one(doc)
        saved_insights.append({k: v for k, v in doc.items() if k != "_id"})
    
    # Save full analysis
    analysis["insights"] = saved_insights
    await db.portfolio_analysis.delete_many({"user_id": user_id})
    await db.portfolio_analysis.insert_one({
        "user_id": user_id,
        "analysis": analysis,
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    return analysis

@api_router.get("/insights/analysis")
async def get_analysis(request: Request):
    """Get the full portfolio analysis (insights + visualizations data)."""
    user = await get_current_user(request)
    doc = await db.portfolio_analysis.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if doc and "analysis" in doc:
        return doc["analysis"]
    return None

# ==================== ROOT ====================

@api_router.get("/")
async def root():
    return {"message": "nivesh.ai API"}

# Include router and middleware
app.include_router(api_router)

app.add_middleware(RateLimitMiddleware)

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
