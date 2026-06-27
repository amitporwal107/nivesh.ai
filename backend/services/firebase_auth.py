"""Firebase ID-token verification for the email/password beta login.

The Android beta build lets testers sign in with Firebase email/password instead
of Google OAuth (which needs per-account OAuth client + whitelist config). The
client sends the Firebase ID token to ``POST /api/auth/firebase``; this module
verifies it (signature + audience == our Firebase project) and returns the
decoded claims. The rest of the login (whitelist gate, user upsert, session
cookie) is identical to the Google flow — see ``backend/routes/auth.py``.

Verification needs only the **project id** — no service-account private key —
because the Admin SDK checks the token against Google's published public keys.
A service account (``FIREBASE_SERVICE_ACCOUNT``) is supported if present but not
required for token verification.

Config (env):
    FIREBASE_PROJECT_ID        Firebase project id (e.g. nivesh-beta). Required.
    FIREBASE_SERVICE_ACCOUNT   Optional service-account JSON (string) or file path.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "").strip()
# Optional: full service-account JSON (as a string) or a path to the JSON file.
_FIREBASE_SA = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()

_app = None  # cached firebase_admin app (initialised lazily on first verify)


def is_configured() -> bool:
    """True when enough config exists to verify Firebase ID tokens."""
    return bool(FIREBASE_PROJECT_ID or _FIREBASE_SA)


def _ensure_app():
    """Initialise (once) and return the firebase_admin app."""
    global _app
    if _app is not None:
        return _app

    import firebase_admin
    from firebase_admin import credentials

    if firebase_admin._apps:  # already initialised elsewhere in the process
        _app = firebase_admin.get_app()
        return _app

    options = {"projectId": FIREBASE_PROJECT_ID} if FIREBASE_PROJECT_ID else None
    if _FIREBASE_SA:
        sa = json.loads(_FIREBASE_SA) if _FIREBASE_SA.startswith("{") else _FIREBASE_SA
        _app = firebase_admin.initialize_app(credentials.Certificate(sa), options)
    else:
        # ID-token verification only needs the project id; no credential required.
        _app = firebase_admin.initialize_app(options=options)
    logger.info("firebase_admin initialised (project=%s, sa=%s)",
                FIREBASE_PROJECT_ID or "?", bool(_FIREBASE_SA))
    return _app


def verify_id_token(id_token: str) -> dict:
    """Verify a Firebase ID token and return its decoded claims.

    Raises whatever ``firebase_admin.auth.verify_id_token`` raises on an invalid,
    expired, or wrong-audience token — the caller maps that to AUTH-003.
    """
    from firebase_admin import auth as fb_auth
    return fb_auth.verify_id_token(id_token, app=_ensure_app())
