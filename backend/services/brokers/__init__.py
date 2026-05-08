"""Native broker adapters for Nivesh Secure Portfolio Connect.

Each broker is a thin module that implements the `Broker` protocol from
`base.py`. Two implementation styles coexist:

  * For brokers with official Python SDKs (Zerodha, Upstox, Angel, Fyers,
    Dhan): use the SDK directly.
  * For brokers without (Motilal, Samco, Shoonya, ...): vendor OpenAlgo's
    `broker/<name>/api/*.py` modules into `_vendored/` and wrap.

Either way the user-facing flow is the same — direct broker OAuth /
credential capture, no OpenAlgo dashboard in the loop.

Public entry: `from services.brokers import registry`.
"""
from __future__ import annotations

from . import registry  # noqa: F401  (registers built-in adapters at import)

__all__ = ["registry"]
