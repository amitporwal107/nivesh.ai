"""Hybrid CAS parser — fast path for the production upload flow.

Pipeline:
  1. SHA-256 cache check  → return cached parse if seen before
  2. Decrypt PDF          → reuses openai_cas_parser._decrypt_pdf
  3. Per-page text extract → PyMuPDF; classify each page
  4. Section detection    → semantic anchors, not coordinates
  5. Per-section extract  → Vision only on sections that need it,
                            parallel via asyncio.gather (cap 4)
  6. Pydantic validation  → CASExtraction
  7. Reconciliation       → qty×price ≈ value; section totals
  8. Retry-on-mismatch    → bounded one Vision retry per dirty section
  9. Cache & return       → drop-in shape for claude_cas_mapper

Returns the same `(holdings, normalized, raw_payload, parser_source)`
tuple as `helpers.parsing.parse_cas_pdf_with_data` is contractually
expected to surface. The orchestration here only produces the *raw*
payload + a parser_source tag; the helpers layer feeds it into
`claude_cas_mapper.map_to_internal`.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
from helpers.openai_key import get_openai_api_key
import re
from typing import Any, Dict, List, Optional, Tuple

import openai

from services import cas_sections
from services.cas_reconciler import reconcile
from services.cas_schema import CASExtraction

logger = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────
DEFAULT_MODEL = "gpt-5"
DEFAULT_REASONING_EFFORT = "medium"
MAX_PARALLEL_SECTIONS = 4       # for text-detected per-section mode
MAX_PARALLEL_BLIND = 2          # blind mode sends bigger payloads → less concurrency to avoid TPM throttling
PER_SECTION_TIMEOUT = 120       # seconds (per call) for per-section mode
BLIND_TIMEOUT = 210             # seconds (per call) for blind mode (4 dense images)
PER_SECTION_MAX_TOKENS = 8000
BLIND_MAX_TOKENS = 16000
MAX_VISION_PAGES_PER_CALL = 4   # batch a section's pages into one call
BLIND_PAGES_PER_CALL = 3        # blind mode keeps payloads smaller per call
CACHE_TTL_S = 30 * 24 * 3600    # 30 days
CACHE_NAMESPACE = "cas:parsed:v1"


# ── OpenAI client ─────────────────────────────────────────────────────
_client: Optional[openai.AsyncOpenAI] = None


def _api_key() -> Optional[str]:
    try:
        from helpers import secrets as _secrets
        key = _secrets.get("OPENAI_API_KEY")
        if key:
            return key
    except ImportError:
        pass
    return get_openai_api_key() or None


def _model() -> str:
    try:
        from helpers import secrets as _secrets
        return _secrets.get("CAS_OPENAI_MODEL") or DEFAULT_MODEL
    except ImportError:
        return os.environ.get("CAS_OPENAI_MODEL") or DEFAULT_MODEL


def _get_client() -> openai.AsyncOpenAI:
    global _client
    key = _api_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing")
    if _client is None or getattr(_client, "_cached_key", None) != key:
        _client = openai.AsyncOpenAI(api_key=key)
        _client._cached_key = key  # type: ignore[attr-defined]
    return _client


def is_configured() -> bool:
    return bool(_api_key())


# ── Per-section extraction prompts ────────────────────────────────────
# Vision is asked for ONE section at a time so token budgets stay tight
# and the schema is unambiguous. The output for each section is merged
# back into a single CASExtraction at the end.

_SYSTEM = (
    "You are a precise financial-document extractor. "
    "You always respond with a single valid JSON object — no prose, "
    "no markdown fences."
)

_SECTION_PROMPTS: Dict[str, str] = {
    cas_sections.SECTION_EQUITY: """Extract every EQUITY holding row visible in the page images.
Return ONLY this JSON:
{"equities": [{"isin": "...", "stock_symbol": "...", "company_name": "...",
  "face_value_inr": 0.0, "num_shares": 0, "pledged_shares": 0,
  "market_price_inr": 0.0, "value_inr": 0.0}]}
Rules: ISINs are 12 chars starting with IN. All numbers are JSON numbers
(no commas, no ₹). Enumerate EVERY row — do not summarise.""",

    cas_sections.SECTION_PREF: """Extract every PREFERENCE SHARE holding row visible.
Return ONLY: {"preference_shares": [{"isin": "...", "company_name": "...",
  "face_value_inr": 0.0, "num_shares": 0, "market_price_inr": 0.0,
  "value_inr": 0.0, "note": "..."}]}""",

    cas_sections.SECTION_SGB: """Extract every Sovereign Gold Bond row visible.
Return ONLY: {"sovereign_gold_bonds": [{"isin": "...", "series": "...",
  "issuer": "...", "coupon_rate_pct": 0.0, "maturity_date": "YYYY-MM-DD",
  "num_units": 0, "face_value_per_unit_inr": 0.0,
  "market_price_per_unit_inr": 0.0, "value_inr": 0.0}]}
Rules: SGB ISINs start with IN0020. Per-unit prices, not totals.""",

    cas_sections.SECTION_MF_DEMAT: """Extract every Mutual Fund unit held in DEMAT form.
Return ONLY: {"mutual_funds_demat": [{"isin": "...", "fund_name": "...",
  "num_units": 0.0, "nav_inr": 0.0, "value_inr": 0.0}]}""",

    cas_sections.SECTION_MF_FOLIO: """Extract every Mutual Fund folio holding.
Return ONLY: {"mutual_fund_folios": [{"isin": "...", "fund_name": "...",
  "folio_number": "...", "amc": "...", "num_units": 0.0,
  "avg_cost_per_unit_inr": 0.0, "total_cost_inr": 0.0,
  "current_nav_inr": 0.0, "current_value_inr": 0.0,
  "unrealised_pnl_inr": 0.0, "annualised_return_pct": 0.0}]}""",

    cas_sections.SECTION_DEMAT_TXN: """Extract every demat transaction row visible.
Return ONLY: {"demat_transactions": [{"account_broker": "...",
  "isin": "...", "security_name": "...", "date": "YYYY-MM-DD",
  "order_no": "...", "description": "...", "instruction_details": "...",
  "opening_balance": 0.0, "debit": 0.0, "credit": 0.0,
  "closing_balance": 0.0, "category": "BUY|SELL|DIVIDEND|BONUS|TRANSFER|OTHER"}]}""",

    cas_sections.SECTION_MF_TXN: """Extract every mutual-fund transaction row visible.
Return ONLY: {"mutual_fund_transactions": [{"isin": "...", "fund_name": "...",
  "folio_number": "...", "date": "YYYY-MM-DD",
  "transaction_type": "PURCHASE|SIP_PURCHASE|REDEMPTION|SWITCH_IN|SWITCH_OUT|DIVIDEND|STAMP_DUTY|OTHER",
  "amount_inr": 0.0, "stamp_duty_inr": 0.0, "nav_inr": 0.0,
  "price_inr": 0.0, "units": 0.0, "opening_balance_units": 0.0,
  "closing_balance_units": 0.0}]}""",

    cas_sections.SECTION_SUMMARY: """Extract the portfolio summary block.
Return ONLY: {"portfolio_summary": {"total_value_inr": 0.0,
  "asset_allocation": [{"asset_class": "...", "value_inr": 0.0,
  "percentage": 0.0}]}, "statement_info": {"depository": "NSDL|CDSL",
  "id": "...", "statement_type": "...", "period": "..."},
  "investor_info": {"name": "...", "pan": "...", "address": "..."}}""",

    cas_sections.SECTION_INVESTOR: """Extract investor identity block.
Return ONLY: {"investor_info": {"name": "...", "pan": "...",
  "address": "..."}}""",
}


# Blind-mode prompt — used when text extraction fails and the section
# detector finds nothing. Asks GPT-5 to extract every section it can see
# in the page batch. Larger schema than per-section prompts but applied
# in parallel chunks of MAX_VISION_PAGES_PER_CALL pages.
_BLIND_PROMPT = """You are looking at PAGE IMAGES from an Indian Consolidated
Account Statement (CAS). Read every visible row and return ONE JSON object
covering everything on these pages. Use null when a field is missing.

{
  "statement_info":     {"depository": "NSDL|CDSL", "id": "...", "statement_type": "...", "period": "..."},
  "investor_info":      {"name": "...", "pan": "...", "address": "..."},
  "portfolio_summary":  {"total_value_inr": 0.0,
                          "asset_allocation": [{"asset_class": "...", "value_inr": 0.0, "percentage": 0.0}]},
  "accounts": [{"type": "...", "broker": "...", "dp_id": "...", "client_id": "...", "value_inr": 0.0}],
  "holdings": {
    "equities":             [{"isin": "...", "stock_symbol": "...", "company_name": "...",
                              "face_value_inr": 0.0, "num_shares": 0, "pledged_shares": 0,
                              "market_price_inr": 0.0, "value_inr": 0.0}],
    "preference_shares":    [{"isin": "...", "company_name": "...", "face_value_inr": 0.0,
                              "num_shares": 0, "market_price_inr": 0.0, "value_inr": 0.0,
                              "note": "..."}],
    "sovereign_gold_bonds": [{"isin": "...", "series": "...", "issuer": "...",
                              "coupon_rate_pct": 0.0, "maturity_date": "YYYY-MM-DD",
                              "num_units": 0, "face_value_per_unit_inr": 0.0,
                              "market_price_per_unit_inr": 0.0, "value_inr": 0.0}],
    "mutual_funds_demat":   [{"isin": "...", "fund_name": "...", "num_units": 0.0,
                              "nav_inr": 0.0, "value_inr": 0.0}],
    "mutual_fund_folios":   [{"isin": "...", "fund_name": "...", "folio_number": "...",
                              "amc": "...", "num_units": 0.0,
                              "avg_cost_per_unit_inr": 0.0, "total_cost_inr": 0.0,
                              "current_nav_inr": 0.0, "current_value_inr": 0.0,
                              "unrealised_pnl_inr": 0.0, "annualised_return_pct": 0.0}]
  },
  "transactions": {
    "demat_transactions":         [{"account_broker": "...", "isin": "...", "security_name": "...",
                                    "date": "YYYY-MM-DD", "order_no": "...", "description": "...",
                                    "instruction_details": "...", "opening_balance": 0.0,
                                    "debit": 0.0, "credit": 0.0, "closing_balance": 0.0,
                                    "category": "BUY|SELL|DIVIDEND|BONUS|TRANSFER|OTHER"}],
    "mutual_fund_transactions":   [{"isin": "...", "fund_name": "...", "folio_number": "...",
                                    "date": "YYYY-MM-DD",
                                    "transaction_type": "PURCHASE|SIP_PURCHASE|REDEMPTION|SWITCH_IN|SWITCH_OUT|DIVIDEND|STAMP_DUTY|OTHER",
                                    "amount_inr": 0.0, "stamp_duty_inr": 0.0, "nav_inr": 0.0,
                                    "price_inr": 0.0, "units": 0.0,
                                    "opening_balance_units": 0.0, "closing_balance_units": 0.0}]
  }
}

Rules:
- Enumerate EVERY row. Empty arrays only when a section is genuinely absent.
- ISINs are 12 chars starting with IN (SGBs start with IN0020).
- All numbers as JSON numbers (no commas, no ₹).
- Dates ISO YYYY-MM-DD."""


# ── Cache ─────────────────────────────────────────────────────────────
def _sha256(pdf_bytes: bytes, password: str) -> str:
    h = hashlib.sha256()
    h.update(pdf_bytes)
    if password:
        h.update(b"\x00")
        h.update(password.encode("utf-8"))
    return h.hexdigest()


async def _cache_get(sha: str) -> Optional[Dict[str, Any]]:
    try:
        from services.redis_client import cache_get
        payload = await cache_get(f"{CACHE_NAMESPACE}:{sha}")
        if payload:
            logger.info("hybrid_cas cache HIT sha=%s", sha[:12])
        return payload
    except Exception as e:  # noqa: BLE001
        logger.debug("hybrid_cas cache_get error: %s", e)
        return None


async def _cache_set(sha: str, payload: Dict[str, Any]) -> None:
    try:
        from services.redis_client import cache_set
        await cache_set(f"{CACHE_NAMESPACE}:{sha}", payload, ttl_s=CACHE_TTL_S)
    except Exception as e:  # noqa: BLE001
        logger.debug("hybrid_cas cache_set error: %s", e)


# ── JSON coercion ─────────────────────────────────────────────────────
def _coerce_json(s: str) -> Dict[str, Any]:
    if not s:
        return {}
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
        except json.JSONDecodeError:
            return {}
    return {}


# ── Vision call (per section) ─────────────────────────────────────────
async def _vision_call(
    prompt: str, page_images: List[bytes], *,
    max_tokens: int = PER_SECTION_MAX_TOKENS,
    timeout_s: int = PER_SECTION_TIMEOUT,
    reasoning: str = DEFAULT_REASONING_EFFORT,
) -> Dict[str, Any]:
    """Single OpenAI chat-completions call with a JSON-object response.
    Wraps the boilerplate (system prompt, reasoning_effort, timeout,
    error swallowing) shared by per-section and blind-mode extraction."""
    client = _get_client()
    model_name = _model()

    content_blocks: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for img_bytes in page_images:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        content_blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })

    extra: Dict[str, Any] = {}
    if model_name.startswith("gpt-5") or model_name.startswith("o"):
        extra["reasoning_effort"] = reasoning

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": content_blocks},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=max_tokens,
                **extra,
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning("vision_call timed out after %ss", timeout_s)
        return {}
    except Exception as e:  # noqa: BLE001
        logger.warning("vision_call failed: %s: %s", type(e).__name__, e)
        return {}

    raw = (response.choices[0].message.content or "").strip()
    return _coerce_json(raw)


async def _vision_extract_section(
    section_name: str,
    page_images: List[bytes],
    *,
    extra_hint: str = "",
) -> Dict[str, Any]:
    """Per-section extraction: tight prompt for the named section, then
    `_vision_call`. Caller controls page-image batching."""
    prompt = _SECTION_PROMPTS.get(section_name)
    if not prompt or not page_images:
        return {}
    if extra_hint:
        prompt = prompt + "\n\nHint: " + extra_hint
    return await _vision_call(prompt, page_images)


async def _vision_extract_blind(page_images: List[bytes]) -> Dict[str, Any]:
    """Blind-mode extraction: used when section detection finds nothing
    (typically image-only PDFs). Asks GPT-5 to return everything it sees
    in the page batch using the full schema.

    Uses reasoning_effort="minimal" — pure table OCR doesn't benefit from
    deep reasoning, and the dropped reasoning tokens shave ~3-5× off per-
    call latency."""
    if not page_images:
        return {}
    return await _vision_call(
        _BLIND_PROMPT, page_images,
        max_tokens=BLIND_MAX_TOKENS,
        timeout_s=BLIND_TIMEOUT,
        reasoning="minimal",
    )


def _chunk(seq: List[int], size: int) -> List[List[int]]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


# ── Section orchestration ─────────────────────────────────────────────
async def _extract_via_vision(
    pdf_bytes: bytes,
    sec: cas_sections.CASSection,
    rendered: Dict[int, bytes],
    sem: asyncio.Semaphore,
    *,
    hint: str = "",
) -> Dict[str, Any]:
    """Render the section's pages (if not yet rendered) and ship them to
    Vision. Splits long sections into multiple calls of at most
    MAX_VISION_PAGES_PER_CALL each, then merges the JSON outputs."""
    # Ensure all pages we need are rendered
    missing = [p for p in sec.pages if p not in rendered]
    if missing:
        more = await asyncio.to_thread(
            cas_sections.render_pages_as_jpeg, pdf_bytes, missing, dpi=180
        )
        rendered.update(more)

    page_groups = _chunk(sec.pages, MAX_VISION_PAGES_PER_CALL)
    merged: Dict[str, Any] = {}

    async def _run(group: List[int]) -> Dict[str, Any]:
        async with sem:
            imgs = [rendered[p] for p in group if p in rendered]
            if not imgs:
                return {}
            return await _vision_extract_section(sec.name, imgs, extra_hint=hint)

    chunks = await asyncio.gather(*[_run(g) for g in page_groups])
    for c in chunks:
        if not c:
            continue
        for k, v in c.items():
            if isinstance(v, list):
                merged.setdefault(k, []).extend(v)
            elif isinstance(v, dict):
                merged.setdefault(k, {}).update(v)
            elif k not in merged:
                merged[k] = v
    return merged


def _attach_section_to_extraction(
    raw: Dict[str, Any], section_name: str, section_json: Dict[str, Any]
) -> None:
    """Fold one section's extracted JSON into the running aggregate dict
    that we'll later validate with CASExtraction.model_validate."""
    if not section_json:
        return

    HOLDING_KEYS = {
        "equities", "preference_shares", "sovereign_gold_bonds",
        "mutual_funds_demat", "mutual_fund_folios",
    }
    TXN_KEYS = {"demat_transactions", "mutual_fund_transactions"}
    TOP_KEYS = {"portfolio_summary", "statement_info", "investor_info"}

    for k, v in section_json.items():
        if k in HOLDING_KEYS and isinstance(v, list):
            raw.setdefault("holdings", {}).setdefault(k, [])
            raw["holdings"][k].extend(v)
        elif k in TXN_KEYS and isinstance(v, list):
            raw.setdefault("transactions", {}).setdefault(k, [])
            raw["transactions"][k].extend(v)
        elif k in TOP_KEYS and isinstance(v, dict):
            # Prefer the first non-empty
            if not raw.get(k):
                raw[k] = v


# ── Public entry point ────────────────────────────────────────────────
async def parse_cas_hybrid(
    content: bytes, password: str = ""
) -> Optional[Tuple[Dict[str, Any], str]]:
    """Run the hybrid pipeline. Returns `(raw_extraction_dict, parser_source)`
    or `None` if Vision isn't configured / catastrophic failure.

    The `raw_extraction_dict` has the same shape as `openai_cas_parser`
    produces so `claude_cas_mapper.map_to_internal()` is a drop-in
    consumer.
    """
    if not is_configured():
        logger.info("hybrid_cas: OPENAI_API_KEY not configured — skipping")
        return None

    # 1. Decrypt + hash (hash the decrypted bytes so cache hits on
    #    pre-decrypted submissions too).
    try:
        from services.openai_cas_parser import _decrypt_pdf
        decrypted = _decrypt_pdf(content, password=password or "")
    except ValueError:
        raise  # password issue — bubble up
    except Exception as e:  # noqa: BLE001
        logger.error("hybrid_cas: decrypt failed: %s", e)
        return None

    sha = _sha256(decrypted, password or "")

    # 2. Cache check
    cached = await _cache_get(sha)
    if cached:
        return cached, "hybrid_cached"

    # 3. Page extract + section detection (CPU — run off the loop)
    pages = await asyncio.to_thread(cas_sections.extract_pages, decrypted)
    if not pages:
        logger.warning("hybrid_cas: no pages extracted")
        return None
    sections = cas_sections.group_sections(pages)
    diag = cas_sections.coverage_summary(pages, sections)
    logger.info("hybrid_cas page-scan: %s", diag)

    # If no recognisable sections were found we have a scanned / image-
    # only PDF. Switch to blind mode: render every page, chunk into
    # MAX_VISION_PAGES_PER_CALL-sized batches, and run them in parallel.
    # Still faster than the monolithic single-call path because we
    # parallelise over page batches.
    if not sections:
        logger.info(
            "hybrid_cas: no sections detected (likely scanned PDF), "
            "switching to blind parallel-page mode"
        )
        all_pages = [p.page_num for p in pages]
        rendered_blind = await asyncio.to_thread(
            cas_sections.render_pages_as_jpeg, decrypted, all_pages, dpi=150,
        )
        page_groups = _chunk(all_pages, BLIND_PAGES_PER_CALL)
        sem_blind = asyncio.Semaphore(MAX_PARALLEL_BLIND)

        async def _run_blind(group: List[int]) -> Dict[str, Any]:
            async with sem_blind:
                imgs = [rendered_blind[p] for p in group if p in rendered_blind]
                out = await _vision_extract_blind(imgs)
                # Per-chunk diagnostic — surfaces silent rate-limit drops
                h = (out or {}).get("holdings") or {}
                counts = {k: len(v) for k, v in h.items() if isinstance(v, list) and v}
                logger.info(
                    "hybrid_cas blind chunk pages=%s -> rows=%s",
                    group, counts or "EMPTY",
                )
                return out

        blind_results = await asyncio.gather(*[_run_blind(g) for g in page_groups])
        raw: Dict[str, Any] = {}
        for chunk_json in blind_results:
            for k, v in (chunk_json or {}).items():
                if k in ("holdings", "transactions") and isinstance(v, dict):
                    for sk, rows in v.items():
                        if isinstance(rows, list):
                            raw.setdefault(k, {}).setdefault(sk, []).extend(rows)
                elif k in ("statement_info", "investor_info",
                           "portfolio_summary") and isinstance(v, dict):
                    if not raw.get(k):
                        raw[k] = v
                elif k == "accounts" and isinstance(v, list):
                    raw.setdefault("accounts", []).extend(v)

        try:
            extraction = CASExtraction.model_validate(raw)
        except Exception:  # noqa: BLE001
            extraction = CASExtraction()
        n = extraction.holding_count()
        logger.info(
            "hybrid_cas (blind): %d page-chunks, holdings=%d",
            len(page_groups), n,
        )
        if n == 0:
            return None
        await _cache_set(sha, raw)
        return raw, "hybrid_blind"

    # 4. Pre-render the pages that we know will go to Vision. Sections
    #    that already have meaningful text can still be re-sent to Vision
    #    on reconciliation retry, so render lazily for those.
    target_pages = cas_sections.vision_target_pages(pages, sections)
    rendered: Dict[int, bytes] = {}
    if target_pages:
        rendered = await asyncio.to_thread(
            cas_sections.render_pages_as_jpeg, decrypted, target_pages, dpi=180,
        )

    # 5. Per-section extraction
    sem = asyncio.Semaphore(MAX_PARALLEL_SECTIONS)

    async def _process(sec: cas_sections.CASSection) -> Tuple[str, Dict[str, Any]]:
        # Vision is the only extractor in this iteration — pdfplumber-based
        # text-mode extraction can be a follow-up. Doing Vision per
        # section is still ~3-4× faster than the monolithic call because
        # each section gets a tighter prompt + smaller token budget +
        # runs in parallel.
        out = await _extract_via_vision(decrypted, sec, rendered, sem)
        return sec.name, out

    section_results = await asyncio.gather(*[_process(s) for s in sections])

    raw: Dict[str, Any] = {}
    for name, data in section_results:
        _attach_section_to_extraction(raw, name, data)

    # 6. Validate
    try:
        extraction = CASExtraction.model_validate(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning("hybrid_cas: schema validation failed: %s", e)
        extraction = CASExtraction()  # fall through to retry

    # 7. Reconcile + bounded retry
    recon = reconcile(extraction)
    if not recon.ok and recon.dirty_sections:
        logger.info("hybrid_cas: retrying dirty sections=%s", recon.dirty_sections)
        retry_targets = [
            s for s in sections
            if s.name in recon.dirty_sections
        ]
        hint = (
            "The previous extraction had row totals that didn't match "
            "(qty × price != value). Re-extract each row carefully, "
            "preserving printed decimal places."
        )

        async def _retry(sec: cas_sections.CASSection) -> Tuple[str, Dict[str, Any]]:
            return sec.name, await _extract_via_vision(
                decrypted, sec, rendered, sem, hint=hint
            )

        retry_results = await asyncio.gather(*[_retry(s) for s in retry_targets])
        # Replace the dirty section's data with the retry payload.
        for name, data in retry_results:
            if not data:
                continue
            # Wipe + rewrite the list keys this section owns
            HOLDING_KEYS = {
                cas_sections.SECTION_EQUITY: "equities",
                cas_sections.SECTION_PREF: "preference_shares",
                cas_sections.SECTION_SGB: "sovereign_gold_bonds",
                cas_sections.SECTION_MF_DEMAT: "mutual_funds_demat",
                cas_sections.SECTION_MF_FOLIO: "mutual_fund_folios",
            }
            tgt = HOLDING_KEYS.get(name)
            if tgt and tgt in data:
                raw.setdefault("holdings", {})[tgt] = data[tgt]
        # Re-validate (best-effort; don't fail if still off)
        try:
            extraction = CASExtraction.model_validate(raw)
        except Exception:  # noqa: BLE001
            pass

    holding_count = extraction.holding_count()
    logger.info(
        "hybrid_cas: parse done — holdings=%d sections=%d "
        "vision_pages=%d row_warnings=%d total_warnings=%d",
        holding_count, len(sections), len(target_pages),
        len(recon.row_warnings), len(recon.total_warnings),
    )

    if holding_count == 0:
        # Nothing recognisable came back — let the caller try a fallback.
        return None

    # 8. Cache + return
    await _cache_set(sha, raw)
    return raw, "hybrid"
