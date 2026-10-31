"""The atomic risk reservation against a REAL MongoDB (TESTCASES F R-1 to R-7; criteria 1.3 acceptance).

The in-memory fakes cannot interleave inside one update, so they cannot prove atomicity. This suite runs only when
RISK_MONGO_URL points at a disposable mongod (a throwaway `mongo:7` container on a private docker network; the commands
are in test_reports/p1_universal_risk_*.md). Each test uses its own database, dropped afterwards. MOCK — not real data:
every user, symbol, sector and amount is made up.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

URL = os.environ.get("RISK_MONGO_URL")
pytestmark = pytest.mark.skipif(not URL, reason="RISK_MONGO_URL not set (needs a disposable mongod)")

NOW = datetime(2026, 10, 28, 5, 0, tzinfo=timezone.utc)     # Wednesday 10:30 IST
CAPS = {"open_risk_cap_rs": 30_000.0, "exposure_cap_rs": 800_000.0, "sector_cap_rs": 250_000.0, "max_positions": 10}


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(URL)
    name = f"p1risk_{uuid.uuid4().hex[:10]}"
    return client, client[name], name


def entry(i, *, risk=5000.0, exposure=50_000.0, symbol=None, sector=None, held=True):
    return {"id": f"r{i}-{uuid.uuid4().hex[:6]}", "trade_id": f"t{i}", "store": "desk_paper_trades", "path": "desk_paper_trade",
            "kind": "cash", "symbol": symbol or f"SYM{i}", "sector": sector or f"Sector {i}", "funding_rs": exposure,
            "risk_rs": risk, "exposure_rs": exposure, "positions": 1, "held": held}


def test_r1_concurrent_reservations_never_exceed_the_open_risk_cap():
    from services import paper_account as acct

    async def go():
        client, db, name = await _db()
        try:
            await acct.ensure(db, "u1")
            results = await asyncio.gather(*(acct.reserve_entry(db, "u1", entry(i), CAPS) for i in range(20)),
                                           return_exceptions=True)
            ok = [r for r in results if isinstance(r, dict)]
            refused = [r for r in results if isinstance(r, acct.ReservationRefused)]
            doc = await db[acct.ACCOUNTS].find_one({"user_id": "u1"})
            return ok, refused, doc
        finally:
            await client.drop_database(name)
            client.close()

    ok, refused, doc = run(go())
    assert len(ok) == 6 and len(refused) == 14                        # Rs 30,000 / Rs 5,000
    assert all("open_risk_exceeded" in r.which for r in refused)
    assert doc["open_risk_rs"] == 30_000.0 and doc["open_positions"] == 6 and len(doc["reservations"]) == 6
    assert doc["blocked_rs"] == 300_000.0
    from services import paper_account as acct2
    assert acct2.reservation_invariants(doc) == []                     # no leaked or double-counted reservation


def test_r3_r4_r5_retry_duplicate_symbol_and_cancel():
    from services import paper_account as acct

    async def go():
        client, db, name = await _db()
        try:
            await acct.ensure(db, "u1")
            e = entry(1)
            first = await acct.reserve_entry(db, "u1", e, CAPS)
            again = await acct.reserve_entry(db, "u1", e, CAPS)         # R-3 a retry of the same reservation
            doc1 = await db[acct.ACCOUNTS].find_one({"user_id": "u1"})
            dup = await asyncio.gather(*(acct.reserve_entry(db, "u1", entry(i, symbol="SAME"), CAPS) for i in (2, 3)),
                                       return_exceptions=True)          # R-4 two concurrent entries in one symbol
            doc2 = await db[acct.ACCOUNTS].find_one({"user_id": "u1"})
            c1 = await acct.cancel_reservation(db, "u1", first["id"], reason="test")      # R-5
            c2 = await acct.cancel_reservation(db, "u1", first["id"], reason="test")
            doc3 = await db[acct.ACCOUNTS].find_one({"user_id": "u1"})
            return first, again, doc1, dup, doc2, (c1, c2), doc3
        finally:
            await client.drop_database(name)
            client.close()

    first, again, doc1, dup, doc2, cancels, doc3 = run(go())
    assert again["id"] == first["id"] and len(doc1["reservations"]) == 1 and doc1["open_risk_rs"] == 5000.0
    assert sum(isinstance(d, dict) for d in dup) == 1
    assert [x.which for x in dup if not isinstance(x, dict)] == [["already_held"]]
    assert doc2["held_symbols"]["SAME"] == 1 and doc2["open_positions"] == 2
    assert cancels == (True, False)
    assert doc3["open_risk_rs"] == 5000.0 and doc3["blocked_rs"] == 50_000.0 and len(doc3["reservations"]) == 1
    from services import paper_account as acct2
    assert acct2.reservation_invariants(doc3) == []


def test_r6_closing_a_trade_releases_its_reservation_exactly_once():
    from services import desk_trading as desk
    from services import paper_account as acct

    async def go():
        client, db, name = await _db()
        try:
            await acct.ensure(db, "u1")
            trade = desk.new_trade("u1", {"symbol": "FIXA", "quantity": 50, "entry_price": 1000.0, "stop_price": 950.0,
                                          "target_price": 1150.0}, NOW)
            e = {**entry(1, symbol="FIXA", exposure=50_000.0), "trade_id": trade["_id"]}
            res = await acct.reserve_entry(db, "u1", e, CAPS)
            trade.update(paper_reserved_rs=50_000.0, risk_reservation_id=res["id"])
            await db[desk.TRADES].insert_one(dict(trade))
            one = await desk.close_trade(db, trade, exit_reason="manual", exit_price=1010.0, exit_session=None)
            two = await desk.close_trade(db, trade, exit_reason="manual", exit_price=1010.0, exit_session=None)
            doc = await db[acct.ACCOUNTS].find_one({"user_id": "u1"})
            return one, two, doc
        finally:
            await client.drop_database(name)
            client.close()

    one, two, doc = run(go())
    assert one[1] is True and two[1] is False                         # the second close matched nothing
    assert doc["blocked_rs"] == 0.0 and doc["open_risk_rs"] == 0.0 and doc["reservations"] == []
    assert doc["held_symbols"]["FIXA"] == 0 and doc["open_positions"] == 0
    assert doc["cash_rs"] == pytest.approx(1_000_000.0 + one[0]["net_pnl_rs"])


def test_r7_a_reservation_whose_process_died_before_the_insert_is_swept_after_the_grace():
    from services import paper_account as acct

    async def go():
        client, db, name = await _db()
        try:
            await acct.ensure(db, "u1")
            await acct.reserve_entry(db, "u1", entry(1), CAPS)          # the "crash": no trade is ever inserted

            async def exists(e):
                return await db["desk_paper_trades"].find_one({"_id": e["trade_id"]}) is not None
            early = await acct.sweep_orphans(db, "u1", exists=exists, now=datetime.now(timezone.utc))
            late = await acct.sweep_orphans(db, "u1", exists=exists,
                                            now=datetime.now(timezone.utc) + timedelta(seconds=acct.ORPHAN_GRACE_S + 5))
            doc = await db[acct.ACCOUNTS].find_one({"user_id": "u1"})
            return early, late, doc
        finally:
            await client.drop_database(name)
            client.close()

    early, late, doc = run(go())
    assert early == [] and len(late) == 1                              # a write in flight is left alone
    assert doc["open_risk_rs"] == 0.0 and doc["blocked_rs"] == 0.0 and doc["reservations"] == []


def test_r2_concurrent_full_decisions_whose_sum_exceeds_the_cap_stay_within_it(monkeypatch):
    """12 entries decided at once through services/risk_gate/service.enter (book read, checks, record, reserve). Each
    decision sees free open risk, so the DECISIONS allow them; the ATOMIC reservation admits only what fits the
    Rs 30,000 open-risk budget (3% of Rs 10 lakh), and every loser is recorded as a blocking row that supersedes it."""
    from services import data_freshness as fresh
    from services import desk_trading as desk
    from services import paper_account as acct
    from services import risk_controls as rc
    from services.risk_gate import estimate as est
    from services.risk_gate import inputs
    from services.risk_gate import service as svc
    from tests.risk_helpers import mock_bars

    # The REAL clock: reservations are stamped with it, and the orphan sweep that runs before every decision judges
    # their age on it (a decision clock 26 hours ahead read every in-flight reservation as an orphan; found by this test).
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(rc, "_indexes_ready", False)
    last = fresh.previous_session(now.astimezone(desk.IST).date())
    days = [last - timedelta(days=k) for k in range(30) if (last - timedelta(days=k)).weekday() < 5][::-1]

    async def bars(symbol, start):
        return mock_bars(1000.0, days=[d for d in days if d >= start])

    async def instrument(symbol, today):
        b = mock_bars(1000.0, days=days)
        return {"bars": b, "last_close": 1000.0, "last_close_as_of": last.isoformat(), "adv_rs": 1e10,
                "adv_sessions": 20, "source": "MOCK", "error": None}

    async def sector_of(symbol):
        return {"sector": f"Sector {symbol}", "as_of": None, "source": "MOCK", "error": None}     # one sector each

    async def market():
        return {"vix": 14.0, "regime": "BULL", "as_of": last.isoformat(), "key": "m", "source": "MOCK", "error": None}

    monkeypatch.setattr(desk, "fetch_bars", bars)
    monkeypatch.setattr(inputs, "instrument", instrument)
    monkeypatch.setattr(inputs, "sector_of", sector_of)
    monkeypatch.setattr(inputs, "market_state", market)
    per = est.cash_risk(60, 1000.0, 950.0)["total"]                    # each entry's estimated risk

    async def go():
        client, db, name = await _db()
        try:
            await acct.ensure(db, "u1")
            reqs = [svc.EntryRequest(correlation_id=f"c{i}", user_id="u1", actor_id="u1", mode="paper",
                                     path="desk_paper_trade", symbol=f"SYM{i}", quantity=60, entry_price=1000.0,
                                     stop_price=950.0, target_price=1150.0, trade_id=f"t{i}") for i in range(12)]
            out = await asyncio.gather(*(svc.enter(db, r, now=now) for r in reqs))
            doc = await db[acct.ACCOUNTS].find_one({"user_id": "u1"})
            rows = await db[rc.DECISIONS].find({"user_id": "u1"}).to_list(100)
            return out, doc, rows
        finally:
            await client.drop_database(name)
            client.close()

    out, doc, rows = run(go())
    accepted = [d for d in out if d["reservation_id"]]
    lost = [d for d in out if not d["reservation_id"]]
    fit = int(30_000.0 // per)
    assert len(accepted) == fit and len(lost) == 12 - fit, (per, len(accepted))
    assert doc["open_risk_rs"] <= 30_000.0 and doc["open_risk_rs"] == pytest.approx(per * fit)
    assert acct.reservation_invariants(doc) == [] and len(doc["reservations"]) == fit
    # A loser either lost the race at the ATOMIC step (its decision allowed, the reservation refused: a second row that
    # supersedes it) or was decided after earlier reservations landed (its own decision reduced or blocked on open
    # risk). Either way nothing was reserved for it.
    raced = [d for d in lost if d.get("supersedes")]
    decided = [d for d in lost if not d.get("supersedes")]
    assert all(d["outcome"] == "block" and any(r["code"] == "open_risk_exceeded" and r["check"] == "reservation"
                                               for r in d["reasons"]) for d in raced)
    assert all(d["outcome"] in ("reduce", "block") and any(r["code"] == "open_risk_exceeded" and r["check"] == "open_risk"
                                                           for r in d["reasons"]) for d in decided)
    by = {r["_id"]: r for r in rows}
    assert len(rows) == 12 + len(raced)                                # every decision, and every lost race, recorded
    assert all(by[d["decision_id"]]["supersedes"] == d["supersedes"] for d in raced)
    print(f"R-2: per-entry risk Rs {per}, accepted {len(accepted)}, lost at the atomic step {len(raced)}, "
          f"refused by their own decision {len(decided)}, reserved Rs {doc['open_risk_rs']} of Rs 30,000")
