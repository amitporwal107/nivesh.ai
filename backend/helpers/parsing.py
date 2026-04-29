"""File parsing helpers: CSV, Excel, CAS PDF, JSON response parsing."""
import io
import csv
import json
import uuid
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional
from fastapi import HTTPException

from deps import db, ai_engine

logger = logging.getLogger(__name__)


def classify_mf_sector(scheme_name: str) -> str:
    """Classify mutual fund into sector based on scheme name."""
    name = scheme_name.lower()
    if any(k in name for k in ["index", "nifty", "sensex", "etf"]): return "Index"
    if any(k in name for k in ["small cap", "smallcap"]): return "Small Cap"
    if any(k in name for k in ["mid cap", "midcap"]): return "Mid Cap"
    if any(k in name for k in ["large cap", "largecap", "bluechip", "large & mid"]): return "Large Cap"
    if any(k in name for k in ["flexi cap", "flexicap", "multi cap", "multicap"]): return "Flexi Cap"
    if any(k in name for k in ["balanced", "hybrid", "advantage", "dynamic"]): return "Balanced"
    if any(k in name for k in ["elss", "tax"]): return "ELSS"
    if any(k in name for k in ["debt", "bond", "gilt", "liquid", "money market", "overnight", "short", "credit", "duration", "arbitrage"]): return "Debt"
    if any(k in name for k in ["gold", "sgb", "sovereign"]): return "Gold"
    if any(k in name for k in ["international", "global", "us ", "nasdaq", "fang", "nyse"]): return "International"
    if any(k in name for k in ["banking", "financial"]): return "Banking & Financial"
    if any(k in name for k in ["pharma", "health"]): return "Healthcare"
    if any(k in name for k in ["technology", "digital", "it "]): return "IT / Technology"
    if any(k in name for k in ["contra", "value"]): return "Value"
    if any(k in name for k in ["focused", "opportunities"]): return "Focused"
    if any(k in name for k in ["multi asset"]): return "Multi Asset"
    return "Other"


async def parse_csv_holdings(content: bytes) -> list:
    """Parse CSV/Excel files into holding rows."""
    holdings = []
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


def convert_casparser_to_holdings(cas_data: dict) -> list:
    """Convert casparser output dict to our holdings format."""
    holdings = []
    folios = cas_data.get("folios", [])
    if not folios:
        return []

    for folio in folios:
        for scheme in folio.get("schemes", []):
            units = scheme.get("close_calculated") or scheme.get("close", 0) or 0
            if units <= 0:
                continue

            scheme_name = scheme.get("scheme", "Unknown Fund")
            isin = scheme.get("isin", "") or ""
            valuation = scheme.get("valuation", {}) or {}
            nav = valuation.get("nav", 0) or 0

            total_cost = 0.0
            total_purchase_units = 0.0
            for tx in scheme.get("transactions", []):
                tx_type = (tx.get("type", "") or "").upper()
                tx_amount = tx.get("amount", 0) or 0
                tx_units = tx.get("units", 0) or 0
                if tx_type in ("PURCHASE", "PURCHASE_SIP", "SWITCH_IN", "SWITCH_IN_MERGER",
                               "NEW_FUND_OFFER", "REINVESTMENT", "SYSTEMATIC_INVESTMENT"):
                    if tx_amount > 0 and tx_units > 0:
                        total_cost += abs(tx_amount)
                        total_purchase_units += abs(tx_units)
                elif tx_type in ("REDEMPTION", "SWITCH_OUT"):
                    if tx_amount > 0 and tx_units > 0:
                        if total_purchase_units > 0:
                            cost_per_unit = total_cost / total_purchase_units
                            total_cost -= cost_per_unit * abs(tx_units)
                            total_purchase_units -= abs(tx_units)

            avg_cost = total_cost / total_purchase_units if total_purchase_units > 0 else 0

            name_lower = scheme_name.lower()
            if any(k in name_lower for k in ["gold", "sgb", "sovereign gold"]):
                asset_type = "gold"
            elif any(k in name_lower for k in ["etf", "exchange traded"]):
                asset_type = "etf"
            else:
                asset_type = "mutual_fund"

            holdings.append({
                "name": scheme_name,
                "ticker": isin,
                "asset_type": asset_type,
                "quantity": round(units, 4),
                "buy_price": round(avg_cost, 4) if avg_cost > 0 else round(nav, 4),
                "current_price": round(nav, 4),
                "sector": classify_mf_sector(scheme_name),
            })

    logger.info(f"casparser: processed {len(folios)} folios -> {len(holdings)} holdings")
    return holdings


def _normalize_casparser_folios(cas_data: dict) -> dict:
    """Convert casparser library folios→schemes to the `mutual_funds` format
    expected by `cas_transactions.extract_transactions()`.

    casparser lib:  {folios: [{folio, amc, schemes: [{scheme, isin, transactions}]}]}
    target format:  {mutual_funds: [{amc, folio_number, schemes: [...]}]}
    """
    mutual_funds = []
    for f in cas_data.get("folios") or []:
        mutual_funds.append({
            "amc": (f.get("amc") or "").strip(),
            "folio_number": (f.get("folio") or f.get("folio_number") or "").strip(),
            "schemes": f.get("schemes") or [],
        })
    return {"mutual_funds": mutual_funds}


async def parse_cas_pdf_with_data(content: bytes, password: str = "") -> tuple:
    """Like parse_cas_pdf() but also returns:
      • normalized `{mutual_funds: [...]}` dict for transaction extraction
      • the RAW parsed payload (API JSON or casparser library dict) so
        the caller can persist it in DB and avoid re-parsing the PDF.

    Returns: (holdings: list,
              normalized_for_txns: dict | None,
              raw_payload: dict | None,
              parser_source: str | None)

    `parser_source` is one of: "claude_vision", "casparser_api",
    "casparser_lib", "local_ocr", "ai", or None on total failure.

    Provider routing:
      The active provider is the *primary* try (default `nivesh_cas_parser`).
      We then auto-fall-back through the remaining providers in order
      (Nivesh → Claude Vision → casparser.in API → casparser library
      → OCR / AI) until one returns holdings. The UI never branches on
      provider — it's purely a server-side concern.
    """
    # Resolve the primary provider (admin-controlled). Default = nivesh_cas_parser.
    active_provider = "nivesh_cas_parser"
    try:
        from deps import db as _db
        cfg = await _db.system_config.find_one({"key": "cas_parser_provider"}, {"_id": 0})
        if cfg and cfg.get("provider"):
            active_provider = cfg["provider"]
    except Exception as e:  # noqa: BLE001
        logger.info(f"Could not load cas_parser_provider, defaulting to nivesh_cas_parser: {e}")

    # Build the try-order with the primary first, then the rest.
    # casparser_api is always last because it consumes paid credits and
    # may return sandbox stubs when admin enabled sandbox mode.
    chain: list = []
    seen: set = set()
    for p in [active_provider, "nivesh_cas_parser", "claude_vision", "casparser_api"]:
        if p not in seen:
            chain.append(p); seen.add(p)
    logger.info(f"parse_cas_pdf_with_data: active={active_provider} chain={chain}")

    # Result accumulators — first non-empty wins.
    holdings: list = []
    normalized = None
    raw_payload = None
    parser_source: Optional[str] = None

    # ── Helper: try Nivesh ────────────────────────────────────────────
    async def _try_nivesh():
        from services.nivesh_cas_parser import (
            parse_with_nivesh, is_configured as _ok,
        )
        from services.claude_cas_mapper import map_to_internal as _mp
        if not _ok():
            return None
        raw = parse_with_nivesh(content, password=password or "")
        if not raw:
            return None
        h, n = _mp(raw)
        return (h, n, raw, "nivesh_cas_parser") if h else None

    # ── Helper: try Claude Vision ─────────────────────────────────────
    async def _try_claude():
        from services.claude_cas_parser import (
            parse_with_claude_vision, is_configured as _ok,
            BudgetExceededError,
        )
        from services.claude_cas_mapper import map_to_internal as _mp
        if not _ok():
            return None
        try:
            raw = await parse_with_claude_vision(content, password=password)
        except BudgetExceededError:
            # Re-raise so the outer caller can render a clear "top-up
            # needed" error — but only if no other parser has succeeded
            # yet. We swallow it here only when subsequent providers
            # might still work.
            raise
        if not raw:
            return None
        h, n = _mp(raw)
        return (h, n, raw, "claude_vision") if h else None

    # ── Helper: try casparser.in API ──────────────────────────────────
    async def _try_casparser_api():
        from services.cas_api_client import parse_cas_via_api_with_data, is_configured as _ok
        if not _ok():
            return None
        h, raw, n = parse_cas_via_api_with_data(content, password or "")
        return (h, n, raw, "casparser_api") if h else None

    handlers = {
        "nivesh_cas_parser": _try_nivesh,
        "claude_vision": _try_claude,
        "casparser_api": _try_casparser_api,
    }

    # If sandbox mode is on for casparser.in, drop it from the chain —
    # sandbox returns canned mock data regardless of the uploaded PDF
    # which would silently mask real parser failures (e.g., a wrong PDF
    # password) with a false 152-holding success.
    try:
        from services.cas_api_client import is_sandbox_active
        if is_sandbox_active() and "casparser_api" in chain:
            chain.remove("casparser_api")
            logger.info(
                "parse_cas_pdf_with_data: casparser.in is in sandbox mode — "
                "removed from auto-fallback chain to avoid false-success mock data"
            )
    except Exception:  # noqa: BLE001
        pass

    budget_error = None
    password_error = None
    for provider in chain:
        fn = handlers.get(provider)
        if not fn:
            continue
        try:
            result = await fn()
            if result:
                holdings, normalized, raw_payload, parser_source = result
                logger.info(
                    f"parse_cas_pdf_with_data: success via {parser_source} "
                    f"({len(holdings)} holdings)"
                )
                break
            logger.info(f"parse_cas_pdf_with_data: {provider} returned nothing, trying next")
        except Exception as e:
            err_str = str(e).lower()
            # PDF password / decryption errors are USER errors. Don't try
            # other providers — they'll all fail the same way OR (worse)
            # casparser.in sandbox will return mock data and falsely succeed.
            if any(tok in err_str for tok in [
                "password rejected", "incorrect password", "wrong password",
                "password is required", "password protected",
            ]):
                password_error = HTTPException(
                    status_code=400,
                    detail=(
                        "Wrong CAS PDF password. Please re-enter your PAN "
                        "(format: ABCDE1234F) and try again."
                    ),
                )
                logger.warning(f"parse_cas_pdf_with_data: password error on {provider} — aborting chain")
                break
            if e.__class__.__name__ == "BudgetExceededError":
                budget_error = e
            logger.warning(f"parse_cas_pdf_with_data: {provider} failed ({e}), trying next")

    if password_error is not None:
        raise password_error
    if not holdings and budget_error:
        # All other providers also failed — surface the budget error so
        # admins can top up the LLM key.
        raise budget_error

    if holdings:
        try:
            from services.masterdata import validate_and_enrich_holdings
            holdings = validate_and_enrich_holdings(holdings)
        except Exception as e:
            logger.info(f"Masterdata enrichment skipped: {e}")
        return holdings, normalized, raw_payload, parser_source

    # ── Final fallback: casparser library + OCR + AI (no provider toggle) ──

    # 2nd: casparser library — also produces structured transactions
    try:
        import casparser
        cas_data = casparser.read_cas_pdf(io.BytesIO(content), password or "", output="dict")
        holdings = convert_casparser_to_holdings(cas_data)
        if holdings:
            logger.info(f"casparser library extracted {len(holdings)} holdings + raw transaction data")
            return holdings, _normalize_casparser_folios(cas_data), cas_data, "casparser_lib"
        logger.info("casparser returned no holdings, falling back to OCR/AI")
    except Exception as e:
        logger.info(f"casparser library failed in parse_cas_pdf_with_data: {e}")

    # 3rd+: delegate to the full fallback chain (OCR, AI). These have no
    # structured transaction data — return holdings only.
    holdings = await parse_cas_pdf(content, password)
    return holdings, None, None, ("local_ocr_or_ai" if holdings else None)


async def parse_cas_pdf(content: bytes, password: str = "") -> list:
    """Parse CAS PDF — auto-fallback chain (holdings-only path).
    Tries the admin-selected primary provider first, then falls through
    Nivesh → Claude Vision → casparser.in API → casparser library →
    OCR / AI. Returns the first non-empty holdings list.
    """
    # Resolve primary provider; default = nivesh_cas_parser.
    try:
        from deps import db as _db
        cfg = await _db.system_config.find_one({"key": "cas_parser_provider"}, {"_id": 0})
        active_provider = (cfg or {}).get("provider") or "nivesh_cas_parser"
    except Exception:  # noqa: BLE001
        active_provider = "nivesh_cas_parser"

    chain: list = []
    seen: set = set()
    for p in [active_provider, "nivesh_cas_parser", "claude_vision", "casparser_api"]:
        if p not in seen:
            chain.append(p); seen.add(p)
    logger.info(f"parse_cas_pdf: active={active_provider} chain={chain}")

    async def _try_nivesh():
        from services.nivesh_cas_parser import parse_with_nivesh, is_configured as _ok
        from services.claude_cas_mapper import map_to_holdings as _mp
        if not _ok():
            return None
        raw = parse_with_nivesh(content, password=password or "")
        if not raw:
            return None
        h = _mp(raw)
        return h or None

    async def _try_claude():
        from services.claude_cas_parser import parse_with_claude_vision, is_configured as _ok
        from services.claude_cas_mapper import map_to_holdings as _mp
        if not _ok():
            return None
        raw = await parse_with_claude_vision(content, password=password or "")
        if not raw:
            return None
        h = _mp(raw)
        return h or None

    async def _try_casparser_api():
        from services.cas_api_client import parse_cas_via_api, is_configured as _ok
        if not _ok():
            return None
        h = parse_cas_via_api(content, password or "")
        return h or None

    handlers = {
        "nivesh_cas_parser": _try_nivesh,
        "claude_vision": _try_claude,
        "casparser_api": _try_casparser_api,
    }

    # Drop casparser.in when sandbox mode is active — see equivalent
    # comment in parse_cas_pdf_with_data above.
    try:
        from services.cas_api_client import is_sandbox_active
        if is_sandbox_active() and "casparser_api" in chain:
            chain.remove("casparser_api")
            logger.info(
                "parse_cas_pdf: casparser.in is in sandbox mode — removed "
                "from auto-fallback chain to avoid false-success mock data"
            )
    except Exception:  # noqa: BLE001
        pass

    for provider in chain:
        fn = handlers.get(provider)
        if not fn:
            continue
        try:
            h = await fn()
            if h:
                logger.info(f"parse_cas_pdf: success via {provider} ({len(h)} holdings)")
                try:
                    from services.masterdata import validate_and_enrich_holdings
                    h = validate_and_enrich_holdings(h)
                except Exception as e:
                    logger.info(f"Masterdata enrichment skipped: {e}")
                return h
            logger.info(f"parse_cas_pdf: {provider} returned nothing, trying next")
        except Exception as e:
            err_str = str(e).lower()
            # PDF password errors → abort entire chain (user error, not
            # parser failure). Bubble up so the upload route surfaces a
            # clear "wrong password" message instead of silently falling
            # through to a sandbox-mock false success.
            if any(tok in err_str for tok in [
                "password rejected", "incorrect password", "wrong password",
                "password is required", "password protected",
            ]):
                logger.warning(f"parse_cas_pdf: password error on {provider} — aborting chain")
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Wrong CAS PDF password. Please re-enter your PAN "
                        "(format: ABCDE1234F) and try again."
                    ),
                )
            logger.warning(f"parse_cas_pdf: {provider} failed ({e}), trying next")

    # 2nd: casparser library
    try:
        import casparser
        cas_data = casparser.read_cas_pdf(io.BytesIO(content), password or "", output="dict")
        holdings = convert_casparser_to_holdings(cas_data)
        if holdings:
            logger.info(f"casparser extracted {len(holdings)} holdings successfully")
            return holdings
        logger.info("casparser returned no holdings, falling back to AI parsing")
    except Exception as e:
        logger.info(f"casparser failed: {e}, falling back to local OCR parsing")

    # 3rd: Local Tesseract OCR
    from services.cas_parser import parse_nsdl_cas_image
    local_holdings = parse_nsdl_cas_image(content, password)
    if local_holdings:
        logger.info(f"Local OCR parser extracted {len(local_holdings)} holdings")
        return local_holdings

    # 4th: AI parsing (text extraction + OpenAI vision)
    import base64

    text = ""
    pdf_is_encrypted = False
    decrypt_succeeded = False
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pdf_is_encrypted = reader.is_encrypted
        if reader.is_encrypted:
            if not password:
                raise HTTPException(status_code=400, detail="PDF is password-protected. Please provide the password.")
            decrypt_result = reader.decrypt(password)
            if not decrypt_result:
                raise HTTPException(status_code=400, detail="Incorrect PDF password. Please try again.")
            decrypt_succeeded = True
            logger.info(f"PDF decrypted successfully (type={decrypt_result})")
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
    except HTTPException:
        raise
    except Exception as e:
        err_str = str(e)
        logger.warning(f"PyPDF2 text extraction failed: {err_str}")
        if "pycryptodome" in err_str.lower() or "aes" in err_str.lower():
            raise HTTPException(status_code=500, detail="Server missing PyCryptodome library for AES-encrypted PDFs.")
        if pdf_is_encrypted and not decrypt_succeeded and not password:
            raise HTTPException(status_code=400, detail="PDF is password-protected. Please provide the password.")
        if pdf_is_encrypted and not decrypt_succeeded and password:
            raise HTTPException(status_code=400, detail="Incorrect PDF password or the file is corrupted.")

    if text.strip() and len(text.strip()) > 200:
        from PyPDF2 import PdfReader as _PdfReader
        page_texts = []
        try:
            _reader = _PdfReader(io.BytesIO(content))
            if _reader.is_encrypted and password:
                _reader.decrypt(password)
            for pg in _reader.pages:
                pt = pg.extract_text() or ""
                if pt.strip():
                    page_texts.append(pt)
        except Exception:
            page_texts = [text]

        if not page_texts:
            page_texts = [text]

        all_parsed = []
        current_batch = ""
        batch_num = 0
        for pt in page_texts:
            if len(current_batch) + len(pt) > 12000 and current_batch:
                try:
                    parsed = await ai_engine.parse_cas_text(current_batch, f"cas_txt_b{batch_num}_{uuid.uuid4().hex[:6]}")
                    if parsed:
                        all_parsed.extend(parsed)
                        logger.info(f"CAS text batch {batch_num}: {len(parsed)} holdings")
                except Exception as e:
                    logger.warning(f"CAS text batch {batch_num} failed: {e}")
                current_batch = pt
                batch_num += 1
            else:
                current_batch += "\n" + pt

        if current_batch.strip():
            try:
                parsed = await ai_engine.parse_cas_text(current_batch, f"cas_txt_b{batch_num}_{uuid.uuid4().hex[:6]}")
                if parsed:
                    all_parsed.extend(parsed)
                    logger.info(f"CAS text batch {batch_num}: {len(parsed)} holdings")
            except Exception as e:
                logger.warning(f"CAS text batch {batch_num} failed: {e}")

        if all_parsed:
            seen = set()
            unique = []
            for h in all_parsed:
                isin = (h.get("ticker") or h.get("isin") or "").strip().upper()
                name = h.get("name", "").strip().lower()[:40]
                key = f"{isin}__{name}" if isin else f"__{name}__{h.get('quantity',0)}"
                if key not in seen:
                    seen.add(key)
                    unique.append(h)
            logger.info(f"CAS text total: {len(all_parsed)} raw -> {len(unique)} unique holdings")
            return unique

    # Image-based PDF
    logger.info(f"CAS PDF is image-based, processing via OpenAI vision")
    try:
        from pdf2image import convert_from_bytes, pdfinfo_from_bytes

        pdfinfo_kwargs = {}
        if password:
            pdfinfo_kwargs["userpw"] = password
        try:
            info = pdfinfo_from_bytes(content, **pdfinfo_kwargs)
            total_pages = info.get("Pages", 0)
        except Exception as e:
            logger.warning(f"pdfinfo failed: {e}")
            total_pages = 0

        if total_pages == 0:
            detail = "Could not read PDF."
            if not password:
                detail += " The file may be password-protected."
            raise HTTPException(status_code=400, detail=detail)

        convert_kwargs = {"dpi": 130}
        if password:
            convert_kwargs["userpw"] = password
        all_page_images = convert_from_bytes(content, **convert_kwargs)

        batches = []
        batch_size = 3
        for start in range(0, len(all_page_images), batch_size):
            end = min(start + batch_size, len(all_page_images))
            image_data_list = []
            for img in all_page_images[start:end]:
                img_buf = io.BytesIO()
                img.save(img_buf, format="PNG", optimize=True)
                image_data_list.append(img_buf.getvalue())
            batches.append((start + 1, end, image_data_list))

        async def parse_batch(start_page, end_page, images):
            try:
                holdings = await ai_engine.parse_cas_images(
                    images, f"{start_page}-{end_page}",
                    f"cas_p{start_page}_{uuid.uuid4().hex[:6]}"
                )
                if holdings:
                    logger.info(f"Pages {start_page}-{end_page}: {len(holdings)} holdings")
                return holdings or []
            except Exception as e:
                logger.warning(f"Pages {start_page}-{end_page} failed: {e}")
                return []

        results = await asyncio.gather(
            *[parse_batch(s, e, imgs) for s, e, imgs in batches]
        )

        all_holdings = []
        for batch_result in results:
            all_holdings.extend(batch_result)

        seen = set()
        unique_holdings = []
        for h in all_holdings:
            key = f"{h.get('name','').strip()}__{h.get('quantity',0)}__{h.get('current_price',0)}"
            if key not in seen:
                seen.add(key)
                unique_holdings.append(h)

        logger.info(f"Total unique holdings from CAS: {len(unique_holdings)}")

        if not unique_holdings:
            raise HTTPException(status_code=422, detail="Could not extract any holdings from the CAS PDF.")

        return unique_holdings

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CAS PDF parsing error: {e}")
        raise HTTPException(status_code=422, detail=f"Could not parse CAS PDF. Error: {str(e)}")


def parse_json_response(response: str) -> list:
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


def parse_json_response_obj(response: str) -> dict:
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


async def save_holdings(user_id: str, parsed: list, file_type: str, task_id: str = None, portfolio_id: str = ""):
    """Save parsed holdings to DB. For CAS uploads, replaces ALL existing holdings."""
    is_cas = "cas" in file_type.lower()

    old_count = 0
    if is_cas:
        delete_query = {"user_id": user_id}
        if portfolio_id:
            delete_query["portfolio_id"] = portfolio_id
        old_count = await db.holdings.count_documents(delete_query)
        await db.holdings.delete_many(delete_query)
        logger.info(f"CAS upload: cleared {old_count} old holdings for user {user_id}")

    holdings_added = []
    for h in parsed:
        asset_type = h.get("asset_type", "equity")
        if asset_type not in ["equity", "mutual_fund", "etf", "bond", "gold", "fd", "other"]:
            asset_type = "mutual_fund" if "fund" in h.get("name", "").lower() else "equity"

        buy_price_val = float(h.get("buy_price", 0))
        current_price_val = float(h.get("current_price", 0))
        if buy_price_val == 0 and current_price_val > 0:
            buy_price_val = current_price_val

        holding_doc = {
            "holding_id": f"hold_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "portfolio_id": portfolio_id,
            "name": h.get("name", "Unknown"),
            "ticker": h.get("ticker", ""),
            "asset_type": asset_type,
            "quantity": float(h.get("quantity", 0)),
            "buy_price": buy_price_val,
            "current_price": current_price_val,
            "sector": h.get("sector", "Other"),
            "buy_date": h.get("buy_date") or None,
            "source": "cas" if is_cas else h.get("source", "manual"),
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.holdings.insert_one(holding_doc)
        holdings_added.append({
            "holding_id": holding_doc["holding_id"],
            "name": holding_doc["name"],
            "asset_type": holding_doc["asset_type"],
            "quantity": holding_doc["quantity"],
        })

    # Invalidate the MFD profile-signal cache for this user so the Advisor
    # dashboard picks up the fresh health score on next load.
    try:
        await db.mfd_profile_signal_cache.delete_one({"user_id": user_id})
    except Exception:  # noqa: BLE001
        pass

    msg = f"{len(holdings_added)} holdings imported from {file_type}"
    if is_cas and old_count > 0:
        msg = f"{len(holdings_added)} holdings imported from {file_type} (replaced {old_count} previous)"

    if task_id:
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {
                "status": "completed",
                "message": msg,
                "count": len(holdings_added),
                "holdings": holdings_added,
                "completed_at": datetime.now(timezone.utc).isoformat()
            }}
        )

    # Invalidate cached analytics
    await db.fund_performance_cache.delete_many({"user_id": user_id})

    # ── On-demand enrichment (background) ─────────────────────────────
    # Fire-and-forget: fetch fundamentals for new holdings so Insights +
    # Plan Board render with complete data on the user's next request.
    # Failure here never blocks the upload response.
    import asyncio as _asyncio
    _asyncio.create_task(_enrich_after_upload(user_id, holdings_added))

    return holdings_added


async def _enrich_after_upload(user_id: str, holdings_added: list) -> None:
    """Background enrichment fired after CAS/manual upload completes.

    - Equity holdings → Groww stock scraper (fundamentals + V3 scoring)
    - MF holdings     → queue for off-hours scraping via fund_data_resolver
    Both are fire-and-forget; errors are logged but never bubble up.
    """
    try:
        has_equity = any(h.get("asset_type") == "equity" for h in holdings_added)
        has_mf = any(h.get("asset_type") == "mutual_fund" for h in holdings_added)

        if has_equity:
            try:
                from services.groww_stock_scraper import refresh_user_stocks
                res = await refresh_user_stocks(user_id)
                logger.info(
                    f"post-upload stock enrichment for {user_id}: "
                    f"scored {res.get('succeeded', 0)}/{res.get('total', 0)} "
                    f"in {res.get('duration_s', 0)}s"
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"post-upload stock enrichment failed: {e}")

        if has_mf:
            try:
                from services import fund_data_resolver as _fdr
                res = await _fdr.scrape_user_mfs_inline(user_id, concurrency=5)
                logger.info(
                    f"post-upload MF inline scrape for {user_id}: "
                    f"scraped {res.get('succeeded', 0)}/{res.get('total', 0)} "
                    f"(cached {res.get('cached', 0)}, failed {res.get('failed', 0)}) "
                    f"in {res.get('duration_s', 0)}s"
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"post-upload MF inline scrape failed: {e}")

        # Post-CAS snapshot — runs after enrichment so Health scores
        # reflect the new holdings. Overwrites today's EOD snapshot if
        # one already exists (later trigger wins).
        try:
            from services import portfolio_snapshot as _snap
            snap = await _snap.persist_snapshot(user_id, trigger="cas_upload")
            logger.info(
                f"post-upload snapshot for {user_id}: "
                f"value=₹{snap.get('total_value', 0):,.0f} "
                f"holdings={snap.get('holdings_count', 0)} "
                f"health={snap.get('health_score')}"
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"post-upload snapshot failed: {e}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"_enrich_after_upload crashed: {e}")
