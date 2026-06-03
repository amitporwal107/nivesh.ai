"""
PortfolioAnalyticsEngine — PA-1..PA-3: Portfolio structure diagnostics.

PA-1: Over-diversification — flag when equity fund count > 8 AND marginal
      diversification gain (measured by effective_holdings delta) is negligible.
PA-2: Under-diversification — effective holdings < 3.0 signals high concentration.
PA-3: AMC concentration already handled by AMCConcentrationEngine (Rule 2).

Rule book §10.4
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)

_DEBT_KEYWORDS = (
    "liquid", "gilt", "bond", "corporate bond", "short term", "overnight",
    "banking & psu", "low duration", "ultra short", "medium duration",
    "long duration", "credit risk", "floater", "dynamic bond", "debt",
    "money market", "arbitrage",
)


def _is_debt_like(category: str, name: str) -> bool:
    combined = f"{category} {name}".lower()
    return any(k in combined for k in _DEBT_KEYWORDS)


class PortfolioAnalyticsEngine(BaseEngine):
    """PA-1 / PA-2: Emit signals for over- and under-diversification."""

    engine_name = "PortfolioAnalyticsEngine"
    enabled_config_key = "portfolio_analytics.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        cfg = ctx.rules_cfg.get("portfolio_analytics") or {}
        if not cfg.get("enabled", True):
            return []

        max_equity_fund_count = int(cfg.get("max_equity_fund_count", 8))
        min_effective_holdings = float(cfg.get("min_effective_holdings", 3.0))

        pi = ctx.portfolio_intelligence or {}
        mf_investments = pi.get("mf_investments") or []

        # Count equity-like MF funds
        equity_funds = [
            m for m in mf_investments
            if not _is_debt_like(m.get("category") or "", m.get("scheme_name") or "")
        ]
        equity_fund_count = len(equity_funds)

        # Effective holdings from compression (Herfindahl reciprocal on top-stock weights)
        effective_holdings = float(
            (pi.get("compression") or {}).get("effective_stocks") or 0.0
        )

        signals: List[EngineSignal] = []

        # PA-1: Over-diversification — too many funds with minimal extra diversification
        if equity_fund_count > max_equity_fund_count:
            if effective_holdings > 0 and effective_holdings < float(equity_fund_count) * 3:
                # The extra funds behave redundantly (rule book §10.4 PA-1)
                excess = equity_fund_count - max_equity_fund_count
                redundancy = pi.get("redundancy_suggestions") or []
                # Suggest exiting the most redundant fund
                top_redundant = redundancy[0] if redundancy else {}
                signals.append(EngineSignal(
                    signal_id=f"portfolio_analytics::pa1::over_diversification",
                    engine_name=self.engine_name,
                    rule_label="PA-1",
                    action_type="EXIT" if top_redundant else "TRIM",
                    instrument_id=top_redundant.get("remove_id"),
                    instrument_name=top_redundant.get("remove_name", "Redundant Fund"),
                    amount_rs=float(top_redundant.get("remove_amount_rs", 0)),
                    base_score=5.5,
                    confidence=0.65,
                    risk_reduction=0.2,
                    diversification_gain=0.4,
                    urgency=0.3,
                    implementation_ease=0.6,
                    reason_codes=["PA1_OVER_DIVERSIFICATION"],
                    reason_text=(
                        f"You hold {equity_fund_count} equity funds — {excess} above the "
                        f"recommended maximum of {max_equity_fund_count}. With only "
                        f"{effective_holdings:.0f} effective holdings, the extra funds add "
                        f"tracking risk without meaningful diversification."
                    ),
                    dedup_key=f"EXIT::{top_redundant.get('remove_id') or 'pa1_redundant'}",
                ))

        # PA-2: Under-diversification — effective holdings too low despite multiple funds
        if effective_holdings > 0 and effective_holdings < min_effective_holdings and len(equity_funds) >= 2:
            signals.append(EngineSignal(
                signal_id="portfolio_analytics::pa2::concentration",
                engine_name=self.engine_name,
                rule_label="PA-2",
                action_type="HOLD",  # informational — no specific EXIT/ADD yet
                instrument_id=None,
                instrument_name="Portfolio",
                amount_rs=0.0,
                base_score=4.0,
                confidence=0.7,
                risk_reduction=0.6,
                diversification_gain=0.5,
                urgency=0.3,
                implementation_ease=0.4,
                reason_codes=["PA2_UNDER_DIVERSIFICATION"],
                reason_text=(
                    f"Despite holding {equity_fund_count} equity funds, the portfolio has only "
                    f"{effective_holdings:.1f} effective holdings — indicating heavy stock "
                    f"concentration. Consider spreading across genuinely uncorrelated categories."
                ),
                dedup_key="HOLD::pa2_concentration",
            ))

        return signals
