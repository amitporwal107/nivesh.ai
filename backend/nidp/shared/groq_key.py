"""Groq key resolution for nidp — the sibling of ``openai_key.py``.

Same layering and the same reason for existing: nidp services must have a stable
import that does NOT assume the app's ``helpers`` package is present. It is not,
in either deployed shape — the service Dockerfiles copy only ``backend/nidp``,
and on the VM the nidp venv has no ``google-cloud-secret-manager``. In both
cases the env var (from ``/opt/nidp/nidp.env``) is the only live source.

Order: GSM -> admin override -> env. Resolve at CALL time — an import-time
capture is what makes a key rotation require a redeploy.

NOTE: ``nidp.services.copilot_agent._llm`` carries an older private copy of this
resolver. It is deliberately left alone here (the copilot has broken twice on
model/provider changes); this module is the one new code should import.
"""
from __future__ import annotations

import os


def get_groq_api_key() -> str:
    """Resolve the key: GSM -> admin override -> env. "" if nothing has it."""
    try:
        from helpers import gsm as _gsm  # type: ignore
        k = _gsm.get("GROQ_API_KEY")
        if k:
            return k.strip()
    except Exception:  # noqa: BLE001 — helpers/GSM absent; keep falling through
        pass
    try:
        from helpers import secrets as _secrets  # type: ignore
        k = _secrets.get("GROQ_API_KEY")
        if k:
            return k.strip()
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("GROQ_API_KEY", "").strip()


def groq_configured() -> bool:
    """True when a key is resolvable from any source (GSM/admin/env)."""
    return bool(get_groq_api_key())
