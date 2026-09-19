"""Versioned Zerodha cost engine (PRD §12) and the slippage simulation parameter.

Rates come from an effective-dated JSON taken from Zerodha's published charges page (URL, retrieval time and page
sha256 are in the file). A fill dated before `effective_from` raises CostModelError unless the caller passes
allow_retroactive=True, and the result then says so: a backtest over 2024-2026 using today's schedule is an
approximation that must be disclosed, never silent. Estimates only — not a contract note.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cost_models")
PAISA = Decimal("0.01")
CRORE = Decimal("10000000")
COMPONENTS = ("brokerage", "stt", "exchange_txn", "sebi", "stamp", "gst", "dp")


class CostModelError(ValueError):
    pass


@dataclass(frozen=True)
class CostModel:
    cost_model_id: str
    version: int
    effective_from: dt.date
    source_url: str
    retrieved_at: str
    source_sha256: str
    profiles: dict
    slippage_buckets: tuple          # ((min_value20, pct_per_side), ...) sorted high to low


def money(x: Decimal) -> Decimal:
    return x.quantize(PAISA, rounding=ROUND_HALF_UP)


def load_cost_model(model_id: str) -> CostModel:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", model_id or ""):
        raise CostModelError(f"invalid cost model id {model_id!r}")
    path = os.path.join(MODEL_DIR, f"{model_id}.json")
    if not os.path.exists(path):
        raise CostModelError(f"unknown cost model {model_id!r}")
    with open(path) as fh:
        d = json.load(fh)
    buckets = tuple(sorted(((Decimal(b["min_value20_inr"]), Decimal(b["pct"])) for b in d["slippage_per_side_pct"]["buckets"]),
                           reverse=True))
    return CostModel(d["cost_model_id"], d["version"], dt.date.fromisoformat(d["effective_from"]), d["source_url"],
                     d["retrieved_at"], d["source_sha256"], d["profiles"], buckets)


def fill_costs(model: CostModel, profile: str, exchange: str, side: str, value: Decimal, *, dp_applies: bool,
               on_date: dt.date, allow_retroactive: bool = False) -> dict:
    """Charges for one fill of `value` rupees. side BUY|SELL; dp_applies = first delivery sale of this scrip that day."""
    if side not in ("BUY", "SELL"):
        raise CostModelError(f"side must be BUY or SELL, got {side!r}")
    if value is None or not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise CostModelError(f"invalid fill value {value!r}")
    retro = on_date < model.effective_from
    if retro and not allow_retroactive:
        raise CostModelError(f"{model.cost_model_id} is effective from {model.effective_from}; fill dated {on_date}")
    try:
        p = model.profiles[profile]
        txn_rate = Decimal(p["txn_pct"][exchange])
    except KeyError as e:
        raise CostModelError(f"no rate for profile={profile!r} exchange={exchange!r}") from e
    brokerage = value * Decimal(p["brokerage_pct"]) / 100
    if p.get("brokerage_cap_inr") is not None:
        brokerage = min(brokerage, Decimal(p["brokerage_cap_inr"]))
    stt = value * Decimal(p["stt_buy_pct" if side == "BUY" else "stt_sell_pct"]) / 100
    txn = value * txn_rate / 100
    sebi = value * Decimal(p["sebi_per_crore_inr"]) / CRORE
    stamp = value * Decimal(p["stamp_buy_pct"]) / 100 if side == "BUY" else Decimal(0)
    gst = (brokerage + sebi + txn) * Decimal(p["gst_pct"]) / 100
    dp = Decimal(p["dp_per_scrip_sell_inr"]) if (side == "SELL" and dp_applies) else Decimal(0)
    out = {"brokerage": money(brokerage), "stt": money(stt), "exchange_txn": money(txn), "sebi": money(sebi),
           "stamp": money(stamp), "gst": money(gst), "dp": money(dp)}
    out["total"] = sum(out[c] for c in COMPONENTS)
    out.update(retroactive=retro, cost_model_id=model.cost_model_id, cost_model_version=model.version)
    return out


def slippage_pct(model: CostModel, value20) -> Decimal:
    """Per-side slippage % for a stock with 20-day average traded value `value20` (rupees)."""
    v = Decimal(str(value20)) if value20 is not None else Decimal(0)
    for floor, pct in model.slippage_buckets:
        if v >= floor:
            return pct
    return model.slippage_buckets[-1][1]
