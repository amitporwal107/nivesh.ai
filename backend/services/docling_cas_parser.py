"""In-house CAS parser — Docling + casparser, fully local, zero external API calls.

Pipeline:
  1. PyMuPDF  → decrypt password-protected PDF
  2. casparser library → MF folio data (CAMS / KFin / NSDL MF portion)
  3. Docling  → table-structured extraction for all holdings (equities, ETFs, SGBs, MF demat)
  4. Text fallback → NSDL/CDSL block-format equity holdings missed by tables
  5. Merge (casparser authoritative for MF folios; Docling fills demat equity gaps)

No data leaves the server.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ISIN_RE = re.compile(r'\bIN[A-Z0-9]{10}\b')


def is_available() -> bool:
    try:
        import docling   # noqa: F401
        import fitz      # noqa: F401
        return True
    except ImportError:
        return False


# ── PDF decryption ────────────────────────────────────────────────────

def _decrypt_pdf(pdf_bytes: bytes, password: str = "") -> bytes:
    """Open + decrypt with PyMuPDF; return raw bytes without encryption."""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.is_encrypted:
        ok = doc.authenticate(password or "")
        if not ok:
            raise ValueError("PDF password rejected")
    buf = io.BytesIO()
    doc.save(buf, encryption=fitz.PDF_ENCRYPT_NONE, garbage=0, deflate=False)
    doc.close()
    return buf.getvalue()


# ── Helpers ───────────────────────────────────────────────────────────

def _num(val: Any, default: float = 0.0) -> float:
    try:
        return float(str(val).replace(",", "").replace("₹", "").strip())
    except (ValueError, AttributeError, TypeError):
        return default


def _classify_asset(name: str, isin: str = "") -> str:
    n = name.lower()
    if isin.startswith("IN0"):              # SGB / Govt bond ISIN prefix
        return "gold"
    if re.search(r'\bsgb\b', n) or "sovereign gold bond" in n:
        return "gold"
    if any(k in n for k in [" etf", "bees", "exchange traded"]):
        return "etf"
    if isin.startswith("INF"):          # AMFI-registered MF
        return "mutual_fund"
    if any(k in n for k in ["fund", "folio"]):
        return "mutual_fund"
    return "equity"


def _classify_sector(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ["index", "nifty", "sensex", "bees"]):       return "Index"
    if any(k in n for k in ["small cap", "smallcap"]):                   return "Small Cap"
    if any(k in n for k in ["mid cap", "midcap"]):                       return "Mid Cap"
    if any(k in n for k in ["large cap", "largecap", "bluechip"]):       return "Large Cap"
    if any(k in n for k in ["flexi", "multi cap", "multicap"]):          return "Flexi Cap"
    if any(k in n for k in ["balanced", "hybrid", "advantage"]):         return "Balanced"
    if any(k in n for k in ["elss", "tax saver", "tax saving"]):         return "ELSS"
    if any(k in n for k in ["gold", "sgb", "sovereign"]):                return "Gold"
    if any(k in n for k in ["debt", "bond", "gilt", "liquid",
                              "money market", "overnight", "credit",
                              "arbitrage"]):                              return "Debt"
    if any(k in n for k in ["international", "global", "nasdaq"]):       return "International"
    return "Other"


# ── Table parsing ─────────────────────────────────────────────────────

def _find_col(headers: List[str], candidates: List[str]) -> Optional[int]:
    for i, h in enumerate(headers):
        h_low = (h or "").lower()
        for c in candidates:
            if c in h_low:
                return i
    return None


def _parse_table(grid: List[List[str]]) -> List[Dict[str, Any]]:
    """Convert a Docling table grid → holdings list.
    Returns [] when the table is not a holdings table.
    """
    if len(grid) < 2:
        return []

    headers = [str(c).strip() for c in grid[0]]

    # Must have an ISIN column (by header or by value in first data rows)
    isin_col = _find_col(headers, ["isin"])
    if isin_col is None:
        for row in grid[1:4]:
            if row and ISIN_RE.search(str(row[0]).strip()):
                isin_col = 0
                break
    if isin_col is None:
        return []

    name_col  = _find_col(headers, ["security", "company", "scheme", "fund", "description", "name"])
    qty_col   = _find_col(headers, ["quantity", "qty", "shares", "units", "balance", "no. of unit"])
    price_col = _find_col(headers, ["market price", "nav", "price", "rate"])
    value_col = _find_col(headers, ["market value", "current value", "value", "amount"])
    cost_col  = _find_col(headers, ["avg cost", "cost", "purchase price", "avg. cost"])
    folio_col = _find_col(headers, ["folio"])

    _PLEDGE_RE = re.compile(r'pledged|unconfirmed pledge', re.IGNORECASE)

    holdings = []
    for row in grid[1:]:
        if not row or len(row) <= isin_col:
            continue
        cell_text = str(row[isin_col]).strip()
        m = ISIN_RE.search(cell_text)
        if not m:
            continue
        isin = m.group()

        # Company / fund name
        name = ""
        if name_col is not None and name_col < len(row):
            name = str(row[name_col]).strip()
        if not name:
            for j, cell in enumerate(row):
                if j == isin_col:
                    continue
                t = str(cell).strip()
                if len(t) > 5 and re.search(r'[A-Za-z]{3,}', t) and not re.match(r'^[\d,.₹ ]+$', t):
                    name = t
                    break
        if not name:
            continue

        # Skip pledged / lien sub-rows (NSDL italicised sub-entries)
        if _PLEDGE_RE.search(name):
            continue

        def _cell(col_idx):
            return row[col_idx] if col_idx is not None and col_idx < len(row) else None

        qty   = _num(_cell(qty_col))
        price = _num(_cell(price_col))
        value = _num(_cell(value_col))
        cost  = _num(_cell(cost_col))
        folio = str(_cell(folio_col) or "").strip()

        if price == 0 and qty > 0 and value > 0:
            price = round(value / qty, 4)
        if qty == 0 and price > 0 and value > 0:
            qty = round(value / price, 4)

        # Skip zero-balance holdings (closed positions shown in NSDL tables)
        if qty == 0 and value == 0:
            continue

        asset_type = _classify_asset(name, isin)
        holdings.append({
            "name":          name,
            "ticker":        isin,
            "asset_type":    asset_type,
            "quantity":      round(qty,  4),
            "buy_price":     round(cost or price, 4),
            "current_price": round(price, 4),
            "sector":        _classify_sector(name),
            "folio_number":  folio,
            "parsed_by":     "docling",
        })

    return holdings


# ── Text-block fallback (NSDL/CDSL block-format) ──────────────────────

def _parse_equity_blocks(text: str) -> List[Dict[str, Any]]:
    """Extract equity holdings from NSDL/CDSL CAS text when tables miss them.

    Block format example:
        ISIN: INE002A01018
        Reliance Industries Limited
        Balance: 100    Market Price: 2,450.00    Market Value: 2,45,000.00
    """
    # Only process demat CAS pages
    if not any(kw in text for kw in [
        "NATIONAL SECURITIES DEPOSITORY", "CENTRAL DEPOSITORY SERVICES",
        "NSDL", "CDSL", "DP Id", "Client Id", "Depository",
    ]):
        return []

    holdings = []
    seen: set = set()

    for m in ISIN_RE.finditer(text):
        isin = m.group()
        if isin in seen:
            continue

        ctx   = text[m.start(): m.start() + 500]
        lines = [ln.strip() for ln in ctx.split("\n") if ln.strip()]

        name  = ""
        qty   = 0.0
        price = 0.0
        value = 0.0

        for ln in lines[1:8]:
            if ISIN_RE.search(ln):   # stop at the next holding's ISIN line
                break
            # Named-value pairs: "Balance: 100  Market Price: 2,450.00"
            kv = dict(re.findall(r'([A-Za-z ]+?)\s*[:\-]\s*([\d,]+\.?\d*)', ln))
            if kv:
                for k, v in kv.items():
                    kl = k.lower().strip()
                    if any(t in kl for t in ["balance", "qty", "quantity", "shares", "units"]):
                        qty = _num(v)
                    elif any(t in kl for t in ["market price", "price", "nav", "rate"]):
                        price = _num(v)
                    elif any(t in kl for t in ["value", "amount"]):
                        value = _num(v)
            elif re.search(r'[A-Za-z]{3,}', ln) and not re.match(r'^[\d,.\s]+$', ln):
                if not name:
                    name = ln

        if not name or (qty == 0 and value == 0):
            continue

        if price == 0 and qty > 0 and value > 0:
            price = round(value / qty, 4)

        seen.add(isin)
        asset_type = _classify_asset(name, isin)
        holdings.append({
            "name":          name,
            "ticker":        isin,
            "asset_type":    asset_type,
            "quantity":      round(qty,  4),
            "buy_price":     round(price, 4),
            "current_price": round(price, 4),
            "sector":        _classify_sector(name),
            "parsed_by":     "docling_text",
        })

    logger.info("docling_cas_parser: text fallback → %d equity blocks", len(holdings))
    return holdings


# ── Public entry point ─────────────────────────────────────────────────

def parse_with_docling(
    pdf_bytes: bytes,
    password: str = "",
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Parse CAS PDF — fully local, no external API calls.

    Returns (holdings, normalized_txns_dict).
    """
    from docling.datamodel.base_models import DocumentStream
    from docling.document_converter import DocumentConverter
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    # ── Step 1: casparser (fast, MF-folio-specialised) ────────────────
    cas_lib_data: Optional[Dict] = None
    cas_lib_holdings: List[Dict] = []
    try:
        import casparser
        cas_lib_data = casparser.read_cas_pdf(
            io.BytesIO(pdf_bytes), password or "", output="dict"
        )
        from helpers.parsing import convert_casparser_to_holdings, _normalize_casparser_folios
        cas_lib_holdings = convert_casparser_to_holdings(cas_lib_data)
        logger.info("docling_cas_parser: casparser → %d MF holdings", len(cas_lib_holdings))
    except Exception as exc:
        err = str(exc).lower()
        if any(t in err for t in ["password", "incorrect", "decrypt", "protected"]):
            raise ValueError(f"PDF password rejected: {exc}") from exc
        logger.debug("docling_cas_parser: casparser skipped (%s)", exc)

    # ── Step 2: decrypt for Docling ───────────────────────────────────
    try:
        decrypted = _decrypt_pdf(pdf_bytes, password)
    except ValueError:
        raise  # propagate wrong-password errors

    # ── Step 3: Docling table + text extraction ────────────────────────
    pipeline_options = PdfPipelineOptions(do_table_structure=True)
    source = DocumentStream(name="cas.pdf", stream=io.BytesIO(decrypted))
    converter = DocumentConverter()
    result = converter.convert(source)

    doc_holdings: List[Dict] = []

    # Tables first
    for table_item in result.document.tables:
        grid = [[cell.text for cell in row] for row in table_item.data.grid]
        th = _parse_table(grid)
        if th:
            logger.info("docling_cas_parser: table → %d holdings", len(th))
            doc_holdings.extend(th)

    # Text fallback for block-format NSDL/CDSL equity pages
    if not doc_holdings:
        full_text = result.document.export_to_text()
        doc_holdings = _parse_equity_blocks(full_text)

    # ── Step 4: merge (casparser owns MF folios; Docling fills equity gaps)
    seen_tickers = {h.get("ticker", "").upper() for h in cas_lib_holdings if h.get("ticker")}
    merged: List[Dict] = list(cas_lib_holdings)
    for h in doc_holdings:
        t = (h.get("ticker") or "").upper()
        if t and t in seen_tickers:
            continue   # casparser already has this — trust its richer data
        merged.append(h)
        if t:
            seen_tickers.add(t)

    normalized: Optional[Dict] = None
    if cas_lib_data:
        from helpers.parsing import _normalize_casparser_folios
        normalized = _normalize_casparser_folios(cas_lib_data)

    logger.info(
        "docling_cas_parser: merged %d holdings (docling=%d casparser=%d)",
        len(merged), len(doc_holdings), len(cas_lib_holdings),
    )
    return merged, normalized
