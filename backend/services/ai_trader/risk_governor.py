"""Risk Governor (PRD Phase 3): a deterministic veto between any strategy and any order.

Independent by construction: this module imports nothing from the strategy, evidence or AI code, takes plain numbers in
and returns a Decision. Limits come from `Limits`, which a person sets; no argument of `evaluate` can raise one. The
same inputs always give the same decision. Long-only (the DSL is long-only).

Precedence when several things apply: halt > reject > defer > reduce > hedge > approve.
Where a fact is unknown (no VIX, no sector on the order, no average traded value) the rule is skipped and an `info`
reason says so; a held position with no sector is counted against the sector allowance rather than ignored, and an
`info` reason says how much was counted that way. An unknown never counts as safe or as unsafe silently."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

LIMITS_VERSION = "gov-v1"
ACTIONS = ("approve", "reduce", "hedge", "defer", "reject", "halt")


@dataclass(frozen=True)
class Limits:
    max_risk_per_trade_pct: float = 1.0
    max_position_pct: float = 10.0
    max_open_positions: int = 10
    max_sector_pct: float = 30.0
    max_net_exposure_pct: float = 80.0
    hedge_at_exposure_pct: float = 70.0
    max_daily_loss_pct: float = 3.0
    max_drawdown_pct: float = 15.0
    min_reward_risk: float = 1.5
    max_stop_distance_pct: float = 15.0
    vix_reduce_at: float = 25.0
    vix_defer_at: float = 35.0
    max_adv_pct: float = 5.0
    bear_regime_size_factor: float = 0.5
    vix_size_factor: float = 0.5


DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class Intent:
    symbol: str
    quantity: int
    entry_price: float
    stop_price: Optional[float]
    target_price: Optional[float]
    sector: Optional[str] = None
    avg_daily_value: Optional[float] = None      # average daily traded value, rupees
    event_blackout: bool = False                 # a results/event date inside the holding window
    # The most shares the caller's own limits allow, whatever was asked (the risk service: its per-trade budget with
    # costs and gap stress). The volatility and regime factors cut it like the governor's own caps; None = no such limit.
    size_cap: Optional[int] = None


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: int
    price: float
    sector: Optional[str] = None


@dataclass(frozen=True)
class Portfolio:
    capital: float
    positions: List[Position] = field(default_factory=list)
    realized_pnl_today: float = 0.0
    drawdown_pct: Optional[float] = None         # positive number = how far below the equity peak
    kill_switch: bool = False                    # set by a person
    halted: bool = False                         # drawdown halt, cleared only by a person


@dataclass(frozen=True)
class Market:
    vix: Optional[float] = None
    regime: Optional[str] = None                 # BULL | BEAR | SIDEWAYS


@dataclass(frozen=True)
class Reason:
    code: str
    text: str
    severity: str                                # halt | reject | defer | reduce | hedge | info
    value: Any = None
    limit: Any = None


@dataclass(frozen=True)
class Decision:
    action: str
    requested_qty: int
    approved_qty: int
    reasons: List[Reason]
    limits_version: str = LIMITS_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {"action": self.action, "requested_qty": self.requested_qty, "approved_qty": self.approved_qty,
                "reasons": [asdict(r) for r in self.reasons], "limits_version": self.limits_version}


def _floor(x: float) -> int:
    return max(0, int(math.floor(x + 1e-9)))


def evaluate(intent: Intent, portfolio: Portfolio, market: Market = Market(), limits: Limits = DEFAULT_LIMITS) -> Decision:
    R: List[Reason] = []
    cap = portfolio.capital
    q = intent.quantity
    e, s, t = intent.entry_price, intent.stop_price, intent.target_price

    # ---- halt -------------------------------------------------------------------
    if portfolio.kill_switch:
        R.append(Reason("KILL_SWITCH", "Trading was stopped by a person.", "halt"))
    if portfolio.halted:
        R.append(Reason("HALTED", "Trading is halted until a person resets it.", "halt"))
    if portfolio.drawdown_pct is None:
        R.append(Reason("DRAWDOWN_UNKNOWN", "Drawdown was not supplied; the drawdown halt could not be checked.", "info"))
    elif portfolio.drawdown_pct >= limits.max_drawdown_pct:
        R.append(Reason("DRAWDOWN_HALT", "Drawdown reached the limit.", "halt", portfolio.drawdown_pct, limits.max_drawdown_pct))
    loss_pct = -portfolio.realized_pnl_today / cap * 100 if cap > 0 else 0.0
    if loss_pct >= limits.max_daily_loss_pct:
        R.append(Reason("DAILY_LOSS_HALT", "Today's loss reached the limit.", "halt", round(loss_pct, 4), limits.max_daily_loss_pct))

    # ---- reject: the order itself is not acceptable ---------------------------------
    if cap <= 0:
        R.append(Reason("NO_CAPITAL", "Capital must be positive.", "reject", cap))
    if q <= 0 or e <= 0:
        R.append(Reason("INVALID_ORDER", "Quantity and entry price must be positive.", "reject", {"qty": q, "entry": e}))
    stop_ok = s is not None and 0 < s < e
    if s is None:
        R.append(Reason("STOP_REQUIRED", "Every order needs a stop.", "reject"))
    elif not stop_ok:
        R.append(Reason("STOP_INVALID", "The stop must be below the entry for a long.", "reject", s, e))
    if stop_ok:
        dist = (e - s) / e * 100
        if dist > limits.max_stop_distance_pct:
            R.append(Reason("STOP_TOO_WIDE", "The stop is further away than allowed.", "reject", round(dist, 4), limits.max_stop_distance_pct))
        if t is None:
            R.append(Reason("TARGET_REQUIRED", "A target is needed to check reward against risk.", "reject"))
        elif t <= e:
            R.append(Reason("TARGET_INVALID", "The target must be above the entry for a long.", "reject", t, e))
        else:
            rr = (t - e) / (e - s)
            if rr < limits.min_reward_risk:
                R.append(Reason("RR_TOO_LOW", "Reward to risk is below the minimum.", "reject", round(rr, 4), limits.min_reward_risk))
    if len(portfolio.positions) >= limits.max_open_positions:
        R.append(Reason("MAX_POSITIONS", "Open positions are at the limit.", "reject", len(portfolio.positions), limits.max_open_positions))
    if any(p.symbol == intent.symbol for p in portfolio.positions):
        R.append(Reason("ALREADY_HELD", "This stock is already held.", "reject", intent.symbol))

    # ---- defer ---------------------------------------------------------------------
    if market.vix is None:
        R.append(Reason("VIX_UNKNOWN", "India VIX was not supplied; the volatility rules were skipped.", "info"))
    elif market.vix >= limits.vix_defer_at:
        R.append(Reason("VIX_DEFER", "Volatility is too high to open new positions.", "defer", market.vix, limits.vix_defer_at))
    if intent.event_blackout:
        R.append(Reason("EVENT_BLACKOUT", "A scheduled event falls inside the holding window.", "defer"))

    # ---- reduce: the largest size every limit allows ---------------------------------
    caps: Dict[str, int] = {}
    cap_limits: Dict[str, Any] = {}        # the configured limit behind each cap, so a reduce reason can name it
    factor = 1.0
    if market.vix is not None and limits.vix_reduce_at <= market.vix < limits.vix_defer_at:
        factor *= limits.vix_size_factor
        R.append(Reason("VIX_REDUCE", "Volatility is elevated; size is cut.", "reduce", market.vix, limits.vix_reduce_at))
    if market.regime == "BEAR":
        factor *= limits.bear_regime_size_factor
        R.append(Reason("BEAR_REGIME", "The market regime is BEAR; size is cut.", "reduce", market.regime))
    elif market.regime is None:
        R.append(Reason("REGIME_UNKNOWN", "Market regime was not supplied; the regime rule was skipped.", "info"))
    if cap > 0 and e > 0:
        if stop_ok:
            caps["RISK_PER_TRADE"] = _floor(cap * limits.max_risk_per_trade_pct / 100 / (e - s))
            cap_limits["RISK_PER_TRADE"] = limits.max_risk_per_trade_pct
        caps["POSITION_SIZE"] = _floor(cap * limits.max_position_pct / 100 / e)
        cap_limits["POSITION_SIZE"] = limits.max_position_pct
        gross = sum(p.quantity * p.price for p in portfolio.positions)
        caps["NET_EXPOSURE"] = _floor((cap * limits.max_net_exposure_pct / 100 - gross) / e)
        cap_limits["NET_EXPOSURE"] = limits.max_net_exposure_pct
        if intent.sector:
            sector_val = sum(p.quantity * p.price for p in portfolio.positions if p.sector == intent.sector)
            # A held position with no sector could be in this one, so its value is counted against the allowance too.
            # Counting it as zero would let a caller buy more of a sector simply by not saying what it holds, which is
            # the one thing no input may do; the reason below reports how much was counted this way, so the
            # conservative reading is never silent.
            unclassified = sum(p.quantity * p.price for p in portfolio.positions if not p.sector)
            caps["SECTOR_LIMIT"] = _floor((cap * limits.max_sector_pct / 100 - sector_val - unclassified) / e)
            cap_limits["SECTOR_LIMIT"] = limits.max_sector_pct
            if unclassified > 0:
                R.append(Reason("SECTOR_EXPOSURE_UNKNOWN",
                                "Some held positions carry no sector; their value was counted against this sector's "
                                "allowance.", "info", unclassified, limits.max_sector_pct))
        else:
            R.append(Reason("SECTOR_UNKNOWN", "Sector was not supplied; the sector limit was skipped.", "info"))
        # A traded value of zero is a FACT about a stock that did not trade, not a missing input: it leaves no 5 per
        # cent to take, so the cap is zero shares and the order is refused further down. Only None is unknown.
        if intent.avg_daily_value is None:
            R.append(Reason("LIQUIDITY_UNKNOWN", "Average traded value was not supplied; the liquidity limit was skipped.", "info"))
        else:
            adv = max(0.0, float(intent.avg_daily_value))
            caps["LIQUIDITY"] = _floor(adv * limits.max_adv_pct / 100 / e)
            cap_limits["LIQUIDITY"] = limits.max_adv_pct

    allowed = q if q > 0 else 0
    for code, c in caps.items():
        if c < allowed:
            allowed = c
            R.append(Reason(code, f"Size limited by {code.lower().replace('_', ' ')}.", "reduce", c,
                            cap_limits.get(code)))
    # The volatility and regime factors cut the LIMIT, never the ask: in a BEAR market the most an order may take is
    # half of what the hard caps allow. Halving the ask instead fails twice. A cap already below half the ask would
    # make the cut no cut at all. And the reduced size, sent again, would be halved again (42 → 21 → 10 → …), so a
    # caller that accepts only "approve" could never place an order in that regime (found on staging, 2026-10-27).
    # The caller's own limit (intent.size_cap) is cut too, so a limit applied before the governor is halved like ours.
    # Without any limit the order has already been rejected (no capital or no entry price), so the ask is cut as before.
    if factor < 1.0:
        limits_now = list(caps.values()) + ([intent.size_cap] if intent.size_cap is not None else [])
        ceiling = _floor((min(limits_now) if limits_now else allowed) * factor)
        if q > 0 and allowed <= ceiling:
            # The order already fits inside the cut limit: the factor applies, but takes nothing from this order.
            R[:] = [Reason(r.code, r.text.replace("size is cut", "the size limit is cut and this order is within it"),
                           "info", r.value, r.limit) if r.code in ("VIX_REDUCE", "BEAR_REGIME") else r for r in R]
        allowed = min(allowed, ceiling)
    if q > 0 and allowed < 1 and not any(r.severity in ("reject", "halt") for r in R):
        R.append(Reason("SIZE_BELOW_ONE_SHARE", "After the limits no whole share fits.", "reject", allowed))

    # ---- hedge: a suggestion once exposure is high, the order itself is still allowed ----
    # Only for an order that could still be placed. Precedence already outranks hedge, but a refused ticket whose
    # reasons suggest hedging an exposure it was never going to add reads as nonsense to whoever gets the ticket.
    blocked = any(r.severity in ("halt", "reject", "defer") for r in R)
    if cap > 0 and e > 0 and not blocked:
        exposure_after = (sum(p.quantity * p.price for p in portfolio.positions) + allowed * e) / cap * 100
        if exposure_after >= limits.hedge_at_exposure_pct:
            R.append(Reason("HEDGE_SUGGESTED", "Exposure is high; consider an index hedge. No hedge order is created.",
                            "hedge", round(exposure_after, 2), limits.hedge_at_exposure_pct))

    sev = {r.severity for r in R}
    if "halt" in sev:
        action, approved = "halt", 0
    elif "reject" in sev:
        action, approved = "reject", 0
    elif "defer" in sev:
        action, approved = "defer", 0
    elif allowed < q:
        action, approved = "reduce", allowed
    elif "hedge" in sev:
        action, approved = "hedge", allowed
    else:
        action, approved = "approve", allowed
    return Decision(action, q, approved, R)
