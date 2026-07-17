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


def temperature_for(requested: float) -> float:
    """Return a temperature the configured model will accept.

    gpt-5.x reasoning models only support the default temperature (1) — any
    other value returns a 400 ("Only the default (1) value is supported"),
    which the nodes catch and surface as "trouble connecting to my AI engine".
    For those models we force 1.0; for others (e.g. gpt-4o) we honour the
    node's requested value so determinism tuning still applies.
    """
    return 1.0 if COPILOT_LLM_MODEL.startswith("gpt-5") else requested


def get_openai_api_key() -> str:
    """Resolve the OpenAI API key at call time (NFR-09 order): GSM -> admin
    override -> env. Delegates to nidp.shared.openai_key, which is the single
    implementation every caller shares — see that module for why.
    """
    from nidp.shared.openai_key import get_openai_api_key as _resolve
    return _resolve()


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

Output format — this chat surface does NOT render Markdown:
7. PLAIN TEXT ONLY. Do not use '#' headings, '*' or '**' emphasis/bold, backticks, or '|' tables — they appear as literal characters to the user.
8. Use short paragraphs and line breaks. For a list, start the line with a hyphen and a space ("- item"). The arrow → is fine.
9. For a comparison, write each item on its own line(s) — a label followed by its points — never a pipe table. Keep the whole answer under ~180 words.
"""
