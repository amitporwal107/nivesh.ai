"""Market-data source switch — MS-1 … MS-16 from test_reports/market_data_switch_TESTCASES.md.

No database and no network: the switch is pure resolution, and the wiring cases replace JobRun, the pool and the
feed's fetch with recording fakes. Coroutines run under asyncio.run (the backend image has no pytest-asyncio).
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from nidp.shared import market_data_source as mds

READY = {"TRUEDATA_USERNAME": "u", "TRUEDATA_PASSWORD": "p"}


def cfg(source, licence=False):
    return {"source": source, "truedata_licence_confirmed": licence}


# ── Resolver ──────────────────────────────────────────────────────────────────────────────────

def test_ms1_current():
    r = mds.resolve(cfg("current"), {}, integrated=True)
    assert (r.effective, r.serve_from, r.our_feeds_on, r.truedata_feeds_on, r.reasons) == \
        ("current", "current", True, False, ())


def test_ms2_not_integrated_stays_current():
    r = mds.resolve(cfg("truedata", licence=True), READY, integrated=False)
    assert r.effective == "current" and r.our_feeds_on and "TRUEDATA_NOT_INTEGRATED" in r.reasons


def test_ms3_no_credentials_stays_current():
    r = mds.resolve(cfg("truedata", licence=True), {"TRUEDATA_USERNAME": "u"}, integrated=True)
    assert r.effective == "current" and r.our_feeds_on and r.reasons == ("TRUEDATA_NOT_CONFIGURED",)


def test_ms4_no_licence_runs_shadow_only():
    r = mds.resolve(cfg("truedata"), READY, integrated=True)
    assert (r.effective, r.serve_from, r.our_feeds_on, r.truedata_feeds_on) == ("shadow", "current", True, True)
    assert r.reasons == ("TRUEDATA_LICENCE_NOT_CONFIRMED",)


def test_ms5_truedata_serves_and_our_feeds_go_off():
    r = mds.resolve(cfg("truedata", licence=True), READY, integrated=True)
    assert (r.effective, r.serve_from, r.our_feeds_on, r.truedata_feeds_on, r.reasons) == \
        ("truedata", "truedata", False, True, ())


def test_ms6_shadow():
    r = mds.resolve(cfg("shadow"), READY, integrated=True)
    assert (r.effective, r.serve_from, r.our_feeds_on, r.truedata_feeds_on) == ("shadow", "current", True, True)


def test_ms7_env_forces_current():
    r = mds.resolve(cfg("truedata", licence=True), {**READY, "MARKET_DATA_SOURCE_FORCE_CURRENT": "1"},
                    integrated=True)
    assert r.effective == "current" and r.our_feeds_on and r.reasons[0] == "FORCED_CURRENT_BY_ENV"


def test_ms8_invalid_source():
    r = mds.resolve(cfg("nse"), READY, integrated=True)
    assert r.effective == "current" and r.reasons[0].startswith("INVALID_SOURCE")


def test_ms9_missing_and_unreadable_file(tmp_path, monkeypatch):
    missing = tmp_path / "nope.json"
    data, reasons = mds.load_config(missing)
    assert data == {} and reasons[0].startswith("CONFIG_MISSING")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    data, reasons = mds.load_config(bad)
    assert data == {} and reasons[0].startswith("CONFIG_UNREADABLE")
    monkeypatch.setattr(mds, "CONFIG_PATH", missing)
    r = mds.resolve(None, READY, integrated=True)
    assert r.effective == "current" and r.our_feeds_on and r.reasons[0].startswith("CONFIG_MISSING")


def test_ms10_only_replaced_feeds_follow_the_switch():
    off = mds.resolve(cfg("truedata", licence=True), READY, integrated=True)
    on = mds.resolve(cfg("current"), {}, integrated=True)
    for feed in ("index_close", "corporate_actions", "kite_live_feed"):
        assert mds.feed_is_on(feed, on) is True and mds.feed_is_on(feed, off) is False
    # NSE's equity and F&O bhavcopies are the record (raw prices, settle, delisted names): never switched off.
    for feed in ("bhavcopy", "fno_bhavcopy", "delivery", "fii_dii", "index_constituents", "nse_shareholding",
                 "event_calendar", "amfi_nav"):
        assert mds.feed_is_on(feed, off) is True
    assert "bhavcopy" not in mds.REPLACED_FEEDS and "fno_bhavcopy" not in mds.REPLACED_FEEDS


def test_ms11_committed_file_is_current():
    data = json.loads(mds.CONFIG_PATH.read_text())
    assert data["source"] == "current" and data["truedata_licence_confirmed"] is False
    assert mds.TRUEDATA_INTEGRATED is False
    r = mds.resolve(env={})
    assert r.effective == "current" and r.our_feeds_on and r.reasons == ()


# ── Wiring ────────────────────────────────────────────────────────────────────────────────────

TRUEDATA_SERVES = mds.resolve(cfg("truedata", licence=True), READY, integrated=True)
CURRENT = mds.resolve(cfg("current"), {}, integrated=True)


class FakeRun:
    def __init__(self, **kw):
        self.run_id = "r1"
        self.final = None
        self.metadata = {}
        self.source_url = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def finalize(self, status, **kw):
        self.final = (status, kw)


def _ingester(name, calls):
    from nidp.shared.ingester_base import BaseIngester

    class Probe(BaseIngester):
        SERVICE_NAME = name
        SOURCE_NAME = "TEST"
        KAFKA_TOPIC = "t"
        AVRO_SCHEMA = "s"

        async def fetch(self, target_date):
            calls.append("fetch")
            return b"", "http://x", 200          # empty body → the existing SKIPPED path

        def parse(self, body, target_date):
            return []

        def validate(self, rows):
            return rows

        async def persist(self, rows, run):
            return 0
    return Probe()


def _run_ingester(monkeypatch, name, resolution):
    from nidp.shared import ingester_base
    calls: list[str] = []
    runs: list[FakeRun] = []

    def make_run(**kw):
        runs.append(FakeRun(**kw))
        return runs[-1]

    monkeypatch.setattr(ingester_base, "JobRun", make_run)
    monkeypatch.setattr(mds, "resolve", lambda *a, **k: resolution)
    asyncio.run(_ingester(name, calls).run(None))
    return calls, runs[0].final


def test_ms12_replaced_feed_is_skipped_when_truedata_serves(monkeypatch):
    calls, final = _run_ingester(monkeypatch, "index_close", TRUEDATA_SERVES)
    assert calls == [] and final[0] == "SKIPPED" and final[1]["error_class"] == "SWITCHED_OFF"
    assert "market data source is TrueData" in final[1]["error_message"]


def test_ms13_replaced_feed_runs_at_current(monkeypatch):
    calls, final = _run_ingester(monkeypatch, "index_close", CURRENT)
    assert calls == ["fetch"] and final[1].get("error_class") != "SWITCHED_OFF"


def test_ms14_other_feeds_run_while_truedata_serves(monkeypatch):
    calls, _ = _run_ingester(monkeypatch, "delivery", TRUEDATA_SERVES)
    assert calls == ["fetch"]


@pytest.mark.parametrize("feed", ["bhavcopy", "fno_bhavcopy"])
def test_ms14b_nse_bhavcopies_keep_running_while_truedata_serves(monkeypatch, feed):
    calls, final = _run_ingester(monkeypatch, feed, TRUEDATA_SERVES)
    assert calls == ["fetch"] and final[1].get("error_class") != "SWITCHED_OFF"


def test_ms15_reconciler_does_not_heal_switched_off_feeds(monkeypatch):
    from nidp.services.feed_reconciler import service as rec
    monkeypatch.delenv("NIDP_RECONCILE_FEEDS", raising=False)
    monkeypatch.setattr(mds, "resolve", lambda *a, **k: TRUEDATA_SERVES)
    assert rec._configured_feeds() == ["bhavcopy", "delivery", "fii_dii", "corporate_announcements", "fno_bhavcopy"]
    monkeypatch.setattr(mds, "resolve", lambda *a, **k: CURRENT)
    assert rec._configured_feeds() == list(rec.DEFAULT_FEEDS)


def test_ms16_dlq_redrive_leaves_switched_off_entries_pending(monkeypatch):
    from nidp.services.dlq_redrive import service as dlq
    rows = [{"id": 1, "feed": "index_close", "target_date": None, "severity": "P0", "notes": None, "created_at": None},
            {"id": 2, "feed": "delivery", "target_date": None, "severity": "P0", "notes": None, "created_at": None}]
    redriven: list[str] = []

    class Conn:
        async def fetch(self, *a):
            return rows

    class Pool:
        def acquire(self):
            class Ctx:
                async def __aenter__(self_inner):
                    return Conn()

                async def __aexit__(self_inner, *a):
                    return False
            return Ctx()

    async def get_pool():
        return Pool()

    async def redrive_one(conn, row, **kw):
        redriven.append(row["feed"])
        return "REPLAYED"

    monkeypatch.setattr(dlq, "get_pool", get_pool)
    monkeypatch.setattr(dlq, "redrive_one", redrive_one)
    monkeypatch.setattr(dlq._job_log, "JobRun", lambda **kw: FakeRun())
    monkeypatch.setattr(mds, "resolve", lambda *a, **k: TRUEDATA_SERVES)
    out = asyncio.run(dlq.redrive(limit=10))
    assert redriven == ["delivery"]
    assert out["SWITCHED_OFF"] == 1 and out["REPLAYED"] == 1 and out["processed"] == 2


# ── The way back (SW-1, SW-2 in test_reports/truedata_client_TESTCASES.md) ────────────────────────────────────

def test_sw1_flipping_the_file_back_to_current_restores_our_feeds(tmp_path, monkeypatch):
    path = tmp_path / "market_data_source.json"
    monkeypatch.setattr(mds, "CONFIG_PATH", path)
    path.write_text(json.dumps(cfg("truedata", licence=True)))
    serving = mds.resolve(env=READY, integrated=True)
    assert serving.effective == "truedata" and mds.truedata_is_on(serving)
    assert not any(mds.feed_is_on(f, serving) for f in mds.REPLACED_FEEDS)

    path.write_text(json.dumps(cfg("current", licence=True)))           # "we are not going with TrueData"
    back = mds.resolve(env=READY, integrated=True)
    assert (back.effective, back.serve_from, back.our_feeds_on, back.truedata_feeds_on, back.reasons) == \
        ("current", "current", True, False, ())
    assert all(mds.feed_is_on(f, back) for f in mds.REPLACED_FEEDS | {"bhavcopy", "fno_bhavcopy", "delivery"})
    assert mds.truedata_is_on(back) is False and "'current'" in mds.truedata_off_message(back)


def test_sw2_emergency_env_switches_truedata_off_without_a_pr():
    r = mds.resolve(cfg("truedata", licence=True), {**READY, "MARKET_DATA_SOURCE_FORCE_CURRENT": "1"},
                    integrated=True)
    assert r.effective == "current" and mds.truedata_is_on(r) is False
    assert all(mds.feed_is_on(f, r) for f in mds.REPLACED_FEEDS)
    assert "FORCED_CURRENT_BY_ENV" in mds.truedata_off_message(r)
