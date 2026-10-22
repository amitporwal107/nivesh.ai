"""Resume behaviour of the bulk/block deal ingest.

THE DEFECT THESE EXIST FOR (measured on staging 2026-10-22)
`_symbols()` ordered candidates `ORDER BY 1` and inferred progress from the fact table
(`nidp.trendlyne_deals WHERE retrieved_at::date = current_date`). That marker was day-scoped, so
every new day restarted the alphabetical walk at 'A'; and it only recorded symbols that PRODUCED
ROWS, so a stock with no deals was re-queried out of the shared budget forever. Result: 19,787
legs across 328 symbols and NOT ONE outside 0-9/A-G, with 643 of 984 candidates never queried.

A test asserting "rows arrived" passes on the broken code. These assert the resume itself.
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nidp.services.trendlyne_ownership import deals
from nidp.services.trendlyne_ownership.client import CallBudget, TrendlyneError

IST = timezone(timedelta(hours=5, minutes=30))
DAY1 = datetime(2026, 10, 22, 9, 0, tzinfo=IST)
DAY2 = DAY1 + timedelta(days=1)

# Ten candidates spanning the alphabet, so "did it get past G" is directly observable.
TEN = ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO",
       "HOTEL", "INDIA", "PAPA", "TANGO", "ZULU"]

_ROW = '["SOME FUND","Block","Purchase","2026-09-19",1000,250.5,0.12,"NSE"]'
_HEADERS = """
tableHeaders:
  Client Name|text|client_name
  Deal Type|text|get_deal_type_display
  Action|text|get_action_display
  Date|date|date
  Quantity|number|quantity
  Price|number|price
  Traded %|number|traded_percent
  Exchange|text|exchange

extraHeaders:
"""


def _payload(rows: str) -> str:
    return f"tableData:\n  {rows}\n{_HEADERS}"


PAYLOAD_ONE_DEAL = _payload(_ROW)
PAYLOAD_NO_DEALS = _payload("")


class Warehouse:
    """Stand-in warehouse that emulates the ordering/coverage semantics of deals.py's SQL."""

    def __init__(self, candidates, now=DAY1):
        self.candidates = list(candidates)
        self.fetch_log: dict[str, dict] = {}
        self.deal_rows: list[tuple] = []
        self.now = now
        self.seen_sql: list[str] = []

    # asyncpg pool/connection surface
    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def transaction(self):
        return self

    async def fetch(self, sql, *args, **kw):
        self.seen_sql.append(sql)
        assert "nidp.trendlyne_deal_fetch_log" in sql, sql
        # The regression that must never come back.
        assert "ORDER BY 1" not in sql, sql
        assert "NULLS FIRST" in sql, sql
        refresh = args[0]
        today = self.now.astimezone(IST).date()
        due = [s for s in self.candidates
               if refresh
               or s not in self.fetch_log
               or self.fetch_log[s]["last_attempt_at"].astimezone(IST).date() < today]
        due.sort(key=lambda s: (
            (1, self.fetch_log[s]["last_attempt_at"]) if s in self.fetch_log else (0, self.now),
            hashlib.md5(s.encode()).hexdigest()))
        return [{"symbol": s} for s in due]

    async def fetchrow(self, sql, *args, **kw):
        self.seen_sql.append(sql)
        assert "attempted_ever" in sql, sql
        n = len(self.candidates)
        att = sum(1 for s in self.candidates if s in self.fetch_log)
        return {"candidates": n, "attempted_ever": att, "never_attempted": n - att,
                "attempted_pct": round(100.0 * att / max(n, 1), 1)}

    async def execute(self, sql, *args, **kw):
        assert "INSERT INTO nidp.trendlyne_deal_fetch_log" in sql, sql
        symbol, status, rows, run_id = args
        prev = self.fetch_log.get(symbol)
        self.fetch_log[symbol] = {
            "last_attempt_at": self.now,
            "last_status": status,
            "last_success_at": None if status == "ERROR" else self.now,
            "attempts": (prev["attempts"] + 1) if prev else 1,
            "deal_rows": rows if rows is not None else (prev or {}).get("deal_rows"),
            "last_run_id": run_id,
        }

    async def executemany(self, sql, rows, **kw):
        assert "INSERT INTO nidp.trendlyne_deals" in sql, sql
        self.deal_rows.extend(rows)


class Provider:
    """Stand-in Trendlyne client. Consumes the shared budget exactly as the real one does."""

    def __init__(self, budget: CallBudget, *, empty=(), errors=()):
        self.budget = budget
        self.empty = set(empty)
        self.errors = set(errors)
        self.asked: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def call_tool(self, name, arguments):
        self.budget.take()
        sym = arguments["stock_code"]
        self.asked.append(sym)
        if sym in self.errors:
            raise TrendlyneError("vendor said no")
        return PAYLOAD_NO_DEALS if sym in self.empty else PAYLOAD_ONE_DEAL


class Job:
    def __init__(self, **kw):
        self.run_id = uuid.uuid4()
        self.rows_fetched = 0
        self.rows_inserted = 0
        self.metadata: dict = {}
        self.status = None
        self.error_message = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def finalize(self, status, *, error_message=None, error_class=None):
        self.status = status
        self.error_message = error_message


@pytest.fixture
def wire(monkeypatch):
    """Point deals.py at a stand-in warehouse and provider; returns a run() driver."""
    def _wire(wh: Warehouse, *, empty=(), errors=()):
        async def _pool():
            return wh
        monkeypatch.setattr(deals, "get_pool", _pool)
        jobs: list[Job] = []

        def _job(**kw):
            jobs.append(Job(**kw))
            return jobs[-1]

        monkeypatch.setattr(deals, "JobRun", _job)
        providers: list[Provider] = []

        def _client(budget):
            providers.append(Provider(budget, empty=empty, errors=errors))
            return providers[-1]

        monkeypatch.setattr(deals, "TrendlyneClient", _client)

        def _run(**kw):
            summary = asyncio.run(deals.run(**kw))
            return summary, providers[-1], (jobs[-1] if jobs else None)
        return _run
    return _wire


# ── TC-2: the actual defect ──────────────────────────────────────────────────

def test_budget_break_does_not_restart_at_a(wire):
    """A budget break part-way through must not restart at 'A' on the next run.

    This is the whole repair. On the old code run 2 re-walked the same alphabetical prefix, so the
    tail of the universe was never reached no matter how many times the job ran.
    """
    wh = Warehouse(TEN)
    run = wire(wh)

    s1, p1, _ = run(max_calls=3)
    assert len(p1.asked) == 3, p1.asked

    wh.now = DAY2                      # a new day: the old marker went blank here
    s2, p2, _ = run(max_calls=3)
    assert len(p2.asked) == 3, p2.asked

    assert set(p1.asked).isdisjoint(p2.asked), (p1.asked, p2.asked)
    assert p2.asked[0] != p1.asked[0]
    # The old behaviour, stated explicitly so a regression is unmistakable.
    assert p2.asked != sorted(TEN)[:3]

    wh.now = DAY2 + timedelta(days=1)
    s3, p3, _ = run(max_calls=3)
    wh.now = DAY2 + timedelta(days=2)
    s4, p4, _ = run(max_calls=3)

    covered = set(p1.asked) | set(p2.asked) | set(p3.asked) | set(p4.asked)
    assert covered == set(TEN), sorted(set(TEN) - covered)
    # Coverage escaped A-G, which 19,787 real legs across 328 symbols never did.
    assert any(s[0] > "G" for s in covered)
    assert s4["never_attempted"] == 0, s4


def test_never_attempted_sorts_before_attempted(wire):
    """TC-1: a symbol already attempted is never fetched ahead of one never attempted."""
    wh = Warehouse(TEN)
    run = wire(wh)
    run(max_calls=4)
    attempted_day1 = set(wh.fetch_log)

    wh.now = DAY2
    due = asyncio.run(deals._symbols(None, True, False))
    fresh = [s for s in due if s not in attempted_day1]
    stale = [s for s in due if s in attempted_day1]
    assert due == fresh + stale, due
    assert len(fresh) == len(TEN) - 4


def test_zero_deal_symbol_is_recorded_and_not_requeried(wire):
    """TC-3: 'no deals' is an answer. Recording only row-producing symbols re-paid 13 calls/run."""
    wh = Warehouse(TEN)
    run = wire(wh, empty=TEN)                      # every stock genuinely has no deals
    s1, p1, job = run(max_calls=4)

    assert s1["rows_written"] == 0
    assert s1["symbols_attempted"] == 4
    assert len(wh.fetch_log) == 4, wh.fetch_log
    assert {v["last_status"] for v in wh.fetch_log.values()} == {"EMPTY"}

    wh.now = DAY2
    s2, p2, _ = run(max_calls=4)
    assert set(p1.asked).isdisjoint(p2.asked), (p1.asked, p2.asked)


def test_errored_symbol_is_recorded_and_does_not_block(wire):
    """TC-4: an error is recorded as an attempt, so it goes to the back of the queue."""
    wh = Warehouse(TEN)
    bad = TEN[0]
    run = wire(wh, errors=[bad])
    s1, p1, _ = run(max_calls=len(TEN))

    assert s1["errors"] >= 1, s1
    assert bad in wh.fetch_log
    assert wh.fetch_log[bad]["last_status"] == "ERROR"
    assert wh.fetch_log[bad]["last_success_at"] is None
    # Every candidate was still reached despite the failure.
    assert set(p1.asked) == set(TEN)


def test_new_candidate_jumps_the_queue(wire):
    """TC-5: robust when the candidate list itself changes — no positional cursor to go stale."""
    wh = Warehouse(TEN)
    run = wire(wh)
    run(max_calls=len(TEN))
    assert len(wh.fetch_log) == len(TEN)

    wh.candidates.append("ZZNEWLISTING")
    wh.candidates.remove("ALPHA")                  # dropped from the universe entirely
    wh.now = DAY2
    due = asyncio.run(deals._symbols(None, True, False))
    assert due[0] == "ZZNEWLISTING", due
    assert "ALPHA" not in due


def test_tie_break_among_never_attempted_is_not_alphabetical(wire):
    """TC-6: a permanently-partial ingest must not be an alphabetically biased sample."""
    wh = Warehouse(TEN)
    wire(wh)
    due = asyncio.run(deals._symbols(None, True, False))
    assert sorted(due) == sorted(TEN)
    assert due != sorted(TEN), due                 # ordering is not the alphabet
    assert due == asyncio.run(deals._symbols(None, True, False))   # but it is stable


def test_refresh_includes_todays_symbols(wire):
    """TC-7: --refresh re-attempts today's symbols and still never orders alphabetically."""
    wh = Warehouse(TEN)
    run = wire(wh)
    run(max_calls=4)

    same_day_due = asyncio.run(deals._symbols(None, True, False))
    assert len(same_day_due) == len(TEN) - 4       # today's four held back

    refreshed = asyncio.run(deals._symbols(None, True, True))
    assert len(refreshed) == len(TEN)
    assert refreshed != sorted(TEN)


def test_partial_run_reports_coverage(wire):
    """TC-8: a partial run states its own coverage, and it reaches job_log.metadata."""
    wh = Warehouse(TEN)
    run = wire(wh)
    summary, _, job = run(max_calls=3)

    assert summary["candidates"] == len(TEN)
    assert summary["attempted_ever"] == 3
    assert summary["never_attempted"] == len(TEN) - 3
    assert summary["attempted_pct"] == 30.0
    for key in ("candidates", "attempted_ever", "never_attempted", "attempted_pct"):
        assert job.metadata[key] == summary[key]


def test_unreached_symbols_are_not_marked_attempted(wire):
    """TC-9: the budget break records nothing for symbols it never reached."""
    wh = Warehouse(TEN)
    run = wire(wh)
    summary, provider, _ = run(max_calls=3)

    assert summary["calls_used"] == 3
    assert set(wh.fetch_log) == set(provider.asked)
    assert len(wh.fetch_log) == 3


def test_zero_row_run_is_not_a_feed_failure(wire):
    """TC-10: attempted-but-deal-free is OK, not FAILED.

    Marking it FAILED climbs source_registry.consecutive_failures and freezes v_feed_status —
    and once coverage reaches genuinely deal-free names, zero-row runs become normal.
    """
    wh = Warehouse(TEN)
    run = wire(wh, empty=TEN)
    summary, _, job = run(max_calls=2)

    assert summary["rows_written"] == 0
    assert job.status == "OK", (job.status, job.error_message)
