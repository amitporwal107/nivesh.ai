"""Single source of truth for resolving the OpenAI API key (NFR-09).

Resolution order:

  1. Google Secret Manager (``helpers.gsm``, secret ``OPENAI_API_KEY``)
  2. DB-backed admin override (``helpers.secrets``)
  3. ``OPENAI_API_KEY`` environment variable

Why this module exists: ``copilot_agent/_llm.py`` already defined this order and
documented that "every specialist node must use this rather than reading
os.environ directly, so the key can be rotated via GSM / the admin console
without a redeploy". Six other call sites read os.environ anyway, and that had a
real cost — after the key was rotated in GSM, document_parser's vision tier kept
sending the stale env key and every call 401'd. It failed *gracefully*, so the
degradation was silent: the pipeline logged a warning per page and carried on.

Reading the key in one place makes a rotation take effect everywhere at once,
which is the entire point of putting it in Secret Manager.

Returns "" when no source has it. Callers must treat that as "not configured"
and skip (the graceful-capability pattern), never as a reason to fail a parse.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def get_openai_api_key() -> str:
    """Resolve the key at CALL time — never cache it at import time.

    Import-time capture is what makes a GSM rotation require a redeploy;
    ``helpers.gsm`` already caches internally with a TTL, so per-call resolution
    is cheap and picks up a rotation within that TTL.
    """
    try:
        from helpers import gsm as _gsm  # type: ignore
        k = _gsm.get("OPENAI_API_KEY")
        if k:
            return k
    except Exception as e:  # noqa: BLE001 — GSM absent in local dev; fall through
        logger.debug("gsm lookup unavailable: %s", e)
    try:
        from helpers import secrets as _secrets  # type: ignore
        k = _secrets.get("OPENAI_API_KEY")
        if k:
            return k
    except Exception as e:  # noqa: BLE001
        logger.debug("secrets lookup unavailable: %s", e)
    return os.environ.get("OPENAI_API_KEY", "")


def openai_configured() -> bool:
    """True when a key is resolvable from any source.

    Use for the graceful-capability check (mirrors ``ocr_available()`` /
    ``audio_available()``) instead of ``os.environ.get("OPENAI_API_KEY")``,
    which is blind to GSM and the admin console.
    """
    return bool(get_openai_api_key())
