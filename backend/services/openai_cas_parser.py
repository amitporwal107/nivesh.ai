"""OpenAI Vision CAS Parser — official OpenAI SDK (GPT-5 vision).

Sends each PDF page as a JPEG image to GPT-5 via the official `openai`
Python SDK using OPENAI_API_KEY. GPT-5 returns a single JSON object
describing the entire NSDL or CDSL Consolidated Account Statement.

Mirrors the interface of `services.claude_cas_parser` so the calling
code (helpers/parsing.py → claude_cas_mapper.map_to_internal) is a
drop-in swap.

Usage:
    from services.openai_cas_parser import parse_with_openai_vision
    raw_json = await parse_with_openai_vision(pdf_bytes, password="ABCDE1234F")

Auth: reads `OPENAI_API_KEY` from `helpers.secrets` first (so admin
console updates take effect immediately), then env var.

Model: defaults to gpt-5 (flagship vision quality for dense tables).
Override via DB setting CAS_OPENAI_MODEL (e.g. "gpt-5-mini" for ~3×
cheaper / ~2× faster at moderate accuracy loss).
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import openai

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5"        # flagship — best vision OCR for CAS tables
MAX_PAGES = 24                 # safety cap — most CAS PDFs are 8-20 pages
MAX_BATCH_PAGES = 8            # 8 images per request is comfortable
DEFAULT_DPI = 150              # dense tables — higher than image-only docs need
MAX_PARALLEL_BATCHES = 2       # avoid OpenAI tier rate-limit throttling
JPEG_QUALITY = 85
PER_BATCH_TIMEOUT = 120        # 2 min per batch — fail fast for SLA visibility


# ── Extraction prompt ──────────────────────────────────────────────────
# Same schema as the Claude parser so downstream mappers are unchanged.
# Generalized from "NSDL only" to "NSDL or CDSL" since CDSL is also valid.
EXTRACTION_PROMPT = """You are a financial-data extraction engine. The user has uploaded one
or more PAGE IMAGES of an Indian Consolidated Account Statement (CAS).
The statement is issued by either NSDL or CDSL — read the page header
to identify which depository it is.

Your job: read every page carefully and emit a SINGLE JSON object that
captures the entire statement. Return ONLY valid JSON — no markdown
fences, no commentary, no preamble.

Required schema (use null when a field is missing):
{
  "statement_info":     {"depository": "NSDL|CDSL", "id": "...", "statement_type": "...", "period": "..."},
  "investor_info":      {"name": "...", "pan": "...", "address": "..."},
  "portfolio_summary":  {
                          "total_value_inr": 0.0,
                          "asset_allocation": [
                            {"asset_class": "Equities (E)", "value_inr": 0.0, "percentage": 0.0}
                          ]
                        },
  "portfolio_value_trend": [{"month": "FEB", "year": 2025, "value_inr": 0.0}],
  "accounts": [
    {"type": "NSDL Demat Account | CDSL Demat Account | Mutual Fund Folio",
     "broker": "...", "dp_id": "...", "client_id": "...", "value_inr": 0.0}
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
       "date": "YYYY-MM-DD",
       "transaction_type": "PURCHASE|SIP_PURCHASE|REDEMPTION|SWITCH_IN|SWITCH_OUT|DIVIDEND|STAMP_DUTY|OTHER",
       "amount_inr": 0.0, "stamp_duty_inr": 0.0, "nav_inr": 0.0,
       "price_inr": 0.0, "units": 0.0,
       "opening_balance_units": 0.0, "closing_balance_units": 0.0}
    ]
  }
}

Rules:
- All numbers MUST be JSON numbers (no commas, no ₹/INR symbols, no quotes).
- Dates MUST be ISO YYYY-MM-DD.
- ISINs are exactly 12 characters starting with "IN" — double-check digits
  against the company name on the same row before emitting.
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

SYSTEM_PROMPT = (
    "You are a precise financial-document extractor. "
    "You always respond with a single valid JSON object — no prose, "
    "no markdown fences."
)


# ── Provider toggle ───────────────────────────────────────────────────
def is_configured() -> bool:
    """True iff OPENAI_API_KEY is set, so GPT-5 Vision can be invoked."""
    return bool(_api_key())


def _api_key() -> Optional[str]:
    try:
        from helpers import secrets as _secrets
        key = _secrets.get("OPENAI_API_KEY")
        if key:
            return key
    except ImportError:
        pass
    return os.environ.get("OPENAI_API_KEY")


def _model() -> str:
    try:
        from helpers import secrets as _secrets
        return _secrets.get("CAS_OPENAI_MODEL") or DEFAULT_MODEL
    except ImportError:
        return os.environ.get("CAS_OPENAI_MODEL") or DEFAULT_MODEL


_client: Optional[openai.AsyncOpenAI] = None


def _get_client() -> openai.AsyncOpenAI:
    """Lazy client init. Re-creates if the API key changes between calls."""
    global _client
    key = _api_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing — cannot call GPT-5 Vision")
    if _client is None or getattr(_client, "_cached_key", None) != key:
        _client = openai.AsyncOpenAI(api_key=key)
        _client._cached_key = key  # type: ignore[attr-defined]
    return _client


# ── PDF → page images ─────────────────────────────────────────────────
def _decrypt_and_render_pdf(content: bytes, password: str = "",
                             dpi: int = DEFAULT_DPI) -> List[bytes]:
    """Render every PDF page to a JPEG byte array. Decrypts first when
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
        logger.warning("CAS PDF has %s pages — capping at %s", total_pages, MAX_PAGES)

    images = convert_from_bytes(content, **kwargs)[:MAX_PAGES]
    out: List[bytes] = []
    for img in images:
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


# ── GPT-5 call ────────────────────────────────────────────────────────
async def _ask_openai_for_json(images: List[bytes]) -> Dict[str, Any]:
    """Send a batch of base64 images to GPT-5 with the extraction prompt
    and return the parsed JSON dict. Raises on hard failures."""
    client = _get_client()

    user_content: List[Dict[str, Any]] = [{"type": "text", "text": EXTRACTION_PROMPT}]
    for img_bytes in images:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })

    # GPT-5 uses `max_completion_tokens`; older models used `max_tokens`.
    # `response_format={"type": "json_object"}` forces valid JSON output.
    response = await client.chat.completions.create(
        model=_model(),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=16000,
    )

    raw = (response.choices[0].message.content or "").strip()
    return _coerce_json(raw)


def _coerce_json(s: str) -> Dict[str, Any]:
    """Parse a GPT-5 reply into a dict. Strips markdown fences and
    falls back to greedy `{...}` capture if the reply has prose."""
    if not s:
        raise ValueError("Empty response from GPT-5")
    text = s.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError as e:
            raise ValueError(f"GPT-5 returned non-JSON: {e}") from e
    raise ValueError("GPT-5 returned no parsable JSON")


# ── Multi-batch merge ─────────────────────────────────────────────────
def _merge(into: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a follow-up batch's JSON into the running aggregate."""
    if not into:
        return dict(extra)

    for top in ("statement_info", "investor_info"):
        if not into.get(top) and extra.get(top):
            into[top] = extra[top]

    if not into.get("portfolio_summary") and extra.get("portfolio_summary"):
        into["portfolio_summary"] = extra["portfolio_summary"]

    for k in ("portfolio_value_trend", "accounts"):
        if extra.get(k):
            into.setdefault(k, [])
            into[k].extend(extra[k] or [])

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
async def parse_with_openai_vision(content: bytes, password: str = "") -> Optional[Dict[str, Any]]:
    """Parse a CAS PDF via GPT-5 Vision. Returns the raw extracted JSON
    dict (same shape as claude_cas_parser) — call
    `claude_cas_mapper.map_to_holdings_and_normalized()` to get the
    internal formats. Returns None if OPENAI_API_KEY isn't configured.
    """
    if not is_configured():
        logger.warning("GPT-5 Vision not configured (OPENAI_API_KEY missing)")
        return None

    try:
        page_jpegs = _decrypt_and_render_pdf(content, password=password)
    except Exception as e:
        logger.error("PDF render failed: %s", e)
        raise

    if not page_jpegs:
        return None

    logger.info(
        f"GPT-5 Vision: parsing {len(page_jpegs)} pages in batches of {MAX_BATCH_PAGES} "
        f"(parallelism={MAX_PARALLEL_BATCHES}, model={_model()})"
    )

    batches: List[List[bytes]] = [
        page_jpegs[i:i + MAX_BATCH_PAGES]
        for i in range(0, len(page_jpegs), MAX_BATCH_PAGES)
    ]

    sem = asyncio.Semaphore(MAX_PARALLEL_BATCHES)

    async def _run_batch(idx: int, chunk: List[bytes]) -> Optional[Dict[str, Any]]:
        async with sem:
            try:
                return await asyncio.wait_for(
                    _ask_openai_for_json(chunk),
                    timeout=PER_BATCH_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("GPT-5 batch %d timed out after %ss", idx, PER_BATCH_TIMEOUT)
                return None
            except openai.AuthenticationError as e:
                logger.error("OpenAI auth failed — check OPENAI_API_KEY: %s", e)
                raise
            except openai.RateLimitError as e:
                logger.warning("GPT-5 batch %d rate-limited: %s", idx, e)
                return None
            except Exception as e:  # noqa: BLE001
                logger.warning("GPT-5 batch %d failed: %s", idx, e)
                return None

    results = await asyncio.gather(*[_run_batch(i, c) for i, c in enumerate(batches)])

    aggregate: Dict[str, Any] = {}
    for data in results:
        if data:
            aggregate = _merge(aggregate, data)

    if not aggregate:
        logger.error("GPT-5 Vision returned no parseable batches")
        return None

    logger.info(
        f"GPT-5 Vision parse done — "
        f"holdings={sum(len(v or []) for v in (aggregate.get('holdings') or {}).values())}, "
        f"txns={sum(len(v or []) for v in (aggregate.get('transactions') or {}).values())}"
    )
    return aggregate
