"""Advisory conviction text templates for recommendation actions.

Produces a `conviction_text` string for every EngineSignal.  The text is
deterministic (same signal → same text), grounded in the signal's own
fields (no invented numbers), and follows the product rule:

  Rule: leads with fund name / bucket / observable metric.
        reason precedes implied action.
        never uses BUY / SELL / HOLD as standalone recommendation words.

Called by _signal_to_action() in orchestrator.py — not by engines.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.recommendation_engine.context import EngineSignal


def build(sig: "EngineSignal") -> str:
    """Return a non-empty conviction_text string for the given signal."""
    name   = (sig.instrument_name or "this holding").strip()
    codes  = set(sig.reason_codes or [])
    action = (sig.action_type or "").upper()
    detail = _clean(sig.reason_text or "")

    if action in ("EXIT", "TRIM", "REDUCE", "SWITCH"):
        return _exit_text(name, codes, detail, action, sig)
    if action == "ADD":
        return _add_text(name, codes, detail, sig)
    if action == "CONSOLIDATE":
        return (
            f"Exit {name} — it overlaps too heavily with a stronger fund in the same bucket. "
            f"Consolidating frees up capital without losing the exposure. {detail}"
        ).strip()
    if action == "REDIRECT":
        return f"Stop adding to {name} — {detail or 'redirect new money to a better-fit fund in this category'}."
    # Fallback: never empty
    return f"{name} — {detail or action.lower()}"


# ── EXIT / TRIM / SWITCH ─────────────────────────────────────────────────────

def _exit_text(name: str, codes: set, detail: str, action: str, sig: "EngineSignal") -> str:
    amount = f"₹{int(sig.amount_rs):,}" if getattr(sig, "amount_rs", None) else None

    if "UNDERPERFORMER" in codes:
        return (
            f"Exit {name} — it has consistently underperformed its benchmark for your risk tier "
            f"with no structural reason to expect recovery. {detail}"
        ).rstrip()

    if any(c in codes for c in ("SUITABILITY_EXIT", "CATEGORY_MISMATCH", "CATEGORY_SUITABILITY",
                                 "CATEGORY_SUITABILITY_BREACH", "SUB_CATEGORY_CAP_BREACH")):
        return (
            f"Exit {name} — this fund category sits outside your risk profile. "
            f"Holding it increases risk without improving your expected return for your goals. {detail}"
        ).rstrip()

    if any(c in codes for c in ("CONSOLIDATION", "SAME_CATEGORY", "OVERLAP", "CORRELATION")):
        overlap_hint = ""
        if detail and "%" in detail:
            overlap_hint = f" ({detail.split('%')[0].split()[-1]}% shared holdings — pure duplication)"
        return (
            f"Exit {name}{overlap_hint} — it duplicates an existing position with no added diversification. "
            f"One strong fund per category is enough."
        ).rstrip()

    if "AMC_CONCENTRATION" in codes:
        return (
            f"Exit {name} — too much of your portfolio is concentrated in one fund house. "
            f"Single-AMC risk isn't compensated by diversification. {detail}"
        ).rstrip()

    if any(c in codes for c in ("SECTOR_CONCENTRATION", "SECTOR_CAP")):
        return (
            f"Trim {name} — a single sector is now above your maximum concentration. "
            f"Sector bets increase volatility without your goals requiring it. {detail}"
        ).rstrip()

    if "INTERNATIONAL_REBALANCE" in codes:
        return (
            f"Trim your international exposure via {name} — it's above your target band. "
            f"Currency and regulatory risk are already priced in; more doesn't help. {detail}"
        ).rstrip()

    if "BEHAVIOURAL_FILTER" in codes:
        return (
            f"Exit {name} — its volatility profile is higher than your risk tolerance. "
            f"You'd be exposed to drawdowns your plan isn't sized to absorb. {detail}"
        ).rstrip()

    if any(c in codes for c in ("DRIFT_REBALANCE", "ALLOCATION_DRIFT")):
        bucket = _bucket_from_name(name)
        amt_clause = f" Free up {amount}." if amount else ""
        return (
            f"Your {bucket} is well above target — trim {name} to bring the allocation back in band.{amt_clause} "
            f"{detail}"
        ).rstrip()

    if action == "SWITCH":
        return (
            f"Switch out of {name} — "
            f"{detail or 'a lower-cost, better-performing alternative is available in the same category'}."
        )

    amt_clause = f" Freeing up {amount} gives you capital to redeploy." if amount else ""
    return f"Exit {name} — {detail or 'this position no longer earns its place in the portfolio'}.{amt_clause}".rstrip()


# ── ADD ─────────────────────────────────────────────────────────────────────

def _add_text(name: str, codes: set, detail: str, sig: "EngineSignal") -> str:
    amount = f"₹{int(sig.amount_rs):,}" if getattr(sig, "amount_rs", None) else None
    amt_clause = f" Top up by {amount}." if amount else ""

    if any(c in codes for c in ("DRIFT_REBALANCE", "ALLOCATION_DRIFT")):
        bucket = _bucket_from_name(name)
        return (
            f"Your {bucket} is significantly below target — this gap is hurting your risk-adjusted return. "
            f"Add to {name} to restore balance.{amt_clause} {detail}"
        ).rstrip()

    if any(c in codes for c in ("GOAL_ALIGNMENT", "GOAL_BUCKET")):
        return (
            f"Add to {name} — your goal timeline requires this allocation and it's currently underfunded. "
            f"{detail}{amt_clause}"
        ).rstrip()

    if "INTERNATIONAL_REBALANCE" in codes:
        return (
            f"Increase your international allocation via {name} — "
            f"geographic concentration in India-only assets increases correlation risk. {detail}{amt_clause}"
        ).rstrip()

    return (
        f"Add to {name} — this category is below its target in your portfolio.{amt_clause} "
        f"{detail}"
    ).rstrip()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    """Strip whitespace; ensure sentence ends with period if non-empty."""
    text = text.strip()
    if text and not text.endswith((".", "!", "?")):
        text += "."
    return text


def _bucket_from_name(name: str) -> str:
    """Extract the asset-class bucket label from an instrument_name like 'equity rebalance'."""
    n = name.lower()
    for bucket in ("equity", "debt", "gold", "cash"):
        if bucket in n:
            return bucket
    return name
