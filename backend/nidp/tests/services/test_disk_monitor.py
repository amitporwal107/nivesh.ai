"""Unit tests for disk_monitor (WORK-0132) — no real disk, no DB, no network."""
from __future__ import annotations

import shutil

from nidp.services.disk_monitor import service as s

GB = 1024 ** 3


def test_evaluate_healthy_returns_none():
    # 50% free
    assert s.evaluate("/", 50 * GB, 100 * GB, warn_pct=15, crit_pct=10) is None


def test_evaluate_warn_band():
    f = s.evaluate("/", 12 * GB, 100 * GB, warn_pct=15, crit_pct=10)   # 12% free
    assert f and f["severity"] == "WARN" and f["free_pct"] == 12.0


def test_evaluate_critical_band():
    f = s.evaluate("/", 8 * GB, 100 * GB, warn_pct=15, crit_pct=10)    # 8% free
    assert f and f["severity"] == "CRITICAL"


def test_evaluate_zero_total_is_safe():
    assert s.evaluate("/x", 0, 0, 15, 10) is None


def test_check_disk_flags_low_paths(monkeypatch):
    usage = {
        "/":              shutil._ntuple_diskusage(100 * GB, 95 * GB, 5 * GB),   # 5% free -> CRIT
        "/mnt/nidp-nfs":  shutil._ntuple_diskusage(80 * GB, 40 * GB, 40 * GB),   # 50% free -> ok
    }

    def fake_usage(path):
        if path not in usage:
            raise FileNotFoundError(path)
        return usage[path]
    monkeypatch.setattr(s.shutil, "disk_usage", fake_usage)

    findings = s.check_disk(["/", "/mnt/nidp-nfs", "/does-not-exist"], warn_pct=15, crit_pct=10)
    assert len(findings) == 1
    assert findings[0]["path"] == "/" and findings[0]["severity"] == "CRITICAL"


def test_run_alerts_only_on_breach(monkeypatch):
    calls = []
    monkeypatch.setattr(s._notify, "notify", lambda subject, body=None: calls.append(subject) or True)
    monkeypatch.setattr(s.shutil, "disk_usage",
                        lambda p: shutil._ntuple_diskusage(100 * GB, 50 * GB, 50 * GB))  # 50% free

    # healthy: no alert
    monkeypatch.setattr(s, "check_disk", lambda *a, **k: [])
    s.run()
    assert calls == []

    # breach: alert fires with a severity-tagged subject
    monkeypatch.setattr(s, "check_disk", lambda *a, **k: [
        {"path": "/", "severity": "CRITICAL", "free_pct": 3.0, "free_gb": 1.5, "total_gb": 49.0}])
    s.run()
    assert len(calls) == 1 and "CRITICAL" in calls[0]
