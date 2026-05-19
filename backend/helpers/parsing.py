"""File parsing helpers: CSV, Excel, CAS PDF, JSON response parsing."""
import io
import os
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

    logger.info("casparser: processed %d folios -> %d holdings", len(folios), len(holdings))
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


# ── parse_cas_pdf_with_data / parse_cas_pdf — REMOVED ──────────────────
#
# Server-side CAS PDF parsing was decommissioned alongside the
# casparser.in REST API integration. All CAS uploads now flow through
# the Connect SDK widget (`CasUploadButton.jsx` → `@cas-parser/connect`):
#
#   1. Browser asks /api/casparser/access-token for a short-lived `at_*`
#      token (backend mints it using the current head of the GSM-sourced
#      key pool — see services/cas_api_client.py).
#   2. The SDK widget opens, the client uploads the PDF (or pulls from
#      Gmail / does CDSL OTP) — all in their browser.
#   3. The widget parses the PDF directly against casparser.in (no
#      size cap, no nginx relay, no Vision fallback to operate).
#   4. The widget returns parsed JSON which the browser POSTs to
#      /api/portfolio/import-connect for mapping + masterdata enrichment
#      + persistence.
#
# `services.cas_api_client.map_api_response_to_holdings()` is the single
# remaining entry point for turning a casparser.in payload into internal
# holdings, used by both /api/portfolio/import-connect and the admin
# debug routes.


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
        logger.info("CAS upload: cleared %d old holdings", old_count, extra={"user_id": user_id})

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
                    "post-upload stock enrichment: scored %d/%d in %ss",
                    res.get("succeeded", 0), res.get("total", 0), res.get("duration_s", 0),
                    extra={"user_id": user_id},
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("post-upload stock enrichment failed: %s", e, extra={"user_id": user_id})

        if has_mf:
            try:
                from services import fund_data_resolver as _fdr
                res = await _fdr.scrape_user_mfs_inline(user_id, concurrency=5)
                logger.info(
                    "post-upload MF inline scrape: scraped %d/%d (cached %d, failed %d) in %ss",
                    res.get("succeeded", 0), res.get("total", 0),
                    res.get("cached", 0), res.get("failed", 0), res.get("duration_s", 0),
                    extra={"user_id": user_id},
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("post-upload MF inline scrape failed: %s", e, extra={"user_id": user_id})

        # Post-CAS snapshot — runs after enrichment so Health scores
        # reflect the new holdings. Overwrites today's EOD snapshot if
        # one already exists (later trigger wins).
        try:
            from services import portfolio_snapshot as _snap
            snap = await _snap.persist_snapshot(user_id, trigger="cas_upload")
            logger.info(
                "post-upload snapshot: value=%.0f holdings=%d health=%s",
                snap.get("total_value", 0), snap.get("holdings_count", 0), snap.get("health_score"),
                extra={"user_id": user_id},
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("post-upload snapshot failed: %s", e, extra={"user_id": user_id})

        # Persona re-inference — runs last so it sees the freshest snapshot.
        # Skipped silently when user has manually overridden their persona.
        try:
            from services.persona_engine import refresh_persona
            persona_result = await refresh_persona(user_id, db)
            logger.info(
                "post-upload persona: %s (confidence=%d, inferred=%s)",
                persona_result.persona, persona_result.confidence, persona_result.inferred,
                extra={"user_id": user_id},
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("post-upload persona refresh failed: %s", e, extra={"user_id": user_id})
    except Exception as e:  # noqa: BLE001
        logger.warning("_enrich_after_upload crashed: %s", e, extra={"user_id": user_id})
