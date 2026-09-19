"""Versioned risk configuration (PRD §5 FR-001, §6, BR-007).

A RiskConfig is immutable; any change produces a new DRAFT version with a new hash. Validation distinguishes
user-configurable bounds from system-level safeguards (SYSTEM_MAX_RISK_PER_TRADE_PCT, leverage 0). A version becomes
ACTIVE only through DRAFT -> VALIDATED -> APPROVED -> ACTIVE; moving a value never activates anything.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs")
SYSTEM_MAX_RISK_PER_TRADE_PCT = Decimal("2.0")      # owner, 2026-09-19: risk per trade may never exceed 2%
DECIMAL_FIELDS = {
    "capital_inr", "risk_per_trade_pct", "min_risk_per_trade_pct", "hard_max_risk_per_trade_pct", "max_portfolio_risk_pct",
    "max_daily_loss_pct", "max_weekly_loss_pct", "min_cash_reserve_pct", "max_stock_allocation_pct",
    "max_sector_allocation_pct", "max_deployed_capital_pct", "max_volume_participation_pct", "min_avg_traded_value",
    "min_stock_price", "max_stop_distance_pct", "min_stop_distance_pct", "drawdown_reduced_risk_pct",
    "reduced_risk_multiplier", "kill_switch_drawdown_pct",
}
TRANSITIONS = {("DRAFT", "validate"): "VALIDATED", ("VALIDATED", "reject"): "DRAFT", ("VALIDATED", "approve"): "APPROVED",
               ("APPROVED", "activate"): "ACTIVE", ("APPROVED", "retire"): "RETIRED", ("ACTIVE", "retire"): "RETIRED"}


class TransitionError(ValueError):
    pass


@dataclass(frozen=True)
class RiskConfig:
    config_id: str
    version: int
    status: str
    description: str
    capital_basis: str
    capital_inr: Decimal
    risk_per_trade_pct: Decimal
    min_risk_per_trade_pct: Decimal
    hard_max_risk_per_trade_pct: Decimal
    max_portfolio_risk_pct: Decimal
    max_daily_loss_pct: Decimal
    max_weekly_loss_pct: Decimal
    min_cash_reserve_pct: Decimal
    max_open_positions: int
    leverage: int
    max_stock_allocation_pct: Decimal
    max_sector_allocation_pct: Decimal
    max_deployed_capital_pct: Decimal
    max_volume_participation_pct: Decimal
    min_avg_traded_value: Decimal
    min_stock_price: Decimal
    allow_averaging_down: bool
    require_valid_stop: bool
    max_stop_distance_pct: Decimal
    min_stop_distance_pct: Decimal
    drawdown_reduced_risk_pct: Optional[Decimal]
    reduced_risk_multiplier: Decimal
    kill_switch_drawdown_pct: Optional[Decimal]
    daily_pause_sessions: int


def _parse(d: dict) -> RiskConfig:
    kw = {}
    for f in dataclasses.fields(RiskConfig):
        v = d[f.name]
        kw[f.name] = Decimal(str(v)) if (f.name in DECIMAL_FIELDS and v is not None) else v
    return RiskConfig(**kw)


def load_config(config_id: str) -> RiskConfig:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", config_id or ""):
        raise ValueError(f"invalid config id {config_id!r}")
    path = os.path.join(CONFIG_DIR, f"{config_id}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"unknown risk config {config_id!r}")
    with open(path) as fh:
        return _parse(json.load(fh))


def as_dict(cfg: RiskConfig) -> dict:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in dataclasses.asdict(cfg).items()}


def config_hash(cfg: RiskConfig) -> str:
    """Identity of the parameters (status excluded: approving a version does not change what it computes)."""
    d = as_dict(cfg)
    d.pop("status")
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def with_changes(cfg: RiskConfig, **changes) -> RiskConfig:
    """A new DRAFT version; the original is untouched."""
    return dataclasses.replace(cfg, version=cfg.version + 1, status="DRAFT", **changes)


def transition(status: str, action: str) -> str:
    try:
        return TRANSITIONS[(status, action)]
    except KeyError:
        raise TransitionError(f"{action!r} is not allowed from {status!r}") from None


def validate(cfg: RiskConfig) -> list[str]:
    """Hard validation rules (§6.1) plus internal consistency. Empty list = valid."""
    e = []
    if cfg.hard_max_risk_per_trade_pct > SYSTEM_MAX_RISK_PER_TRADE_PCT:
        e.append(f"hard_max_risk_per_trade_pct {cfg.hard_max_risk_per_trade_pct} exceeds the system limit {SYSTEM_MAX_RISK_PER_TRADE_PCT}")
    if not (cfg.min_risk_per_trade_pct <= cfg.risk_per_trade_pct <= cfg.hard_max_risk_per_trade_pct):
        e.append(f"risk_per_trade_pct {cfg.risk_per_trade_pct} outside [{cfg.min_risk_per_trade_pct}, {cfg.hard_max_risk_per_trade_pct}]")
    if cfg.max_daily_loss_pct > cfg.max_weekly_loss_pct:
        e.append("max_daily_loss_pct exceeds max_weekly_loss_pct")
    if cfg.leverage != 0:
        e.append("leverage must be 0 in v1")
    if not isinstance(cfg.max_open_positions, int) or isinstance(cfg.max_open_positions, bool) or cfg.max_open_positions < 1:
        e.append("max_open_positions must be a positive integer")
    if cfg.min_cash_reserve_pct < 0:
        e.append("min_cash_reserve_pct must be nonnegative")
    if cfg.capital_inr <= 0:
        e.append("capital_inr must be positive")
    if cfg.capital_basis not in ("FIXED", "EQUITY"):
        e.append("capital_basis must be FIXED or EQUITY")
    for name in ("max_portfolio_risk_pct", "max_daily_loss_pct", "max_weekly_loss_pct", "max_stock_allocation_pct",
                 "max_sector_allocation_pct", "max_deployed_capital_pct", "max_volume_participation_pct"):
        v = getattr(cfg, name)
        if not (Decimal(0) < v <= Decimal(100)):
            e.append(f"{name} must be in (0, 100]")
    if cfg.max_deployed_capital_pct + cfg.min_cash_reserve_pct > 100:
        e.append("max_deployed_capital_pct + min_cash_reserve_pct exceed 100")
    if not (Decimal(0) < cfg.min_stop_distance_pct < cfg.max_stop_distance_pct):
        e.append("min_stop_distance_pct must be positive and below max_stop_distance_pct")
    if not (Decimal(0) < cfg.reduced_risk_multiplier <= 1):
        e.append("reduced_risk_multiplier must be in (0, 1]")
    if (cfg.drawdown_reduced_risk_pct is not None and cfg.kill_switch_drawdown_pct is not None
            and cfg.drawdown_reduced_risk_pct >= cfg.kill_switch_drawdown_pct):
        e.append("drawdown_reduced_risk_pct must be below kill_switch_drawdown_pct")
    if not isinstance(cfg.daily_pause_sessions, int) or cfg.daily_pause_sessions < 0:
        e.append("daily_pause_sessions must be a nonnegative integer")
    return e
