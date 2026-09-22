"""Trade-record assembly: resolves the rule applicable on each leg's trade date and computes the
gross / cost-breakdown / net-before-tax / taxable-gain / tax / net-after-tax fields for one round
trip (PRD: Series A = net trading return, Series B = investor after-tax return; the two are always
reported as separate fields, never netted into one number).

Two independent cost-resolution paths, both feeding the same TradeRecord shape:

1. `bundled_fill_costs()` -- for a "bundled_broker_plan_v1" rule file (zerodha-equity-v1.json,
   prd-illustrative-v1.json): one self-contained snapshot of brokerage + every statutory rate + a
   GST base list. This path exists ONLY to reproduce known-good numbers exactly (the old
   tpd_model/risk/costs.py behaviour, and the PRD's own worked example) -- see tests/.

2. `statutory_fill_costs()` -- the PRD-general path: brokerage comes from an independent
   `brokerage.py` spec (any broker plan, any type), while every statutory rate (STT, exchange
   charge, SEBI fee, GST, stamp duty, DP charge) is resolved from nse-equity-statutory-v1.json for
   the LEG'S OWN trade date. A round trip whose buy and sell legs straddle a rate change therefore
   correctly uses two different rates, one per leg.

Versioning: every TradeRecord carries `cost_rule_version`, `tax_rule_version` and
`slippage_model_version` so a report can always say exactly which rate vintage produced a number.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from research.costs import tax as tax_mod
from research.costs.brokerage import compute_brokerage
from research.costs.rule_loader import load_rule_file, resolve_record

PAISA = Decimal("0.01")
CRORE = Decimal("10000000")
STATUTORY_COMPONENTS = ("brokerage", "stt", "exchange_txn", "sebi", "stamp", "gst", "dp")


class CostEngineError(ValueError):
    pass


def money(x: Decimal) -> Decimal:
    return x.quantize(PAISA, rounding=ROUND_HALF_UP)


def _d(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


# --------------------------------------------------------------------------------------------
# Path 1: bundled broker-plan rule files (legacy-exact reproduction)
# --------------------------------------------------------------------------------------------

def bundled_fill_costs(rule_id: str, profile: str, exchange: str, side: str, value: Decimal, *,
                        dp_applies: bool, on_date: dt.date, allow_retroactive: bool = False) -> dict:
    """Charges for one fill of `value` rupees under a bundled broker-plan rule file. Byte-for-byte
    the same arithmetic as the legacy tpd_model/risk/costs.py:fill_costs() when `rule_id` is
    "zerodha-equity-v1" (same components, same rounding, same retroactive-use error), generalised
    only to read the GST base from the profile (`gst_base`) instead of hard-coding
    brokerage+sebi+exchange_txn."""
    if side not in ("BUY", "SELL"):
        raise CostEngineError(f"side must be BUY or SELL, got {side!r}")
    value = _d(value)
    if not value.is_finite() or value < 0:
        raise CostEngineError(f"invalid fill value {value!r}")
    rs = load_rule_file(rule_id)
    effective_from = dt.date.fromisoformat(rs["effective_from"])
    retro = on_date < effective_from
    if retro and not allow_retroactive:
        raise CostEngineError(f"{rule_id} is effective from {effective_from}; fill dated {on_date}")
    try:
        p = rs["profiles"][profile]
        txn_rate = _d(p["txn_pct"][exchange])
    except KeyError as e:
        raise CostEngineError(f"no rate for profile={profile!r} exchange={exchange!r}") from e
    brokerage = value * _d(p["brokerage_pct"]) / 100
    if p.get("brokerage_cap_inr") is not None:
        brokerage = min(brokerage, _d(p["brokerage_cap_inr"]))
    stt = value * _d(p["stt_buy_pct" if side == "BUY" else "stt_sell_pct"]) / 100
    txn = value * txn_rate / 100
    sebi = value * _d(p["sebi_per_crore_inr"]) / CRORE
    stamp = value * _d(p["stamp_buy_pct"]) / 100 if side == "BUY" else Decimal(0)
    unrounded = {"brokerage": brokerage, "stt": stt, "exchange_txn": txn, "sebi": sebi, "stamp": stamp}
    gst_base_keys = p.get("gst_base", ["brokerage", "sebi", "exchange_txn"])
    gst = sum((unrounded[k] for k in gst_base_keys), Decimal(0)) * _d(p["gst_pct"]) / 100
    dp = _d(p["dp_per_scrip_sell_inr"]) if (side == "SELL" and dp_applies) else Decimal(0)
    out = {"brokerage": money(brokerage), "stt": money(stt), "exchange_txn": money(txn), "sebi": money(sebi),
           "stamp": money(stamp), "gst": money(gst), "dp": money(dp)}
    out["total"] = sum(out[c] for c in STATUTORY_COMPONENTS)
    out.update(retroactive=retro, cost_model_id=rule_id, cost_model_version=rs["version"])
    return out


# --------------------------------------------------------------------------------------------
# Path 2: independently-versioned statutory table + pluggable brokerage spec
# --------------------------------------------------------------------------------------------

def statutory_fill_costs(brokerage_spec: dict, exchange: str, segment: str, side: str, value: Decimal, *,
                          dp_applies: bool, dp_broker: Optional[str], on_date: dt.date,
                          statutory_rule_id: str = "nse-equity-statutory-v1",
                          gst_base_keys: tuple = ("brokerage", "sebi", "exchange_txn"),
                          rules_dir: Optional[str] = None) -> dict:
    """Charges for one fill, resolving every statutory rate from `statutory_rule_id` for `on_date`
    (so a straddling round trip naturally uses each leg's own rate), with brokerage computed
    independently from `brokerage_spec` (see brokerage.py -- any plan, no broker hard-coded here).
    `rules_dir` lets tests point at a synthetic rule set instead of rules/ (used by
    tests/test_date_effectiveness.py to exercise the leg-own-date mechanism without depending on
    which real-world spans happen to be fully verified end-to-end)."""
    if side not in ("BUY", "SELL"):
        raise CostEngineError(f"side must be BUY or SELL, got {side!r}")
    value = _d(value)
    if not value.is_finite() or value < 0:
        raise CostEngineError(f"invalid fill value {value!r}")
    load_kwargs = {"rules_dir": rules_dir} if rules_dir is not None else {}
    rs = load_rule_file(statutory_rule_id, **load_kwargs)
    comps = rs["components"]

    def _rate(rec, field, component_name):
        """A resolved record may deliberately carry no rate (see e.g. sebi_fee's 2021-2026
        placeholder in nse-equity-statutory-v1.json) rather than invent one. Fail loudly here
        instead of letting Decimal(str(None)) raise an opaque InvalidOperation deep in arithmetic."""
        val = rec.record.get(field)
        if val is None:
            raise CostEngineError(f"{component_name} has no confirmed rate for {on_date} "
                                   f"(verified={rec.verified}, note={rec.note!r}); refusing to silently use zero")
        return _d(val)

    brokerage = compute_brokerage(brokerage_spec, value)
    stt_rec = resolve_record(comps["stt"]["records"], on_date, segment=segment, side=side)
    stt = value * _rate(stt_rec, "pct", "stt") / 100
    txn_rec = resolve_record(comps["exchange_txn_charge"]["records"], on_date, exchange=exchange, segment=segment)
    txn = value * _rate(txn_rec, "pct", "exchange_txn_charge") / 100
    sebi_rec = resolve_record(comps["sebi_fee"]["records"], on_date)
    sebi = value * _rate(sebi_rec, "per_crore_inr", "sebi_fee") / CRORE
    stamp = Decimal(0)
    stamp_rec = None
    if side == "BUY":
        stamp_rec = resolve_record(comps["stamp_duty"]["records"], on_date, segment=segment, side=side)
        stamp = value * _rate(stamp_rec, "pct", "stamp_duty") / 100
    gst_rec = resolve_record(comps["gst"]["records"], on_date)
    unrounded = {"brokerage": brokerage, "stt": stt, "exchange_txn": txn, "sebi": sebi, "stamp": stamp}
    gst = sum((unrounded[k] for k in gst_base_keys), Decimal(0)) * _rate(gst_rec, "pct", "gst") / 100
    dp = Decimal(0)
    dp_rec = None
    if side == "SELL" and dp_applies and dp_broker:
        dp_rec = resolve_record(comps["dp_charge"]["records"], on_date, broker=dp_broker)
        dp = _rate(dp_rec, "inr_per_scrip_per_sell_day", "dp_charge")
    out = {"brokerage": money(brokerage), "stt": money(stt), "exchange_txn": money(txn), "sebi": money(sebi),
           "stamp": money(stamp), "gst": money(gst), "dp": money(dp)}
    out["total"] = sum(out[c] for c in STATUTORY_COMPONENTS)
    out["cost_rule_version"] = f"{statutory_rule_id}@{rs['version']}"
    out["unverified_rates_used"] = tuple(
        r.source_url for r in (stt_rec, txn_rec, sebi_rec, stamp_rec, gst_rec, dp_rec) if r is not None and not r.verified
    )
    return out


# --------------------------------------------------------------------------------------------
# Trade record (both Series A and Series B, always reported separately)
# --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class TradeRecord:
    buy_date: dt.date
    sell_date: dt.date
    qty: int
    entry_price: Decimal
    exit_price: Decimal
    gross: Decimal                    # sale value - buy value, no costs, no slippage
    entry_slippage: Decimal
    exit_slippage: Decimal
    brokerage: Decimal
    stt: Decimal
    exchange_txn: Decimal
    sebi: Decimal
    stamp: Decimal
    gst: Decimal
    dp: Decimal
    total_cost: Decimal               # brokerage+stt+exchange_txn+sebi+stamp+gst+dp (NOT slippage)
    net_before_tax: Decimal           # Series A: gross - entry_slippage - exit_slippage - total_cost
    taxable_gain: Optional[Decimal]
    tax_before_cess: Optional[Decimal]
    surcharge: Optional[Decimal]
    cess: Optional[Decimal]
    total_tax: Optional[Decimal]
    net_after_tax: Optional[Decimal]  # Series B: net_before_tax - total_tax
    cost_rule_version: str
    tax_rule_version: Optional[str]
    slippage_model_version: str


def compute_round_trip(*, buy_date: dt.date, sell_date: dt.date, qty: int, entry_price: Decimal,
                        exit_price: Decimal, entry_slippage_per_share: Decimal = Decimal(0),
                        exit_slippage_per_share: Decimal = Decimal(0), slippage_model_version: str = "none",
                        cost_path: str, cost_kwargs: dict, compute_tax_flag: bool = False,
                        tax_kwargs: Optional[dict] = None) -> TradeRecord:
    """Assemble one round-trip TradeRecord. `cost_path` selects "bundled" (bundled_fill_costs) or
    "statutory" (statutory_fill_costs); `cost_kwargs` are the extra kwargs each path needs beyond
    exchange/segment/side/value/dp_applies/on_date. Slippage is a pure P&L line item applied to
    GROSS, never re-flowed into the %-based cost formulas (this matches the PRD's own worked
    example: Rs 3/share entry+exit slippage on a 100-share trade reduces net-before-tax by exactly
    Rs 600, leaving every cost component unchanged)."""
    qty = int(qty)
    if qty <= 0:
        raise CostEngineError(f"qty must be positive, got {qty!r}")
    entry_price, exit_price = _d(entry_price), _d(exit_price)
    buy_value = entry_price * qty
    sell_value = exit_price * qty

    if cost_path == "bundled":
        buy_costs = bundled_fill_costs(side="BUY", value=buy_value, on_date=buy_date, **cost_kwargs)
        sell_costs = bundled_fill_costs(side="SELL", value=sell_value, on_date=sell_date, **cost_kwargs)
        cost_rule_version = f"{cost_kwargs['rule_id']}@{buy_costs['cost_model_version']}"
    elif cost_path == "statutory":
        buy_costs = statutory_fill_costs(side="BUY", value=buy_value, on_date=buy_date, **cost_kwargs)
        sell_costs = statutory_fill_costs(side="SELL", value=sell_value, on_date=sell_date, **cost_kwargs)
        cost_rule_version = sell_costs["cost_rule_version"]
    else:
        raise CostEngineError(f"unknown cost_path {cost_path!r}")

    combined = {c: buy_costs[c] + sell_costs[c] for c in STATUTORY_COMPONENTS}
    total_cost = sum(combined[c] for c in STATUTORY_COMPONENTS)
    gross = sell_value - buy_value
    entry_slip_amt = money(_d(entry_slippage_per_share) * qty)
    exit_slip_amt = money(_d(exit_slippage_per_share) * qty)
    net_before_tax = gross - entry_slip_amt - exit_slip_amt - total_cost

    taxable = tax_rule_version = tax_before_cess = surcharge = cess = total_tax = net_after_tax = None
    if compute_tax_flag:
        tk = dict(tax_kwargs or {})
        eligible = tk.pop("eligible_components", tax_mod.DEFAULT_ELIGIBLE_COMPONENTS)
        rule_id = tk.pop("rule_id", "tax-equity-v1")
        rs = load_rule_file(rule_id)
        # capital gain is on the consideration actually received / paid: the slipped fills, not the
        # theoretical prices (the cost lines above follow the PRD's convention of theoretical values)
        taxable = tax_mod.taxable_gain(sell_value - exit_slip_amt, buy_value + entry_slip_amt, combined,
                                       eligible_components=eligible)
        term = tax_mod.classify_term(buy_date, sell_date, rule_set=rs)
        result = tax_mod.compute_tax(taxable, term=term, on_date=sell_date, rule_id=rule_id,
                                      eligible_components=eligible, **tk)
        tax_rule_version = result.tax_rule_version
        tax_before_cess, surcharge, cess, total_tax = (result.tax_before_cess, result.surcharge, result.cess,
                                                         result.total_tax)
        net_after_tax = net_before_tax - total_tax

    return TradeRecord(
        buy_date=buy_date, sell_date=sell_date, qty=qty, entry_price=entry_price, exit_price=exit_price,
        gross=gross, entry_slippage=entry_slip_amt, exit_slippage=exit_slip_amt,
        brokerage=combined["brokerage"], stt=combined["stt"], exchange_txn=combined["exchange_txn"],
        sebi=combined["sebi"], stamp=combined["stamp"], gst=combined["gst"], dp=combined["dp"],
        total_cost=total_cost, net_before_tax=net_before_tax, taxable_gain=taxable,
        tax_before_cess=tax_before_cess, surcharge=surcharge, cess=cess, total_tax=total_tax,
        net_after_tax=net_after_tax, cost_rule_version=cost_rule_version, tax_rule_version=tax_rule_version,
        slippage_model_version=slippage_model_version,
    )
