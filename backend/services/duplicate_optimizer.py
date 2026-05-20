"""Duplicate-funds optimisation engine.

Given a duplicate / overlap insight and the user's holdings, produces a
concrete recommendation:

  - Which fund to keep (best of the pair on the scoring rubric)
  - Which to exit (the other one)
  - Capital released (AUM of the exit fund)
  - Estimated tax impact on switch (LTCG / STCG)
  - 6-factor score breakdown so the UI can show *why* this fund won

# Scoring rubric

Spec asked for 6 factors weighted: Expense 25%, 5Y risk-adj return 30%,
Downside protection 15%, Manager stability 10%, AUM/liquidity 10%, Tax
impact 10%.

We don't yet have fund-master data wired (no live expense ratio, no 5Y
returns, no manager tenure). So this V1 uses a **degraded** rubric that
works from the data we do have:

  - Expense (40%)     — Direct plan > Regular plan (heuristic on name)
  - User CAGR (40%)   — actual annualised return on the user's lots
  - AUM/liquidity (10%) — bigger position = easier to exit cleanly
  - Tax impact (10%)  — lower tax-to-exit = better

The remaining 3 factors (5Y risk-adj, downside, manager stability) are
flagged in `score_breakdown.placeholders` so the UI can show "data
unavailable" rather than fake numbers. Phase B+ wires real fund data.

# Tax impact

We use a simplified estimator (not the full FIFO engine) because we
don't always have lot-level buy dates in `holdings`:

  - holding_period_days = (today - first observed buy_date) or fallback
    to 365+1 (assume LTCG) when missing
  - gain = (current_price - buy_price) * quantity
  - if holding_period >= 365 days → LTCG at 10% over ₹1L exemption
  - else → STCG at 15%

For lot-precision tax, callers can route to
`services.tax_engine_fifo.tax_calculator.TaxCalculator`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Tax constants (FY24-25 equity/equity-MF) ─────────────────────────
STCG_RATE = 0.15
LTCG_RATE = 0.10
LTCG_EXEMPTION_RS = 100_000
LT_THRESHOLD_DAYS = 365

# ── Heuristic expense ratios when fund-master not available ───────────
ER_REGULAR_DEFAULT = 0.0165  # 1.65% — typical equity regular plan
ER_DIRECT_DEFAULT  = 0.0072  # 0.72% — typical equity direct plan


# ── Data classes ─────────────────────────────────────────────────────
@dataclass
class FundScore:
    fund_name: str
    aum_rs: float
    expense_ratio: float
    user_cagr_pct: Optional[float]
    holding_period_days: int

    # Weighted sub-scores (0..1)
    expense_score: float = 0.0
    cagr_score: float = 0.0
    aum_score: float = 0.0
    tax_score: float = 0.0

    # Composite (0..100)
    total_score: float = 0.0

    # Estimated tax impact if this fund is the *exit* candidate
    tax_impact_rs: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fund_name": self.fund_name,
            "aum_rs": round(self.aum_rs, 2),
            "expense_ratio": round(self.expense_ratio, 4),
            "expense_ratio_pct": round(self.expense_ratio * 100, 2),
            "user_cagr_pct": round(self.user_cagr_pct, 2) if self.user_cagr_pct is not None else None,
            "holding_period_days": self.holding_period_days,
            "sub_scores": {
                "expense": round(self.expense_score, 3),
                "cagr": round(self.cagr_score, 3),
                "aum": round(self.aum_score, 3),
                "tax": round(self.tax_score, 3),
            },
            "total_score": round(self.total_score, 1),
            "tax_impact_rs_on_exit": round(self.tax_impact_rs, 2),
        }


@dataclass
class OptimizationPlan:
    insight_id: str
    keep: Dict[str, Any]
    exit: Dict[str, Any]
    capital_released_rs: float
    tax_impact_rs: float
    annual_fee_savings_rs: float
    rationale: List[str] = field(default_factory=list)
    placeholders: List[str] = field(default_factory=list)  # factors we couldn't compute

    def to_dict(self) -> Dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "keep": self.keep,
            "exit": self.exit,
            "capital_released_rs": round(self.capital_released_rs, 2),
            "tax_impact_rs": round(self.tax_impact_rs, 2),
            "annual_fee_savings_rs": round(self.annual_fee_savings_rs, 2),
            "rationale": self.rationale,
            "placeholders": self.placeholders,
        }


# ── Helpers ──────────────────────────────────────────────────────────
def _is_direct_plan(name: str) -> bool:
    n = (name or "").lower()
    return "direct" in n


def _is_regular_plan(name: str) -> bool:
    n = (name or "").lower()
    return "regular" in n or ("direct" not in n and "growth" in n)


def _expense_ratio(holding: Dict[str, Any]) -> float:
    """Use holding-attached `expense_ratio` when present, else heuristic."""
    er = holding.get("expense_ratio")
    if er is not None and 0 < float(er) < 0.05:
        return float(er)
    if _is_direct_plan(holding.get("name", "")):
        return ER_DIRECT_DEFAULT
    return ER_REGULAR_DEFAULT


def _parse_buy_date(holding: Dict[str, Any]) -> Optional[date]:
    for key in ("buy_date", "purchase_date", "first_buy_date"):
        v = holding.get(key)
        if not v:
            continue
        try:
            if isinstance(v, datetime):
                return v.date()
            if isinstance(v, date):
                return v
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            continue
    return None


def _holding_period_days(holding: Dict[str, Any]) -> int:
    d = _parse_buy_date(holding)
    if d is None:
        # No buy_date — assume long-term to be tax-conservative (no
        # STCG estimate); UI can override once we wire lot dates.
        return LT_THRESHOLD_DAYS + 1
    return (datetime.now(timezone.utc).date() - d).days


def _user_cagr_pct(holding: Dict[str, Any], days: int) -> Optional[float]:
    """Annualised return from buy_price → current_price."""
    bp = float(holding.get("buy_price") or 0)
    cp = float(holding.get("current_price") or 0)
    if bp <= 0 or cp <= 0 or days <= 30:
        return None
    years = max(days / 365.25, 30 / 365.25)
    try:
        return ((cp / bp) ** (1 / years) - 1) * 100
    except (ValueError, ZeroDivisionError):
        return None


def _estimate_tax_on_exit(holding: Dict[str, Any], days: int) -> float:
    """Conservative tax impact if the entire holding were sold today.

    For LTCG events we don't know the user's other LT gains this FY,
    so we apply the ₹1L exemption locally (best-case for the user).
    The caller (insights route) can call into the real
    `TaxCalculator` when lot data is available.
    """
    bp = float(holding.get("buy_price") or 0)
    cp = float(holding.get("current_price") or 0)
    qty = float(holding.get("quantity") or 0)
    gain = max(0.0, (cp - bp) * qty)
    if gain <= 0:
        return 0.0
    if days < LT_THRESHOLD_DAYS:
        return gain * STCG_RATE
    taxable = max(0.0, gain - LTCG_EXEMPTION_RS)
    return taxable * LTCG_RATE


# ── Scoring ──────────────────────────────────────────────────────────
def _score_fund(holding: Dict[str, Any], peer_max_aum: float, peer_max_cagr: Optional[float]) -> FundScore:
    name = holding.get("name") or ""
    aum = float(holding.get("quantity") or 0) * float(holding.get("current_price") or 0)
    er = _expense_ratio(holding)
    days = _holding_period_days(holding)
    cagr = _user_cagr_pct(holding, days)
    tax_impact = _estimate_tax_on_exit(holding, days)

    # Sub-scores 0..1 (higher = better)
    # Expense: anchor on 1.65% (worst) → 0.5% (best). Lower expense scores higher.
    expense_score = max(0.0, min(1.0, (ER_REGULAR_DEFAULT - er) / (ER_REGULAR_DEFAULT - 0.005)))

    # CAGR: relative to the better peer. None → 0.5 (neutral, can't penalise w/o data).
    if cagr is None or peer_max_cagr is None or peer_max_cagr <= 0:
        cagr_score = 0.5
    else:
        cagr_score = max(0.0, min(1.0, cagr / peer_max_cagr))

    # AUM: relative to peer max.
    aum_score = (aum / peer_max_aum) if peer_max_aum > 0 else 0.5

    # Tax: lower is better → invert. Anchor on the higher of the two peers; here
    # we just use 1.0 if no gain, else scale down. Caller normalises across peers.
    tax_score_raw = 1.0 / (1 + tax_impact / max(aum, 1.0))  # smaller tax/AUM = closer to 1
    tax_score = max(0.0, min(1.0, tax_score_raw))

    # Weighted total (× 100 for display 0..100)
    total = (
        expense_score * 0.40 +
        cagr_score    * 0.40 +
        aum_score     * 0.10 +
        tax_score     * 0.10
    ) * 100

    return FundScore(
        fund_name=name,
        aum_rs=aum,
        expense_ratio=er,
        user_cagr_pct=cagr,
        holding_period_days=days,
        expense_score=expense_score,
        cagr_score=cagr_score,
        aum_score=aum_score,
        tax_score=tax_score,
        total_score=total,
        tax_impact_rs=tax_impact,
    )


# ── Public API ───────────────────────────────────────────────────────
def _name_tokens(name: str) -> set:
    """Normalised set of significant tokens for fuzzy matching."""
    n = (name or "").lower()
    # Drop noise tokens that match too many funds
    stop = {"fund", "plan", "growth", "scheme", "the", "india", "of"}
    return {t for t in n.replace("-", " ").replace(".", " ").split() if t and t not in stop and len(t) > 1}


def find_holdings_for_insight(
    insight: Dict[str, Any], holdings: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Match an insight's affected_funds against the holdings list.

    Uses token-overlap scoring instead of a fixed prefix so "Regular" vs
    "Direct" variants of the same scheme are distinguished correctly.
    """
    affected = insight.get("affected_funds") or []
    if not affected:
        return []
    out: List[Dict[str, Any]] = []
    used_idx: set = set()
    for af in affected:
        af_tokens = _name_tokens(af)
        if not af_tokens:
            continue
        best_idx = -1
        best_score = 0
        for i, h in enumerate(holdings):
            if i in used_idx or h.get("asset_type") not in ("mutual_fund", "etf"):
                continue
            h_tokens = _name_tokens(h.get("name") or "")
            if not h_tokens:
                continue
            overlap = len(af_tokens & h_tokens)
            # Require strong overlap — at least half the affected fund's tokens
            if overlap >= max(2, len(af_tokens) // 2) and overlap > best_score:
                best_score = overlap
                best_idx = i
        if best_idx >= 0:
            used_idx.add(best_idx)
            out.append(holdings[best_idx])
    return out


def build_plan(
    insight: Dict[str, Any],
    holdings: List[Dict[str, Any]],
) -> Optional[OptimizationPlan]:
    """Produce a Keep/Exit/Redeploy plan for one duplicate-pair insight.

    Returns None if the insight isn't a duplicate/overlap, if we can't
    resolve at least 2 holdings from `affected_funds`, or if both
    funds score essentially the same (within 2 points — caller can
    surface that as "user choice" rather than auto-decide).
    """
    theme = insight.get("theme") or ""
    if theme not in ("duplication", "overlap"):
        return None

    resolved = find_holdings_for_insight(insight, holdings)
    if len(resolved) < 2:
        return None

    # Score every resolved holding then rank
    peer_aums = [float(h.get("quantity", 0)) * float(h.get("current_price", 0)) for h in resolved]
    max_aum = max(peer_aums) if peer_aums else 1.0

    # First pass to find peer max CAGR for normalisation
    prelim_cagrs: List[Optional[float]] = []
    for h in resolved:
        days = _holding_period_days(h)
        prelim_cagrs.append(_user_cagr_pct(h, days))
    max_cagr = max([c for c in prelim_cagrs if c is not None] or [None])

    scores = [_score_fund(h, max_aum, max_cagr) for h in resolved]
    scores.sort(key=lambda s: -s.total_score)
    keep_score = scores[0]
    exit_score = scores[-1]  # for >2 holdings we keep top, exit bottom

    # When the two are essentially equal, prefer the Direct plan
    if abs(keep_score.total_score - exit_score.total_score) < 2.0:
        if _is_direct_plan(exit_score.fund_name) and not _is_direct_plan(keep_score.fund_name):
            keep_score, exit_score = exit_score, keep_score

    rationale: List[str] = []
    placeholders: List[str] = []

    if _is_direct_plan(keep_score.fund_name) and _is_regular_plan(exit_score.fund_name):
        rationale.append("Direct plan has ~93 bps lower expense ratio than the regular plan — same portfolio, lower cost.")
    if keep_score.expense_ratio < exit_score.expense_ratio:
        delta_pct = (exit_score.expense_ratio - keep_score.expense_ratio) * 100
        rationale.append(f"Keep fund expense ratio {keep_score.expense_ratio*100:.2f}% vs exit {exit_score.expense_ratio*100:.2f}% (saves {delta_pct:.2f}% per year).")
    if (keep_score.user_cagr_pct or 0) > (exit_score.user_cagr_pct or 0):
        rationale.append(f"Your realised CAGR is {keep_score.user_cagr_pct:.1f}% vs {exit_score.user_cagr_pct:.1f}% on the duplicate.")
    if keep_score.aum_rs > exit_score.aum_rs:
        rationale.append(f"Larger position (₹{keep_score.aum_rs/1_00_000:.1f}L) — less tax disruption to retain.")
    if exit_score.tax_impact_rs > 0:
        rationale.append(f"Exit triggers ~₹{exit_score.tax_impact_rs:,.0f} {'LTCG' if exit_score.holding_period_days >= LT_THRESHOLD_DAYS else 'STCG'} tax — account for this before switching.")

    placeholders.extend([
        "5Y risk-adjusted return (need fund-master feed)",
        "Downside protection / max drawdown (need fund-master feed)",
        "Fund manager tenure (need fund-master feed)",
    ])

    capital_released = exit_score.aum_rs
    annual_fee_savings = capital_released * max(0.0, exit_score.expense_ratio - keep_score.expense_ratio)

    return OptimizationPlan(
        insight_id=insight.get("insight_id", ""),
        keep=keep_score.to_dict(),
        exit=exit_score.to_dict(),
        capital_released_rs=capital_released,
        tax_impact_rs=exit_score.tax_impact_rs,
        annual_fee_savings_rs=annual_fee_savings,
        rationale=rationale,
        placeholders=placeholders,
    )
