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
DEFAULT_REASONING_EFFORT = "medium"  # "low" causes the model to summarise instead of enumerating rows
MAX_PAGES = 24                 # safety cap — informational only when sending native PDF
SINGLE_CALL_TIMEOUT = 240      # one call sees the whole PDF — give it room
MAX_COMPLETION_TOKENS = 32000  # 20+ holdings + transactions can be sizable


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

CRITICAL extraction rules:
- You MUST enumerate EVERY row of EVERY holdings table on EVERY page.
  Do not stop after the portfolio summary on page 1. The statement has
  detailed holdings tables on later pages — open and read each one.
- All numbers MUST be JSON numbers (no commas, no ₹/INR symbols, no quotes).
- Dates MUST be ISO YYYY-MM-DD.
- ISINs are exactly 12 characters starting with "IN" — double-check digits
  against the company name on the same row before emitting.
- The statement contains SEPARATE sections for equities, preference shares,
  sovereign gold bonds (SGBs, ISINs starting with "IN0020..."), demat mutual
  funds, and mutual fund folios. Walk every section and emit every row.
- For mutual fund transaction_type, classify based on the description:
  * "Purchase via SIP" / "SIP" / "Systematic" → "SIP_PURCHASE"
  * "Purchase" / "Allotment" / "Investment" → "PURCHASE"
  * "Redemption" / "Redeem" / "Withdrawal" → "REDEMPTION"
  * "Switch In" → "SWITCH_IN", "Switch Out" → "SWITCH_OUT"
  * "Dividend" / "IDCW" → "DIVIDEND"
  * "Stamp Duty" / "STT" / "TDS" → "STAMP_DUTY"
- If a section is genuinely absent from the statement, return an empty
  array — but ONLY after confirming you've scanned every page.
- Capture EVERY row in EVERY table — do not summarise or truncate.
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


# ── PDF prep ──────────────────────────────────────────────────────────
def _decrypt_pdf(content: bytes, password: str = "") -> bytes:
    """Return a PDF byte string with any user-password removed. If no
    password is supplied and the PDF is encrypted, raises. If the PDF
    isn't encrypted, returns `content` unchanged.

    OpenAI's `type: "file"` content block accepts the PDF as-is — we no
    longer rasterize pages client-side; the server-side pipeline does
    rendering + OCR with whatever ChatGPT itself uses.
    """
    import fitz  # PyMuPDF

    doc = fitz.open(stream=content, filetype="pdf")
    try:
        if not doc.needs_pass:
            if doc.page_count == 0:
                raise ValueError("PDF has 0 pages — file is corrupted")
            return content
        if not password:
            raise ValueError("PDF is password-protected and no password was provided")
        if not doc.authenticate(password):
            raise ValueError("PDF password rejected")
        # Re-emit decrypted — `save(garbage=4)` rewrites the xref clean.
        out = io.BytesIO()
        doc.save(out, garbage=4, deflate=True, encryption=fitz.PDF_ENCRYPT_NONE)
        return out.getvalue()
    finally:
        doc.close()


# ── GPT-5 call ────────────────────────────────────────────────────────
async def _ask_openai_for_json(pdf_bytes: bytes) -> Dict[str, Any]:
    """Upload the CAS PDF via the Files API, then reference it by file_id
    in the chat message. This mirrors how the ChatGPT UI handles a PDF
    upload — OpenAI's server stores the file once and the server-side
    pipeline can apply richer preprocessing (page indexing, OCR, layout
    analysis) than the inline-base64 path.

    Cleans up the uploaded file after the call so it doesn't accumulate
    in your Files quota.
    """
    client = _get_client()
    model_name = _model()

    file_obj = await client.files.create(
        file=("cas.pdf", pdf_bytes, "application/pdf"),
        purpose="user_data",
    )
    logger.info(f"Uploaded PDF to Files API: file_id={file_obj.id} ({file_obj.bytes:,} bytes)")

    try:
        user_content = [
            {"type": "file", "file": {"file_id": file_obj.id}},
            {"type": "text", "text": EXTRACTION_PROMPT},
        ]

        extra: Dict[str, Any] = {}
        if model_name.startswith("gpt-5") or model_name.startswith("o"):
            extra["reasoning_effort"] = DEFAULT_REASONING_EFFORT

        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=MAX_COMPLETION_TOKENS,
            **extra,
        )

        raw = (response.choices[0].message.content or "").strip()
        logger.info(
            f"GPT-5 native-PDF parse: input={response.usage.prompt_tokens} "
            f"output={response.usage.completion_tokens} tokens "
            f"(reasoning={getattr(response.usage, 'completion_tokens_details', None)})"
        )
        return _coerce_json(raw)
    finally:
        # Best-effort delete — don't block on cleanup failures
        try:
            await client.files.delete(file_obj.id)
        except Exception as e:  # noqa: BLE001
            logger.debug("files.delete cleanup failed: %s", e)


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
        decrypted_pdf = _decrypt_pdf(content, password=password)
    except Exception as e:
        logger.error("PDF prep failed: %s", e)
        raise

    logger.info(
        f"GPT-5 Vision: native PDF call (size={len(decrypted_pdf):,} bytes, "
        f"model={_model()}, reasoning_effort={DEFAULT_REASONING_EFFORT})"
    )

    try:
        result = await asyncio.wait_for(
            _ask_openai_for_json(decrypted_pdf),
            timeout=SINGLE_CALL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error("GPT-5 call timed out after %ss", SINGLE_CALL_TIMEOUT)
        return None
    except openai.AuthenticationError:
        logger.error("OpenAI auth failed — check OPENAI_API_KEY")
        raise
    except openai.RateLimitError as e:
        logger.error("GPT-5 rate-limited: %s", e)
        return None
    except Exception as e:  # noqa: BLE001
        logger.error("GPT-5 call failed: %s", e)
        return None

    if not result:
        return None

    logger.info(
        f"GPT-5 native-PDF parse done — "
        f"holdings={sum(len(v or []) for v in (result.get('holdings') or {}).values())}, "
        f"txns={sum(len(v or []) for v in (result.get('transactions') or {}).values())}"
    )
    return result
