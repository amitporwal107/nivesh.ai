"""LLM-powered financial data extractor.

Takes raw text (HTML / PDF text / XBRL JSON) from a company's result
document and extracts structured financial figures into a dict matching
the nidp.nse_financials_quarterly schema.

Backend selection (checked in order):
  1. OPENAI_API_KEY set  → OpenAI gpt-4o-mini
  2. ANTHROPIC_API_KEY set → Claude claude-haiku-4-5
Falls back gracefully if the LLM cannot find a number (returns None).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CLAUDE_MODEL = "claude-haiku-4-5-20251001"
_OPENAI_MODEL = "gpt-4o-mini"

_SYSTEM = """You are a financial data extraction assistant specialised in Indian company quarterly results.
Extract structured financial data from the provided document text.
Return ONLY valid JSON — no explanation, no markdown, no code fences.
All monetary values must be in Indian Rupees Crore (₹ Cr).
If a value is not found, use null.
Use negative numbers for losses/expenses where appropriate."""

_PROMPT_TEMPLATE = """Extract the quarterly financial results for {symbol} from the following document.

Document text:
---
{text}
---

Return JSON with exactly this structure:
{{
  "period_end": "YYYY-MM-DD",
  "period_start": "YYYY-MM-DD",
  "period_type": "quarterly",
  "consolidated": true or false,
  "audited": true or false,
  "revenue_from_ops_cr": number or null,
  "other_income_cr": number or null,
  "total_income_cr": number or null,
  "total_expenses_cr": number or null,
  "ebitda_cr": number or null,
  "finance_costs_cr": number or null,
  "depreciation_cr": number or null,
  "pbt_before_exc_cr": number or null,
  "exceptional_items_cr": number or null,
  "pbt_cr": number or null,
  "tax_expense_cr": number or null,
  "pat_cr": number or null,
  "pat_attrib_owners_cr": number or null,
  "eps_basic": number or null,
  "eps_diluted": number or null,
  "face_value": number or null,
  "total_equity_cr": number or null,
  "long_term_debt_cr": number or null,
  "short_term_debt_cr": number or null,
  "cash_and_equiv_cr": number or null,
  "interest_earned_cr": number or null,
  "interest_expended_cr": number or null,
  "nim_pct": number or null
}}"""


def _provider() -> str:
    """Return 'openai' or 'anthropic' based on which key is set."""
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "anthropic"


async def extract_financials(
    symbol: str,
    raw_text: str,
    source_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Extract structured financials from raw document text using the configured LLM.

    Returns a dict matching nse_financials_quarterly columns, or None on failure.
    """
    if not raw_text or len(raw_text) < 100:
        return None

    # Trim to 15k chars — enough for a full result page without burning tokens
    text = raw_text[:15_000]
    prompt = _PROMPT_TEMPLATE.format(symbol=symbol, text=text)

    try:
        if _provider() == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            resp = client.chat.completions.create(
                model=_OPENAI_MODEL,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = resp.choices[0].message.content.strip()
            tokens = resp.usage.prompt_tokens
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
            msg = client.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=1024,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            tokens = msg.usage.input_tokens

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        logger.info("llm_extractor: extracted financials for %s via %s (tokens=%d)", symbol, _provider(), tokens)
        return data
    except json.JSONDecodeError as e:
        logger.warning("llm_extractor: JSON parse failed for %s: %s", symbol, e)
        return None
    except Exception as e:
        logger.error("llm_extractor: extraction failed for %s: %s", symbol, e)
        return None


def parse_nse_xbrl_json(symbol: str, xbrl_text: str) -> Optional[dict[str, Any]]:
    """Parse NSE's structured XBRL comparator JSON response directly (no LLM needed)."""
    try:
        data = json.loads(xbrl_text)
    except Exception:
        return None

    rows = data if isinstance(data, list) else data.get("data", data.get("result", []))
    if not rows:
        return None

    # NSE XBRL comparator returns rows keyed by metric name
    # Latest quarter is usually rows[0]
    def _get(key: str) -> Optional[float]:
        for row in rows:
            if isinstance(row, dict):
                v = row.get(key)
                if v is not None:
                    try:
                        return float(str(v).replace(",", ""))
                    except (ValueError, TypeError):
                        pass
        return None

    return {
        "period_end":            None,  # to be filled by caller from event_calendar
        "consolidated":          False,
        "audited":               None,
        "revenue_from_ops_cr":   _get("totalIncome") or _get("revenue"),
        "total_income_cr":       _get("totalIncome"),
        "total_expenses_cr":     _get("totalExpenses"),
        "ebitda_cr":             _get("ebitda"),
        "pbt_cr":                _get("pbt"),
        "tax_expense_cr":        _get("tax"),
        "pat_cr":                _get("pat") or _get("netProfit"),
        "eps_basic":             _get("eps") or _get("basicEps"),
        "eps_diluted":           _get("dilutedEps"),
        "interest_earned_cr":    _get("interestEarned"),
        "interest_expended_cr":  _get("interestExpended"),
    }
