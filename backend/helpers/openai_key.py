"""Single source of truth for the OpenAI API key — GSM first, always.

Resolution order:

  1. Google Secret Manager (``helpers.gsm``, secret ``OPENAI_API_KEY``)
  2. DB-backed admin override (``helpers.secrets`` — admin console)
  3. ``OPENAI_API_KEY`` environment variable

Every caller in this repo — app routes/services AND nidp — must use this rather
than reading ``os.environ`` or calling ``helpers.secrets`` directly. That is the
whole point of holding the key in Secret Manager: rotate once, and every caller
picks it up without a redeploy and without the value existing on any box.

This module exists because the rule was documented and then not followed. NIDP's
``copilot_agent/_llm.py`` defined this exact order and said "every specialist
node must use this"; fourteen call sites across nidp and the app read
``os.environ`` anyway. The cost was real: after the key was rotated in GSM,
document_parser's vision tier kept sending the stale env key and 401'd on every
low-text page — silently, because that tier is graceful by design.

Returns "" when no source has it. Callers must treat "" as "not configured" and
skip the feature (the graceful-capability pattern), never as a reason to fail a
user request with a confusing traceback.

Caching: none here on purpose. ``helpers.gsm`` already caches with a TTL, and
``helpers.secrets`` caches its DB read; adding a third layer would only make a
rotation take longer to land. Resolve at CALL time, never at import time — an
import-time capture is precisely what makes a rotation need a restart.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

SECRET_NAME = "OPENAI_API_KEY"


def get_openai_api_key() -> str:
    """Resolve the key: GSM -> admin override -> env. "" if nothing has it."""
    try:
        from helpers import gsm as _gsm
        k = _gsm.get(SECRET_NAME)
        if k:
            return k.strip()
    except Exception as e:  # noqa: BLE001 — no GCP creds in local dev; fall through
        logger.debug("gsm lookup unavailable: %s", e)
    try:
        from helpers import secrets as _secrets
        k = _secrets.get(SECRET_NAME)
        if k:
            return k.strip()
    except Exception as e:  # noqa: BLE001
        logger.debug("admin-override lookup unavailable: %s", e)
    return os.environ.get(SECRET_NAME, "").strip()


def openai_configured() -> bool:
    """True when a key is resolvable from any source.

    Use for capability checks instead of ``os.environ.get("OPENAI_API_KEY")``,
    which is blind to both GSM and the admin console — a box with the key only
    in Secret Manager would report "not configured" and silently skip the
    feature.
    """
    return bool(get_openai_api_key())


def source_of_key() -> Optional[str]:
    """Which tier actually supplied the key: 'gsm' | 'admin' | 'env' | None.

    Diagnostics only — never log the key itself. Exists because "the key is
    wrong" and "the key is coming from somewhere I didn't expect" look identical
    from a 401, which is what made the stale-env-key bug take so long to see.
    """
    try:
        from helpers import gsm as _gsm
        if _gsm.get(SECRET_NAME):
            return "gsm"
    except Exception:  # noqa: BLE001
        pass
    try:
        from helpers import secrets as _secrets
        if _secrets.get(SECRET_NAME):
            return "admin"
    except Exception:  # noqa: BLE001
        pass
    return "env" if os.environ.get(SECRET_NAME) else None
