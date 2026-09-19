"""Drawdown and kill-switch controls (PRD §10, BR-006, BR-008).

Three independent flags give the PRD's states, with precedence KILL_SWITCH > ENTRY_PAUSE > REDUCED_RISK > NORMAL:
- paused: daily loss >= max_daily_loss_pct pauses new entries for `daily_pause_sessions` sessions; weekly loss >=
  max_weekly_loss_pct pauses them until the next ISO week. (The PRD's "authorized resume" is automated this way for
  backtests; the rule is registered in the config.)
- reduced: drawdown from the persisted peak >= drawdown_reduced_risk_pct halves risk (reduced_risk_multiplier); it is
  lifted when the drawdown falls back to half the threshold.
- killed: drawdown >= kill_switch_drawdown_pct, or a manual kill; only an approved review (resume(approved=True))
  clears it. Existing positions keep their own exit rules — the monitor never assumes exits at the stop.
Losses include realised and unrealised P&L and simulated costs (the caller passes marked-to-market equity).
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Optional

from .config import RiskConfig

TWO = Decimal("0.01")


class DrawdownMonitor:
    def __init__(self, cfg: RiskConfig, peak_equity: Optional[Decimal] = None):
        self.cfg = cfg
        self.peak_equity = peak_equity
        self.day_start_equity: Optional[Decimal] = None
        self.week_key = None
        self.week_start_equity: Optional[Decimal] = None
        self.last_equity: Optional[Decimal] = None
        self.paused = False
        self.pause_kind: Optional[str] = None
        self.pause_sessions_left = 0
        self.pause_week = None
        self.reduced = False
        self.killed = False
        self.events: list[dict] = []

    # ---- state ----
    @property
    def state(self) -> str:
        if self.killed:
            return "KILL_SWITCH"
        if self.paused:
            return "ENTRY_PAUSE"
        if self.reduced:
            return "REDUCED_RISK"
        return "NORMAL"

    def entries_allowed(self, d: dt.date) -> bool:
        return not (self.killed or self.paused)

    def risk_multiplier(self) -> Decimal:
        if self.killed or self.paused:
            return Decimal(0)
        return self.cfg.reduced_risk_multiplier if self.reduced else Decimal(1)

    def drawdown_pct(self) -> Decimal:
        if not self.peak_equity or self.last_equity is None:
            return Decimal("0.00")
        return ((self.peak_equity - self.last_equity) / self.peak_equity * 100).quantize(TWO)

    def _event(self, d, event_type, severity, threshold, observed, before):
        e = {"date": d.isoformat(), "event_type": event_type, "severity": severity,
             "threshold_value": None if threshold is None else str(threshold),
             "observed_value": None if observed is None else str(observed.quantize(TWO)),
             "state_before": before, "state_after": self.state}
        self.events.append(e)
        return e

    # ---- session hooks ----
    def start_day(self, d: dt.date, equity: Decimal) -> list[dict]:
        out = []
        if self.peak_equity is None:
            self.peak_equity = equity
        wk = d.isocalendar()[:2]
        if wk != self.week_key:
            self.week_key, self.week_start_equity = wk, equity
        self.day_start_equity = equity
        self.last_equity = equity
        if self.paused:
            before = self.state
            if self.pause_kind == "DAILY":
                if self.pause_sessions_left > 0:
                    self.pause_sessions_left -= 1          # this session is still paused
                else:
                    self.paused = False
            elif self.pause_kind == "WEEKLY" and wk != self.pause_week:
                self.paused = False
            if not self.paused:
                self.pause_kind = None
                out.append(self._event(d, "AUTO_RESUME", "INFO", None, None, before))
        return out

    def end_day(self, d: dt.date, equity: Decimal) -> list[dict]:
        out = []
        cfg = self.cfg
        self.last_equity = equity
        self.peak_equity = max(self.peak_equity or equity, equity)
        daily = (self.day_start_equity - equity) / self.day_start_equity * 100
        weekly = (self.week_start_equity - equity) / self.week_start_equity * 100
        dd = (self.peak_equity - equity) / self.peak_equity * 100
        if cfg.kill_switch_drawdown_pct is not None and dd >= cfg.kill_switch_drawdown_pct and not self.killed:
            before = self.state
            self.killed = True
            out.append(self._event(d, "DRAWDOWN_KILL_SWITCH", "CRITICAL", cfg.kill_switch_drawdown_pct, dd, before))
        if weekly >= cfg.max_weekly_loss_pct and not (self.paused and self.pause_kind == "WEEKLY"):
            before = self.state
            self.paused, self.pause_kind, self.pause_week = True, "WEEKLY", self.week_key
            out.append(self._event(d, "WEEKLY_LOSS_LIMIT", "HIGH", cfg.max_weekly_loss_pct, weekly, before))
        elif daily >= cfg.max_daily_loss_pct and not self.paused:
            before = self.state
            self.paused, self.pause_kind, self.pause_sessions_left = True, "DAILY", cfg.daily_pause_sessions
            out.append(self._event(d, "DAILY_LOSS_LIMIT", "HIGH", cfg.max_daily_loss_pct, daily, before))
        th = cfg.drawdown_reduced_risk_pct
        if th is not None:
            if not self.reduced and dd >= th:
                before = self.state
                self.reduced = True
                out.append(self._event(d, "DRAWDOWN_REDUCED_RISK", "HIGH", th, dd, before))
            elif self.reduced and dd <= th / 2:
                before = self.state
                self.reduced = False
                out.append(self._event(d, "RISK_RESTORED", "INFO", th / 2, dd, before))
        return out

    # ---- manual controls (BR-008) ----
    def kill(self, d: dt.date, reason: str) -> dict:
        before = self.state
        self.killed = True
        e = self._event(d, "KILL_SWITCH_MANUAL", "CRITICAL", None, None, before)
        e["reason"] = reason
        return e

    def resume(self, d: dt.date, approved: bool) -> dict:
        """REVIEW of a kill switch: approved -> NORMAL (flags cleared, peak kept); denied -> stays KILL_SWITCH."""
        before = self.state
        if approved:
            self.killed = self.paused = self.reduced = False
            self.pause_kind = None
            return self._event(d, "RESUME_APPROVED", "INFO", None, None, before)
        return self._event(d, "RESUME_DENIED", "HIGH", None, None, before)
