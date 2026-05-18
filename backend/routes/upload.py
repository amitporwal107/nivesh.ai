"""File upload routes: CAS PDF, CSV, Excel, CAS Connect SDK."""
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from datetime import datetime, timezone
from typing import Dict
import uuid
import asyncio
import logging

from deps import db, get_current_user
from helpers.parsing import (
    parse_csv_holdings, parse_excel_holdings, parse_cas_pdf, save_holdings
)
from helpers.upload_validation import validate_upload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/portfolio/upload")
async def upload_portfolio(request: Request, file: UploadFile = File(...)):
    """Upload portfolio file - supports CSV, Excel (.xlsx), and CAS PDF."""
    user = await get_current_user(request)
    filename = (file.filename or "").lower()
    user_id = user["user_id"]

    content = file.file.read()
    # FR-UPLOAD-001/005: enforce size + magic-byte sniff before any parser
    # touches the bytes. Raises 413/415 directly.
    validate_upload(content, filename)

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

        logger.info("CAS PDF received: %s bytes, task %s", len(content), task_id)
        try:
            from services import audit as _audit
            await _audit.record(
                user_id=user_id, action="cas_upload", resource=task_id,
                ip=request.client.host if request.client else "",
                ua=request.headers.get("user-agent", ""),
                details={"size_bytes": len(content), "filename": filename[:100]},
            )
        except Exception:  # noqa: BLE001
            pass
        asyncio.create_task(_process_cas_background(content, user_id, task_id))
        return {
            "task_id": task_id,
            "status": "processing",
            "message": "CAS PDF is being processed by AI. This may take 1-2 minutes.",
            "count": 0,
            "holdings": []
        }

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

    holdings_added = await save_holdings(user_id, parsed, file_type)
    return {
        "message": f"{len(holdings_added)} holdings imported from {file_type}",
        "count": len(holdings_added),
        "holdings": holdings_added
    }


@router.post("/portfolio/upload-raw")
async def upload_portfolio_raw(request: Request):
    """Raw upload endpoint for large files."""
    user = await get_current_user(request)
    filename = request.headers.get("X-Filename", "upload.pdf").lower()
    portfolio_id = request.headers.get("X-Portfolio-Id", "")
    pdf_password = request.headers.get("X-Password", "")
    user_id = user["user_id"]

    # Stream with a hard byte budget so a malicious 10GB body doesn't OOM us.
    from helpers.upload_validation import MAX_UPLOAD_BYTES
    body_chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (>{MAX_UPLOAD_BYTES} bytes).",
            )
        body_chunks.append(chunk)
    content = b"".join(body_chunks)

    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    # Magic-byte + extension validation (size already capped above)
    validate_upload(content, filename)

    logger.info("Raw upload received: %s bytes, filename: %s", len(content), filename)

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
    holdings_added = await save_holdings(user_id, parsed, file_type, portfolio_id=portfolio_id)
    return {"message": f"{len(holdings_added)} holdings imported from {file_type}", "count": len(holdings_added), "holdings": holdings_added}


@router.get("/portfolio/upload-status/{task_id}")
async def get_upload_status(request: Request, task_id: str):
    """Poll the status of a CAS PDF upload task."""
    user = await get_current_user(request)
    task = await db.upload_tasks.find_one(
        {"task_id": task_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not task:
        raise HTTPException(status_code=404, detail="Upload task not found")
    return task


@router.get("/portfolio/upload-latest-task")
async def get_latest_upload_task(request: Request):
    """Get the most recent upload task for the user."""
    user = await get_current_user(request)
    task = await db.upload_tasks.find_one(
        {"user_id": user["user_id"]},
        {"_id": 0},
        sort=[("created_at", -1)]
    )
    if not task:
        raise HTTPException(status_code=404, detail="No upload tasks found")
    return task


@router.post("/portfolio/upload-csv")
async def upload_csv_legacy(request: Request, file: UploadFile = File(...)):
    return await upload_portfolio(request, file)


# ── CAS Parser: Portfolio Connect SDK integration ──

@router.post("/casparser/access-token")
async def casparser_access_token(request: Request):
    """Mint a short-lived CAS Parser access token for the frontend widget."""
    user = await get_current_user(request)
    from services.cas_api_client import generate_access_token, is_configured
    if not is_configured():
        raise HTTPException(status_code=503, detail="CAS Parser not configured")
    token_payload = generate_access_token(expiry_minutes=60)
    if not token_payload:
        raise HTTPException(status_code=502, detail="Failed to mint CAS Parser access token")
    logger.info("Minted CAS Parser access token for user=%s", user['user_id'])
    return token_payload


@router.post("/portfolio/import-connect")
async def portfolio_import_from_connect(request: Request):
    """Ingest parsed portfolio from the CAS Connect widget."""
    user = await get_current_user(request)
    body = await request.json()
    parsed_data = body.get("data") if isinstance(body, dict) and "data" in body else body
    if not isinstance(parsed_data, dict):
        raise HTTPException(status_code=400, detail="Invalid payload: expected parsed CAS JSON")

    from services.cas_api_client import map_api_response_to_holdings
    holdings = map_api_response_to_holdings(parsed_data)
    if not holdings:
        raise HTTPException(status_code=422, detail="No holdings found in parsed data")

    try:
        from services.masterdata import validate_and_enrich_holdings
        holdings = validate_and_enrich_holdings(holdings)
    except Exception as e:
        logger.info("Masterdata enrichment skipped: %s", e)

    saved = await save_holdings(user["user_id"], holdings, "CAS Connect")

    # Extract transactions + detect SIP patterns
    sip_summary: Dict[str, int] = {}
    try:
        from services import cas_transactions as _ct
        sip_summary = await _ct.persist_transactions_and_sips(
            db, user["user_id"], parsed_data, source="CAS Connect"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Transaction extraction skipped: %s", e)

    cas_type = (parsed_data.get("meta") or {}).get("cas_type", "")
    investor_name = (parsed_data.get("investor") or {}).get("name", "")
    logger.info(
        f"CAS Connect: saved {len(saved)} holdings for user={user['user_id']} "
        f"cas_type={cas_type} investor={investor_name} "
        f"txns={sip_summary.get('transactions', 0)} sips={sip_summary.get('sips', 0)}"
    )
    return {
        "message": f"{len(saved)} holdings imported via Portfolio Connect",
        "count": len(saved),
        "holdings": saved,
        "cas_type": cas_type,
        "investor": investor_name,
        "transactions": sip_summary.get("transactions", 0),
        "sips_detected": sip_summary.get("sips", 0),
    }


async def _process_cas_background(content: bytes, user_id: str, task_id: str, portfolio_id: str = "", password: str = ""):
    """Background task for CAS PDF processing."""
    try:
        logger.info("Background CAS task %s: password=%s, size=%s", task_id, 'provided' if password else 'none', len(content))
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
        await save_holdings(user_id, parsed, "CAS PDF", task_id, portfolio_id)
        # Re-infer persona now that holdings have changed
        try:
            from services.persona_engine import refresh_persona
            await refresh_persona(user_id, db)
        except Exception as pe:
            logger.warning("Persona refresh failed (non-fatal): %s", pe)
    except HTTPException as he:
        error_msg = he.detail if hasattr(he, 'detail') else str(he)
        logger.error("Background CAS processing HTTPException: %s", error_msg)
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "error", "message": error_msg, "count": 0, "holdings": []}}
        )
    except Exception as e:
        logger.error("Background CAS processing error: %s", e)
        error_msg = str(e)
        if "password" in error_msg.lower() or "decrypt" in error_msg.lower() or "encrypted" in error_msg.lower():
            error_msg = "PDF is password-protected. Please provide the correct password."
        elif "could not read" in error_msg.lower():
            error_msg = "Could not read PDF. The file may be corrupted or in an unsupported format."
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "error", "message": error_msg, "count": 0, "holdings": []}}
        )
