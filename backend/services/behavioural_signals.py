"""Behavioural Signals service — Step 2 of the Nivesh Decision Engine.

Computes durable behavioural signals from a user's CAS transaction
history + current holdings, used to nudge target allocation away from
the pure risk-profile base. The Decision Engine architecture treats
behaviour as the project's intelligence moat:

    Behavior            System Response
    Panic selling   →   Reduce equity
    High trading    →   Increase cash
    Long holding    →   Increase equity

This v1 derives signals heuristically from observable activity. As the
behavioural-data corpus grows we'll move to an event-stream signal
store; the OUTPUT contract here is the single source of truth either
way:

    {
        "drawdown_tolerance": "low" | "medium" | "high",
        "trading_activity":   "low" | "medium" | "high",
        "volatility_preference": "low" | "medium" | "high",
        "evidence": {...}     # human-readable explainability
    }

These keys map 1:1 to the slots already wired in
`target_allocator._behaviour_modifier`. Caller can pass the dict
straight to `_behaviour_modifier` (or via user_profiles.behaviour).
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from deps import db

logger = logging.getLogger(__name__)


@dataclass
class BehaviouralSignals:
    drawdown_tolerance: Optional[str] = None      # "low"/"medium"/"high"
    trading_activity: Optional[str] = None        # "low"/"medium"/"high"
    volatility_preference: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    confidence_score: float = 0.0                 # 0-100

    def to_dict(self) -> Dict[str, Any]:
        # Match the shape `target_allocator._behaviour_modifier` reads.
        return {
            "drawdown_tolerance": self.drawdown_tolerance,
            "trading_activity": self.trading_activity,
            "volatility_preference": self.volatility_preference,
        }


# ── Trading activity ────────────────────────────────────────────────────
# Counts non-SIP purchase + redemption events in the last 12 months.
# SIPs are excluded because monthly auto-debit isn't "trading" — it's
# habit. Buckets at 6 / 24 transactions/year.
async def _trading_activity(user_id: str) -> Dict[str, Any]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    n_active = 0
    n_sip = 0
    try:
        cursor = db.cas_transactions.find(
            {
                "user_id": user_id,
                "date": {"$gte": cutoff},
            },
            {"_id": 0, "type": 1, "amount": 1, "date": 1},
        )
        async for t in cursor:
            ttype = (t.get("type") or "").upper()
            if "SIP" in ttype:
                n_sip += 1
            elif ttype in ("PURCHASE", "BUY", "REDEMPTION", "REDEEM", "SELL", "SWITCH"):
                n_active += 1
    except Exception as e:  # noqa: BLE001
        logger.warning("trading_activity probe failed for %s: %s", user_id, e)
        return {"signal": None, "evidence": {"error": str(e)[:120]}}

    if n_active == 0 and n_sip == 0:
        return {"signal": None,
                "evidence": {"reason": "no transactions in last 12 months"}}
    if n_active >= 24:
        signal = "high"
    elif n_active >= 6:
        signal = "medium"
    else:
        signal = "low"
    return {
        "signal": signal,
        "evidence": {
            "non_sip_transactions_12m": n_active,
            "sip_transactions_12m": n_sip,
        },
    }


# ── Drawdown tolerance ──────────────────────────────────────────────────
# Heuristic: holding-age is a proxy for tolerance — investors who held
# through past corrections without redeeming have higher tolerance.
# Mean of (today - earliest_buy_date) across holdings, capped at 7y.
async def _drawdown_tolerance(user_id: str) -> Dict[str, Any]:
    holdings = await db.holdings.find(
        {"user_id": user_id}, {"_id": 0, "buy_date": 1, "asset_type": 1},
    ).to_list(500)
    if not holdings:
        return {"signal": None,
                "evidence": {"reason": "no holdings"}}

    today = datetime.now(timezone.utc).date()
    ages_days: List[int] = []
    for h in holdings:
        bd = h.get("buy_date")
        if not bd:
            continue
        try:
            if isinstance(bd, str):
                d = datetime.fromisoformat(bd.replace("Z", "+00:00")).date()
            elif isinstance(bd, datetime):
                d = bd.date()
            else:
                continue
            ages_days.append(max(0, (today - d).days))
        except Exception:  # noqa: BLE001
            continue
    if not ages_days:
        return {"signal": None,
                "evidence": {"reason": "no buy_date on any holding"}}
    avg_years = (sum(ages_days) / len(ages_days)) / 365.25
    # Count redemptions in last 24 months — anyone who panicked recently
    # demotes the tolerance signal regardless of age.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=730)).isoformat()
    redemptions = 0
    try:
        async for _ in db.cas_transactions.find(
            {"user_id": user_id, "date": {"$gte": cutoff},
             "type": {"$in": ["REDEMPTION", "REDEEM", "SELL"]}},
            {"_id": 0, "_dummy": 1},
        ):
            redemptions += 1
    except Exception:  # noqa: BLE001
        pass

    # Bucketing
    if redemptions >= 5:
        signal = "low"
    elif avg_years >= 4:
        signal = "high"
    elif avg_years >= 1.5:
        signal = "medium"
    else:
        signal = "low"
    return {
        "signal": signal,
        "evidence": {
            "avg_holding_age_years": round(avg_years, 2),
            "n_holdings_with_buy_date": len(ages_days),
            "redemptions_24m": redemptions,
        },
    }


# ── Volatility preference ───────────────────────────────────────────────
# Proxy: % of equity AUM in mid/small cap or sector funds. >40% → high
# preference for volatility; <15% → low.
async def _volatility_preference(user_id: str) -> Dict[str, Any]:
    holdings = await db.holdings.find(
        {"user_id": user_id}, {"_id": 0, "name": 1, "asset_type": 1,
                                "quantity": 1, "current_price": 1, "sector": 1},
    ).to_list(500)
    if not holdings:
        return {"signal": None, "evidence": {"reason": "no holdings"}}

    eq_total = 0.0
    high_vol_total = 0.0
    high_vol_markers = ("small cap", "smallcap", "micro cap", "mid cap",
                        "midcap", "sectoral", "thematic")
    for h in holdings:
        at = (h.get("asset_type") or "").lower()
        if at not in ("equity", "mutual_fund", "mf", "etf"):
            continue
        v = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
        if v <= 0:
            continue
        eq_total += v
        n = (h.get("name") or "").lower()
        s = (h.get("sector") or "").lower()
        is_high_vol = (
            any(k in n for k in high_vol_markers) or
            any(k in s for k in ("mid", "small", "micro"))
        )
        if is_high_vol:
            high_vol_total += v
    if eq_total <= 0:
        return {"signal": None, "evidence": {"reason": "no equity exposure"}}
    pct = high_vol_total / eq_total * 100
    if pct >= 40:
        signal = "high"
    elif pct >= 15:
        signal = "medium"
    else:
        signal = "low"
    return {
        "signal": signal,
        "evidence": {
            "high_vol_pct_of_equity": round(pct, 2),
            "high_vol_amount_rs": round(high_vol_total, 0),
        },
    }


# ── Public API ──────────────────────────────────────────────────────────
async def compute_signals(user_id: str) -> BehaviouralSignals:
    """Build the full signal set for `user_id`. Each sub-probe fails
    softly — missing source data leaves the corresponding signal as
    None instead of crashing the whole compute."""
    trade = await _trading_activity(user_id)
    dd = await _drawdown_tolerance(user_id)
    vol = await _volatility_preference(user_id)

    n_signals = sum(1 for s in (trade["signal"], dd["signal"], vol["signal"]) if s)
    confidence = round(33.3 * n_signals, 1)

    return BehaviouralSignals(
        drawdown_tolerance=dd["signal"],
        trading_activity=trade["signal"],
        volatility_preference=vol["signal"],
        evidence={
            "trading_activity": trade["evidence"],
            "drawdown_tolerance": dd["evidence"],
            "volatility_preference": vol["evidence"],
        },
        confidence_score=confidence,
    )
