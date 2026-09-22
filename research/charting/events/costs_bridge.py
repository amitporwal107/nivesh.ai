"""Net-of-cost computation for one event+horizon round trip -- docs/charting.md S36 (Amendment
B) and the cost PRD (`.claude/workspace/charting-pattern-engine/prd-transaction-cost-tax-v1.md`)
S18, S21, S22, S26-S30.

This module NEVER edits `research/costs/*`; it only calls the public functions documented
there: `research.costs.engine.compute_round_trip` / `statutory_fill_costs` (the statutory cost
path -- independently versioned rates, per the task brief), `research.costs.sensitivity
.run_scenarios` (the 4 PRD sensitivity scenarios), `research.costs.slippage.liquidity_bucket`
(the liquidity-bucket slippage model already shipped in this codebase), and
`research.costs.liquidity.participation_ratio` (position value / ADV).

-- Defaults (documented so nothing is guessed silently) -------------------------------------
  - qty is derived from a configurable notional (default Rs 1,00,000, `schema
    .DEFAULT_NOTIONAL_INR`): `qty = floor(notional / entry_price)`, minimum 1 share -- a signal
    whose entry price alone exceeds the notional still gets a 1-share round trip rather than
    being silently dropped; the caller can filter on the recorded `position_value_inr` /
    `participation_ratio` downstream if a stricter rule is wanted.
  - exchange="NSE", segment="delivery" (cost PRD S21 "Pattern backtesting integration";
    task brief "delivery segment on NSE").
  - brokerage_spec defaults to "Zerodha delivery = 0" (see schema.DEFAULT_BROKERAGE_SPEC).
  - DP charge (`dp_applies`/`dp_broker`) defaults ON with broker="zerodha", matching the
    default brokerage_spec's own real-world Zerodha delivery terms (Zerodha does charge a
    per-scrip sell-side DP charge even at 0% brokerage) -- turn it off (`dp_applies=False`) for
    a different broker profile.
  - Liquidity-bucket slippage buckets default to `schema.default_liquidity_buckets()`
    (zerodha-equity-v1.json's own table).

Every TradeRecord field is converted to a plain float/str/int for JSON serialisation
(`_trade_record_to_dict`) -- Decimal is not JSON-serialisable and every money figure here is
already paisa-rounded (2 dp), so float64 loses nothing that matters at these magnitudes.
`unverified_rates_used` (S36.5 "recorded... in the trade's unverified_rates_used") is NOT a
`TradeRecord` field (engine.py's `compute_round_trip` computes it internally via
`statutory_fill_costs` but does not surface it on the dataclass) -- this module recovers it by
calling `statutory_fill_costs` directly, once per event+horizon (cost-path-independent of the
slippage scenario, so it need not be recomputed per scenario), exactly mirroring the buy/sell
leg construction `compute_round_trip` already does internally.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Optional

from research.charting.events import schema
from research.costs.engine import TradeRecord, compute_round_trip, statutory_fill_costs
from research.costs import liquidity
from research.costs import sensitivity
from research.costs import slippage


def _d(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


@dataclass(frozen=True)
class CostConfig:
    """Every knob this bridge exposes, all with the documented defaults above -- a caller
    overrides only what it needs to, never re-derives the rest."""

    notional_inr: Decimal = schema.DEFAULT_NOTIONAL_INR
    exchange: str = schema.DEFAULT_EXCHANGE
    segment: str = schema.DEFAULT_SEGMENT
    brokerage_spec: dict = field(default_factory=lambda: dict(schema.DEFAULT_BROKERAGE_SPEC))
    statutory_rule_id: str = schema.DEFAULT_STATUTORY_RULE_ID
    tax_rule_id: str = schema.DEFAULT_TAX_RULE_ID
    dp_applies: bool = True
    dp_broker: Optional[str] = schema.DEFAULT_DP_BROKER
    compute_tax: bool = True
    liquidity_buckets: tuple = field(default_factory=schema.default_liquidity_buckets)


def qty_for_notional(entry_price, notional) -> int:
    """floor(notional / entry_price), minimum 1 share for a positive entry price; 0 for a
    non-positive entry price (the caller must treat 0 as "no trade possible")."""
    price = _d(entry_price)
    if price <= 0:
        return 0
    q = int((_d(notional) / price).to_integral_value(rounding=ROUND_DOWN))
    return max(q, 1)


def position_value_inr(entry_price, qty: int) -> float:
    return float(_d(entry_price) * qty)


def participation_ratio_for(position_value: float, adv_inr: Optional[float]) -> Optional[float]:
    """position_value / ADV via research.costs.liquidity, or None if ADV was itself unavailable
    (never silently treated as liquid). Infinity (a zero-ADV name) is reported as the Python
    float `inf`, never coerced to a finite number."""
    if adv_inr is None:
        return None
    ratio = liquidity.participation_ratio(_d(position_value), _d(adv_inr))
    return float("inf") if ratio.is_infinite() else float(ratio)


def _trade_record_to_dict(rec: TradeRecord) -> dict:
    def f(x):
        return float(x) if x is not None else None

    return {
        "buy_date": rec.buy_date.isoformat(),
        "sell_date": rec.sell_date.isoformat(),
        "qty": rec.qty,
        "entry_price": f(rec.entry_price),
        "exit_price": f(rec.exit_price),
        "gross": f(rec.gross),
        "entry_slippage": f(rec.entry_slippage),
        "exit_slippage": f(rec.exit_slippage),
        "brokerage": f(rec.brokerage),
        "stt": f(rec.stt),
        "exchange_txn": f(rec.exchange_txn),
        "sebi": f(rec.sebi),
        "stamp": f(rec.stamp),
        "gst": f(rec.gst),
        "dp": f(rec.dp),
        "total_cost": f(rec.total_cost),
        "net_before_tax": f(rec.net_before_tax),
        "taxable_gain": f(rec.taxable_gain),
        "tax_before_cess": f(rec.tax_before_cess),
        "surcharge": f(rec.surcharge),
        "cess": f(rec.cess),
        "total_tax": f(rec.total_tax),
        "net_after_tax": f(rec.net_after_tax),
        "cost_rule_version": rec.cost_rule_version,
        "tax_rule_version": rec.tax_rule_version,
        "slippage_model_version": rec.slippage_model_version,
    }


def _unverified_rates(cfg: CostConfig, *, buy_date: dt.date, sell_date: dt.date, buy_value: Decimal, sell_value: Decimal) -> list:
    buy_costs = statutory_fill_costs(
        cfg.brokerage_spec, cfg.exchange, cfg.segment, "BUY", buy_value,
        dp_applies=False, dp_broker=None, on_date=buy_date, statutory_rule_id=cfg.statutory_rule_id,
    )
    sell_costs = statutory_fill_costs(
        cfg.brokerage_spec, cfg.exchange, cfg.segment, "SELL", sell_value,
        dp_applies=cfg.dp_applies, dp_broker=cfg.dp_broker, on_date=sell_date, statutory_rule_id=cfg.statutory_rule_id,
    )
    return sorted(set(buy_costs["unverified_rates_used"]) | set(sell_costs["unverified_rates_used"]))


def compute_cost_block(
    *, entry_date: dt.date, entry_price: float, exit_date: dt.date, exit_price: float,
    qty: int, adv_inr: Optional[float], cfg: CostConfig = CostConfig(),
) -> dict:
    """One event+horizon's full cost picture (task item 4): the 4 PRD sensitivity scenarios
    (S36.3) AND the liquidity-bucket model, each a `TradeRecord` (gross, every statutory
    component, total_cost, net_before_tax -- Series A -- and, when `cfg.compute_tax`, the tax
    breakdown and net_after_tax -- Series B, always a SEPARATE field, never netted into Series
    A). `unverified_rates_used` (S36.5) is recorded once for the whole block (cost-path only,
    independent of slippage scenario).

    `qty` is a parameter, not recomputed here, so the SAME qty (and therefore the same
    position_value_inr/participation_ratio) is used consistently by every scenario AND is
    available to the caller (extraction.py) for the row's `liquidity` section without a second,
    possibly-divergent calculation.
    """
    if qty <= 0:
        return {"available": False, "reason": "non_positive_qty"}

    buy_value = _d(entry_price) * qty
    sell_value = _d(exit_price) * qty

    cost_kwargs = dict(
        brokerage_spec=cfg.brokerage_spec, exchange=cfg.exchange, segment=cfg.segment,
        dp_applies=cfg.dp_applies, dp_broker=cfg.dp_broker, statutory_rule_id=cfg.statutory_rule_id,
    )
    round_trip_kwargs = dict(
        buy_date=entry_date, sell_date=exit_date, qty=qty, cost_path="statutory", cost_kwargs=cost_kwargs,
        compute_tax_flag=cfg.compute_tax,
        tax_kwargs=dict(rule_id=cfg.tax_rule_id) if cfg.compute_tax else None,
    )

    scenarios_raw = sensitivity.run_scenarios(
        entry_price=_d(entry_price), exit_price=_d(exit_price), round_trip_kwargs=round_trip_kwargs
    )
    scenarios = {name: _trade_record_to_dict(rec) for name, rec in scenarios_raw.items()}

    liquidity_block: dict
    if adv_inr is not None and adv_inr > 0:
        entry_slip = slippage.liquidity_bucket(_d(entry_price), _d(adv_inr), cfg.liquidity_buckets)
        exit_slip = slippage.liquidity_bucket(_d(exit_price), _d(adv_inr), cfg.liquidity_buckets)
        lb_rec = compute_round_trip(
            entry_price=_d(entry_price), exit_price=_d(exit_price),
            entry_slippage_per_share=entry_slip, exit_slippage_per_share=exit_slip,
            slippage_model_version=f"liquidity_bucket_v1[adv_inr={adv_inr:.2f}]",
            **round_trip_kwargs,
        )
        liquidity_block = _trade_record_to_dict(lb_rec)
        liquidity_block["available"] = True
    else:
        liquidity_block = {"available": False, "reason": "adv_unavailable"}

    unverified = _unverified_rates(cfg, buy_date=entry_date, sell_date=exit_date, buy_value=buy_value, sell_value=sell_value)

    base_rec = scenarios_raw["base"]
    return {
        "available": True,
        "qty": qty,
        "scenarios": scenarios,
        "liquidity_bucket": liquidity_block,
        "unverified_rates_used": unverified,
        "cost_rule_version": base_rec.cost_rule_version,
        "tax_rule_version": base_rec.tax_rule_version,
    }
