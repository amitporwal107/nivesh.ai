"""OpenAI key resolution for nidp — delegates to the canonical resolver.

The single implementation lives in ``helpers/openai_key.py`` (next to gsm.py and
secrets.py, which it composes). This module exists so nidp code has a stable
import that does not assume the app's helpers package is present: if it is not
(bare nidp checkout, local dev), we fall back to the env var rather than fail.

Order, via helpers: GSM -> admin override -> env. Resolve at CALL time — an
import-time capture is what makes a GSM rotation require a redeploy.
"""
from __future__ import annotations

import os


def get_openai_api_key() -> str:
    """Resolve the key: GSM -> admin override -> env. "" if nothing has it."""
    try:
        from helpers.openai_key import get_openai_api_key as _resolve  # type: ignore
        return _resolve()
    except Exception:  # noqa: BLE001 — helpers absent; env is the only source left
        return os.environ.get("OPENAI_API_KEY", "").strip()


def openai_configured() -> bool:
    """True when a key is resolvable from any source (GSM/admin/env)."""
    return bool(get_openai_api_key())
