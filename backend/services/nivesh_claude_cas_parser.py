"""Nivesh Claude CAS Parser — direct Anthropic SDK, no third-party wrappers.

Replaces the emergentintegrations-based claude_cas_parser.py with a
self-contained implementation that uses the official anthropic Python SDK.
PDF pages are rendered via PyMuPDF (fitz) — no poppler/ImageMagick needed.

Key improvements over the legacy parser:
  • No EMERGENT_LLM_KEY dependency — uses ANTHROPIC_API_KEY
  • PyMuPDF is 5-10× faster than pdf2image for rendering
  • 6 pages/batch (vs 8) to stay inside Anthropic's image token budget
  • 4 parallel batches (vs 2) — roughly 2× throughput for long CAS PDFs
  • Prompt tuned for NSDL/CDSL/CAMS/KFin CAS specifics

Configuration (resolved from DB secrets then env):
    ANTHROPIC_API_KEY   — required (sk-ant-api03-...)
    CAS_CLAUDE_MODEL    — optional override (default: claude-sonnet-4-6)

Usage:
    from services.nivesh_claude_cas_parser import parse_with_claude
    raw = await parse_with_claude(pdf_bytes, password="ABCDE1234F")
    # raw is a dict in the same shape as claude_cas_parser.py output
    # feed it to claude_cas_mapper.map_to_internal() as usual
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_MODEL    = "claude-sonnet-4-6"
MAX_PAGES        = 30        # hard cap — most CAS PDFs are 8-20 pages
PAGES_PER_BATCH  = 6         # 6 pages × ~300KB JPEG ≈ 1.8MB per call, well inside limits
MAX_PARALLEL     = 4         # 4 concurrent Anthropic calls
DPI              = 120       # balanced: legible text without huge payloads
JPEG_QUALITY     = 82
PER_BATCH_TIMEOUT = 120      # seconds per Claude call before we abort that batch


# ── CAS extraction prompt ─────────────────────────────────────────────
# Designed for NSDL / CDSL demat CAS and CAMS / KFin mutual-fund CAS PDFs.
EXTRACTION_PROMPT = """You are a financial-document extraction engine processing an Indian
Consolidated Account Statement (CAS). The CAS may be issued by NSDL, CDSL,
CAMS, or KFintech and contains demat holdings (equities, ETFs, SGBs) and/or
mutual-fund folio holdings.

Return ONLY a single valid JSON object — no markdown, no prose, no fences.

JSON schema (use null for missing fields, [] for missing arrays):
{
  "statement_info": {
    "depository": "NSDL|CDSL|CAMS|KFINTECH",
    "statement_id": null,
    "statement_type": "Detailed|Summary",
    "period": "MMM YYYY to MMM YYYY"
  },
  "investor_info": {
    "name": null,
    "pan": null,
    "email": null,
    "mobile": null,
    "address": null
  },
  "portfolio_summary": {
    "total_value_inr": 0.0,
    "asset_allocation": [
      {"asset_class": "Equities (E)", "value_inr": 0.0, "percentage": 0.0}
    ]
  },
  "portfolio_value_trend": [
    {"month": "JAN", "year": 2025, "value_inr": 0.0}
  ],
  "accounts": [
    {
      "type": "NSDL Demat|CDSL Demat|MF Folio",
      "broker": null,
      "dp_id": null,
      "client_id": null,
      "value_inr": 0.0
    }
  ],
  "holdings": {
    "equities": [
      {
        "isin": "INE000A01000",
        "stock_symbol": null,
        "company_name": "FULL COMPANY NAME AS PRINTED",
        "face_value_inr": 0.0,
        "num_shares": 0,
        "pledged_shares": 0,
        "market_price_inr": 0.0,
        "value_inr": 0.0
      }
    ],
    "sovereign_gold_bonds": [
      {
        "isin": null,
        "series": "FULL SERIES NAME e.g. SGB 2023-24 Series III",
        "issuer": "RBI",
        "coupon_rate_pct": 0.0,
        "maturity_date": "YYYY-MM-DD",
        "num_units": 0.0,
        "face_value_per_unit_inr": 0.0,
        "market_price_per_unit_inr": 0.0,
        "value_inr": 0.0
      }
    ],
    "mutual_funds_demat": [
      {
        "isin": "INF000A01000",
        "fund_name": "FULL FUND NAME AS PRINTED",
        "num_units": 0.0,
        "nav_inr": 0.0,
        "value_inr": 0.0
      }
    ],
    "mutual_fund_folios": [
      {
        "isin": null,
        "fund_name": "FULL FUND NAME AS PRINTED",
        "folio_number": null,
        "amc": null,
        "num_units": 0.0,
        "avg_cost_per_unit_inr": 0.0,
        "total_cost_inr": 0.0,
        "current_nav_inr": 0.0,
        "current_value_inr": 0.0,
        "unrealised_pnl_inr": 0.0,
        "annualised_return_pct": 0.0
      }
    ]
  },
  "transactions": {
    "demat_transactions": [
      {
        "isin": null,
        "security_name": null,
        "date": "YYYY-MM-DD",
        "description": null,
        "opening_balance": 0.0,
        "debit": 0.0,
        "credit": 0.0,
        "closing_balance": 0.0
      }
    ],
    "mutual_fund_transactions": [
      {
        "isin": null,
        "fund_name": null,
        "folio_number": null,
        "date": "YYYY-MM-DD",
        "transaction_type": "SIP_PURCHASE|PURCHASE|REDEMPTION|SWITCH_IN|SWITCH_OUT|DIVIDEND|STAMP_DUTY|OTHER",
        "amount_inr": 0.0,
        "units": 0.0,
        "nav_inr": 0.0,
        "opening_balance_units": 0.0,
        "closing_balance_units": 0.0
      }
    ]
  }
}

STRICT RULES — follow exactly:
1. FULL NAMES: Never truncate company or fund names. Copy the exact text as printed.
   Wrong: "HDFC Balanced"   Right: "HDFC Balanced Advantage Fund Regular Plan Growth"
2. ISIN: Copy the 12-character ISIN exactly (format: INxxxxxxxx). It appears next to
   every equity and usually next to ETFs/demat MFs. Folio-mode MFs may not have ISIN.
3. NUMBERS: Plain JSON numbers only — no ₹, commas, INR, or quotes around numbers.
4. DATES: ISO format YYYY-MM-DD only.
5. ZERO QTY: Include holdings with 0 units only if explicitly shown as current balance.
   Do NOT include historical/closed positions.
6. DUPLICATES: One entry per holding line as printed. Different folios of the same fund
   are separate entries.
7. TRANSACTIONS: Classify transaction_type from description:
   "SIP" / "Systematic" → SIP_PURCHASE
   "Purchase" / "Allotment" → PURCHASE
   "Redemption" / "Withdrawal" → REDEMPTION
   "Switch In" → SWITCH_IN, "Switch Out" → SWITCH_OUT
   "Dividend" / "IDCW" → DIVIDEND
   "Stamp Duty" / "STT" / "TDS" → STAMP_DUTY
8. If a section is not present on these pages, return [].
9. Capture EVERY row — do not skip any holding or transaction.
"""


# ── Configuration ─────────────────────────────────────────────────────

def _api_key() -> str:
    from helpers import secrets as _secrets
    return _secrets.get("ANTHROPIC_API_KEY") or ""


def _model() -> str:
    from helpers import secrets as _secrets
    return _secrets.get("CAS_CLAUDE_MODEL") or DEFAULT_MODEL


def is_configured() -> bool:
    return bool(_api_key())


# ── PDF → JPEG page images ────────────────────────────────────────────

def _render_pages(pdf_bytes: bytes, password: str = "") -> List[bytes]:
    """Decrypt + render PDF to JPEG bytes via PyMuPDF (fitz).
    Much faster than pdf2image/poppler and has no system dependency.
    """
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.is_encrypted:
        result = doc.authenticate(password or "")
        if not result:
            raise ValueError(f"PDF password rejected")

    total = len(doc)
    if total == 0:
        raise ValueError("PDF has 0 pages — file corrupted or password wrong")
    if total > MAX_PAGES:
        logger.warning("CAS PDF has %d pages, capping at %d", total, MAX_PAGES)

    mat = fitz.Matrix(DPI / 72, DPI / 72)
    pages: List[bytes] = []
    for i, page in enumerate(doc):
        if i >= MAX_PAGES:
            break
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        pages.append(pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY))

    doc.close()
    avg_kb = sum(len(p) for p in pages) // max(len(pages), 1) // 1024
    logger.info("Rendered %d pages @ %ddpi JPEG, avg %dKB/page", len(pages), DPI, avg_kb)
    return pages


# ── Anthropic call ────────────────────────────────────────────────────

def _coerce_json(text: str) -> Dict[str, Any]:
    """Strip markdown fences and parse JSON. Fallback to greedy {…} scan."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError as exc:
            raise ValueError(f"Claude returned non-JSON: {exc}") from exc
    raise ValueError("No parseable JSON in Claude response")


def _call_claude_sync(page_jpegs: List[bytes], model: str, api_key: str) -> Dict[str, Any]:
    """Synchronous Anthropic API call. Run via asyncio.to_thread() in async context."""
    import anthropic

    content: List[Dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(img).decode(),
            },
        }
        for img in page_jpegs
    ]
    content.append({"type": "text", "text": EXTRACTION_PROMPT})

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=8192,
        system=(
            "You are a precise financial-document extractor. "
            "You always respond with a single valid JSON object — no prose, no markdown."
        ),
        messages=[{"role": "user", "content": content}],
    )
    return _coerce_json(msg.content[0].text)


# ── Batch merge ───────────────────────────────────────────────────────

def _merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """Merge extra batch result into the running aggregate.
    Scalars/objects: first non-null wins. Lists: always extend.
    """
    if not base:
        return dict(extra)

    for key in ("statement_info", "investor_info", "portfolio_summary"):
        if not base.get(key) and extra.get(key):
            base[key] = extra[key]

    for key in ("portfolio_value_trend", "accounts"):
        if extra.get(key):
            base.setdefault(key, [])
            base[key].extend(extra[key])

    for section in ("holdings", "transactions"):
        sub = extra.get(section) or {}
        if not isinstance(sub, dict):
            continue
        base.setdefault(section, {})
        for subkey, rows in sub.items():
            if isinstance(rows, list):
                base[section].setdefault(subkey, [])
                base[section][subkey].extend(rows)

    return base


# ── Public entry point ────────────────────────────────────────────────

async def parse_with_claude(pdf_bytes: bytes, password: str = "") -> Optional[Dict[str, Any]]:
    """Parse a CAS PDF using the Anthropic API directly.

    Returns the raw extracted JSON dict in the same shape as
    `claude_cas_parser.parse_with_claude_vision()`. Feed the result to
    `claude_cas_mapper.map_to_internal()` for the internal holdings format.

    Returns None if ANTHROPIC_API_KEY is not configured.
    """
    api_key = _api_key()
    if not api_key:
        logger.warning("nivesh_claude_cas_parser: ANTHROPIC_API_KEY not set")
        return None

    model = _model()

    # Render PDF pages (synchronous, CPU-bound — run in thread)
    try:
        page_jpegs = await asyncio.to_thread(_render_pages, pdf_bytes, password)
    except Exception as exc:
        logger.error("PDF render failed: %s", exc)
        raise

    if not page_jpegs:
        return None

    # Split into batches
    batches: List[List[bytes]] = [
        page_jpegs[i : i + PAGES_PER_BATCH]
        for i in range(0, len(page_jpegs), PAGES_PER_BATCH)
    ]
    logger.info(
        "nivesh_claude_cas_parser: %d pages → %d batches, parallelism=%d, model=%s",
        len(page_jpegs), len(batches), MAX_PARALLEL, model,
    )

    sem = asyncio.Semaphore(MAX_PARALLEL)

    async def _run(batch_idx: int, imgs: List[bytes]) -> Optional[Dict[str, Any]]:
        async with sem:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(_call_claude_sync, imgs, model, api_key),
                    timeout=PER_BATCH_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("Batch %d timed out after %ds", batch_idx, PER_BATCH_TIMEOUT)
                return None
            except Exception as exc:  # noqa: BLE001
                logger.warning("Batch %d failed: %s", batch_idx, exc)
                return None

    results = await asyncio.gather(*[_run(i, b) for i, b in enumerate(batches)])

    aggregate: Dict[str, Any] = {}
    for data in results:
        if data:
            aggregate = _merge(aggregate, data)

    if not aggregate:
        logger.error("nivesh_claude_cas_parser: all batches returned no data")
        return None

    h_counts = {k: len(v) for k, v in (aggregate.get("holdings") or {}).items()}
    t_counts = {k: len(v) for k, v in (aggregate.get("transactions") or {}).items()}
    logger.info("Parse complete — holdings: %s  transactions: %s", h_counts, t_counts)
    return aggregate
