"""TEST DATA — the Tech Support scenarios shared by the health-status tests (AD-HS-25, AD-HS-30).

Each scenario is a market view (crafted data in a FrozenMarketView, NOT real market data) plus the session being prepared and
the thresholds; `run_agent` runs the real TechSupport agent on it. AD-HS-30 compares the agent's whole result with
`golden_tech_support.json`, which was generated from the agent's code BEFORE the shared check was extracted from it
(commit 82e5eedd), by `python -m tests.autodesk.ts_scenarios` run on that code.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Callable

from tests.autodesk import conftest  # noqa: F401  (sets the environment defaults the imports below need)
from autodesk import contracts as C
from autodesk.agents import tech_support
from autodesk.agents.tech_support import TechSupport
from autodesk.market.view import IST, Bar, DataUnavailable, FnoContract, FrozenMarketView
from tests.autodesk import marketdata as md
from tests.autodesk import test_ai_trader_ts as t

D, SD, AS_OF = md.FNO_DAY, md.SD, md.AS_OF


def at(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=IST)


class NoCalendarView(FrozenMarketView):
    """TEST DOUBLE: the data is there but the calendar cannot say which session precedes the one prepared."""
    async def previous_session(self, day: date) -> date:
        raise DataUnavailable("the NSE holiday list for 2026 is not loaded")


class UnreadableView(FrozenMarketView):
    """TEST DOUBLE: every data read fails the way a data-API outage does (the message holds a host name on purpose)."""
    MESSAGE = "data API: GET https://daas.example-internal.test:8443/prices/eod refused"

    async def day_snapshot(self, day):
        raise DataUnavailable(self.MESSAGE)

    async def fno_universe(self, day=None):
        raise DataUnavailable(self.MESSAGE)

    async def vix(self, day=None):
        raise DataUnavailable(self.MESSAGE)


def mini(last: date, sessions: list[date]) -> dict:
    """Three cash symbols and three F&O underlyings on `last` only."""
    bar = lambda s, d: Bar(day=d, open=Decimal(99), high=Decimal(102), low=Decimal(98), close=Decimal(100), volume=1000)  # noqa: E731
    fut = lambda u: FnoContract(day=last, underlying=u, kind="FUT", expiry=date(2026, 11, 24), strike=None,   # noqa: E731
                                close=Decimal(100), settle=Decimal(100), underlying_price=Decimal(100),
                                open_interest=1, change_in_oi=0, traded_volume=1, lot_size=10)
    syms = ["AAA", "BBB", "CCC"]
    return {"sessions": sessions, "bars": {s: [bar(s, last)] for s in syms}, "fno": {s: [fut(s)] for s in syms},
            "vix": {last: Decimal("13")}}


def on_day(rows: list[FnoContract], day: date) -> list[FnoContract]:
    return [FnoContract(**{**r.__dict__, "day": day}) for r in rows]


@dataclass
class Scenario:
    name: str
    make: Callable[[], FrozenMarketView]      # a fresh view each time (calls are recorded on it)
    session: date = SD
    db_ok: bool = True
    min_cash: int = 2
    min_fno: int = 2
    expect: str = ""                          # what the agent says (READY / DEGRADED / BLOCKED): documented, and asserted


def _view(d: dict, *, as_of: datetime = AS_OF, cls=FrozenMarketView):
    return lambda: cls(as_of, d)


def scenarios() -> list[Scenario]:
    fri, mon, wed = date(2026, 11, 6), date(2026, 11, 9), date(2026, 11, 11)
    sess = [date(2026, 11, 5), fri, mon, wed]
    cut = {k: [b for b in v if b.day < D] for k, v in t.data()["bars"].items()}
    old_fno = t.data()
    old_fno["fno"] = {k: on_day(v, date(2026, 11, 4)) for k, v in old_fno["fno"].items()}
    return [
        Scenario("ready", _view(t.data()), expect="READY"),
        Scenario("vix_missing", _view(t.data(vix={})), expect="READY"),
        Scenario("fno_missing", _view(t.data(fno={})), expect="DEGRADED"),
        Scenario("fno_two_sessions_old", _view(old_fno, as_of=at(D, "20:00")), expect="DEGRADED"),
        Scenario("cash_old_before_cutoff", _view(t.data(), as_of=at(D, "18:50")), expect="BLOCKED"),
        Scenario("cash_file_missing", _view(t.data(bars=cut)), expect="BLOCKED"),
        Scenario("few_rows_default_thresholds", _view(t.data()), min_cash=500, min_fno=50, expect="BLOCKED"),
        Scenario("weekend_monday_needs_friday", _view(mini(fri, sess), as_of=at(mon, "08:45")), session=mon, expect="READY"),
        Scenario("calendar_unknown", _view(t.data(), cls=NoCalendarView), expect="BLOCKED"),
        Scenario("data_unreadable", _view(t.data(), cls=UnreadableView), expect="BLOCKED"),
        Scenario("database_down", _view(t.data()), db_ok=False, expect="BLOCKED"),
    ]


def run_agent(s: Scenario) -> tuple[dict, FrozenMarketView]:
    """The agent's whole result (schema, output, summary) on the scenario, and the view it read through."""
    from tests.autodesk.conftest import run
    saved = tech_support.MIN_CASH_ROWS, tech_support.MIN_FNO_UNDERLYINGS
    tech_support.MIN_CASH_ROWS, tech_support.MIN_FNO_UNDERLYINGS = s.min_cash, s.min_fno
    try:
        view = s.make()
        ctx = md.ctx(view, {"session_date": s.session.isoformat(), "db_ok": s.db_ok})
        res = run(TechSupport().run(md.task(C.TaskType.PREMARKET_HEALTH_CHECK), ctx))
    finally:
        tech_support.MIN_CASH_ROWS, tech_support.MIN_FNO_UNDERLYINGS = saved
    return {"output_schema": res.output_schema, "output": res.output, "summary": res.summary}, view


def fingerprint(s: Scenario) -> dict:
    """What AD-HS-30 compares: the agent's result and the market calls it made, in order (timings left out)."""
    result, view = run_agent(s)
    calls = [{"tool": c.tool, "args": c.args, "ok": c.ok, "rows": c.rows, "error": c.error} for c in view.tool_calls()]
    return json.loads(json.dumps({"result": result, "calls": calls}, default=str, sort_keys=True))


if __name__ == "__main__":     # regenerate the golden file from the code in this tree: only ever run on the ORIGINAL agent
    json.dump({s.name: fingerprint(s) for s in scenarios()}, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")
