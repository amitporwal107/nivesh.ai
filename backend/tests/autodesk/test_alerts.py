"""AD-AL-xx (docs/autodesk/testcases_alerts_slack.md): support issues of the desk are published to Slack.

Unit tests use a fake transport, labelled MOCK. No test touches the real Slack channel (AD-AL-27/28 are manual and
need the owner's go-ahead). The webhook URL used here is a made-up string, never a real one.
"""
from __future__ import annotations

import inspect
import re
from datetime import datetime, timezone

import pytest

from autodesk.notify import alerts, notifier, transport
from autodesk.notify.alerts import Severity
from autodesk.notify.notifier import Notifier
from autodesk.notify.transport import SendResult, SlackWebhookTransport

from .test_safety import ADVICE

FAKE_URL = "https://hooks.example.invalid/services/TFAKE/BFAKE/fake-secret-value"   # MOCK — not real data
T0 = datetime(2026, 11, 9, 3, 0, tzinfo=timezone.utc)                              # 08:30 IST


def ev(seq=1, typ="PREMARKET_BLOCKED", payload=None, occurred=T0, account="ACC-demo", sim=None, wf="WF-1"):
    return {"seq": seq, "event_id": f"EVT-{seq}", "event_type": typ, "occurred_at": occurred, "tenant_id": "t1",
            "account_id": account, "simulation_id": sim, "workflow_id": wf, "producer": "orchestrator",
            "payload": payload if payload is not None else {"session_date": "2026-11-09", "status": "BLOCKED"}}


class FakeTransport:      # MOCK — not real data
    def __init__(self, results=None):
        self.sent = []
        self.results = list(results or [])

    def send(self, text, thread_ts=None):
        self.sent.append(text)
        return self.results.pop(0) if self.results else SendResult(ok=True)


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def mk(tr=None, **kw):
    clk = Clock()
    n = Notifier(tr or FakeTransport(), clock=clk.now, sleep=clk.sleep, **kw)
    return n, clk


# ── content and format ─────────────────────────────────────────────────────────────────────────────────────────────
def test_al01_blocked_premarket_becomes_one_alert():
    a = alerts.classify(ev())
    assert a is not None and a.severity == Severity.CRITICAL and a.result == "BLOCKED"
    text = alerts.render(a)
    for part in ("CRITICAL", "premarket", "BLOCKED", "2026-11-09", "ACC-demo", "Next action"):
        assert part in text


def test_al02_severity_mapping():
    assert alerts.classify(ev(typ="DESK_CONTROL_ACTIVATED", payload={"control": "STOP_NEW_ENTRIES"})).severity \
        == Severity.CRITICAL
    assert alerts.classify(ev(typ="WORKFLOW_FAILED", payload={"error": "x"})).severity == Severity.CRITICAL
    assert alerts.classify(ev(typ="PREMARKET_READY", payload={"status": "DEGRADED"})).severity == Severity.WARNING
    assert alerts.classify(ev(typ="MARKET_DATA_STALE")).severity == Severity.WARNING
    assert alerts.classify(ev(typ="AGENT_UNHEALTHY")).severity == Severity.WARNING
    assert alerts.classify(ev(typ="DESK_CONTROL_LIFTED", payload={"control": "STOP_NEW_ENTRIES"})).severity \
        == Severity.INFO


def test_al02b_normal_events_are_not_alerts():
    assert alerts.classify(ev(typ="PREMARKET_READY", payload={"status": "READY"})) is None
    for t in ("SIGNAL_DETECTED", "TASK_CREATED", "WORKFLOW_STATE_CHANGED", "APPROVAL_GRANTED"):
        assert alerts.classify(ev(typ=t)) is None


def test_al03_times_in_ist_and_utc_from_the_event():
    text = alerts.render(alerts.classify(ev()))
    assert "08:30 IST" in text and "03:00 UTC" in text


def test_al04_account_label_only():
    a = alerts.classify(ev(payload={"status": "BLOCKED", "email": "someone@example.com", "tenant": "t1"}))
    text = alerts.render(a)
    assert "someone@example.com" not in text and "ACC-demo" in text
    sim = alerts.render(alerts.classify(ev(sim="SIM-7")))
    assert "SIMULATION SIM-7" in sim


def test_al05_wording_lint():
    samples = [ev(), ev(typ="DESK_CONTROL_ACTIVATED", payload={"control": "STOP_NEW_ENTRIES", "reason": "check"}),
               ev(typ="WORKFLOW_FAILED", payload={"error": "boom"}), ev(typ="MARKET_DATA_STALE"),
               ev(typ="AGENT_UNHEALTHY"), ev(typ="PREMARKET_READY", payload={"status": "DEGRADED"}),
               ev(typ="DESK_CONTROL_LIFTED", payload={"control": "STOP_NEW_ENTRIES"})]
    for e in samples:
        t = alerts.render(alerts.classify(e))
        assert not ADVICE.findall(t), t


def test_al06_long_message_is_truncated_visibly():
    a = alerts.classify(ev(typ="WORKFLOW_FAILED", payload={"error": "x" * 10000}))
    text = alerts.render(a)
    assert len(text) <= alerts.MAX_LEN and text.endswith("[truncated]")


# ── secrets and configuration ──────────────────────────────────────────────────────────────────────────────────────
def test_al07_url_never_leaks():
    t = SlackWebhookTransport(FAKE_URL, http_post=lambda *a, **k: (500, "boom " + FAKE_URL, {}))
    assert "fake-secret-value" not in repr(t) and "fake-secret-value" not in str(t)
    r = t.send("hello")
    assert not r.ok and "fake-secret-value" not in (r.reason or "")
    t2 = SlackWebhookTransport(FAKE_URL, http_post=lambda *a, **k: (_ for _ in ()).throw(OSError(FAKE_URL)))
    assert "fake-secret-value" not in (t2.send("hello").reason or "")


def test_al08_not_configured_is_disabled_and_silent():
    n = notifier.from_env({})
    assert n.enabled is False
    assert n.process([ev()]) == []          # sends nothing, raises nothing


def test_al08b_configured_from_env_without_leaking():
    n = notifier.from_env({"AUTODESK_SLACK_WEBHOOK_URL": FAKE_URL})
    assert n.enabled is True and "fake-secret-value" not in repr(n)


def test_al09_bad_token_is_permanent_not_retried():
    tr = FakeTransport([SendResult(ok=False, permanent=True, reason="invalid_auth")])
    n, clk = mk(tr)
    out = n.process([ev()])
    assert len(tr.sent) == 1 and out[0].status == "FAILED" and out[0].reason == "invalid_auth" and not clk.slept


# ── delivery ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_al10_retries_then_gives_up_without_raising():
    tr = FakeTransport([SendResult(ok=False, reason="http_503")] * 5)
    n, clk = mk(tr)
    out = n.process([ev()])
    assert len(tr.sent) == 3 and out[0].status == "FAILED" and len(clk.slept) == 2
    assert clk.slept[1] > clk.slept[0]


def test_al10b_recovers_on_second_try():
    tr = FakeTransport([SendResult(ok=False, reason="timeout"), SendResult(ok=True)])
    n, _ = mk(tr)
    assert n.process([ev()])[0].status == "SENT" and len(tr.sent) == 2


def test_al11_rate_limited_waits_retry_after():
    tr = FakeTransport([SendResult(ok=False, retry_after=7.0, reason="rate_limited"), SendResult(ok=True)])
    n, clk = mk(tr)
    assert n.process([ev()])[0].status == "SENT" and clk.slept == [7.0]


def test_al12_channel_not_found_is_permanent():
    tr = FakeTransport([SendResult(ok=False, permanent=True, reason="channel_not_found")])
    n, clk = mk(tr)
    assert n.process([ev()])[0].status == "FAILED" and len(tr.sent) == 1 and not clk.slept


def test_al15_critical_goes_before_info():
    tr = FakeTransport()
    n, _ = mk(tr)
    n.process([ev(1, typ="DESK_CONTROL_LIFTED", payload={"control": "STOP_NEW_ENTRIES"}),
               ev(2, typ="MARKET_DATA_STALE"), ev(3)])
    assert "CRITICAL" in tr.sent[0] and "WARNING" in tr.sent[1] and "RESOLVED" in tr.sent[2]


def test_webhook_http_mapping():
    def t(status, body="ok", headers=None):
        return SlackWebhookTransport(FAKE_URL, http_post=lambda *a, **k: (status, body, headers or {})).send("x")
    assert t(200).ok
    assert t(429, "rate", {"Retry-After": "5"}).retry_after == 5.0
    assert t(404, "no_service").permanent and t(403, "invalid_token").permanent
    r = t(500, "err")
    assert not r.ok and not r.permanent


# ── noise control ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_al16_same_alert_posts_once_then_counts():
    tr = FakeTransport()
    n, clk = mk(tr, dedupe_window=900)
    n.process([ev(1)])
    clk.t += 60
    out = n.process([ev(2)])
    assert len(tr.sent) == 1 and out[0].status == "SUPPRESSED"
    clk.t += 1000
    n.process([ev(3)])
    assert len(tr.sent) == 2 and "Repeated 1 time" in tr.sent[1]


def test_al17_different_key_is_separate():
    tr = FakeTransport()
    n, _ = mk(tr)
    n.process([ev(1), ev(2, account="ACC-other")])
    assert len(tr.sent) == 2


def test_al18_burst_is_collapsed():
    tr = FakeTransport()
    n, _ = mk(tr, per_minute=3)
    n.process([ev(i, account=f"ACC-{i}") for i in range(1, 9)])
    assert len(tr.sent) == 4 and "5 more" in tr.sent[-1]


def test_al19_recovery_posts_resolved():
    tr = FakeTransport()
    n, _ = mk(tr)
    n.process([ev(1, typ="DESK_CONTROL_ACTIVATED", payload={"control": "STOP_NEW_ENTRIES"})])
    n.process([ev(2, typ="DESK_CONTROL_LIFTED", payload={"control": "STOP_NEW_ENTRIES"})])
    assert "RESOLVED" in tr.sent[-1]


# ── safety ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_al23_send_only_no_inbound_handler():
    src = inspect.getsource(alerts) + inspect.getsource(notifier) + inspect.getsource(transport)
    assert not re.search(r"APIRouter|@router|FastAPI|websocket|events_api|slash", src, re.IGNORECASE)


def test_al24_no_order_code_imported():
    src = inspect.getsource(alerts) + inspect.getsource(notifier) + inspect.getsource(transport)
    assert not re.search(r"kiteconnect|place_order|modify_order|cancel_order|execution", src, re.IGNORECASE)


def test_al25_a_failing_transport_never_raises():
    class Boom:
        def send(self, text, thread_ts=None):
            raise RuntimeError("down")
    n, _ = mk(Boom())
    out = n.process([ev()])
    assert out[0].status == "FAILED"


def test_malformed_event_is_skipped_not_raised():
    n, _ = mk()
    assert n.process([{"seq": 1}, ev(2, payload=None) | {"payload": None}]) is not None
