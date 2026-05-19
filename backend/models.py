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
    session_id: Optional[str] = None


class JourneyType(str, Enum):
    EXISTING_INVESTOR = "existing_investor"
    NEW_INVESTOR = "new_investor"
    MFD_ADVISOR = "mfd_advisor"


class JourneyInput(BaseModel):
    journey_type: JourneyType


class RiskProfileAnswer(BaseModel):
    question_id: str
    answer: str


class RiskProfileInput(BaseModel):
    answers: List[RiskProfileAnswer]


class InvestmentGoal(str, Enum):
    RETIREMENT = "retirement"
    HOUSE = "house"
    EDUCATION = "education"
    TRAVEL = "travel"
    WEALTH = "wealth"
    EMERGENCY = "emergency"


class RiskAppetiteLevel(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class InvestmentHorizonLevel(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"
    VERY_LONG = "very_long"


class QuickSetupInput(BaseModel):
    age: int = Field(..., ge=18, le=100)
    goal: InvestmentGoal
    risk_appetite: RiskAppetiteLevel
    investment_horizon: InvestmentHorizonLevel
    monthly_investment: Optional[float] = Field(default=None, ge=0)


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


class PersonaType(str, Enum):
    RETAIL_INVESTOR       = "retail_investor"
    MUTUAL_FUND_INVESTOR  = "mutual_fund_investor"
    STOCK_INVESTOR        = "stock_investor"
    ACTIVE_TRADER         = "active_trader"
    SWING_TRADER          = "swing_trader"
    INTRADAY_TRADER       = "intraday_trader"
    OPTIONS_TRADER        = "options_trader"
    MFD_ADVISOR           = "mfd_advisor"
    HNI_INVESTOR          = "hni_investor"
    RETIREMENT_PLANNER    = "retirement_planner"
    PARENTS_PLANNING      = "parents_planning"
    TAX_SAVER             = "tax_saver"
    CONSERVATIVE_INVESTOR = "conservative_investor"
    BEGINNER_INVESTOR     = "beginner_investor"
    NRI_INVESTOR          = "nri_investor"


class PersonaOverrideInput(BaseModel):
    persona: PersonaType
