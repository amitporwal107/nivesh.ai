"""File upload routes: CAS PDF, CSV, Excel, CAS Connect SDK.

Portfolio import with a preview before anything is saved (PRD §8.2, §14.3):

    POST /api/portfolio/upload/preview               multipart `file` (.csv / .xlsx / .xls, ≤ 5 MB, ≤ 5,000 rows)
        → {preview_id, created_at, expires_at, file, account_ref, currency, rows, counts, effects, checks, limits,
           nothing_saved: true}. Each row: row_no, name, symbol, isin (+ isin_source), exchange, quantity, avg_cost,
           current_price, instrument_type, account_ref, currency, status ready | review | rejected, include (the
           default choice) and flags [{code, level, text}]. Duplicates, mismatched symbols and unsupported instruments
           are flagged, never merged. Nothing is written to the holdings.
    POST /api/portfolio/upload/preview/{preview_id}/commit   {rows?: [row_no, …]} (default: the ready rows)
        → the /portfolio/upload answer plus committed_rows / left_out_rows. 404 not yours or unknown, 410 expired,
          409 already committed, 422 invalid_rows (a rejected or unknown row) / nothing_to_import.

File safety, before any parser runs: the preview size limit, the extension allow-list and magic bytes
(helpers.upload_validation), the malware scan, and for workbooks no macros (vbaProject / _VBA_PROJECT), no ActiveX
and no zip bomb (members and expanded size capped). Parsing is openpyxl read-only with cached values (formulas are
never evaluated) or xlrd; text that starts like a formula is stored without its leading formula character and
flagged. `csv_safe_cell` is the neutraliser exports should apply to text cells.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import io
import re
import uuid
import asyncio
import logging
import zipfile

from deps import db, get_current_user
from services import dashboard_cache
from core.idempotency import IdempotencyState, check_idempotency, store_idempotency_result
from helpers.upload_validation import validate_upload_async
from helpers.parsing import save_holdings
from helpers.statement_exports import ParsedStatement, parse_csv_statement, parse_excel_statement
from helpers import holdings_reconcile

# Deprecation message returned to clients that still POST CAS PDFs to
# the legacy direct-upload endpoints. CAS parsing now lives exclusively
# in the Connect SDK widget — see `CasUploadButton.jsx` for the client
# flow and `/api/casparser/access-token` + `/api/portfolio/import-connect`
# for the backend pair that backs it.
_CAS_PDF_DEPRECATED = (
    "Direct CAS PDF upload to this endpoint is no longer supported. "
    "Use the CAS Connect SDK widget instead — call "
    "POST /api/casparser/access-token, open the @cas-parser/connect "
    "widget with the returned access token, then POST the widget's "
    "parsed JSON to /api/portfolio/import-connect."
)
from helpers.upload_validation import validate_upload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post(
    "/portfolio/upload",
    tags=["Portfolio Upload"],
    summary="Upload portfolio file (CAS PDF / CSV / Excel)",
    responses={
        200: {
            "description": (
                "For CSV/Excel: holdings parsed synchronously and returned immediately. "
                "For PDF: a `task_id` is returned and parsing continues in the background; "
                "poll `/portfolio/upload-status/{task_id}` until `status == \"completed\"`."
            ),
            "content": {
                "application/json": {
                    "examples": {
                        "pdf_accepted": {
                            "summary": "CAS PDF accepted for background parsing",
                            "value": {
                                "task_id": "task_a1b2c3d4e5f6",
                                "status": "processing",
                                "message": "CAS PDF is being processed by AI. This may take 1-2 minutes.",
                                "count": 0,
                                "holdings": [],
                            },
                        },
                        "csv_done": {
                            "summary": "CSV / Excel parsed synchronously",
                            "value": {
                                "message": "3 holdings imported from CSV",
                                "count": 3,
                                "holdings": [{"ticker": "INE040A01034", "quantity": 10}],
                                "broker": "zerodha",
                                "broker_name": "Zerodha",
                                "format": "zerodha",
                            },
                        },
                    }
                }
            },
        },
        400: {"description": "Unsupported format, empty or unreadable file, or no holdings table recognised in it."},
        413: {"description": "File exceeds the maximum upload size."},
        415: {"description": "File magic-byte check failed (validate_upload)."},
    },
)
async def upload_portfolio(request: Request, file: UploadFile = File(...)):
    """Upload a portfolio file. Accepts **CSV**, **Excel (.xlsx / .xls)** and
    **CAS PDF** (NSDL / CDSL / CAMS / KFintech).

    **CSV / Excel** are parsed synchronously — holdings are returned in the
    response body.

    **CAS PDF** uploads kick off background parsing via the tiered chain
    in `helpers.parsing.parse_cas_pdf_with_data`:

    | Tier | Parser | When it runs | Latency | Cost |
    |------|--------|--------------|---------|------|
    | 1 | **GPT-5 Vision** (default) | Always tried first if `OPENAI_API_KEY` is set | 35-70 s | ~$0.30 / parse |
    | 2 | casparser library | Fallback for text-based PDFs | < 1 s | free |
    | 3 | Docling local OCR | Last resort if both above fail | 30-60 s | free |

    For PDFs the response contains a `task_id`; poll
    `/portfolio/upload-status/{task_id}` until `status == "completed"`.
    The completed payload carries the holdings list plus the
    `parser_source` that produced them (`openai_gpt5` / `casparser_lib` /
    `docling`).

    **Password-protected CAS PDFs**: use the
    `/portfolio/upload-raw` variant with the `X-Password` header (PAN in
    UPPERCASE, e.g. `ABCDE1234F`).
    """
    user = await get_current_user(request)
    filename = (file.filename or "").lower()
    user_id = user["user_id"]

    content = file.file.read()
    # FR-UPLOAD-001/005/007: size + magic-byte + malware scan before any parser.
    await validate_upload_async(content, filename)

    if filename.endswith(".pdf"):
        raise HTTPException(status_code=410, detail=_CAS_PDF_DEPRECATED)

    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        statement = parse_excel_statement(content, filename)
        file_type = "Excel"
    elif filename.endswith(".csv"):
        statement = parse_csv_statement(content, filename)
        file_type = "CSV"
    else:
        try:
            statement = parse_csv_statement(content, filename)
            file_type = "CSV"
        except Exception:
            raise HTTPException(status_code=400, detail="Unsupported file format. Please upload CSV, Excel (.xlsx), or CAS PDF.")

    parsed = statement.holdings
    # What the file was read as: `broker` is the slug stored on the rows (None for
    # the generic template or a table whose broker is not identified).
    detected = {"broker": statement.broker, "broker_name": statement.broker_name, "format": statement.layout}
    if not parsed:
        return {"message": "No holdings found in the uploaded file", "count": 0, "holdings": [], **detected}

    holdings_added = await save_holdings(user_id, parsed, file_type)
    await dashboard_cache.invalidate(user_id)
    return {
        "message": f"{len(holdings_added)} holdings imported from {file_type}",
        "count": len(holdings_added),
        "holdings": holdings_added,
        **detected,
    }


@router.post(
    "/portfolio/upload-raw",
    tags=["Portfolio Upload"],
    summary="Raw stream upload (large files, password-protected CAS PDFs)",
    responses={
        200: {
            "description": (
                "Same response shape as `/portfolio/upload` — async `task_id` for "
                "PDFs, synchronous holdings list for CSV/Excel."
            )
        },
        400: {"description": "Empty body, unsupported format, unreadable file, or no holdings table recognised in it."},
        413: {"description": "Body exceeds the maximum upload size."},
    },
)
async def upload_portfolio_raw(request: Request):
    """Raw `application/octet-stream` upload endpoint. Use this when:

    - The file is too large for the multipart form path.
    - The CAS PDF needs a **password** (use the `X-Password` header — PAN
      in UPPERCASE, e.g. `ABCDE1234F`).
    - You want to attach the upload to a specific portfolio (use the
      `X-Portfolio-Id` header).

    **Required headers**

    | Header | Required | Notes |
    |--------|----------|-------|
    | `X-Filename` | Yes | e.g. `cas.pdf`, `portfolio.csv` — drives parser selection |
    | `X-Password` | Conditional | CAS PDF password (PAN uppercase). Empty for unprotected files. |
    | `X-Portfolio-Id` | Optional | Save holdings into this portfolio; defaults to the user's primary portfolio |

    Parsing chain and async response semantics are identical to
    `/portfolio/upload` — see that endpoint's description for the tier
    table (GPT-5 Vision → casparser → Docling).
    """
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

    # Magic-byte + extension + malware scan (size already capped above)
    await validate_upload_async(content, filename)

    logger.info("Raw upload received: %s bytes, filename: %s", len(content), filename)

    if filename.endswith(".pdf"):
        raise HTTPException(status_code=410, detail=_CAS_PDF_DEPRECATED)

    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        statement = parse_excel_statement(content, filename)
        file_type = "Excel"
    elif filename.endswith(".csv"):
        statement = parse_csv_statement(content, filename)
        file_type = "CSV"
    else:
        raise HTTPException(status_code=400, detail="Unsupported format")

    parsed = statement.holdings
    detected = {"broker": statement.broker, "broker_name": statement.broker_name, "format": statement.layout}
    if not parsed:
        return {"message": "No holdings found", "count": 0, "holdings": [], **detected}
    holdings_added = await save_holdings(user_id, parsed, file_type, portfolio_id=portfolio_id)
    await dashboard_cache.invalidate(user_id)
    return {"message": f"{len(holdings_added)} holdings imported from {file_type}", "count": len(holdings_added), "holdings": holdings_added, **detected}


@router.get(
    "/portfolio/upload-status/{task_id}",
    tags=["Portfolio Upload"],
    summary="Poll the status of an async CAS PDF parse task",
    responses={
        200: {
            "description": "Current task state. `status` ∈ {`processing`, `completed`, `failed`}.",
            "content": {
                "application/json": {
                    "examples": {
                        "processing": {
                            "value": {
                                "task_id": "task_a1b2c3d4e5f6",
                                "status": "processing",
                                "message": "Parsing CAS PDF with AI...",
                                "count": 0,
                                "holdings": [],
                            }
                        },
                        "completed": {
                            "value": {
                                "task_id": "task_a1b2c3d4e5f6",
                                "status": "completed",
                                "message": "23 holdings imported from CAS PDF",
                                "count": 23,
                                "holdings": [
                                    {"ticker": "INE040A01034", "quantity": 50,
                                     "asset_type": "equity"}
                                ],
                                "parser_source": "openai_gpt5",
                            }
                        },
                        "failed": {
                            "value": {
                                "task_id": "task_a1b2c3d4e5f6",
                                "status": "failed",
                                "message": "Wrong CAS PDF password. Enter your PAN in UPPERCASE.",
                                "count": 0,
                                "holdings": [],
                            }
                        },
                    }
                }
            },
        },
        404: {"description": "No task with this ID belongs to the calling user."},
    },
)
async def get_upload_status(request: Request, task_id: str):
    """Poll the status of an async CAS PDF parse task started by
    `/portfolio/upload` or `/portfolio/upload-raw`.

    Typical PDF parsing takes 35-70 s when GPT-5 Vision is the active
    parser (`OPENAI_API_KEY` configured), under 1 s when the casparser-lib
    fallback handles a text-based PDF, or 30-60 s for the Docling
    fallback. Poll every ~2-5 s; stop when `status` leaves `processing`.
    """
    user = await get_current_user(request)
    task = await db.upload_tasks.find_one(
        {"task_id": task_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not task:
        raise HTTPException(status_code=404, detail="Upload task not found")
    return task


@router.get(
    "/portfolio/upload-latest-task",
    tags=["Portfolio Upload"],
    summary="Return the most recent CAS upload task for the caller",
    responses={
        200: {"description": "Same shape as `/portfolio/upload-status/{task_id}`."},
        404: {"description": "The caller has never uploaded a CAS PDF."},
    },
)
async def get_latest_upload_task(request: Request):
    """Return the most recent CAS upload task for the authenticated user
    (sorted by `created_at` descending). Useful for the frontend to
    resume polling after a page reload without persisting the task_id
    client-side.
    """
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


# ── Import with a preview (PRD §8.2, §14.3) ─────────────────────────────────

PREVIEWS = "holdings_import_previews"
PREVIEW_EXTS = (".csv", ".xlsx", ".xls")
PREVIEW_MAX_BYTES = 5 * 1024 * 1024          # a holdings file is kilobytes; 5 MB is generous
PREVIEW_MAX_ROWS = 5000
PREVIEW_TTL = timedelta(minutes=30)
XLSX_MAX_MEMBERS = 2000
XLSX_MAX_EXPANDED = 50 * 1024 * 1024         # a workbook that inflates past this is refused (zip bomb)
_ACTIVE_PARTS = ("vbaproject.bin", "xl/activex/", "xl/embeddings/", "customui/")
_OLE_VBA_MARKER = "_VBA_PROJECT".encode("utf-16-le")       # the VBA storage's directory entry in an OLE2 workbook
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_ISIN_RE = re.compile(r"^IN[A-Z0-9]{9}\d$")
# Futures and options contracts (NIFTY26OCTFUT, RELIANCE26OCT1400CE): the holdings store has no derivative type.
_DERIVATIVE_RE = re.compile(r"^[A-Z&-]*\d[A-Z0-9&.-]*(FUT|CE|PE)$")
_SUPPORTED_TYPES = {
    "equity": "equity", "stock": "equity", "stocks": "equity", "share": "equity", "shares": "equity", "equities": "equity",
    "mutual_fund": "mutual_fund", "mutual fund": "mutual_fund", "mutual funds": "mutual_fund", "mf": "mutual_fund",
    "fund": "mutual_fund", "etf": "etf", "bond": "bond", "bonds": "bond", "debt": "bond", "gold": "gold", "sgb": "sgb",
    "fd": "fd", "fixed deposit": "fd", "nps": "nps", "other": "other",
}
PREVIEW_CHECKS = (
    "File type checked by its content, not only its name (.csv, .xlsx or .xls).",
    f"At most {PREVIEW_MAX_BYTES // (1024 * 1024)} MB and {PREVIEW_MAX_ROWS:,} rows.",
    "Malware scan when the scanner is available.",
    "Workbooks with macros or ActiveX, and archives that expand too far, are refused.",
    "Formulas are never run: cached cell values are read, and text that starts like a formula is stored as plain text.",
    "Nothing is saved until you confirm.",
)

_previews_ready = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def csv_safe_cell(value: Optional[str]) -> Optional[str]:
    """A text cell made safe for a CSV / XLSX export: one that a spreadsheet would read as a formula (= + - @, tab,
    carriage return) gets a leading apostrophe. Exports should pass every text cell through this."""
    if value is None or not isinstance(value, str) or not value:
        return value
    return "'" + value if value.startswith(_FORMULA_START) else value


def _plain_text(value: Any) -> Tuple[str, bool]:
    """(the text without any leading formula characters, whether any were removed)."""
    text = str(value or "").strip()
    cleaned = text.lstrip("".join(_FORMULA_START)).strip()
    return cleaned, cleaned != text


def isin_check_digit_ok(isin: str) -> bool:
    """ISO 6166: letters → numbers (A = 10 … Z = 35), then Luhn over the digits."""
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", isin or ""):
        return False
    digits = "".join(str(int(c, 36)) for c in isin[:-1])
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10 == int(isin[-1])


def check_active_content(content: bytes, ext: str) -> None:
    """Refuse a workbook that carries macros or ActiveX, or that inflates past the limits, before it is parsed."""
    if ext == ".xlsx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                infos = z.infolist()
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="The .xlsx file could not be opened: it is damaged or not a workbook.")
        if len(infos) > XLSX_MAX_MEMBERS or sum(i.file_size for i in infos) > XLSX_MAX_EXPANDED:
            raise HTTPException(status_code=413, detail="The workbook expands to more than a holdings file can hold; it was not opened.")
        names = [i.filename.lower() for i in infos]
        if any(part in n for n in names for part in _ACTIVE_PARTS):
            raise HTTPException(status_code=415, detail="The workbook contains macros or other active content; save it as a plain .xlsx or .csv.")
    elif ext == ".xls":
        if _OLE_VBA_MARKER in content:
            raise HTTPException(status_code=415, detail="The workbook contains macros; save it as a plain .xlsx or .csv.")


def _existing_label(r: Dict[str, Any]) -> str:
    broker = (r.get("broker") or "").strip()
    if r.get("broker_account_id"):
        return f"your connected {broker.title() or 'broker'} account"
    if r.get("source") == holdings_reconcile.BROKER_EXPORT_SOURCE:
        return f"your earlier {broker.title() or 'broker'} file"
    if r.get("source") in holdings_reconcile.STATEMENT_SOURCES:
        return "a CAS statement"
    return "an earlier upload or manual entry"


def _flag(code: str, level: str, text: str) -> Dict[str, str]:
    return {"code": code, "level": level, "text": text}


def assess_rows(statement: ParsedStatement, existing: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Validate and flag every parsed row (pure; nothing is written). Returns (rows, effects). Each row keeps the
    holding dict save_holdings will store under `holding`."""
    index = holdings_reconcile._load_symbol_index()
    broker = statement.broker
    broker_name = statement.broker_name
    by_isin: Dict[str, List[Dict[str, Any]]] = {}
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for r in existing:
        isin = holdings_reconcile.resolve_isin(r)
        if isin:
            by_isin.setdefault(isin, []).append(r)
        sym = str(r.get("ticker") or "").strip().upper()
        if sym and not _ISIN_RE.match(sym):
            by_symbol.setdefault(sym, []).append(r)
    seen: Dict[str, int] = {}
    rows: List[Dict[str, Any]] = []
    for n, h in enumerate(statement.holdings, start=1):
        flags: List[Dict[str, str]] = []
        holding = dict(h)
        name, name_changed = _plain_text(h.get("name"))
        ticker = str(h.get("ticker") or "").strip().upper()
        if name_changed:
            holding["name"] = name
            flags.append(_flag("formula_text", "review",
                               "This text starts like a spreadsheet formula. It is stored as plain text, without the leading character."))
        file_isin = str(h.get("isin") or "").strip().upper() or (ticker if _ISIN_RE.match(ticker) else "")
        symbol = ticker if ticker and not _ISIN_RE.match(ticker) else None
        isin, isin_source = (file_isin, "file") if file_isin else ("", None)
        if file_isin and not isin_check_digit_ok(file_isin):
            flags.append(_flag("isin_check_failed", "review", f"The ISIN {file_isin} fails its check digit; check it against your statement."))
        if symbol and not isin and index.get(symbol):
            isin, isin_source = index[symbol], "nse_list"
        if symbol and file_isin and index.get(symbol) and index[symbol] != file_isin:
            flags.append(_flag("symbol_isin_mismatch", "review",
                               f"The symbol {symbol} belongs to ISIN {index[symbol]} on the NSE list, not {file_isin}."))
        if symbol and not file_isin and index and symbol not in index and not _DERIVATIVE_RE.match(symbol):
            flags.append(_flag("unknown_symbol", "review", f"{symbol} is not on the NSE list Nivesh holds; check the symbol."))
        if not symbol and not isin:
            flags.append(_flag("no_identifier", "review", "No symbol or ISIN: this holding can be matched by name only."))

        raw_type = str(h.get("asset_type") or "equity").strip().lower()
        itype = _SUPPORTED_TYPES.get(raw_type) or _SUPPORTED_TYPES.get(raw_type.replace("_", " "))
        if symbol and _DERIVATIVE_RE.match(symbol):
            flags.append(_flag("unsupported_instrument", "reject",
                               f"{symbol} is a futures or options contract; the holdings import takes delivery holdings only."))
        elif itype is None:
            flags.append(_flag("unsupported_instrument", "reject", f"“{raw_type}” is not an instrument type Nivesh imports."))
        else:
            holding["asset_type"] = itype
        qty = float(h.get("quantity") or 0)
        if not qty > 0:
            flags.append(_flag("no_quantity", "reject", "The quantity is zero or missing."))
        elif itype in ("equity", "etf") and not float(qty).is_integer():
            flags.append(_flag("fractional_shares", "review", f"{qty:g} is not a whole number of shares."))
        avg = float(h.get("buy_price") or 0)
        price = float(h.get("current_price") or 0)
        if not avg > 0:
            flags.append(_flag("no_average_cost", "review",
                               "No average cost in the file. If you include it, Nivesh records the file's price as the cost "
                               "(helpers.parsing.save_holdings), so this row would show no gain or loss."))
        if not price > 0:
            flags.append(_flag("no_price", "info", "No price in the file; the holding has no value until Nivesh prices it."))

        key = isin or (f"SYM:{symbol}" if symbol else f"NAME:{name.lower()}")
        if key in seen:
            flags.append(_flag("duplicate_in_file", "review",
                               f"Same instrument as row {seen[key]}. It is not merged: include it only if it is a separate lot."))
        else:
            seen[key] = n

        matches = (by_isin.get(isin, []) if isin else []) or (by_symbol.get(symbol, []) if symbol else [])
        if matches:
            same_live = [m for m in matches if m.get("broker_account_id") and broker and m.get("broker") == broker]
            same_export = [m for m in matches if m.get("source") == holdings_reconcile.BROKER_EXPORT_SOURCE and broker and m.get("broker") == broker]
            statement_rows = [m for m in matches if not m.get("broker_account_id") and m.get("source") in holdings_reconcile.STATEMENT_SOURCES]
            other = [m for m in matches if m not in same_live and m not in same_export and m not in statement_rows]
            if broker and same_live:
                flags.append(_flag("held_by_connected_account", "reject",
                                   f"Your connected {broker_name or broker} account already reports this holding; the file's row is left out."))
            elif broker and same_export:
                flags.append(_flag("replaces_earlier_export", "info", f"Replaces this holding from your earlier {broker_name or broker} file."))
            elif broker and statement_rows and not other:
                flags.append(_flag("replaces_statement_row", "info",
                                   "Replaces the CAS statement's copy of this holding (a broker's file wins over a statement)."))
            else:
                where = ", ".join(sorted({_existing_label(m) for m in matches}))
                flags.append(_flag("already_on_file", "review",
                                   f"Already on file from {where}. Importing adds a second row; nothing is merged."))

        levels = {f["level"] for f in flags}
        status = "rejected" if "reject" in levels else "review" if "review" in levels else "ready"
        rows.append({
            "row_no": n, "name": holding.get("name") or name, "symbol": symbol, "isin": isin or None,
            "isin_source": isin_source, "exchange": None, "quantity": qty, "avg_cost": avg if avg > 0 else None,
            "current_price": price if price > 0 else None, "instrument_type": itype if itype else raw_type,
            "account_ref": broker_name, "currency": "INR", "status": status, "include": status == "ready",
            "flags": flags, "holding": holding,
        })
    effects = {
        "broker": broker,
        "replaces_export_rows": sum(1 for r in existing if broker and r.get("source") == holdings_reconcile.BROKER_EXPORT_SOURCE
                                    and r.get("broker") == broker),
    }
    effects["note"] = (
        f"Confirming replaces every row of your earlier {broker_name or broker} file ({effects['replaces_export_rows']}) "
        "with the rows you include." if broker else
        "Rows you include are added to what is on file; nothing on file is replaced."
    )
    return rows, effects


def _public_row(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in r.items() if k != "holding"}


def _public_preview(doc: Dict[str, Any]) -> Dict[str, Any]:
    rows = [_public_row(r) for r in doc["rows"]]
    return {
        "preview_id": doc["_id"],
        "status": doc["status"],
        "created_at": doc["created_at"],
        "expires_at": doc["expires_at"],
        "file": doc["file"],
        "account_ref": doc["account_ref"],
        "currency": "INR",
        "currency_basis": "Indian broker exports and Indian ISINs are in rupees; the file has no currency column.",
        "rows": rows,
        "counts": {"rows": len(rows), **{s: sum(1 for r in rows if r["status"] == s) for s in ("ready", "review", "rejected")}},
        "effects": doc["effects"],
        "checks": list(PREVIEW_CHECKS),
        "limits": {"max_bytes": PREVIEW_MAX_BYTES, "max_rows": PREVIEW_MAX_ROWS,
                   "expires_minutes": int(PREVIEW_TTL.total_seconds() // 60)},
        "nothing_saved": doc["status"] == "open",
    }


async def _ensure_preview_indexes() -> None:
    global _previews_ready
    if _previews_ready:
        return
    try:
        await db[PREVIEWS].create_index("expires_at_dt", expireAfterSeconds=0)
        await db[PREVIEWS].create_index([("user_id", 1), ("created_at", -1)])
        _previews_ready = True
    except Exception as exc:  # noqa: BLE001 — expiry is also checked in code; a failed index is retried next call
        logger.warning("import preview: index creation failed: %r", exc)


@router.post("/portfolio/upload/preview", tags=["Portfolio Upload"],
             summary="Read and validate a holdings file; save nothing until it is confirmed")
async def preview_portfolio_upload(request: Request, file: UploadFile = File(...)):
    user = await get_current_user(request)
    uid = user["user_id"]
    filename = (file.filename or "").strip()
    content = await file.read()
    if len(content) > PREVIEW_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"The file is over {PREVIEW_MAX_BYTES // (1024 * 1024)} MB; a holdings file is much smaller.")
    ext, _ = await validate_upload_async(content, filename.lower(), allowed_exts=PREVIEW_EXTS)
    check_active_content(content, ext)
    statement = parse_csv_statement(content, filename) if ext == ".csv" else parse_excel_statement(content, filename)
    if len(statement.holdings) > PREVIEW_MAX_ROWS:
        raise HTTPException(status_code=413, detail=f"The file has more than {PREVIEW_MAX_ROWS:,} rows of holdings.")

    existing = await db.holdings.find(
        {"user_id": uid},
        {"_id": 0, "holding_id": 1, "name": 1, "ticker": 1, "isin": 1, "source": 1, "broker": 1, "broker_account_id": 1},
    ).to_list(5000)
    rows, effects = assess_rows(statement, existing)
    now = _utcnow()
    doc = {
        "_id": f"imp_{uuid.uuid4().hex}",
        "user_id": uid,
        "status": "open",
        "created_at": now.isoformat(),
        "expires_at": (now + PREVIEW_TTL).isoformat(),
        "expires_at_dt": now + PREVIEW_TTL,
        "file_type": "CSV" if ext == ".csv" else "Excel",
        "file": {
            "name": filename[:200], "kind": statement.kind or ext.lstrip("."), "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(), "format": statement.layout, "broker": statement.broker,
            "broker_name": statement.broker_name, "header_row": statement.header_row, "skipped_rows": statement.skipped_rows,
        },
        "account_ref": {
            "broker": statement.broker, "broker_name": statement.broker_name,
            "note": (f"Read as a {statement.broker_name} holdings file." if statement.broker_name else
                     "Read as a plain sheet: no broker account is named." if statement.layout == "generic" else
                     "The columns do not name a broker; no broker account is named."),
        },
        "rows": rows,
        "effects": effects,
    }
    await _ensure_preview_indexes()
    await db[PREVIEWS].insert_one(doc)
    logger.info("import preview: user=%s rows=%d format=%s", uid, len(rows), statement.layout)
    return _public_preview(doc)


@router.post("/portfolio/upload/preview/{preview_id}/commit", tags=["Portfolio Upload"],
             summary="Save the rows of a preview the user confirmed")
async def commit_portfolio_upload(request: Request, preview_id: str):
    user = await get_current_user(request)
    uid = user["user_id"]
    raw = await request.body()
    body: Any = {}
    if raw.strip():
        try:
            import json as _json
            body = _json.loads(raw)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid_body")
    if not isinstance(body, dict) or set(body) - {"rows"}:
        raise HTTPException(status_code=422, detail="invalid_body")

    doc = await db[PREVIEWS].find_one({"_id": preview_id, "user_id": uid}) if len(preview_id) <= 64 else None
    if not doc:
        raise HTTPException(status_code=404, detail="preview_not_found")
    if doc["status"] != "open":
        raise HTTPException(status_code=409, detail="preview_already_committed")
    if datetime.fromisoformat(doc["expires_at"]) <= _utcnow():
        raise HTTPException(status_code=410, detail="preview_expired")

    by_no = {r["row_no"]: r for r in doc["rows"]}
    wanted = body.get("rows")
    if wanted is None:
        chosen = [n for n, r in by_no.items() if r["include"]]
    else:
        if not isinstance(wanted, list) or any(not isinstance(n, int) or isinstance(n, bool) for n in wanted):
            raise HTTPException(status_code=422, detail="invalid_rows")
        if any(n not in by_no or by_no[n]["status"] == "rejected" for n in wanted):
            raise HTTPException(status_code=422, detail="invalid_rows")
        chosen = sorted(set(wanted))
    if not chosen:
        raise HTTPException(status_code=422, detail="nothing_to_import")

    owner = {"_id": preview_id, "user_id": uid}
    claim = await db[PREVIEWS].update_one({**owner, "status": "open"}, {"$set": {"status": "committing"}})
    if not claim.matched_count:
        raise HTTPException(status_code=409, detail="preview_already_committed")
    try:
        saved = await save_holdings(uid, [dict(by_no[n]["holding"]) for n in chosen], doc["file_type"])
    except Exception:
        await db[PREVIEWS].update_one({**owner, "status": "committing"}, {"$set": {"status": "open"}})
        raise
    await db[PREVIEWS].update_one(owner, {"$set": {"status": "committed", "committed_at": _utcnow().isoformat(),
                                                   "committed_rows": chosen}})
    await dashboard_cache.invalidate(uid)
    left_out = [n for n in by_no if n not in chosen]
    logger.info("import commit: user=%s preview=%s saved=%d left_out=%d", uid, preview_id, len(saved), len(left_out))
    return {
        "message": f"{len(saved)} holdings imported from {doc['file_type']}",
        "count": len(saved),
        "holdings": saved,
        "broker": doc["file"]["broker"],
        "broker_name": doc["file"]["broker_name"],
        "format": doc["file"]["format"],
        "preview_id": preview_id,
        "committed_rows": chosen,
        "left_out_rows": left_out,
    }


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
async def portfolio_import_from_connect(
    request: Request,
    idem: IdempotencyState = Depends(check_idempotency),
):
    """Ingest parsed portfolio from the CAS Connect widget.

    Supports the ``Idempotency-Key`` request header: if the same key is sent
    twice within 24 hours the second call replays the first response without
    re-importing holdings, preventing duplicate-import on network retries.
    """
    if idem.cached is not None:
        return idem.cached
    user = await get_current_user(request)
    body = await request.json()
    parsed_data = body.get("data") if isinstance(body, dict) and "data" in body else body
    portfolio_id = (body.get("portfolio_id") or "").strip() if isinstance(body, dict) else ""
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

    saved = await save_holdings(
        user["user_id"], holdings, "CAS Connect",
        portfolio_id=portfolio_id,
    )

    # Mirror the Gmail-import behaviour: save onboarding flag + CAS metadata
    # so the dashboard banner, chart, and action matrix all have data to render.
    if saved:
        now = datetime.now(timezone.utc)

        # Extract statement period ("Apr/2026") from the casparser JSON.
        from services.cas_api_client import extract_statement_period, period_label_from_date
        cas_statement_period = extract_statement_period(parsed_data)

        # Statement date — try standard casparser meta fields first.
        meta_block = parsed_data.get("meta") or {}
        cas_statement_date = (
            meta_block.get("to_date")
            or meta_block.get("period_to")
            or meta_block.get("statement_to")
        )

        # Fall back to deriving the period from the statement date when the
        # casparser meta had no explicit period (keeps the "Last CAS" banner
        # populated for custom-extractor layouts).
        if not cas_statement_period and cas_statement_date:
            cas_statement_period = period_label_from_date(cas_statement_date)

        # Portfolio value — sum current_price × quantity across saved holdings.
        # This is the last-known NAV value at statement time.
        portfolio_value_rs = round(
            sum(
                float(h.get("current_price", 0)) * float(h.get("quantity", 0))
                for h in saved
            ),
            2,
        )

        profile_set: dict = {
            "onboarding_completed": True,
            "journey_type": "existing_investor",
            "updated_at": now,
        }
        if cas_statement_period:
            profile_set["cas_statement_period"] = cas_statement_period
        if cas_statement_date:
            profile_set["cas_statement_date"] = cas_statement_date
        if portfolio_value_rs > 0:
            profile_set["cas_portfolio_value_rs"] = portfolio_value_rs

        await db.user_profiles.update_one(
            {"user_id": user["user_id"]},
            {
                "$set": profile_set,
                "$setOnInsert": {"user_id": user["user_id"], "created_at": now},
            },
            upsert=True,
        )

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

    # Auto-generate action plan so the dashboard action matrix is immediately
    # populated — mirrors what Gmail sync does after a successful import.
    # refresh_plan() fetches holdings + intelligence internally and saves
    # directly as status="active".
    if saved:
        try:
            from services.action_plan_manager import ActionPlanManager
            plan = await ActionPlanManager().refresh_plan(user["user_id"])
            logger.info(
                "import-connect: action plan generated for user=%s plan_id=%s actions=%d",
                user["user_id"], plan.get("plan_id"), len(plan.get("actions") or []),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("import-connect: plan generation failed for user=%s: %s", user["user_id"], e)

        # Kick off NIDP sync + PRA so the Risk screen populates without manual admin action.
        asyncio.create_task(_trigger_nidp_pipeline_background(user["user_id"]))

    await dashboard_cache.invalidate(user["user_id"])
    result = {
        "message": f"{len(saved)} holdings imported via Portfolio Connect",
        "count": len(saved),
        "holdings": saved,
        "cas_type": cas_type,
        "investor": investor_name,
        "transactions": sip_summary.get("transactions", 0),
        "sips_detected": sip_summary.get("sips", 0),
    }
    await store_idempotency_result(idem, result)
    return result


async def _trigger_nidp_pipeline_background(user_id: str) -> None:
    """Fire-and-forget: after a CAS import, kick off the NIDP sync + risk pipeline.

    Sequence:
      1. portfolio_holdings_sync  — copies Nivesh MongoDB holdings → NIDP Postgres
      2. pra_engine               — computes VaR/vol/drawdown/beta for the Risk screen

    Both calls are best-effort; a failure is logged but does NOT fail the upload.
    The jobs run detached on the NIDP VM via the Query API.
    """
    from services import nidp_query_client as _nq

    if not _nq.is_configured():
        logger.info("nidp-pipeline: NIDP_QUERY_API_URL not configured — skipping auto-trigger")
        return

    for ingester in ("portfolio_holdings_sync", "pra_engine"):
        try:
            resp = await _nq.execute_feed(ingester)
            logger.info(
                "nidp-pipeline: triggered %s for user=%s status=%s",
                ingester, user_id, resp.get("status", "spawned"),
            )
        except _nq.NidpQueryClientError as e:
            logger.warning("nidp-pipeline: %s trigger failed for user=%s: %s", ingester, user_id, e.detail)
        except Exception as e:  # noqa: BLE001
            logger.warning("nidp-pipeline: %s trigger error for user=%s: %s", ingester, user_id, e)


# CAS PDF background processor removed — all PDF parsing now happens
# inside the Connect SDK widget (browser → casparser.in direct). The
# widget returns parsed JSON which is POSTed to /api/portfolio/import-connect.
