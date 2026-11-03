"""AI scanner watchlist: the F&O chain date gate, the cron after the F&O ingest, and the board's expiry rule — J-1 … J-8,
E-1 … E-8 and C-1 of test_reports/watchlist_fno_chain_expiry_TESTCASES.md.

No database, DaaS, NSE or Kite: the store, the scan check, the regime and the two F&O reads are stubbed. The board cases
price the REAL captured NIFTY chain (tests/fixtures/fno_chain_nifty_20261021.json) under the chain day and expiry each
case sets, so what is asserted is which expiry is chosen, not the pricing (covered in test_regime_fit.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from routes import fno
from scripts import build_ai_watchlist as job
from services import ai_watchlist_build as build
from services import ai_watchlist_store as store
from services.strategy_plan import regime_fit as rf

FIXTURE = Path(__file__).parent / "fixtures" / "fno_chain_nifty_20261021.json"
DAY, PREV = "2026-10-27", "2026-10-26"      # 27 Oct 2026 is a Tuesday and a monthly expiry; 26 Oct the session before


# ── J: the job refuses a day whose F&O half is not on that day's chain ─────────

def top_on(*chain_days, unavailable=()):
    """A board answer whose index class read `chain_days[0]` and whose ideas each carry one of `chain_days`."""
    ideas = [{"underlying": f"U{n}", "structure": "bear_put_spread", "fit": {"score": 90.0 - n, "because": []},
              "reward_risk": 1.0, "expiry": "2026-11-03", "data_as_of": {"chain": d, "regime": PREV}, "alternatives": []}
             for n, d in enumerate(chain_days)]
    return {"classes": {"index_options": {"as_of": chain_days[0] if chain_days else None, "ideas": ideas,
                                          "unavailable": list(unavailable)},
                        "stock_fno": {"ideas": [], "unavailable": []}}}


@pytest.fixture
def world(monkeypatch):
    seen = {"built": 0, "inserted": []}
    state = {"signals": 666, "has": False, "top": top_on(DAY)}

    async def signals_on(d):
        return state["signals"]

    async def has_day(d):
        return state["has"]

    async def build_day(d):
        seen["built"] += 1
        return build.shape_day(d, {"ideas": []}, state["top"], datetime(2026, 10, 27, 17, 15, tzinfo=timezone.utc))

    async def insert_day(doc):
        seen["inserted"].append(doc["list_date"])
        state["has"] = True
        return True

    import scripts.run_positional_engine as rpe
    monkeypatch.setattr(rpe, "signals_on", signals_on)
    monkeypatch.setattr(store, "has_day", has_day)
    monkeypatch.setattr(store, "insert_day", insert_day)
    monkeypatch.setattr(build, "build_day", build_day)
    return seen, state


def run(**kw):
    return asyncio.run(job.run(DAY, skip_if_done=kw.get("skip_if_done", True), dry_run=kw.get("dry_run", False)))


def test_j1_chain_of_the_list_date_builds_and_stores_once(world):
    seen, _ = world
    assert run() == 0
    assert seen == {"built": 1, "inserted": [DAY]}


def test_j2_previous_sessions_chain_is_refused_with_exit_4_and_nothing_written(world, caplog):
    seen, state = world
    state["top"] = top_on(PREV)
    with caplog.at_level(logging.INFO, logger="ai_watchlist"):
        assert run() == 4
    assert seen["inserted"] == []
    refused = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(refused) == 1 and PREV in refused[0] and f"not the list date {DAY}" in refused[0]


def test_j3_no_chain_at_all_is_refused_with_the_boards_reasons(world, caplog):
    seen, state = world
    state["top"] = top_on(unavailable=[{"underlying": "NIFTY", "reason": rf._NO_REGIME}])
    with caplog.at_level(logging.INFO, logger="ai_watchlist"):
        assert run() == 4
    assert seen["inserted"] == []
    msg = next(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert "read no option chain" in msg and rf._NO_REGIME in msg


def test_j4_one_idea_on_the_previous_chain_refuses_the_whole_day(world):
    seen, state = world
    state["top"] = top_on(DAY, DAY, PREV)
    assert run() == 4 and seen["inserted"] == []


def test_j5_a_retry_after_the_chain_arrives_builds_once_and_then_skips(world):
    seen, state = world
    state["top"] = top_on(PREV)
    assert run() == 4                                   # 22:45: the F&O file is late
    state["top"] = top_on(DAY)
    assert run() == 0                                   # 23:30: it is in
    assert run() == 0                                   # 23:55: stored, nothing to do
    assert seen == {"built": 2, "inserted": [DAY]}


def test_j6_skip_if_done_with_the_day_stored_builds_nothing(world):
    seen, state = world
    state["has"] = True
    assert run() == 0 and seen == {"built": 0, "inserted": []}


def test_j7_dry_run_applies_the_same_check_and_never_writes(world):
    seen, state = world
    state["top"] = top_on(PREV)
    assert run(dry_run=True) == 4
    state["top"] = top_on(DAY)
    assert run(dry_run=True) == 0
    assert seen["inserted"] == []


def test_j8_every_chain_day_is_recorded_and_the_cash_half_is_unchanged():
    top = top_on(DAY, PREV)
    top["classes"]["index_options"]["ideas"][0]["alternatives"] = [{"data_as_of": {"chain": "2026-10-23"}}]
    top["classes"]["stock_fno"]["as_of"] = DAY
    d = build.shape_day(DAY, {"ideas": [{"symbol": "A", "scanner": {}}]}, top, datetime(2026, 10, 27, tzinfo=timezone.utc))
    assert d["notes"]["fno_chain_dates"] == ["2026-10-23", PREV, DAY]
    assert build.chain_refusal(d) == f"the F&O option chain is from 2026-10-23, {PREV}, {DAY}, not the list date {DAY}"
    assert [c["symbol"] for c in d["cash"]] == ["A"]
    assert build.chain_refusal(build.shape_day(DAY, {}, top_on(DAY), datetime(2026, 10, 27, tzinfo=timezone.utc))) is None


# ── E: the board never offers a contract expiring on or before its chain day ───

def captured_chain():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def chain_reads(monkeypatch):
    """fno.expiries / fno.chain stubbed: `listing[symbol]` is (as_of, [expiries]); the chain read answers for
    `answer_day[symbol]` (default: the listing's day) with the requested expiry, priced off the captured chain."""
    listing: dict = {}
    answer_day: dict = {}
    reads: list = []

    async def expiries(request, symbol):
        as_of, exps = listing[symbol]
        from datetime import date
        return {"symbol": symbol, "as_of": as_of, "count": len(exps),
                "expiries": [{"expiry": e, "days_to_expiry": (date.fromisoformat(e) - date.fromisoformat(as_of)).days} for e in exps]}

    async def chain(request, symbol, expiry, around):
        reads.append((symbol, expiry.isoformat()))
        ch = captured_chain()
        ch["symbol"] = symbol
        ch["summary"].update(as_of=answer_day.get(symbol, listing[symbol][0]), expiry=expiry.isoformat())
        return ch

    monkeypatch.setattr(fno, "expiries", expiries)
    monkeypatch.setattr(fno, "chain", chain)
    return listing, answer_day, reads


REGIME = {"available": True, "key": "bearish", "as_of": PREV, "trend": "down", "nifty_vs_average_pct": -2.66,
          "india_vix": 14.77, "vix_high_threshold": 20.0, "volatility": "low", "breadth": "down", "advancing_share_pct": 19.0}


@pytest.mark.parametrize("chain_day, expiry, want", [
    (DAY, DAY, 0),                      # the expiry day itself
    (DAY, PREV, 0),                     # already expired
    (PREV, DAY, 1),                     # Mon -> Tue
    ("2026-10-23", PREV, 1),            # Fri -> Mon
    ("2026-10-22", DAY, 3),             # Thu -> next Tue
    (PREV, "2026-11-24", 21),           # four weeks and a day
])
def test_e1_sessions_to_expiry_counts_weekdays_after_the_chain_day(chain_day, expiry, want):
    assert rf.sessions_to_expiry(chain_day, expiry) == want


def test_e2_e3_a_chain_dated_an_expiry_day_uses_the_next_expiry_and_records_the_skipped_one(chain_reads):
    listing, _, reads = chain_reads
    listing["NIFTY"] = (DAY, [DAY, "2026-11-03", "2026-11-24"])
    r = asyncio.run(rf.ideas_for_underlying(None, "NIFTY", REGIME, limit=50))
    assert r["available"] is True and r["ideas"], r.get("reason")
    assert reads == [("NIFTY", "2026-11-03")]                         # the chain day's expiry is never read
    assert r["expiry"] == "2026-11-03" and r["as_of"] == DAY
    assert {i["expiry"] for i in r["ideas"]} == {"2026-11-03"}
    assert {l["expiry"] for i in r["ideas"] for l in i["legs"]} == {"2026-11-03"}
    assert r["expiries_skipped"] == [{"expiry": DAY, "reason": f"expiry {DAY} is 0 session(s) after the chain date {DAY}; at least 1 needed"}]


def test_e4_no_qualifying_expiry_drops_the_underlying_with_the_reason(chain_reads, monkeypatch):
    listing, _, reads = chain_reads
    listing["NIFTY"] = (DAY, [DAY])
    listing["BANKNIFTY"] = (DAY, [DAY, "2026-11-24"])

    with pytest.raises(LookupError, match=r"no listed expiry is at least 1 session\(s\) after the chain date 2026-10-27"):
        asyncio.run(rf._chain_for(None, "NIFTY", None))
    r = asyncio.run(rf.ideas_for_underlying(None, "NIFTY", REGIME))
    assert r["available"] is False and r["ideas"] == [] and "no listed expiry" in r["reason"]

    async def regime():
        return REGIME
    monkeypatch.setattr(rf, "read_regime", regime)
    out = asyncio.run(rf.build_top(None, "u1", limit=10, classes=["index_options"], distinct=True))
    idx = out["classes"]["index_options"]
    assert [u["underlying"] for u in idx["unavailable"]] == ["NIFTY"] and "no listed expiry" in idx["unavailable"][0]["reason"]
    assert {i["underlying"] for i in idx["ideas"]} == {"BANKNIFTY"}
    offered = [x for i in idx["ideas"] for x in (i, *i["alternatives"])]
    assert offered and all(x["expiry"] > x["data_as_of"]["chain"] for x in offered)
    assert all(l["expiry"] == "2026-11-24" for x in offered for l in x["legs"])
    assert ("NIFTY", DAY) not in reads


def test_e5_a_requested_expiry_on_the_chain_day_is_refused_without_a_chain_read(chain_reads):
    listing, _, reads = chain_reads
    listing["NIFTY"] = (DAY, [DAY, "2026-11-03"])
    with pytest.raises(LookupError, match=r"the requested expiry 2026-10-27 is 0 session\(s\)"):
        asyncio.run(rf._chain_for(None, "NIFTY", DAY))
    assert reads == []
    assert asyncio.run(rf._chain_for(None, "NIFTY", "2026-11-03"))["summary"]["expiry"] == "2026-11-03"


def test_e6_a_chain_that_moved_to_the_expiry_day_between_the_reads_is_refused(chain_reads):
    listing, answer_day, _ = chain_reads
    listing["NIFTY"] = (PREV, [DAY, "2026-11-03"])      # listed on the 26th: the 27th is one session out, so it qualifies
    answer_day["NIFTY"] = DAY                            # but the chain read answers for the 27th itself
    with pytest.raises(LookupError, match=r"expiry 2026-10-27 is 0 session\(s\) after the chain date 2026-10-27"):
        asyncio.run(rf._chain_for(None, "NIFTY", None))


def test_e7_the_constant_is_the_one_control(chain_reads, monkeypatch):
    listing, _, _ = chain_reads
    listing["NIFTY"] = (PREV, [DAY, "2026-11-03"])
    assert asyncio.run(rf._chain_for(None, "NIFTY", None))["summary"]["expiry"] == DAY          # default 1: one session out is fine
    monkeypatch.setattr(rf, "MIN_SESSIONS_TO_EXPIRY", 2)
    ch = asyncio.run(rf._chain_for(None, "NIFTY", None))
    assert ch["summary"]["expiry"] == "2026-11-03"
    assert ch["expiries_skipped"] == [{"expiry": DAY, "reason": f"expiry {DAY} is 1 session(s) after the chain date {PREV}; at least 2 needed"}]


def test_e8_the_rule_is_stated_with_the_boards_notes_and_tells_no_one_to_trade():
    rule = next(g for g in rf.GAPS if g.startswith("Expiry rule"))
    assert "on or before the chain's own day" in rule and f"at least {rf.MIN_SESSIONS_TO_EXPIRY} session" in rule
    assert rf.MIN_SESSIONS_TO_EXPIRY == 1
    assert rf.REGIME_FIT_VERSION.startswith("regime-fit-v1.1")
    text = " ".join(rf.GAPS).lower()
    for word in (" buy ", " sell ", "you should", "we recommend", "pick", "recommended", "suggested"):
        assert word not in text


# ── C-1: the cron runs after the F&O bhavcopy, retries, and cannot overlap ─────

def test_c1_the_job_runs_after_the_last_fno_bhavcopy_ingest_with_retries_under_a_lock():
    deploy = Path(__file__).resolve().parents[2] / "deploy"
    cron = (deploy / "nivesh-staging" / "ai-watchlist.cron").read_text()
    assert "CRON_TZ=Asia/Kolkata" in cron
    lines = [l for l in cron.splitlines() if l and not l.startswith("#") and "python -m" in l]
    assert [l.split()[:5] for l in lines] == [["45", "22", "*", "*", "1-5"], ["30", "23", "*", "*", "1-5"],
                                              ["55", "23", "*", "*", "1-5"]]
    for l in lines:
        assert "/usr/bin/flock -n /run/lock/nivesh-staging-ai-watchlist.lock /usr/bin/docker exec nivesh-staging-app-backend" in l
        assert "python -m scripts.build_ai_watchlist --skip-if-done >>" in l and "--dry-run" not in l
    ingest = [l.split()[:2] for l in (deploy / "cloudpe" / "nidp" / "nidp-staging.cron").read_text().splitlines()
              if l and not l.startswith("#") and l.rstrip().endswith("run_service.sh fno_bhavcopy")]
    assert ingest and max((int(h), int(m)) for m, h in ingest) < (22, 45)
