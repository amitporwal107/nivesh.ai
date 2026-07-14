"""Canonical NIDP feed registry — the single source of truth (WORK-0144).

Historically the feed set was hand-maintained in 4+ places that drifted (cron,
admin NIDP_INGESTERS, feed_health_check.EXPECTED_FEEDS, health_check.sh SLO),
causing monitoring blind spots (HANDOFF §Theme E). This module is the ONE
canonical list. Consumers derive from it:
  - feed_health_check.EXPECTED_FEEDS  = monitored feeds (name, slo_hours, severity)
  - test_feed_registry_drift.py        enforces the cron schedule agrees with it

Add/change a feed HERE; the derived consumers + the drift test keep the rest honest.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class Feed:
    name: str
    cadence: str        # daily | monthly | high-freq | event | manual
    monitored: bool     # tracked by the freshness detector?
    slo_hours: int      # max hours since last OK before a gap alert (monitored only)
    severity: str       # ERROR (page on miss) | WARN (log only)
    recoverable: bool    # can feed_reconciler heal a missed trading day?


# The authoritative feed set. `monitored`/`slo_hours`/`severity` drive
# feed_health_check; keep in sync with the cron (drift test enforces it).
FEEDS: List[Feed] = [
    # ── daily NSE market data (ERROR: a miss breaks scoring) ──
    Feed("bhavcopy",                    "daily",     True,  30, "ERROR", True),
    Feed("delivery",                    "daily",     True,  30, "ERROR", True),
    Feed("index_close",                 "daily",     True,  30, "ERROR", True),
    Feed("fno_bhavcopy",                "daily",     True,  30, "ERROR", False),
    Feed("fii_dii",                     "daily",     True,  30, "ERROR", True),
    # ── daily NSE flows (WARN: sparse/rolling) ──
    Feed("bulk_deals",                  "daily",     True,  30, "WARN",  False),
    Feed("block_deals",                 "daily",     True,  30, "WARN",  False),
    Feed("corporate_actions",           "event",     True,  30, "WARN",  False),
    # ── mutual funds ──
    Feed("amfi_nav",                    "daily",     True,  30, "ERROR", False),
    Feed("amfi_nav_history",            "manual",    True,  30, "WARN",  False),
    # ── macro / weekly ──
    Feed("rbi_yields",                  "daily",     True,  72, "WARN",  False),
    Feed("fred_macro",                  "daily",     True,  30, "WARN",  False),
    # ── master refresh (infrequent) ──
    Feed("nse_calendar",                "monthly",   True, 168, "WARN",  False),
    Feed("nse_equity_master",           "monthly",   True, 168, "WARN",  False),
    Feed("index_constituents",          "monthly",   True, 168, "WARN",  False),
    # ── derived analytics engines (ERROR: feed Action-Matrix scoring) ──
    Feed("price_adjuster",              "daily",     True,  30, "ERROR", False),
    Feed("mf_analytics_engine",         "daily",     True,  30, "ERROR", True),
    Feed("technical_indicator_engine",  "daily",     True,  30, "ERROR", True),
    Feed("fundamental_engine",          "daily",     True,  30, "ERROR", True),
]

FEEDS_BY_NAME = {f.name: f for f in FEEDS}


def expected_feeds() -> List[Tuple[str, int, str]]:
    """(name, max_age_hours, severity) for every monitored feed — the shape
    feed_health_check consumes."""
    return [(f.name, f.slo_hours, f.severity) for f in FEEDS if f.monitored]


def monitored_error_feeds() -> List[str]:
    return [f.name for f in FEEDS if f.monitored and f.severity == "ERROR"]
