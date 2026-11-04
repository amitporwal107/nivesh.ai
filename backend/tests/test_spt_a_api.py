"""SPT slice A — routes and the backfill script (test cases test_reports/spt_a_TESTCASES.md SPT-A-32 … SPT-A-35).

Covers routes/spt_signals.py and scripts/spt_backfill_signals.py. No network and no real database:
    Mongo               tests/spt_a_fakes.DB, set as the route's `db`
    the user            the route's get_current_user reads the X-Test-User header (401 without it)
    market data         spt_a_fakes.Inputs for POST …/validate, with the clock pinned to 4 Nov 2026 10:00 IST

MOCK — not real data, except the archive lines written for SPT-A-35, which are records copied from the 4 Nov 2026 Redis dump
(tests/fixtures/spt_a_signals_20261104.json: market-wide scanner output).
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import spt_signals as route
from scripts import spt_backfill_signals as backfill
from services.spt import constants as C
from services.spt.opportunities import consolidate as cons
from services.spt.opportunities import validate as val
from services.spt.signals import ingest
from tests.spt_a_fakes import DAY, DB, D, Inputs, ist, mark, reset_module_state, rising, strong

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "spt_a_signals_20261104.json").read_text())
NOW = ist(10, 0, 30)
A = {"X-Test-User": "user_a"}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean():
    reset_module_state()
    yield


@pytest.fixture
def api(monkeypatch):
    db = DB()
    monkeypatch.setattr(route, "db", db)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    monkeypatch.setattr(route, "get_current_user", fake_user)
    inputs = Inputs({"AAA": rising(260, start=50.0, step=0.2, end=date(2026, 11, 3))})
    real = val.validate

    async def pinned(db_, oid, **kw):
        return await real(db_, oid, inputs=inputs, now=NOW)

    monkeypatch.setattr(route.opp_validate, "validate", pinned)
    run(ingest.ingest(db, day=DAY, marks=[mark("dt_52w_high", "AAA", ist(9, 30), 102.0),
                                          mark("dt_below_dma", "BBB", ist(9, 31), 50.0),
                                          mark("no_such_list", "CCC", ist(9, 32))],
                      strong=[strong("AAA", ist(9, 45), entry=103.0)], now=NOW))
    run(cons.consolidate(db, days=[DAY], now=NOW))
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), db


ROUTES = [("get", "/api/v1/scanner/signals"), ("get", "/api/v1/scanner/signals/sig:2026-11-04:strong:AAA"),
          ("get", "/api/v1/opportunities"), ("get", "/api/v1/opportunities/x"), ("post", "/api/v1/opportunities/x/validate")]


@pytest.mark.parametrize("method, url", ROUTES)
def test_SPT_A_32_every_route_needs_a_session(api, method, url):
    client, db = api
    r = getattr(client, method)(url)
    assert r.status_code == 401


def test_SPT_A_33_signals_list_filters_and_limits(api):
    client, db = api
    body = client.get("/api/v1/scanner/signals", headers=A).json()
    assert body["ok"] and body["count"] == 4 and body["limit"] == 100
    assert [s["_id"] for s in body["signals"]][0] == "sig:2026-11-04:strong:AAA"             # newest detection first
    assert client.get("/api/v1/scanner/signals", params={"symbol": "aaa"}, headers=A).json()["count"] == 2
    assert client.get("/api/v1/scanner/signals", params={"scanner_id": "strength_70"}, headers=A).json()["count"] == 1
    assert client.get("/api/v1/scanner/signals", params={"category": "breakdown"}, headers=A).json()["count"] == 1
    q = client.get("/api/v1/scanner/signals", params={"status": "quarantined"}, headers=A).json()
    assert [s["symbol"] for s in q["signals"]] == ["CCC"] and q["signals"][0]["quarantine_reasons"] == ["missing_mapping"]
    assert client.get("/api/v1/scanner/signals", params={"day": "2026-11-05"}, headers=A).json()["count"] == 0
    assert client.get("/api/v1/scanner/signals", params={"limit": 1}, headers=A).json()["count"] == 1
    for params, code in (({"limit": 501}, "invalid_limit"), ({"limit": 0}, "invalid_limit"), ({"day": "4 Nov"}, "invalid_day"),
                         ({"symbol": "A B"}, "invalid_symbol"), ({"category": "luck"}, "invalid_category"),
                         ({"status": "done"}, "invalid_status"), ({"scanner_id": "x y"}, "invalid_scanner_id")):
        r = client.get("/api/v1/scanner/signals", params=params, headers=A)
        assert (r.status_code, r.json()["detail"]) == (422, code), params
    one = client.get("/api/v1/scanner/signals/sig:2026-11-04:strong:AAA", headers=A).json()
    assert one["signal"]["scanner_score"] == 75 and len(one["opportunities"]) == 1
    assert one["opportunities"][0]["consolidation_key"] == "AAA|long|positional|2026-11-04"
    r = client.get("/api/v1/scanner/signals/sig:2026-11-04:strong:ZZZ", headers=A)
    assert (r.status_code, r.json()["detail"]) == (404, "signal_not_found")


def test_SPT_A_34_opportunities_list_get_and_revalidate(api):
    client, db = api
    body = client.get("/api/v1/opportunities", headers=A).json()
    assert body["count"] == 2 and "not a probability" in body["score_label"]
    assert [o["symbol"] for o in client.get("/api/v1/opportunities", params={"direction": "short"},
                                            headers=A).json()["opportunities"]] == ["BBB"]
    assert client.get("/api/v1/opportunities", params={"horizon": "intraday"}, headers=A).json()["count"] == 0
    assert client.get("/api/v1/opportunities", params={"state": "CREATED", "day": DAY, "symbol": "AAA"},
                      headers=A).json()["count"] == 1
    for params, code in (({"state": "DONE"}, "invalid_state"), ({"horizon": "weekly"}, "invalid_horizon"),
                         ({"direction": "up"}, "invalid_direction"), ({"limit": 999}, "invalid_limit")):
        r = client.get("/api/v1/opportunities", params=params, headers=A)
        assert (r.status_code, r.json()["detail"]) == (422, code), params
    aaa = next(o for o in body["opportunities"] if o["symbol"] == "AAA")
    got = client.get(f"/api/v1/opportunities/{aaa['_id']}", headers=A).json()
    assert got["opportunity"]["strong"]["plan"]["stop_loss"] == 99.0
    r = client.get("/api/v1/opportunities/not-there", headers=A)
    assert (r.status_code, r.json()["detail"]) == (404, "opportunity_not_found")
    r = client.post(f"/api/v1/opportunities/{aaa['_id']}/validate", headers=A)
    assert r.status_code == 200 and r.json()["state"] == C.OPP_QUALIFIED
    assert r.json()["validation"]["decision"] == C.OPP_QUALIFIED
    r = client.post(f"/api/v1/opportunities/{aaa['_id']}/validate", headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "opportunity_not_revalidatable")
    r = client.post("/api/v1/opportunities/not-there/validate", headers=A)
    assert (r.status_code, r.json()["detail"]) == (404, "opportunity_not_found")


# ── SPT-A-35: the backfill script ────────────────────────────────────────────────────────────────────────────────────

def archive_file(tmp_path: Path) -> Path:
    """Write the fixture's real 4 Nov records the way the Redis dump stores them (one JSON line per key)."""
    p = tmp_path / "dump.jsonl"
    lines = []
    for m in FIXTURE["marks"]:
        lines.append({"key": f"nivesh:sb:signals:{DAY}:s:{m['widget_id']}:{m['symbol']}", "type": "string", "ttl_s": 1,
                      "value": json.dumps(m)})
    for s in FIXTURE["strong"]:
        lines.append({"key": f"nivesh:sb:signals:{DAY}:g:{s['symbol']}", "type": "string", "ttl_s": 1, "value": json.dumps(s)})
    lines.append({"key": f"nivesh:sb:signals:{DAY}:scores", "type": "string", "ttl_s": 1,
                  "value": json.dumps(FIXTURE["scores_doc"])})
    lines.append({"key": f"nivesh:sb:signals:{DAY}:index", "type": "list", "ttl_s": 1, "value": ["ignored"]})
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    return p


def test_SPT_A_35_backfill_dry_run_writes_nothing_and_write_is_idempotent(tmp_path):
    p = archive_file(tmp_path)
    db = DB()
    out = []
    next_morning = ist(2, 30, day=D + timedelta(days=1))
    code = run(backfill.main(["--source", f"archive:{p}"], db=db, out=out.append, now=next_morning))
    assert code == 0 and db.writes == 0
    dry = json.loads(out[0])
    assert (dry["mode"], dry["day"], dry["events"], dry["list_marks"], dry["strong"]) == ("dry-run", DAY, 16, 14, 2)
    # the next morning: the intraday marks (15-minute breakouts, RSI VWAP, early movers) are past their window
    assert dry["quarantine_reasons"] == {"stale": 5} and dry["normalized"] == 11
    assert dry["with_scanner_score"] == 2                                  # the strong ones; the 22:45 scores doc is too late
    out.clear()
    code = run(backfill.main(["--source", f"archive:{p}", "--day", DAY, "--write"], db=db, out=out.append, now=next_morning))
    res = json.loads(out[0])
    assert code == 0 and res["ingest"]["inserted"] == 16 and res["consolidate"]["created"] == dry["opportunity_groups"]
    hd = [o for o in db["spt_opportunities"].docs if o["symbol"] == "HDFCAMC"]
    assert len(hd) == 1 and hd[0]["strong"]["plan"]["stop_loss"] == 2376.28
    assert sorted(s["scanner_id"] for s in hd[0]["signals"]) == ["dt_multiyear", "long_buildup", "oi_7", "strength_70"]
    writes = db.writes
    out.clear()
    code = run(backfill.main(["--source", f"archive:{p}", "--write"], db=db, out=out.append, now=next_morning))
    again = json.loads(out[0])
    assert code == 0 and again["ingest"]["inserted"] == 0 and again["ingest"]["duplicate"] == 16
    assert again["consolidate"]["created"] == 0 and db.writes == writes


def test_SPT_A_35_backfill_bad_arguments(tmp_path):
    out = []
    assert run(backfill.main(["--source", "redis"], db=DB(), out=out.append)) == 2
    assert run(backfill.main(["--source", "ftp:x"], db=DB(), out=out.append)) == 2
    assert run(backfill.main(["--source", "archive:/no/such/file"], db=DB(), out=out.append)) == 1
    assert run(backfill.main(["--source", f"archive:{archive_file(tmp_path)}", "--day", "2026-13-01"], db=DB(),
                             out=out.append)) == 2
