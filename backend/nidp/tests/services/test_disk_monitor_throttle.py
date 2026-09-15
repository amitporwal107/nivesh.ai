"""disk_monitor must stay loud on escalation and quiet on repetition.

The 2026-08 disk-full outage was *correctly* detected and emailed 123+
times ("CRITICAL / 2.4% free", every 10 minutes) and still ran the volume
to 100%, taking out MinIO, nse_shareholding and the nightly analytics
chain. The monitor was not broken — the alert volume was, and an alert
nobody can act on is indistinguishable from no alert.
"""
from __future__ import annotations

import json
import time

import pytest

from nidp.services.disk_monitor import service


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    f = tmp_path / "state.json"
    monkeypatch.setattr(service, "_STATE_FILE", str(f))
    return f


def _f(path="/", sev="CRITICAL"):
    return {"path": path, "severity": sev, "free_pct": 2.4,
            "free_gb": 1.9, "total_gb": 79.0}


def test_first_breach_alerts():
    assert service._should_alert([_f()]) is True


def test_identical_repeat_is_suppressed():
    assert service._should_alert([_f()]) is True
    assert service._should_alert([_f()]) is False


def test_escalation_from_warn_to_critical_always_alerts():
    assert service._should_alert([_f(sev="WARN")]) is True
    assert service._should_alert([_f(sev="CRITICAL")]) is True


def test_a_newly_breaching_path_always_alerts():
    assert service._should_alert([_f("/")]) is True
    assert service._should_alert([_f("/"), _f("/mnt/nidp-nfs")]) is True


def test_repeat_alerts_again_after_the_window(_state, monkeypatch):
    assert service._should_alert([_f()]) is True
    assert service._should_alert([_f()]) is False
    # age the recorded alert past the window
    st = json.loads(_state.read_text())
    st["alerted_at"] = time.time() - 7 * 3600
    _state.write_text(json.dumps(st))
    assert service._should_alert([_f()]) is True


def test_window_is_configurable(monkeypatch, _state):
    monkeypatch.setenv("NIDP_DISK_REALERT_HOURS", "0")
    assert service._should_alert([_f()]) is True
    assert service._should_alert([_f()]) is True   # window 0 => never throttle


def test_unwritable_state_still_alerts(monkeypatch):
    """A full disk is exactly when the state write fails — never go silent."""
    monkeypatch.setattr(service, "_STATE_FILE", "/proc/definitely/not/writable")
    assert service._should_alert([_f()]) is True
    assert service._should_alert([_f()]) is True


def test_signature_is_order_independent():
    a = service._alert_signature([_f("/"), _f("/mnt/nidp-nfs")])
    b = service._alert_signature([_f("/mnt/nidp-nfs"), _f("/")])
    assert a == b


def test_recovery_clears_state_so_the_next_breach_pages_immediately(_state):
    """A breach, a recovery, then a fresh breach is a NEW incident.

    Without clearing on recovery the second incident falls inside the
    re-alert window and is suppressed — the throttle would hide exactly
    the event it exists to surface. Caught by the pre-existing
    test_disk_monitor.py::test_run_alerts_only_on_breach.
    """
    assert service._should_alert([_f()]) is True
    assert service._should_alert([_f()]) is False      # throttled, correctly
    service._clear_alert_state()                       # disk recovered
    assert service._should_alert([_f()]) is True       # new incident: page


def test_clearing_absent_state_is_harmless(_state):
    service._clear_alert_state()
    service._clear_alert_state()
    assert service._should_alert([_f()]) is True
