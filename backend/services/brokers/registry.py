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

_REGISTRY: Dict[str, base.Broker] = {}


def register(broker: base.Broker) -> None:
    slug = getattr(broker, "SLUG", "")
    if not slug:
        raise ValueError("Broker module must define SLUG")
    _REGISTRY[slug] = broker


def get(slug: str) -> base.Broker:
    if slug not in _REGISTRY:
        raise KeyError(f"Unknown broker '{slug}'")
    return _REGISTRY[slug]


def list_supported() -> List[Dict[str, str]]:
    """Public listing for the frontend broker dropdown.

    `implemented` flags fully-shipped adapters vs. placeholder stubs.
    Frontend uses this to render "Coming soon" badges on stub brokers.
    """
    rows: List[Dict[str, Any]] = []
    for b in _REGISTRY.values():
        rows.append({
            "slug": b.SLUG,
            "name": b.DISPLAY,
            "auth_style": b.AUTH_STYLE,
            "implemented": getattr(b, "IMPLEMENTED", True),
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
from . import _stub      # noqa: E402,F401  registers placeholder adapters
