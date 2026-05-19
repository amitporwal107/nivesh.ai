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


COPILOT_LLM_MODEL: str = os.environ.get("COPILOT_LLM_MODEL", "gpt-5")


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
