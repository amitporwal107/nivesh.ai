"""Claude Vision CAS Parser — alternative to casparser.in API.

Sends each PDF page as a PNG image to Anthropic Claude Sonnet 4.5 via
the emergentintegrations LlmChat helper. Claude returns a single JSON
object describing the entire NSDL Consolidated Account Statement
(holdings, transactions, accounts, investor info).

Usage:
    from services.claude_cas_parser import parse_with_claude_vision
    raw_json = await parse_with_claude_vision(pdf_bytes, password="ABCDE1234F")

Cost note: each page ≈ 1 image @ ~$0.005 with Sonnet 4.5. A typical
NSDL CAS is 8-15 pages → roughly $0.05-$0.08 per parse. Cached in
`cas_parsed_responses` so we never re-bill the same file.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default to Sonnet 4.5 — best vision quality for tabular data; user can
# override via DB setting CAS_CLAUDE_MODEL.
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
MAX_PAGES = 24             # safety cap — most CAS PDFs are 8-15 pages
MAX_BATCH_PAGES = 8        # Claude Sonnet 4.5 handles 8 images comfortably in a single request
DEFAULT_DPI = 100          # tuned for legibility of CAS tables vs payload size
MAX_PARALLEL_BATCHES = 2   # 2 parallel calls avoids Anthropic rate-limit throttling
JPEG_QUALITY = 78          # JPEG is ~3-4× smaller than PNG for the same readable quality
PER_BATCH_TIMEOUT = 180    # each Claude call gets up to 3 min before we fail-fast


# ── Extraction prompt ──────────────────────────────────────────────────
# Mirrors the user-provided CAS_PARSER.txt schema verbatim so downstream
# mappers can rely on a stable shape.
EXTRACTION_PROMPT = """You are a financial-data extraction engine. The user has uploaded one
or more PAGE IMAGES of an NSDL Consolidated Account Statement (CAS).

Your job: read every page carefully and emit a SINGLE JSON object that
captures the entire statement. Return ONLY valid JSON — no markdown
fences, no commentary, no preamble.

Required schema (use null when a field is missing):
{
  "statement_info":     {"depository": "NSDL", "id": "...", "statement_type": "...", "period": "..."},
  "investor_info":      {"name": "...", "pan": "...", "address": "..."},
  "portfolio_summary":  {
                          "total_value_inr": 0.0,
                          "asset_allocation": [
                            {"asset_class": "Equities (E)", "value_inr": 0.0, "percentage": 0.0}
                          ]
                        },
  "portfolio_value_trend": [{"month": "FEB", "year": 2025, "value_inr": 0.0}],
  "accounts": [
    {"type": "NSDL Demat Account", "broker": "...", "dp_id": "...",
     "client_id": "...", "value_inr": 0.0}
  ],
  "holdings": {
    "equities": [
      {"isin": "...", "stock_symbol": "...", "company_name": "...",
       "face_value_inr": 0.0, "num_shares": 0, "pledged_shares": 0,
       "market_price_inr": 0.0, "value_inr": 0.0}
    ],
    "preference_shares": [
      {"isin": "...", "company_name": "...", "face_value_inr": 0.0,
       "num_shares": 0, "market_price_inr": 0.0, "value_inr": 0.0,
       "note": "..."}
    ],
    "sovereign_gold_bonds": [
      {"isin": "...", "series": "...", "issuer": "...",
       "coupon_rate_pct": 0.0, "maturity_date": "YYYY-MM-DD",
       "num_units": 0, "face_value_per_unit_inr": 0.0,
       "market_price_per_unit_inr": 0.0, "value_inr": 0.0}
    ],
    "mutual_funds_demat": [
      {"isin": "...", "fund_name": "...", "num_units": 0.0,
       "nav_inr": 0.0, "value_inr": 0.0}
    ],
    "mutual_fund_folios": [
      {"isin": "...", "fund_name": "...", "folio_number": "...",
       "amc": "...", "num_units": 0.0,
       "avg_cost_per_unit_inr": 0.0, "total_cost_inr": 0.0,
       "current_nav_inr": 0.0, "current_value_inr": 0.0,
       "unrealised_pnl_inr": 0.0, "annualised_return_pct": 0.0}
    ]
  },
  "transactions": {
    "demat_transactions": [
      {"account_broker": "...", "isin": "...", "security_name": "...",
       "date": "YYYY-MM-DD", "order_no": "...", "description": "...",
       "instruction_details": "...", "opening_balance": 0.0,
       "debit": 0.0, "credit": 0.0, "closing_balance": 0.0,
       "category": "BUY|SELL|DIVIDEND|BONUS|TRANSFER|OTHER"}
    ],
    "mutual_fund_transactions": [
      {"isin": "...", "fund_name": "...", "folio_number": "...",
       "date": "YYYY-MM-DD", "transaction_type": "PURCHASE|SIP_PURCHASE|REDEMPTION|SWITCH_IN|SWITCH_OUT|DIVIDEND|STAMP_DUTY|OTHER",
       "amount_inr": 0.0, "stamp_duty_inr": 0.0, "nav_inr": 0.0,
       "price_inr": 0.0, "units": 0.0,
       "opening_balance_units": 0.0, "closing_balance_units": 0.0}
    ]
  }
}

Rules:
- All numbers MUST be JSON numbers (no commas, no ₹/INR symbols, no quotes).
- Dates MUST be ISO YYYY-MM-DD.
- For mutual fund transaction_type, classify based on the description:
  * "Purchase via SIP" / "SIP" / "Systematic" → "SIP_PURCHASE"
  * "Purchase" / "Allotment" / "Investment" → "PURCHASE"
  * "Redemption" / "Redeem" / "Withdrawal" → "REDEMPTION"
  * "Switch In" → "SWITCH_IN", "Switch Out" → "SWITCH_OUT"
  * "Dividend" / "IDCW" → "DIVIDEND"
  * "Stamp Duty" / "STT" / "TDS" → "STAMP_DUTY"
- If a section is empty or absent, return an empty array.
- Capture EVERY row in tables — do not summarise.
- Do not invent data; if you can't read it cleanly, set the field to null.
"""


# ── Provider toggle ───────────────────────────────────────────────────
def is_configured() -> bool:
    """True iff the EMERGENT_LLM_KEY (or override) is set, so Claude
    Vision can be invoked."""
    from helpers import secrets as _secrets
    key = _secrets.get("EMERGENT_LLM_KEY") or os.environ.get("EMERGENT_LLM_KEY")
    return bool(key)


def _api_key() -> Optional[str]:
    from helpers import secrets as _secrets
    return _secrets.get("EMERGENT_LLM_KEY") or os.environ.get("EMERGENT_LLM_KEY")


def _model() -> str:
    from helpers import secrets as _secrets
    return _secrets.get("CAS_CLAUDE_MODEL") or DEFAULT_MODEL


# ── PDF → page images ─────────────────────────────────────────────────
def _decrypt_and_render_pdf(content: bytes, password: str = "",
                             dpi: int = DEFAULT_DPI) -> List[bytes]:
    """Render every PDF page to a PNG byte array. Decrypts first when
    a password is supplied. Caps at MAX_PAGES to avoid runaway costs.
    """
    from pdf2image import convert_from_bytes, pdfinfo_from_bytes

    kwargs: Dict[str, Any] = {"dpi": dpi}
    if password:
        kwargs["userpw"] = password

    info = pdfinfo_from_bytes(content, **{k: v for k, v in kwargs.items() if k != "dpi"})
    total_pages = int(info.get("Pages", 0) or 0)
    if total_pages == 0:
        raise ValueError("PDF has 0 pages — file is corrupted or password rejected")
    if total_pages > MAX_PAGES:
        logger.warning(f"CAS PDF has {total_pages} pages — capping at {MAX_PAGES}")

    images = convert_from_bytes(content, **kwargs)[:MAX_PAGES]
    out: List[bytes] = []
    for img in images:
        # Convert to RGB → JPEG. JPEG is ~3-4× smaller than PNG for
        # screenshots of text/tables and Claude reads them just fine.
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        out.append(buf.getvalue())
    logger.info(
        f"Rendered {len(out)} pages @ {dpi}dpi JPEG, "
        f"avg {sum(len(b) for b in out) // max(len(out), 1) // 1024}KB/page"
    )
    return out


# ── Claude call ───────────────────────────────────────────────────────
class BudgetExceededError(RuntimeError):
    """Raised when the Emergent LLM key has run out of budget. Surfaces
    in the API response so the MFD UI can prompt the admin to top up
    instead of silently retrying for minutes."""


async def _ask_claude_for_json(images: List[bytes], session_id: str) -> Dict[str, Any]:
    """Send a batch of base64 images to Claude with the extraction prompt
    and return the parsed JSON dict. Raises on hard failures."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

    api_key = _api_key()
    if not api_key:
        raise RuntimeError("EMERGENT_LLM_KEY missing — cannot call Claude Vision")

    chat = LlmChat(
        api_key=api_key,
        session_id=session_id,
        system_message=(
            "You are a precise financial-document extractor. "
            "You always respond with a single valid JSON object — no prose, "
            "no markdown fences."
        ),
    ).with_model("anthropic", _model())

    file_contents = [ImageContent(image_base64=base64.b64encode(b).decode("ascii")) for b in images]
    msg = UserMessage(text=EXTRACTION_PROMPT, file_contents=file_contents)

    try:
        raw = await chat.send_message(msg)
    except Exception as e:
        # Surface budget errors immediately — do NOT retry, the next call
        # will fail with the exact same error. Admin needs to top up.
        emsg = str(e)
        if "Budget has been exceeded" in emsg or "Max budget" in emsg:
            raise BudgetExceededError(
                "Emergent LLM key budget exhausted. Top up at "
                "Profile → Universal Key → Add Balance."
            ) from e
        raise
    return _coerce_json(raw)


def _coerce_json(s: str) -> Dict[str, Any]:
    """Parse a Claude reply into a dict. Strips markdown fences and
    falls back to greedy `{...}` capture if the reply has prose."""
    if not s:
        raise ValueError("Empty response from Claude")
    text = s.strip()
    # Strip ```json ... ``` fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Greedy fallback — last-chance attempt to find the outermost object
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError as e:
            raise ValueError(f"Claude returned non-JSON: {e}") from e
    raise ValueError("Claude returned no parsable JSON")


# ── Multi-batch merge ─────────────────────────────────────────────────
def _merge(into: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a follow-up batch's JSON into the running aggregate. We
    extend list-typed children (holdings.*, transactions.*, accounts,
    portfolio_value_trend) and fill scalar/object children only when
    missing in `into`.
    """
    if not into:
        return dict(extra)

    # Statement / investor — keep first non-null
    for top in ("statement_info", "investor_info"):
        if not into.get(top) and extra.get(top):
            into[top] = extra[top]

    # Portfolio summary — total_value_inr from latest, allocation from latest
    if not into.get("portfolio_summary") and extra.get("portfolio_summary"):
        into["portfolio_summary"] = extra["portfolio_summary"]

    # Trend / accounts → extend
    for k in ("portfolio_value_trend", "accounts"):
        if extra.get(k):
            into.setdefault(k, [])
            into[k].extend(extra[k] or [])

    # Holdings + transactions: extend per sub-key
    for parent in ("holdings", "transactions"):
        sub = extra.get(parent) or {}
        if not isinstance(sub, dict):
            continue
        into.setdefault(parent, {})
        for sk, rows in sub.items():
            if not isinstance(rows, list):
                continue
            into[parent].setdefault(sk, [])
            into[parent][sk].extend(rows)

    return into


# ── Public entry point ────────────────────────────────────────────────
async def parse_with_claude_vision(content: bytes, password: str = "") -> Optional[Dict[str, Any]]:
    """Parse a CAS PDF via Claude Vision. Returns the raw extracted
    JSON dict (Claude's shape, NOT the casparser.in shape) — call
    `claude_cas_mapper.map_to_holdings_and_normalized()` to get the
    internal formats. Returns None if Claude isn't configured.
    """
    if not is_configured():
        logger.warning("Claude Vision not configured (EMERGENT_LLM_KEY missing)")
        return None

    try:
        page_pngs = _decrypt_and_render_pdf(content, password=password)
    except Exception as e:
        logger.error(f"PDF render failed: {e}")
        raise

    if not page_pngs:
        return None

    logger.info(
        f"Claude Vision: parsing {len(page_pngs)} pages in batches of {MAX_BATCH_PAGES} "
        f"(parallelism={MAX_PARALLEL_BATCHES})"
    )

    # Build batches and dispatch them in parallel using asyncio.gather.
    # 22-page CAS @ 3 pages/batch = 8 batches; with parallelism=4 we
    # finish in 2 waves instead of 8 sequential calls (≈4× faster).
    session = f"cas_claude_{uuid.uuid4().hex[:10]}"
    batches: List[Tuple[str, List[bytes]]] = []
    for i in range(0, len(page_pngs), MAX_BATCH_PAGES):
        chunk = page_pngs[i:i + MAX_BATCH_PAGES]
        batch_id = f"{session}_b{i // MAX_BATCH_PAGES}"
        batches.append((batch_id, chunk))

    sem = asyncio.Semaphore(MAX_PARALLEL_BATCHES)

    async def _run_batch(batch_id: str, chunk: List[bytes]) -> Optional[Dict[str, Any]]:
        async with sem:
            try:
                return await asyncio.wait_for(
                    _ask_claude_for_json(chunk, session_id=batch_id),
                    timeout=PER_BATCH_TIMEOUT,
                )
            except BudgetExceededError:
                # Re-raise so gather() cancels the rest — no point continuing.
                raise
            except asyncio.TimeoutError:
                logger.warning(f"Claude batch {batch_id} timed out after {PER_BATCH_TIMEOUT}s")
                return None
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Claude batch {batch_id} failed: {e}")
                return None

    try:
        results = await asyncio.gather(*[_run_batch(b, c) for b, c in batches])
    except BudgetExceededError as e:
        logger.error(f"Claude Vision aborted: {e}")
        raise

    aggregate: Dict[str, Any] = {}
    for data in results:
        if data:
            aggregate = _merge(aggregate, data)

    if not aggregate:
        logger.error("Claude Vision returned no parseable batches")
        return None

    logger.info(
        f"Claude Vision parse done — "
        f"holdings={sum(len(v or []) for v in (aggregate.get('holdings') or {}).values())}, "
        f"txns={sum(len(v or []) for v in (aggregate.get('transactions') or {}).values())}"
    )
    return aggregate
