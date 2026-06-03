"""Canonical financial primitive Pydantic models.

These types enforce validation constraints on the raw numbers that flow through
every analytics, scoring, and portfolio route. They are intended to be used as
typed return types in route response-building functions and as nested fields in
response schemas.

Design principles:
- All monetary amounts are in Indian Rupees (₹) unless ``currency`` is present.
- Percentages are represented as floats (e.g. 14.2 means 14.2%, NOT 0.142).
- Fields that are genuinely optional carry ``Optional[T] = None`` — never use
  sentinel values like -1 or 0 to mean "unknown".
- Use ``model_config = ConfigDict(extra='forbid')`` on concrete response models
  to catch unexpected fields from the DB at the API boundary.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Money ─────────────────────────────────────────────────────────────────────

class Money(BaseModel):
    """A monetary amount with an ISO-4217 currency code.

    Example::

        Money(amount=Decimal("15000.00"), currency="INR")
    """
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(
        ...,
        ge=Decimal("0"),
        decimal_places=2,
        description="Monetary amount, rounded to 2 decimal places.",
        examples=[Decimal("15000.00")],
    )
    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
        description="ISO-4217 currency code.",
        examples=["INR"],
    )


# ── Percentage ────────────────────────────────────────────────────────────────

class Percentage(BaseModel):
    """A validated percentage value.

    Supports negative values (e.g. -8.4% drawdown) and values > 100% (e.g.
    200% gain). Clamps are enforced by the caller, not here.
    """
    model_config = ConfigDict(extra="forbid")

    value: float = Field(
        ...,
        ge=-10000.0,
        le=100000.0,
        description="Percentage value (e.g. 14.2 means 14.2%, not 0.142).",
        examples=[14.2],
    )


# ── Return Metrics ────────────────────────────────────────────────────────────

class ReturnMetrics(BaseModel):
    """Standardised return metrics for a portfolio or holding.

    All values are percentage-form (not decimal). ``xirr_pct`` and
    ``cagr_3y_pct`` are ``None`` when there is insufficient history.
    """
    model_config = ConfigDict(extra="forbid")

    absolute_pct: float = Field(
        ...,
        description="Simple P&L as a percentage of cost basis.",
        examples=[35.8],
    )
    xirr_pct: Optional[float] = Field(
        default=None,
        description="Annualised internal rate of return (time-weighted).",
        examples=[14.2],
    )
    cagr_1y_pct: Optional[float] = Field(
        default=None,
        description="1-year compounded annual growth rate.",
        examples=[24.3],
    )
    cagr_3y_pct: Optional[float] = Field(
        default=None,
        description="3-year compounded annual growth rate.",
        examples=[19.8],
    )
    cagr_5y_pct: Optional[float] = Field(
        default=None,
        description="5-year compounded annual growth rate.",
        examples=[22.1],
    )
    alpha_pct: Optional[float] = Field(
        default=None,
        description="Excess return vs benchmark.",
        examples=[5.2],
    )


# ── Allocation Breakdown ─────────────────────────────────────────────────────

class AllocationBreakdown(BaseModel):
    """Asset-class allocation weights for a portfolio (must sum to ≈100).

    Individual weights may be 0 but not negative. The ``other_pct`` bucket
    absorbs FDs, commodities, REITs, etc.
    """
    model_config = ConfigDict(extra="forbid")

    equity_pct: float = Field(..., ge=0, le=100, examples=[65.0])
    debt_pct: float = Field(..., ge=0, le=100, examples=[25.0])
    gold_pct: float = Field(default=0.0, ge=0, le=100, examples=[5.0])
    other_pct: float = Field(default=0.0, ge=0, le=100, examples=[5.0])

    @property
    def total(self) -> float:
        return round(self.equity_pct + self.debt_pct + self.gold_pct + self.other_pct, 2)


# ── NAV Data ──────────────────────────────────────────────────────────────────

class NAVData(BaseModel):
    """Current NAV snapshot for a mutual fund scheme."""
    model_config = ConfigDict(extra="forbid")

    isin: str = Field(
        ...,
        pattern=r"^INF[A-Z0-9]{9}$",
        description="Fund ISIN (AMFI format).",
        examples=["INF769K01EW6"],
    )
    nav: float = Field(
        ...,
        gt=0,
        description="Net asset value per unit in ₹.",
        examples=[72.45],
    )
    nav_date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Date for which NAV was published (YYYY-MM-DD).",
        examples=["2026-05-27"],
    )
    aum_cr: Optional[float] = Field(
        default=None,
        ge=0,
        description="Assets under management in ₹ crore.",
        examples=[72800.0],
    )


# ── Risk Metrics ──────────────────────────────────────────────────────────────

class RiskMetrics(BaseModel):
    """Quantitative risk measures for a fund or equity.

    All values are from the most recent available trailing period unless
    a period suffix (``_1y``, ``_3y``) is present in the field name.
    """
    model_config = ConfigDict(extra="forbid")

    beta: Optional[float] = Field(
        default=None,
        description="Market sensitivity vs benchmark (1.0 = moves with market).",
        examples=[0.78],
    )
    sharpe: Optional[float] = Field(
        default=None,
        description="Risk-adjusted return (Sharpe ratio). Higher is better.",
        examples=[1.42],
    )
    sortino: Optional[float] = Field(
        default=None,
        description="Downside-adjusted return. Higher is better.",
        examples=[1.89],
    )
    max_drawdown_pct: Optional[float] = Field(
        default=None,
        le=0,
        description="Worst peak-to-trough decline (always ≤ 0).",
        examples=[-18.4],
    )
    volatility_pct: Optional[float] = Field(
        default=None,
        ge=0,
        description="Annualised standard deviation of returns.",
        examples=[14.2],
    )
    var_95_pct: Optional[float] = Field(
        default=None,
        description="Value at Risk at 95% confidence (typically negative).",
        examples=[-2.1],
    )


# ── V3 Score ──────────────────────────────────────────────────────────────────

class V3CompositeScores(BaseModel):
    """Composite-level breakdown of a V3 score (0–100 per dimension)."""
    model_config = ConfigDict(extra="forbid")

    returns: Optional[float] = Field(default=None, ge=0, le=100, examples=[91.0])
    risk: Optional[float] = Field(default=None, ge=0, le=100, examples=[82.0])
    cost: Optional[float] = Field(default=None, ge=0, le=100, examples=[95.0])
    consistency: Optional[float] = Field(default=None, ge=0, le=100, examples=[88.0])
    portfolio_fit: Optional[float] = Field(default=None, ge=0, le=100, examples=[84.0])
    esg_proxy: Optional[float] = Field(default=None, ge=0, le=100, examples=[78.0])
    # Equity-specific composites
    quality: Optional[float] = Field(default=None, ge=0, le=100, examples=[85.0])
    valuation: Optional[float] = Field(default=None, ge=0, le=100, examples=[68.0])
    momentum: Optional[float] = Field(default=None, ge=0, le=100, examples=[74.0])


class V3Score(BaseModel):
    """Complete V3 score for a single instrument."""
    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(..., description="ISIN or NSE ticker.", examples=["INF769K01EW6"])
    v3_score: float = Field(..., ge=0, le=100, examples=[88.5])
    grade: str = Field(
        ...,
        pattern=r"^[A-F]$",
        description="Letter grade: A (≥80), B (≥65), C (≥50), D (≥35), F (<35).",
        examples=["A"],
    )
    coverage_pct: float = Field(
        ...,
        ge=0,
        le=100,
        description="% of the 38 primitives that had live data at scoring time.",
        examples=[97.2],
    )
    composites: Optional[V3CompositeScores] = None


# ── Sector Weight ─────────────────────────────────────────────────────────────

class SectorWeight(BaseModel):
    """Sector allocation entry."""
    model_config = ConfigDict(extra="forbid")

    sector: str = Field(..., examples=["Financial Services"])
    weight_pct: float = Field(..., ge=0, le=100, examples=[28.4])
    flag: Optional[str] = Field(
        default=None,
        description="Concentration flag if applicable.",
        examples=["overweight"],
    )


# ── Pagination ────────────────────────────────────────────────────────────────

class PaginationMeta(BaseModel):
    """Standard pagination metadata for list endpoints."""
    model_config = ConfigDict(extra="forbid")

    total: int = Field(..., ge=0, description="Total items matching the query.")
    limit: int = Field(..., ge=1, le=1000, description="Page size requested.")
    skip: int = Field(default=0, ge=0, description="Offset applied.")
    has_more: bool = Field(..., description="True if more items exist beyond this page.")
