"""Positional Trading Engine.

Generates 5–30 day trade recommendations from daily OHLCV + Chartink scan
gates. Pure-Python, deterministic feature math; thin async layer for I/O.

Public entry points:
    pipeline.run_for_date(scan_date) — daily orchestrator
    pipeline.score_symbol(symbol, ohlcv) — single-symbol path (testable)
"""

ENGINE_VERSION = "positional.v1.0"
