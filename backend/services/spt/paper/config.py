"""Slice C's settings, read from the environment at call time (so a restart is not needed to test a value, and tests
can set them). Every value is clamped to a sane range; a missing or unreadable value is the default.

    SPT_QUOTE_MAX_AGE_S            120    a quote older than this (by its received_at) never fills anything
    SPT_NO_DEPTH_MAX_QTY_FRACTION  0.25   without displayed quantity: at most this fraction of the ORDER per round
    SPT_NO_DEPTH_SPREAD_PCT        0.05   without bid/ask: the spread allowance added to (BUY) / taken from (SELL) LTP, %
    SPT_ENTRY_MAX_DEVIATION_PCT    2.0    an ENTRY does not fill above the planned entry by more than this, %
    SPT_C_LOOP_S                   15     the monitor's cadence in the session, seconds
    SPT_C_ENABLED                  ""     "1" on, "0" off; otherwise on where APP_ENV=staging
"""
from __future__ import annotations

import os
from typing import Dict, Optional


def _num(name: str, default: float, lo: float, hi: float, env: Optional[Dict[str, str]] = None) -> float:
    raw = (env if env is not None else os.environ).get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        v = float(str(raw).strip())
    except ValueError:
        return default
    if v != v:                                     # NaN
        return default
    return max(lo, min(hi, v))


def quote_max_age_s() -> float:
    return _num("SPT_QUOTE_MAX_AGE_S", 120.0, 5.0, 600.0)


def no_depth_fraction() -> float:
    return _num("SPT_NO_DEPTH_MAX_QTY_FRACTION", 0.25, 0.01, 1.0)


def no_depth_spread_pct() -> float:
    return _num("SPT_NO_DEPTH_SPREAD_PCT", 0.05, 0.0, 5.0)


def entry_max_deviation_pct() -> float:
    return _num("SPT_ENTRY_MAX_DEVIATION_PCT", 2.0, 0.0, 20.0)


def loop_seconds() -> float:
    return _num("SPT_C_LOOP_S", 15.0, 5.0, 300.0)


def enabled(env: Optional[Dict[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    flag = (env.get("SPT_C_ENABLED") or "").strip()
    if flag == "0":
        return False
    return flag == "1" or (env.get("APP_ENV") or "").strip().lower() == "staging"
