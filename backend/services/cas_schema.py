"""Pydantic v2 schema for extracted CAS data.

Mirrors the JSON shape that `services.openai_cas_parser.EXTRACTION_PROMPT`
emits and that `services.claude_cas_mapper.map_to_internal` consumes. By
declaring it as a Pydantic model the hybrid parser can validate raw LLM
output, normalise numeric coercions, and feed structured errors into the
per-section retry loop.

This schema is intentionally permissive — every field is optional and
unknown fields are dropped silently, because real-world CAS vendors keep
adding columns and we don't want a single schema drift to break parsing.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _to_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("₹", "").replace("INR", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, str_strip_whitespace=True)


class StatementInfo(_Base):
    depository: Optional[str] = None
    id: Optional[str] = None
    statement_type: Optional[str] = None
    period: Optional[str] = None


class InvestorInfo(_Base):
    name: Optional[str] = None
    pan: Optional[str] = None
    address: Optional[str] = None


class AssetAllocationRow(_Base):
    asset_class: Optional[str] = None
    value_inr: Optional[float] = None
    percentage: Optional[float] = None

    _coerce_value = field_validator("value_inr", "percentage", mode="before")(lambda v: _to_float(v))


class PortfolioSummary(_Base):
    total_value_inr: Optional[float] = None
    asset_allocation: List[AssetAllocationRow] = Field(default_factory=list)

    _coerce_total = field_validator("total_value_inr", mode="before")(lambda v: _to_float(v))


class ValueTrendRow(_Base):
    month: Optional[str] = None
    year: Optional[int] = None
    value_inr: Optional[float] = None

    _coerce_value = field_validator("value_inr", mode="before")(lambda v: _to_float(v))


class AccountInfo(_Base):
    type: Optional[str] = None
    broker: Optional[str] = None
    dp_id: Optional[str] = None
    client_id: Optional[str] = None
    value_inr: Optional[float] = None

    _coerce_value = field_validator("value_inr", mode="before")(lambda v: _to_float(v))


class EquityHolding(_Base):
    isin: Optional[str] = None
    stock_symbol: Optional[str] = None
    company_name: Optional[str] = None
    face_value_inr: Optional[float] = None
    num_shares: Optional[float] = None
    pledged_shares: Optional[float] = 0
    market_price_inr: Optional[float] = None
    value_inr: Optional[float] = None

    _coerce = field_validator(
        "face_value_inr", "num_shares", "pledged_shares",
        "market_price_inr", "value_inr",
        mode="before",
    )(lambda v: _to_float(v))


class PreferenceShareHolding(_Base):
    isin: Optional[str] = None
    company_name: Optional[str] = None
    face_value_inr: Optional[float] = None
    num_shares: Optional[float] = None
    market_price_inr: Optional[float] = None
    value_inr: Optional[float] = None
    note: Optional[str] = None

    _coerce = field_validator(
        "face_value_inr", "num_shares", "market_price_inr", "value_inr",
        mode="before",
    )(lambda v: _to_float(v))


class SGBHolding(_Base):
    isin: Optional[str] = None
    series: Optional[str] = None
    issuer: Optional[str] = None
    coupon_rate_pct: Optional[float] = None
    maturity_date: Optional[str] = None
    num_units: Optional[float] = None
    face_value_per_unit_inr: Optional[float] = None
    market_price_per_unit_inr: Optional[float] = None
    value_inr: Optional[float] = None

    _coerce = field_validator(
        "coupon_rate_pct", "num_units", "face_value_per_unit_inr",
        "market_price_per_unit_inr", "value_inr",
        mode="before",
    )(lambda v: _to_float(v))


class MFDematHolding(_Base):
    isin: Optional[str] = None
    fund_name: Optional[str] = None
    num_units: Optional[float] = None
    nav_inr: Optional[float] = None
    value_inr: Optional[float] = None

    _coerce = field_validator(
        "num_units", "nav_inr", "value_inr",
        mode="before",
    )(lambda v: _to_float(v))


class MFFolioHolding(_Base):
    isin: Optional[str] = None
    fund_name: Optional[str] = None
    folio_number: Optional[str] = None
    amc: Optional[str] = None
    num_units: Optional[float] = None
    avg_cost_per_unit_inr: Optional[float] = None
    total_cost_inr: Optional[float] = None
    current_nav_inr: Optional[float] = None
    current_value_inr: Optional[float] = None
    unrealised_pnl_inr: Optional[float] = None
    annualised_return_pct: Optional[float] = None

    _coerce = field_validator(
        "num_units", "avg_cost_per_unit_inr", "total_cost_inr",
        "current_nav_inr", "current_value_inr", "unrealised_pnl_inr",
        "annualised_return_pct",
        mode="before",
    )(lambda v: _to_float(v))


class HoldingsBundle(_Base):
    equities: List[EquityHolding] = Field(default_factory=list)
    preference_shares: List[PreferenceShareHolding] = Field(default_factory=list)
    sovereign_gold_bonds: List[SGBHolding] = Field(default_factory=list)
    mutual_funds_demat: List[MFDematHolding] = Field(default_factory=list)
    mutual_fund_folios: List[MFFolioHolding] = Field(default_factory=list)


class DematTransaction(_Base):
    account_broker: Optional[str] = None
    isin: Optional[str] = None
    security_name: Optional[str] = None
    date: Optional[str] = None
    order_no: Optional[str] = None
    description: Optional[str] = None
    instruction_details: Optional[str] = None
    opening_balance: Optional[float] = None
    debit: Optional[float] = None
    credit: Optional[float] = None
    closing_balance: Optional[float] = None
    category: Optional[str] = None

    _coerce = field_validator(
        "opening_balance", "debit", "credit", "closing_balance",
        mode="before",
    )(lambda v: _to_float(v))


class MFTransaction(_Base):
    isin: Optional[str] = None
    fund_name: Optional[str] = None
    folio_number: Optional[str] = None
    date: Optional[str] = None
    transaction_type: Optional[str] = None
    amount_inr: Optional[float] = None
    stamp_duty_inr: Optional[float] = None
    nav_inr: Optional[float] = None
    price_inr: Optional[float] = None
    units: Optional[float] = None
    opening_balance_units: Optional[float] = None
    closing_balance_units: Optional[float] = None

    _coerce = field_validator(
        "amount_inr", "stamp_duty_inr", "nav_inr", "price_inr",
        "units", "opening_balance_units", "closing_balance_units",
        mode="before",
    )(lambda v: _to_float(v))


class TransactionsBundle(_Base):
    demat_transactions: List[DematTransaction] = Field(default_factory=list)
    mutual_fund_transactions: List[MFTransaction] = Field(default_factory=list)


class CASExtraction(_Base):
    """Top-level extracted-CAS shape. Equivalent to the JSON returned by
    `openai_cas_parser.parse_with_openai_vision` so downstream mappers
    work unchanged."""
    statement_info: Optional[StatementInfo] = None
    investor_info: Optional[InvestorInfo] = None
    portfolio_summary: Optional[PortfolioSummary] = None
    portfolio_value_trend: List[ValueTrendRow] = Field(default_factory=list)
    accounts: List[AccountInfo] = Field(default_factory=list)
    holdings: HoldingsBundle = Field(default_factory=HoldingsBundle)
    transactions: TransactionsBundle = Field(default_factory=TransactionsBundle)

    def total_holding_value(self) -> float:
        """Sum of every holding row's value_inr across all sections.
        Used by the reconciler to compare against portfolio_summary.total_value_inr."""
        s = 0.0
        for row in self.holdings.equities:
            s += row.value_inr or 0
        for row in self.holdings.preference_shares:
            s += row.value_inr or 0
        for row in self.holdings.sovereign_gold_bonds:
            s += row.value_inr or 0
        for row in self.holdings.mutual_funds_demat:
            s += row.value_inr or 0
        for row in self.holdings.mutual_fund_folios:
            s += row.current_value_inr or 0
        return s

    def holding_count(self) -> int:
        return (
            len(self.holdings.equities)
            + len(self.holdings.preference_shares)
            + len(self.holdings.sovereign_gold_bonds)
            + len(self.holdings.mutual_funds_demat)
            + len(self.holdings.mutual_fund_folios)
        )
