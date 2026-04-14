"""Pydantic models with strict validation and enums."""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from enum import Enum


class AssetType(str, Enum):
    EQUITY = "equity"
    MUTUAL_FUND = "mutual_fund"
    ETF = "etf"
    BOND = "bond"
    GOLD = "gold"
    FD = "fd"
    OTHER = "other"


class Relationship(str, Enum):
    SELF = "Self"
    SPOUSE = "Spouse"
    CHILD = "Child"
    PARENT = "Parent"
    SIBLING = "Sibling"
    OTHER = "Other"


class InsightType(str, Enum):
    WARNING = "warning"
    OPPORTUNITY = "opportunity"
    ACTION = "action"
    INFO = "info"


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ── Request Models ──

class PortfolioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    member_name: str = Field(..., min_length=1, max_length=100)
    relationship: Relationship

    @field_validator("name", "member_name")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


class HoldingCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    ticker: Optional[str] = Field(default="", max_length=50)
    asset_type: AssetType
    quantity: float = Field(..., gt=0)
    buy_price: float = Field(..., ge=0)
    current_price: float = Field(..., ge=0)
    sector: Optional[str] = Field(default="Other", max_length=80)
    buy_date: Optional[str] = Field(default="")
    portfolio_id: Optional[str] = Field(default="")

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip()


class HoldingUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    ticker: Optional[str] = Field(default=None, max_length=50)
    asset_type: Optional[AssetType] = None
    quantity: Optional[float] = Field(default=None, gt=0)
    buy_price: Optional[float] = Field(default=None, ge=0)
    current_price: Optional[float] = Field(default=None, ge=0)
    sector: Optional[str] = Field(default=None, max_length=80)
    buy_date: Optional[str] = None


class ChatMessageInput(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


# ── Response / Internal Models ──

class HealthScoreBreakdown(BaseModel):
    diversification: int = Field(ge=0, le=100)
    risk: int = Field(ge=0, le=100)
    cost_efficiency: int = Field(ge=0, le=100)
    performance: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)
    grade: str  # A+, A, B+, B, C, D, F


class RiskAnalysis(BaseModel):
    score: int = Field(ge=0, le=100)
    label: str  # Low, Moderate, High, Very High
    concentration_risk: float
    top_holding_pct: float
    asset_count: int
    sector_count: int
    warnings: List[str]


class Recommendation(BaseModel):
    action: str  # buy, sell, hold, rebalance, switch
    title: str
    description: str
    priority: Priority
    impact: str  # "Save ₹32K/yr", "Reduce risk by 20%"
