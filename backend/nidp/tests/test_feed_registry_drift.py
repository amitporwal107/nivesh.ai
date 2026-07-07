"""WORK-0144: drift guardrail across the feed lists.

The feed set is defined in several hand-maintained places that historically
drifted (causing monitoring blind spots — HANDOFF §Theme E):
  - the cron schedule            (deploy/vm/nidp.cron)
  - what's MONITORED             (feed_health_check.EXPECTED_FEEDS)
  - what auto-recovery can HEAL  (backfill.SPECS)

This test fails when they diverge in a way that's a real bug: a feed monitored
at ERROR severity but never scheduled (permanent false alarm), or a recoverable
daily feed that isn't scheduled. It doesn't force the lists to be identical
(they legitimately differ) — it enforces the invariants that matter.
"""
from __future__ import annotations

import re
from pathlib import Path

from nidp import backfill as bf
from nidp.services.feed_health_check.__main__ import EXPECTED_FEEDS

_CRON = Path(__file__).resolve().parents[1] / "deploy" / "vm" / "nidp.cron"


def _cron_feeds() -> set[str]:
    """Feed names invoked via run_service.sh in the prod crontab."""
    text = _CRON.read_text()
    return set(re.findall(r"run_service\.sh\s+([a-z0-9_]+)", text))


def test_every_error_monitored_feed_is_scheduled():
    """A feed monitored at ERROR severity but never run = a permanent gap alarm."""
    cron = _cron_feeds()
    missing = sorted(f for (f, _hrs, sev) in EXPECTED_FEEDS if sev == "ERROR" and f not in cron)
    assert not missing, f"ERROR-monitored feeds NOT scheduled in nidp.cron: {missing}"


def test_every_recoverable_daily_feed_is_scheduled():
    """A daily feed the reconciler can heal should also run on its own schedule."""
    cron = _cron_feeds()
    daily = sorted(s.name for s in bf.SPECS if s.needs_date)
    missing = [f for f in daily if f not in cron]
    assert not missing, f"recoverable daily feeds NOT scheduled in nidp.cron: {missing}"


def test_recovery_and_monitoring_jobs_are_scheduled():
    """The jobs this program added must actually be in cron (else they never run)."""
    cron = _cron_feeds()
    for f in ("feed_reconciler", "dlq_redrive", "disk_monitor", "feed_health_check"):
        assert f in cron, f"{f} is not scheduled in nidp.cron"
