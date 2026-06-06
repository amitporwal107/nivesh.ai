"""Shared LLM config for all Copilot agent nodes.

Single source of truth for:
  * The model id — overridable via env so ops can pin to a specific
    snapshot (e.g. `gpt-5-2026-01-15`) without a code change.
  * The anti-hallucination clause appended to every specialist agent's
    system prompt — added centrally so we can't accidentally ship one
    agent with weaker guardrails than the others.
"""
from __future__ import annotations

import os


# Copilot model. Set to gpt-5.5 per product direction (2026-06). NOTE: this
# id is unverified against the live OpenAI account from CI — if the account's
# exact id differs (e.g. a dated snapshot) or lacks gpt-5.5 access, the nodes
# will 'model_not_found' and surface "trouble connecting to my AI engine".
# Override without a code change via the COPILOT_LLM_MODEL env var / GSM.
COPILOT_LLM_MODEL: str = os.environ.get("COPILOT_LLM_MODEL", "gpt-5.5")


def get_openai_api_key() -> str:
    """Resolve the OpenAI API key at call time (NFR-09 order):

      1. Google Secret Manager (``helpers.gsm`` — secret ``OPENAI_API_KEY``)
      2. DB-backed admin override (``helpers.secrets``)
      3. ``OPENAI_API_KEY`` env var

    Every specialist node must use this rather than reading os.environ
    directly, so the key can be rotated via GSM / the admin console
    without a redeploy and without an env var being present on the box.
    Returns "" if no source has it — the caller's LLM call then fails
    loudly, which the node surfaces as an error (no silent fallback).
    """
    try:
        from helpers import gsm as _gsm  # type: ignore
        k = _gsm.get("OPENAI_API_KEY")
        if k:
            return k
    except Exception:  # noqa: BLE001 — GSM unavailable in local dev; fall through
        pass
    try:
        from helpers import secrets as _secrets  # type: ignore
        k = _secrets.get("OPENAI_API_KEY")
        if k:
            return k
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("OPENAI_API_KEY", "")


# Appended verbatim to every specialist agent's system prompt. Kept
# blunt and numbered because the failure mode (LLM inventing fund
# names like "Fund A" when the tool didn't return per-fund data) is a
# user-visible trust-killer.
ANTI_HALLUCINATION_RULES: str = """
Anti-hallucination rules — these override every other instruction:
1. Use ONLY values present in TOOL_DATA above. Never invent fund names, ticker symbols, scheme codes, ISINs, sector names, or numerical values.
2. If a requested metric (rolling returns, expense ratio, sector overlap, P/E, anything else) is not in TOOL_DATA, write "data unavailable" for that field and stop — never fill the gap with a plausible-looking number.
3. Do not use placeholder labels ("Fund A", "Stock X", "Sector Y") or round/illustrative figures (e.g. 1.0%, 15%, 97%) unless those exact values appear in TOOL_DATA.
4. If TOOL_DATA is empty, says no_data, or all tool calls failed, reply: "I couldn't retrieve the data needed to answer this — please try again or contact support." Do not answer from training data.
5. Do not interpolate, extrapolate, average, or estimate values not explicitly present in TOOL_DATA. If unsure, say so.
6. Quote scheme names, symbols and figures verbatim from TOOL_DATA — do not paraphrase numerical values.
"""
