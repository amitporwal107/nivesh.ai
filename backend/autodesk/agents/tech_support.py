"""Tech Support — Reliability (PRD §6.5), Phase 1 part: the pre-market health check. Deterministic.

  previous session's cash end-of-day present (≥ MIN_CASH_ROWS rows)   else BLOCKED: no new risk this session
  previous session's F&O end-of-day present (≥ MIN_FNO_UNDERLYINGS)   else DEGRADED: cash only
  India VIX for that session                                          missing → noted, not blocking
  desk database answers                                                else BLOCKED

"Previous session" is the NSE session immediately before the one being prepared (market.previous_session). Data for an
older day is stale (owner rule: no stale market data): cash older than that is BLOCKED, F&O that is not for that day is
DEGRADED. A day that is published by the clock but has not landed yet shows up the same way (the latest day with data is
older than the previous session) or as too few rows.
"""
from __future__ import annotations

from datetime import date

from ..contracts import (AgentDescriptor, AgentKey, AgentResult, HealthCheck, HealthStatus, PremarketReport, Segment,
                         TaskSpec, TaskType)
from ..market.view import DataUnavailable
from .base import Agent, AgentContext

VERSION = "autodesk-ts-v1"
MIN_CASH_ROWS = 500
MIN_FNO_UNDERLYINGS = 50
DESCRIPTOR = AgentDescriptor(
    agent_key=AgentKey.TECH_SUPPORT, version=VERSION, kind="DETERMINISTIC",
    task_types=[TaskType.PREMARKET_HEALTH_CHECK],
    tools=["market.day_snapshot", "market.fno_universe", "market.vix", "market.previous_session"],
    prohibited=["create trading signals", "approve", "execute"])


class TechSupport(Agent):
    descriptor = DESCRIPTOR

    async def run(self, task: TaskSpec, ctx: AgentContext) -> AgentResult:
        m = ctx.market
        sd = date.fromisoformat(ctx.inputs["session_date"])
        checks: list[HealthCheck] = []
        data_as_of: dict[str, str | None] = {"cash_eod": None, "fno_eod": None}

        db_ok = bool(ctx.inputs.get("db_ok"))
        checks.append(HealthCheck(name="desk_db", status=HealthStatus.READY if db_ok else HealthStatus.BLOCKED,
                                  detail="answers" if db_ok else "the desk database did not answer"))
        prev: date | None = None
        prev_err = ""
        try:
            prev = await m.previous_session(sd)
        except DataUnavailable as e:
            prev_err = str(e)
        unknown = f"cannot tell which session precedes {sd}: {prev_err}"
        cash_ok = False
        try:
            d = m.latest_session("cash")
            data_as_of["cash_eod"] = d.isoformat()
            if prev is None:
                checks.append(HealthCheck(name="cash_eod", status=HealthStatus.BLOCKED, detail=unknown,
                                          as_of=d.isoformat()))
            elif d < prev:
                checks.append(HealthCheck(name="cash_eod", status=HealthStatus.BLOCKED, as_of=d.isoformat(),
                                          detail=f"Cash data is for {d}; the {sd} session needs {prev}"))
            else:
                snap = await m.day_snapshot(d)
                cash_ok = len(snap) >= MIN_CASH_ROWS
                checks.append(HealthCheck(name="cash_eod",
                                          status=HealthStatus.READY if cash_ok else HealthStatus.BLOCKED,
                                          detail=f"{len(snap)} cash rows for {d} (need {MIN_CASH_ROWS})",
                                          as_of=d.isoformat()))
        except DataUnavailable as e:
            checks.append(HealthCheck(name="cash_eod", status=HealthStatus.BLOCKED, detail=f"not readable: {e}"))
        fno_ok = False
        try:
            d = m.latest_session("fno")
            data_as_of["fno_eod"] = d.isoformat()
            if prev is None:
                checks.append(HealthCheck(name="fno_eod", status=HealthStatus.DEGRADED, detail=unknown,
                                          as_of=d.isoformat()))
            elif d != prev:
                checks.append(HealthCheck(name="fno_eod", status=HealthStatus.DEGRADED, as_of=d.isoformat(),
                                          detail=f"F&O data is for {d}; the {sd} session needs {prev}"))
            else:
                uni = await m.fno_universe(d)
                fno_ok = len(uni) >= MIN_FNO_UNDERLYINGS
                checks.append(HealthCheck(name="fno_eod",
                                          status=HealthStatus.READY if fno_ok else HealthStatus.DEGRADED,
                                          detail=f"{len(uni)} F&O underlyings for {d} (need {MIN_FNO_UNDERLYINGS})",
                                          as_of=d.isoformat()))
        except DataUnavailable as e:
            checks.append(HealthCheck(name="fno_eod", status=HealthStatus.DEGRADED, detail=f"not readable: {e}"))
        try:
            v = await m.vix()
            checks.append(HealthCheck(name="vix", status=HealthStatus.READY if v is not None else HealthStatus.DEGRADED,
                                      detail=f"India VIX {v}" if v is not None else "no India VIX for the session "
                                      "(regime inputs will be listed as missing)"))
        except DataUnavailable as e:
            checks.append(HealthCheck(name="vix", status=HealthStatus.DEGRADED, detail=f"not readable: {e}"))

        if not (db_ok and cash_ok):
            status, allowed = HealthStatus.BLOCKED, []
        elif not fno_ok:
            status, allowed = HealthStatus.DEGRADED, [Segment.CASH]
        else:
            status, allowed = HealthStatus.READY, [Segment.CASH, Segment.FUTURES, Segment.OPTIONS]
        rep = PremarketReport(status=status, session_date=sd, checks=checks, data_as_of=data_as_of,
                              allowed_segments=allowed)
        return AgentResult(output_schema="premarket-report-v1", output=rep.model_dump(mode="json"),
                           summary=f"pre-market {status.value}: new risk allowed in "
                                   f"{', '.join(a.value for a in allowed) or 'nothing'}")
