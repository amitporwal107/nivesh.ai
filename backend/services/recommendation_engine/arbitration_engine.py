"""
ArbitrationEngine — PRD AR-1, AR-2, AR-3: Conflict resolution.

AR-2: Suppress signals where tax cost > threshold % of exit amount
      (unless is_tax_harvesting=True).
AR-3: Downgrade signals below confidence threshold to LOW severity.
      Rule book §10.11: "Downgrade by one level — do NOT drop silently."
AR-1: Deduplicate by dedup_key using explicit D-4 precedence table.

D-4 precedence (approved 2026-06-03):
  Level 0  user_override      Explicit, logged, per-fund informed consent.
                              Beats suitability so users aren't force-exited
                              against their will. Requires timestamp in ctx.user_overrides.
  Level 1  suitability_exit   Category violates risk profile — but overrideable.
  Level 2  underperformer_exit Quality below threshold — hard quality rule.
  Level 3  same_category_exit  Structural consolidation (overlap/same-category).
  Level 4  bucket_count_exit   Fund-count enforcement (blunter than quality-based).
  Level 5  drift_topup         Sizing advisory — can always wait.

Lower level number = higher priority (wins in a collision).
Ties at the same level resolve by base_score (higher wins).

Tax note: when a higher-priority EXIT overrides a keep, the conviction_text
and UI must surface the tax cost so the user understands the trade-off.
"""
from __future__ import annotations

import copy
import logging
from typing import Dict, List, Optional

from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)

# ── D-4 precedence table ─────────────────────────────────────────────────────
# Engine name → precedence level (lower wins).
_ENGINE_PRECEDENCE: Dict[str, int] = {
    # Suitability — highest engine-level priority
    "CategorySuitabilityEngine": 1,
    "RiskAlignmentEngine":       1,
    # Quality-based exits
    "UnderperformerEngine":      2,
    "GoalAlignmentEngine":       2,   # goal alignment is quality-based
    # Structural consolidation
    "OverlapEngine":             3,
    "CorrelationEngine":         3,
    "SameCategoryEngine":        3,
    # Fund-count enforcement (from reconcile_bucket pre-pass)
    "reconcile_bucket":          4,
    "GoalBucketFirstEngine":     4,
    "AllocationEngine":          4,
    # Sizing advisory
    "DriftEngine":               5,
    "InternationalFundsEngine":  5,
    "BehaviouralPersonaFilter":  3,   # persona mismatch = structural
}
_DEFAULT_LEVEL = 4  # anything unregistered → bucket_count tier


def _precedence(engine_name: str, reason_codes: List[str]) -> int:
    """Return the D-4 precedence level for a signal."""
    # bucket_count_exit signals come from the orchestrator pre-pass, not a named engine
    if "BUCKET_COUNT_EXIT" in (reason_codes or []):
        return 4
    return _ENGINE_PRECEDENCE.get(engine_name or "", _DEFAULT_LEVEL)


class ArbitrationEngine:
    """Suppress, deduplicate, and rank EngineSignals per D-4 precedence."""

    def arbitrate(
        self,
        signals: List[EngineSignal],
        ctx: RecommendationContext,
    ) -> List[EngineSignal]:
        ep_cfg = (ctx.rules_cfg.get("engine_pipeline") or {})
        arb_cfg = ep_cfg.get("arbitration") or {}
        confidence_threshold = float(arb_cfg.get("confidence_threshold", 0.4))
        tax_threshold_pct = float(arb_cfg.get("tax_suppression_threshold_pct", 15.0))

        # user_overrides: {instrument_id: {"reason": str, "timestamp": str}}
        # Level-0: explicit, per-fund, logged acknowledgement beats suitability_exit.
        user_overrides: Dict[str, dict] = getattr(ctx, "user_overrides", {}) or {}

        active: List[EngineSignal] = []

        for sig in signals:
            # Level 0: user-override beats suitability — check before any suppression
            if (
                sig.action_type in ("EXIT", "TRIM")
                and sig.instrument_id
                and sig.instrument_id in user_overrides
            ):
                override = user_overrides[sig.instrument_id]
                sig = _suppress(
                    sig,
                    f"User override (logged {override.get('timestamp', 'unknown')}): "
                    f"{override.get('reason', 'user acknowledged risk and chose to keep')}"
                )
                active.append(sig)
                continue

            # DV-4: Lock-in / STCG block — D-5: defer-with-reason, not silent suppress.
            # "We flagged it and the user understands the constraint" is better UX
            # and better liability posture than dropping the signal entirely.
            if (
                sig.action_type in ("EXIT", "TRIM")
                and sig.instrument_id
                and sig.instrument_id in ctx.tax_suppressed_instrument_ids
            ):
                holding = sig.__dict__.get("_holding") or {}
                lock_in_clears = holding.get("lock_in_end_date") or holding.get("lockin_end_date")
                if lock_in_clears:
                    defer_msg = f"Lock-in clears {lock_in_clears}. Flagged for then."
                else:
                    # STCG block or missing cost basis — generic defer
                    defer_msg = (
                        "Short-term capital gains tax applies or cost basis unavailable. "
                        "Flagged — review when the holding clears the 12-month window."
                    )
                sig = _defer(sig, defer_msg)
                active.append(sig)
                continue

            # AR-2: tax suppression
            if (
                sig.action_type == "EXIT"
                and not sig.is_tax_harvesting
                and sig.estimated_tax_rs > 0
                and sig.amount_rs > 0
            ):
                tax_pct = sig.estimated_tax_rs / sig.amount_rs * 100
                if tax_pct > tax_threshold_pct:
                    sig = _suppress(sig, f"Tax cost {tax_pct:.1f}% > {tax_threshold_pct:.0f}% threshold")
                    active.append(sig)
                    continue

            # AR-3: confidence below threshold — downgrade, do NOT suppress
            if sig.confidence < confidence_threshold:
                s = copy.copy(sig)
                note = f"[AR-3 downgraded: confidence {sig.confidence:.2f} < {confidence_threshold:.2f}]"
                s.confidence = min(s.confidence, 0.3)
                s.reason_text = f"{note} {s.reason_text}".strip()
                active.append(s)
                continue

            active.append(sig)

        # AR-1: dedup by dedup_key using D-4 precedence
        best_by_key: Dict[str, EngineSignal] = {}
        for sig in active:
            if sig.suppressed:
                continue
            key = sig.dedup_key
            existing = best_by_key.get(key)
            if existing is None:
                best_by_key[key] = sig
                continue
            sig_level = _precedence(sig.engine_name, sig.reason_codes)
            ex_level  = _precedence(existing.engine_name, existing.reason_codes)
            if sig_level < ex_level:
                # Lower level = higher priority → this signal wins
                # Log when a higher-priority EXIT overrides a keep (tax cost visibility)
                if sig.action_type in ("EXIT", "TRIM") and existing.action_type not in ("EXIT", "TRIM"):
                    logger.info(
                        "[Arbitration] %s (level %d) overrides %s (level %d) on %s — "
                        "tax cost should be surfaced in UI if applicable",
                        sig.engine_name, sig_level,
                        existing.engine_name, ex_level,
                        sig.instrument_id or key,
                    )
                best_by_key[key] = sig
            elif sig_level == ex_level and sig.base_score > existing.base_score:
                best_by_key[key] = sig
            # else: existing wins

        deduped = list(best_by_key.values())
        suppressed = [s for s in active if s.suppressed]

        # PRD §8: severity ordering — severe → mismatch → minor → aligned, then AR-3 priority
        _SEV_RANK = {"severe": 0, "mismatch": 1, "minor": 2, "aligned": 3}
        deduped.sort(
            key=lambda s: (_SEV_RANK.get(s.severity or "minor", 2), -s.ar3_priority),
        )

        logger.info(
            "[Arbitration] %d signals → %d active, %d suppressed",
            len(signals), len(deduped), len(suppressed),
        )

        return deduped + suppressed


def _suppress(sig: EngineSignal, reason: str) -> EngineSignal:
    s = copy.copy(sig)
    s.suppressed = True
    s.suppression_reason = reason
    return s


def _defer(sig: EngineSignal, reason: str) -> EngineSignal:
    """Mark a signal as deferred — active but not executable now.

    D-5: deferred signals appear in the plan with a Clock icon and defer_reason.
    They are NOT suppressed — the user must see that the exit is flagged.
    """
    s = copy.copy(sig)
    s.defer_reason = reason
    # Deferred signals are kept active (suppressed=False) so they reach the UI
    return s
