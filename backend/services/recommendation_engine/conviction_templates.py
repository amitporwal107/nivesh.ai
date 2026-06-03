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
        return _exit_text(name, codes, detail, action)
    if action == "ADD":
        return _add_text(name, codes, detail)
    if action == "CONSOLIDATE":
        return f"Trim the redundancy — {name} duplicates a stronger holding in the same bucket. {detail}".strip()
    if action == "REDIRECT":
        return f"Redirect away from {name} — {detail or 'a better-fit option is available'}."
    # Fallback: never empty
    return f"{name} — {detail or action.lower()}"


# ── EXIT / TRIM / SWITCH ─────────────────────────────────────────────────────

def _exit_text(name: str, codes: set, detail: str, action: str) -> str:
    if "UNDERPERFORMER" in codes:
        return f"{name} — quality falls below your risk tier's threshold. {detail}".rstrip()

    if any(c in codes for c in ("SUITABILITY_EXIT", "CATEGORY_MISMATCH", "CATEGORY_SUITABILITY")):
        return f"{name} — category doesn't fit your risk profile. {detail}".rstrip()

    if any(c in codes for c in ("CONSOLIDATION", "SAME_CATEGORY", "OVERLAP", "CORRELATION")):
        return f"{name} — duplicates an existing holding with no additional diversification. {detail}".rstrip()

    if "AMC_CONCENTRATION" in codes:
        return f"{name} — takes your AMC concentration over the limit. {detail}".rstrip()

    if any(c in codes for c in ("SECTOR_CONCENTRATION", "SECTOR_CAP")):
        return f"{name} — pushes a single sector above your concentration cap. {detail}".rstrip()

    if "INTERNATIONAL_REBALANCE" in codes:
        return f"{name} — international allocation above your band target. {detail}".rstrip()

    if "BEHAVIOURAL_FILTER" in codes:
        return f"{name} — volatility profile mismatches your risk tolerance. {detail}".rstrip()

    if any(c in codes for c in ("DRIFT_REBALANCE", "ALLOCATION_DRIFT")):
        bucket = _bucket_from_name(name)
        return f"{bucket.capitalize()} above your band — trim {name} to restore balance. {detail}".rstrip()

    if action == "SWITCH":
        return f"Switch out of {name} — {detail or 'a better-fit option is available'}."

    # Generic: fund name leads, reason follows
    return f"{name} — {detail or 'exit recommended based on current portfolio analysis'}."


# ── ADD ─────────────────────────────────────────────────────────────────────

def _add_text(name: str, codes: set, detail: str) -> str:
    if any(c in codes for c in ("DRIFT_REBALANCE", "ALLOCATION_DRIFT")):
        bucket = _bucket_from_name(name)
        return f"Build your {bucket} position — {detail or 'below your target band'}."

    if any(c in codes for c in ("GOAL_ALIGNMENT", "GOAL_BUCKET")):
        return f"Add to {name} — closes the gap on a priority goal. {detail}".rstrip()

    if "INTERNATIONAL_REBALANCE" in codes:
        return f"Build your international allocation — {name} fits your band target. {detail}".rstrip()

    return f"Build your {name} position — {detail or 'below target allocation'}."


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
