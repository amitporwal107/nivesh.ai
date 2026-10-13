"""Broker adapter registry.

Adapters self-register on import. To add a broker:
    1. Create `services/brokers/<slug>.py` with module-level
       `SLUG`, `DISPLAY`, `AUTH_STYLE`, and the protocol functions.
    2. Add an `import services.brokers.<slug>` line below.
    3. The module's `register()` call (or import-time side effect) lands
       it in `_REGISTRY`.

Routes call `registry.get(slug)` to dispatch.
"""
from __future__ import annotations

from typing import Any, Dict, List

from . import base
from ._helpers import conf

_REGISTRY: Dict[str, base.Broker] = {}

# Nivesh's own app credentials each adapter reads — secret NAMES only, taken
# from the `conf(...)` / `require(...)` calls in the adapter modules. A broker
# is "configured" when every one of them is set. Dhan reads none (the user
# brings a token); stubs are absent on purpose and never count as configured.
_REQUIRED_SECRETS: Dict[str, tuple] = {
    "zerodha": ("BROKER_ZERODHA_API_KEY", "BROKER_ZERODHA_API_SECRET"),
    "upstox": ("BROKER_UPSTOX_API_KEY", "BROKER_UPSTOX_API_SECRET"),
    "fyers": ("BROKER_FYERS_API_KEY", "BROKER_FYERS_API_SECRET"),
    "aliceblue": ("BROKER_ALICEBLUE_API_KEY", "BROKER_ALICEBLUE_API_SECRET"),
    "angel": ("BROKER_ANGEL_API_KEY",),
    "fivepaisa": (
        "BROKER_FIVEPAISA_API_KEY", "BROKER_FIVEPAISA_API_SECRET",
        "BROKER_FIVEPAISA_USER_ID", "BROKER_FIVEPAISA_USER_KEY",
    ),
    "dhan": (),
    "groww": (),  # the user brings the day's access token; Nivesh registers no app
    "icicidirect": ("BROKER_ICICIDIRECT_API_KEY", "BROKER_ICICIDIRECT_API_SECRET"),
    # VENDOR_INFO is the vendor short name MOFSL assigns (for a key a client
    # made for their own use, that client's code); every call must send it.
    "motilal": ("BROKER_MOTILAL_API_KEY", "BROKER_MOTILAL_API_SECRET", "BROKER_MOTILAL_VENDOR_INFO"),
}


def register(broker: base.Broker) -> None:
    slug = getattr(broker, "SLUG", "")
    if not slug:
        raise ValueError("Broker module must define SLUG")
    _REGISTRY[slug] = broker


def get(slug: str) -> base.Broker:
    if slug not in _REGISTRY:
        raise KeyError(f"Unknown broker '{slug}'")
    return _REGISTRY[slug]


def missing_secrets(slug: str) -> List[str]:
    """Names (never values) of the app secrets `slug` still needs."""
    return [name for name in _REQUIRED_SECRETS.get(slug, ()) if not conf(name)]


def is_configured(slug: str) -> bool:
    """True when Nivesh's app keys for `slug` are all set."""
    return slug in _REQUIRED_SECRETS and not missing_secrets(slug)


def list_supported() -> List[Dict[str, str]]:
    """Public listing for the frontend broker dropdown.

    `implemented` flags fully-shipped adapters vs. placeholder stubs.
    Frontend uses this to render "Coming soon" badges on stub brokers.
    `configured` says Nivesh's app keys for the broker are set, and
    `connectable` that a user can sign in on the broker's own page right
    now (implemented + oauth + configured).
    """
    rows: List[Dict[str, Any]] = []
    for b in _REGISTRY.values():
        implemented = getattr(b, "IMPLEMENTED", True)
        configured = is_configured(b.SLUG)
        rows.append({
            "slug": b.SLUG,
            "name": b.DISPLAY,
            "auth_style": b.AUTH_STYLE,
            "implemented": implemented,
            "configured": configured,
            "connectable": implemented and b.AUTH_STYLE == "oauth" and configured,
        })
    # Implemented brokers first; alphabetical within each group.
    rows.sort(key=lambda r: (not r["implemented"], r["name"].lower()))
    return rows


# ── Built-in adapter registration ────────────────────────────────────────
# Imports below run each adapter's module-level `register(...)` call.
from . import zerodha    # noqa: E402,F401  Kite Connect SDK
from . import upstox     # noqa: E402,F401  Upstox v2 (raw HTTP)
from . import angelone   # noqa: E402,F401  SmartAPI (form-auth)
from . import fyers      # noqa: E402,F401  Fyers v3 (raw HTTP)
from . import dhan       # noqa: E402,F401  Dhan v2 (apikey-paste)
from . import fivepaisa  # noqa: E402,F401  py5paisa SDK (form-auth)
from . import aliceblue  # noqa: E402,F401  Ant API (oauth)
from . import groww      # noqa: E402,F401  Groww Trading API (pasted daily token)
from . import icicidirect  # noqa: E402,F401  Breeze API (raw HTTP; returns by form POST)
from . import motilal    # noqa: E402,F401  MOFSL OpenAPI (raw HTTP; portal redirect)
from . import _stub      # noqa: E402,F401  registers placeholder adapters
