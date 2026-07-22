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


# ── Provider + model ─────────────────────────────────────────────────────────
# Two OpenAI-wire-compatible providers are wired, selected via env (no code change):
#   • openai (default) — the OpenAI account; key resolved via nidp.shared.openai_key.
#   • groq             — Groq's OpenAI-compatible endpoint, used to run a FREE open
#                        model (openai/gpt-oss-120b) while OpenAI model access is
#                        being sorted out (an inaccessible gpt-5.x default broke the
#                        whole copilot — see git history).
# Groq is AUTO-selected whenever GROQ_API_KEY is set (or force COPILOT_LLM_PROVIDER).
# Because Groq speaks the OpenAI wire format we reuse langchain_openai.ChatOpenAI
# with a Groq base_url — NO new dependency — and ONLY the copilot chat nodes are
# redirected (embeddings / other OpenAI calls elsewhere in the app are untouched).
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"   # free on Groq (product choice, 2026-07)
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"         # known-good OpenAI default


def get_groq_api_key() -> str:
    """Resolve GROQ_API_KEY the same layered way as the OpenAI key
    (helpers/openai_key.py): GSM -> admin (secrets) override -> env, at CALL time.
    Store it in Google Secret Manager (secret name GROQ_API_KEY) for a deployed
    environment; backend/.env is the local fallback. "" when nothing has it."""
    try:
        from helpers import gsm as _gsm
        k = _gsm.get("GROQ_API_KEY")
        if k:
            return k.strip()
    except Exception:  # noqa: BLE001 — no GCP creds locally; fall through
        pass
    try:
        from helpers import secrets as _secrets
        k = _secrets.get("GROQ_API_KEY")
        if k:
            return k.strip()
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("GROQ_API_KEY", "").strip()


def llm_provider() -> str:
    """'groq' or 'openai' (default). An explicit COPILOT_LLM_PROVIDER wins; otherwise
    Groq is auto-selected whenever a GROQ_API_KEY is resolvable (GSM / admin / env)."""
    p = os.environ.get("COPILOT_LLM_PROVIDER", "").strip().lower()
    if p in ("groq", "openai"):
        return p
    return "groq" if get_groq_api_key() else "openai"


def resolve_model() -> str:
    """The chat-model id for the active provider (resolved at call time, so env wins).

    On Groq we use GROQ_MODEL / the free default and deliberately IGNORE
    COPILOT_LLM_MODEL — a stale OpenAI id left there (e.g. a `gpt-5.5` pin in the
    deployed env) would be rejected by Groq. On OpenAI, COPILOT_LLM_MODEL pins the
    model, defaulting to the known-good gpt-4o-mini."""
    if llm_provider() == "groq":
        return os.environ.get("GROQ_MODEL", "").strip() or _GROQ_DEFAULT_MODEL
    return os.environ.get("COPILOT_LLM_MODEL", "").strip() or _OPENAI_DEFAULT_MODEL


# Back-compat: a few call sites / tests import this. It reflects the resolved model
# for the active provider at import time.
COPILOT_LLM_MODEL: str = resolve_model()


def temperature_for(requested: float) -> float:
    """Return a temperature the active model accepts. gpt-5.x reasoning models only
    support the default (1) — any other value 400s; gpt-4o and Groq's gpt-oss/llama
    honour the requested value, so determinism tuning still applies."""
    return 1.0 if resolve_model().startswith("gpt-5") else requested


def get_openai_api_key() -> str:
    """Resolve the OpenAI API key at call time (NFR-09 order): GSM -> admin
    override -> env. Delegates to nidp.shared.openai_key, which is the single
    implementation every caller shares — see that module for why.
    """
    from nidp.shared.openai_key import get_openai_api_key as _resolve
    return _resolve()


def make_chat_llm(temperature: float, **kwargs):
    """The single chat-model constructor every copilot node uses, so the provider
    (OpenAI vs Groq) is decided in exactly ONE place. Groq reuses ChatOpenAI against
    Groq's OpenAI-compatible base_url."""
    from langchain_openai import ChatOpenAI
    if llm_provider() == "groq":
        return ChatOpenAI(
            model=resolve_model(),
            temperature=temperature,
            api_key=get_groq_api_key(),
            base_url=_GROQ_BASE_URL,
            **kwargs,
        )
    return ChatOpenAI(
        model=resolve_model(),
        temperature=temperature,
        api_key=get_openai_api_key(),
        **kwargs,
    )


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
