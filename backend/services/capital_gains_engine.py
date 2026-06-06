"""Indian Capital Gains Tax Engine — FY 2025-26 (AY 2026-27).

Implements the complete rulebook from the NIDP tax specification:

  Asset classes : listed equity, equity MF, debt MF (pre/post Apr-2023),
                  hybrid MF, gold ETF/MF, SGB (RBI redemption vs. exchange),
                  bonds/debentures, REIT/InvIT, property, unlisted shares.

  Computation order (10 steps per PDF §16):
    1. Gain/loss per transaction
    2. Classify STCG / LTCG
    3. Aggregate by category
    4. Current-year loss set-off (STCL → STCG+LTCG; LTCL → LTCG only)
    5. Brought-forward losses
    6. ₹1,25,000 equity LTCG exemption (shared: listed equity + equity MF + REIT/InvIT)
    7. Category-wise tax
    8. Surcharge
    9. 4% cess
    10. Net payable after TDS / advance tax

  Grandfathering : pre-31-Jan-2018 listed equity & equity MF.
  Surcharge cap  : 15% for special-rate capital gains (Sec 111A / 112A per Budget 2023).

Public API
----------
  compute_capital_gains(transactions, *, slab_rate, brought_forward_losses,
                        total_income_rs, taxes_paid) -> CapitalGainsResult

  classify_asset(asset_type, name, equity_allocation_pct, acquisition_date,
                 redemption_via_rbi) -> AssetCategory

  compute_single_gain(transaction) -> GainRecord

  quick_tax_estimate(holding, *, ltcg_used, slab_rate) -> dict
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Tax constants FY 2025-26 ─────────────────────────────────────────────

EQUITY_LTCG_EXEMPTION      = 125_000        # ₹1,25,000 — shared across equity + REIT
EQUITY_STCG_RATE           = 0.20           # Sec 111A
EQUITY_LTCG_RATE           = 0.125          # Sec 112A
NON_EQUITY_LTCG_RATE       = 0.125          # all other LTCG categories
CESS_RATE                  = 0.04           # 4% health & education cess

GRANDFATHERING_DATE        = date(2018, 1, 31)  # FMV reference for pre-2018 assets
DEBT_MF_SLAB_CUTOVER       = date(2023, 4, 1)   # debt MF acquired on/after → always slab

# ── Indexation (Cost Inflation Index, Sec 48) ────────────────────────────
# Budget 2024 (Finance (No.2) Act 2024) removed indexation for most assets and
# set a flat 12.5% LTCG. The ONE surviving relief: immovable PROPERTY acquired
# before 23-Jul-2024 may be taxed at the LOWER of
#   (a) 12.5% on the unindexed gain, or
#   (b) 20% on the indexed gain (CII benefit) — proviso to Sec 112.
# We implement exactly that option; for all other assets indexation is gone.
INDEXATION_PROPERTY_CUTOFF = date(2024, 7, 23)  # property bought before this → option applies
PROPERTY_INDEXED_LTCG_RATE = 0.20               # 20% when the indexed option is elected

# Official CBDT Cost Inflation Index, base FY 2001-02 = 100. Keyed by FY start
# year (e.g. 2015 == FY 2015-16). Source: incometaxindia.gov.in CII notifications.
_CII: Dict[int, int] = {
    2001: 100, 2002: 105, 2003: 109, 2004: 113, 2005: 117, 2006: 122,
    2007: 129, 2008: 137, 2009: 148, 2010: 167, 2011: 184, 2012: 200,
    2013: 220, 2014: 240, 2015: 254, 2016: 264, 2017: 272, 2018: 280,
    2019: 289, 2020: 301, 2021: 317, 2022: 331, 2023: 348, 2024: 363,
    2025: 376,
}


def _fy_start_year(d: date) -> int:
    """Indian financial year start year for a date (FY runs 1-Apr → 31-Mar)."""
    return d.year if d.month >= 4 else d.year - 1


def cost_inflation_index(d: date) -> int:
    """CII for the FY containing ``d``, clamped to the published range."""
    fy = _fy_start_year(d)
    if fy <= 2001:
        return _CII[2001]
    if fy in _CII:
        return _CII[fy]
    return _CII[max(_CII)]  # sale in an FY not yet notified → latest published


def indexed_cost(cost_basis: float, buy_date: date, sell_date: date) -> float:
    """Indexed acquisition cost = cost × CII(sell FY) / CII(buy FY)."""
    buy_cii = cost_inflation_index(buy_date)
    sell_cii = cost_inflation_index(sell_date)
    if buy_cii <= 0:
        return cost_basis
    return cost_basis * sell_cii / buy_cii

# Holding-period thresholds (days)
_THRESH_12M = 365    # listed equity, equity MF, SGB exchange, REIT/InvIT
_THRESH_24M = 730    # property, gold ETF/MF, unlisted, bonds, debt MF pre-Apr23
# Note: fiscal "12 months" strictly means >365 calendar days per IT Act §2(42A).

# Surcharge brackets (income from special-rate capital gains capped at 15%)
_SURCHARGE_BRACKETS = [
    (50_00_000,   0.00),
    (1_00_00_000, 0.10),
    (2_00_00_000, 0.15),
    (float("inf"), 0.15),   # cap at 15% for equity/REIT special-rate gains
]


# ── Asset categories ─────────────────────────────────────────────────────

class AssetCategory(str, Enum):
    LISTED_EQUITY    = "listed_equity"        # STT-paid, exchange-listed equity
    EQUITY_MF        = "equity_mf"            # domestic equity ≥ 65%
    DEBT_MF_POST23   = "debt_mf_post23"       # acquired on/after 1-Apr-2023 → slab always
    DEBT_MF_PRE23    = "debt_mf_pre23"        # acquired before 1-Apr-2023 → 24-m threshold
    HYBRID_EQUITY    = "hybrid_equity"        # equity allocation ≥ 65% → equity MF rules
    HYBRID_NON_EQUITY= "hybrid_non_equity"    # equity < 65% → slab
    GOLD_ETF         = "gold_etf"             # gold ETF / gold MF → 24-m threshold
    SGB_EXEMPT       = "sgb_exempt"           # SGB redeemed via RBI → FULLY EXEMPT
    SGB_EXCHANGE     = "sgb_exchange"         # SGB sold on exchange → 12-m threshold
    REIT_INVIT       = "reit_invit"           # REIT/InvIT → 12-m, shared exemption
    BOND             = "bond"                 # listed/unlisted bond, debenture → 24-m
    PROPERTY         = "property"             # immovable → 24-m
    UNLISTED_EQUITY  = "unlisted_equity"      # unlisted shares → 24-m
    UNKNOWN          = "unknown"


# ── Dataclasses ──────────────────────────────────────────────────────────

@dataclass
class Transaction:
    """A single realised sale.  Build one per redemption/sale event."""
    asset_category: AssetCategory
    quantity: float
    buy_price: float          # per unit / share
    sell_price: float         # per unit / share
    buy_date: date
    sell_date: date
    transfer_expenses: float = 0.0
    improvement_cost: float  = 0.0
    fmv_31jan2018: Optional[float] = None   # required for grandfathering eligible assets
    name: str = ""
    holding_id: Optional[str] = None


@dataclass
class GainRecord:
    """Computed gain for a single transaction."""
    transaction: Transaction
    holding_days: int
    is_long_term: bool
    cost_basis: float         # after grandfathering if applicable
    sale_proceeds: float
    gross_gain: float         # sale_proceeds − cost_basis − transfer_expenses
    is_grandfathered: bool
    is_exempt: bool           # e.g. SGB via RBI
    tax_category: str         # "equity_stcg" | "equity_ltcg" | "debt_slab" | …
    applicable_rate: Optional[float]  # None if slab, else fixed rate
    note: str = ""
    # Indexation (property option only, per FY25-26 law)
    indexed_cost_basis: Optional[float] = None  # cost × CII(sell)/CII(buy)
    indexed_gain: Optional[float] = None        # sale_proceeds − indexed_cost_basis
    indexation_applied: bool = False            # True → taxed at 20% on indexed_gain

    @property
    def is_gain(self) -> bool:
        return self.gross_gain > 0

    @property
    def is_loss(self) -> bool:
        return self.gross_gain < 0


@dataclass
class BroughtForwardLoss:
    """A prior-year assessed capital loss available for set-off."""
    loss_type: str            # "STCL" | "LTCL"
    amount: float             # positive number (magnitude of loss)
    ay: str                   # assessment year, e.g. "2024-25"


@dataclass
class CapitalGainsResult:
    """Complete FY capital gains computation output."""
    # Raw buckets (before set-off)
    equity_stcg: float = 0.0
    equity_ltcg: float = 0.0
    reit_stcg: float = 0.0
    reit_ltcg: float = 0.0
    debt_slab_gain: float = 0.0       # always slab (debt post-Apr23 + hybrid non-equity)
    debt_ltcg: float = 0.0            # debt pre-Apr23 > 24m
    debt_stcg_slab: float = 0.0      # debt pre-Apr23 ≤ 24m
    gold_stcg_slab: float = 0.0
    gold_ltcg: float = 0.0
    bond_stcg_slab: float = 0.0
    bond_ltcg: float = 0.0
    property_stcg_slab: float = 0.0
    property_ltcg: float = 0.0
    unlisted_stcg_slab: float = 0.0
    unlisted_ltcg: float = 0.0
    property_ltcg_indexed: float = 0.0  # property LTCG where the 20%-indexed option won
    sgb_exempt_gain: float = 0.0

    # Losses (positive magnitudes)
    equity_stcl: float = 0.0
    equity_ltcl: float = 0.0
    other_stcl: float = 0.0
    other_ltcl: float = 0.0

    # After set-off
    net_stcg_special: float = 0.0    # residual STCG at 20% (equity + REIT)
    net_ltcg_equity: float = 0.0     # residual equity LTCG before exemption
    net_ltcg_other: float = 0.0      # residual other LTCG
    net_property_ltcg_indexed: float = 0.0  # residual property LTCG taxed at 20% indexed
    net_slab_gains: float = 0.0      # all slab-rate gains after set-off

    # Exemption
    equity_ltcg_exemption_applied: float = 0.0
    taxable_equity_ltcg: float = 0.0

    # Tax
    stcg_tax: float = 0.0
    ltcg_equity_tax: float = 0.0
    ltcg_other_tax: float = 0.0
    property_ltcg_indexed_tax: float = 0.0   # 20% on indexed property LTCG
    slab_tax: float = 0.0
    base_tax: float = 0.0
    surcharge: float = 0.0
    cess: float = 0.0
    total_tax: float = 0.0
    taxes_paid: float = 0.0
    net_tax_payable: float = 0.0

    # Metadata
    slab_rate_used: float = 0.30
    total_income_rs: float = 0.0
    gain_records: List[GainRecord] = field(default_factory=list)
    bf_losses_applied: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """PDF §24 output structure."""
        return {
            # Raw gains by category
            "equity_stcg": round(self.equity_stcg, 2),
            "equity_ltcg": round(self.equity_ltcg, 2),
            "reit_stcg": round(self.reit_stcg, 2),
            "reit_ltcg": round(self.reit_ltcg, 2),
            "debt_slab_gain": round(self.debt_slab_gain, 2),
            "debt_ltcg": round(self.debt_ltcg, 2),
            "gold_stcg_slab": round(self.gold_stcg_slab, 2),
            "gold_ltcg": round(self.gold_ltcg, 2),
            "bond_stcg_slab": round(self.bond_stcg_slab, 2),
            "bond_ltcg": round(self.bond_ltcg, 2),
            "property_stcg_slab": round(self.property_stcg_slab, 2),
            "property_ltcg": round(self.property_ltcg, 2),
            "unlisted_stcg_slab": round(self.unlisted_stcg_slab, 2),
            "unlisted_ltcg": round(self.unlisted_ltcg, 2),
            "property_ltcg_indexed": round(self.property_ltcg_indexed, 2),
            "sgb_exempt_gain": round(self.sgb_exempt_gain, 2),
            # Losses
            "equity_stcl": round(self.equity_stcl, 2),
            "equity_ltcl": round(self.equity_ltcl, 2),
            # After set-off
            "net_stcg_special_rate": round(self.net_stcg_special, 2),
            "net_ltcg_equity": round(self.net_ltcg_equity, 2),
            "net_ltcg_other": round(self.net_ltcg_other, 2),
            "net_property_ltcg_indexed": round(self.net_property_ltcg_indexed, 2),
            "net_slab_gains": round(self.net_slab_gains, 2),
            # Exemption
            "equity_ltcg_exemption": round(self.equity_ltcg_exemption_applied, 2),
            "taxable_equity_ltcg": round(self.taxable_equity_ltcg, 2),
            # Tax computation
            "stcg_tax": round(self.stcg_tax, 2),
            "ltcg_equity_tax": round(self.ltcg_equity_tax, 2),
            "ltcg_other_tax": round(self.ltcg_other_tax, 2),
            "property_ltcg_indexed_tax": round(self.property_ltcg_indexed_tax, 2),
            "slab_tax": round(self.slab_tax, 2),
            "base_tax": round(self.base_tax, 2),
            "surcharge": round(self.surcharge, 2),
            "cess": round(self.cess, 2),
            "total_tax": round(self.total_tax, 2),
            "taxes_paid": round(self.taxes_paid, 2),
            "net_tax_payable": round(self.net_tax_payable, 2),
            # Meta
            "slab_rate_used": self.slab_rate_used,
            "warnings": self.warnings,
            "bf_losses_applied": self.bf_losses_applied,
        }


# ── Asset classification ──────────────────────────────────────────────────

_DEBT_KEYWORDS = frozenset([
    "liquid", "overnight", "money market", "ultra short", "low duration",
    "short duration", "short term", "medium duration", "long duration",
    "gilt", "dynamic bond", "corporate bond", "banking & psu", "banking psu",
    "credit risk", "floater", "debt", "income fund",
])

_GOLD_KEYWORDS = frozenset(["gold etf", "gold fund", "gold mutual fund"])
_SGB_KEYWORDS  = frozenset(["sovereign gold bond", "sgb"])


def _name_has(name: str, keywords: frozenset) -> bool:
    n = name.lower()
    return any(k in n for k in keywords)


def classify_asset(
    asset_type: str,
    name: str = "",
    equity_allocation_pct: Optional[float] = None,
    acquisition_date: Optional[date] = None,
    redemption_via_rbi: bool = False,
) -> AssetCategory:
    """Classify a holding into one of the 13 asset categories.

    Args:
        asset_type       : e.g. "equity", "mutual_fund", "bond", "property", "reit"
        name             : scheme/instrument name (used for name-based subclassification)
        equity_allocation_pct : declared equity % for hybrid MFs (0-100)
        acquisition_date : date of purchase (needed for debt MF pre/post cutover)
        redemption_via_rbi : True for SGB redeemed directly with RBI (exempt)
    """
    at = (asset_type or "").lower().replace(" ", "_").replace("-", "_")
    n  = (name or "").lower()

    # SGB — must check before generic gold/MF paths
    if _name_has(n, _SGB_KEYWORDS) or at == "sgb":
        return AssetCategory.SGB_EXEMPT if redemption_via_rbi else AssetCategory.SGB_EXCHANGE

    # Listed equity
    if at in ("equity", "stock", "listed_equity"):
        return AssetCategory.LISTED_EQUITY

    # REIT / InvIT
    if at in ("reit", "invit", "reit_invit") or "reit" in n or "invit" in n:
        return AssetCategory.REIT_INVIT

    # Gold ETF / Gold MF (non-SGB)
    if at == "gold" or _name_has(n, _GOLD_KEYWORDS) or ("gold" in n and "etf" in n):
        return AssetCategory.GOLD_ETF

    # Property
    if at in ("property", "real_estate", "immovable"):
        return AssetCategory.PROPERTY

    # Unlisted shares
    if at == "unlisted_equity" or (at == "equity" and "unlisted" in n):
        return AssetCategory.UNLISTED_EQUITY

    # Bonds / Debentures
    if at in ("bond", "bonds", "debenture", "ncd", "fd", "deposit") or \
       "bond" in n or "debenture" in n or "ncd" in n:
        return AssetCategory.BOND

    # Mutual Funds (including ETFs except gold)
    if at in ("mutual_fund", "mf", "etf"):
        # Hybrid: equity allocation given explicitly
        if equity_allocation_pct is not None:
            if equity_allocation_pct >= 65:
                return AssetCategory.HYBRID_EQUITY
            else:
                return AssetCategory.HYBRID_NON_EQUITY

        # Debt fund by name
        if _name_has(n, _DEBT_KEYWORDS):
            acq = acquisition_date or date.today()
            if acq >= DEBT_MF_SLAB_CUTOVER:
                return AssetCategory.DEBT_MF_POST23
            return AssetCategory.DEBT_MF_PRE23

        # Default MF → equity (covers large/mid/small cap, flexi cap, ELSS, etc.)
        return AssetCategory.EQUITY_MF

    return AssetCategory.UNKNOWN


# ── Holding period ────────────────────────────────────────────────────────

def _holding_days(buy_date: date, sell_date: date) -> int:
    return max(0, (sell_date - buy_date).days)


def _is_long_term(days: int, category: AssetCategory) -> bool:
    twelve_month_cats = {
        AssetCategory.LISTED_EQUITY,
        AssetCategory.EQUITY_MF,
        AssetCategory.HYBRID_EQUITY,
        AssetCategory.SGB_EXCHANGE,
        AssetCategory.REIT_INVIT,
    }
    if category in twelve_month_cats:
        return days > _THRESH_12M
    # 24-month categories
    return days > _THRESH_24M


# ── Grandfathering ────────────────────────────────────────────────────────

def _apply_grandfathering(
    buy_price: float,
    sell_price: float,
    buy_date: date,
    fmv_31jan2018: Optional[float],
    category: AssetCategory,
) -> Tuple[float, bool]:
    """Return (deemed_cost_per_unit, was_grandfathered).

    Grandfathering applies only to listed equity + equity MF acquired
    before 31-Jan-2018 where the asset is being sold at a gain as LTCG.
    """
    eligible_cats = {AssetCategory.LISTED_EQUITY, AssetCategory.EQUITY_MF, AssetCategory.HYBRID_EQUITY}
    if category not in eligible_cats:
        return buy_price, False
    if buy_date >= GRANDFATHERING_DATE:
        return buy_price, False
    if fmv_31jan2018 is None:
        return buy_price, False   # no FMV provided — skip grandfathering

    # Deemed cost = max(actual cost, min(FMV, sale price))
    deemed_cost = max(buy_price, min(fmv_31jan2018, sell_price))
    return deemed_cost, (deemed_cost != buy_price)


# ── Single-transaction gain ───────────────────────────────────────────────

def compute_single_gain(txn: Transaction) -> GainRecord:
    """Step 1: compute gain/loss for one transaction."""
    days = _holding_days(txn.buy_date, txn.sell_date)
    is_lt = _is_long_term(days, txn.asset_category)

    sale_proceeds = txn.quantity * txn.sell_price - txn.transfer_expenses

    # SGB via RBI — fully exempt
    if txn.asset_category == AssetCategory.SGB_EXEMPT:
        return GainRecord(
            transaction=txn,
            holding_days=days,
            is_long_term=True,
            cost_basis=txn.quantity * txn.buy_price,
            sale_proceeds=sale_proceeds,
            gross_gain=sale_proceeds - txn.quantity * txn.buy_price - txn.improvement_cost,
            is_grandfathered=False,
            is_exempt=True,
            tax_category="sgb_exempt",
            applicable_rate=0.0,
            note="SGB RBI redemption — capital gain fully exempt for individual investors",
        )

    # Grandfathering check (LTCG only)
    if is_lt:
        deemed_cost_pu, grandfathered = _apply_grandfathering(
            txn.buy_price, txn.sell_price, txn.buy_date,
            txn.fmv_31jan2018, txn.asset_category,
        )
    else:
        deemed_cost_pu, grandfathered = txn.buy_price, False

    cost_basis = txn.quantity * deemed_cost_pu + txn.improvement_cost
    gross_gain = sale_proceeds - cost_basis

    # Debt MF post-Apr23: ALWAYS slab regardless of holding period
    if txn.asset_category == AssetCategory.DEBT_MF_POST23:
        return GainRecord(
            transaction=txn, holding_days=days, is_long_term=False,
            cost_basis=cost_basis, sale_proceeds=sale_proceeds, gross_gain=gross_gain,
            is_grandfathered=False, is_exempt=False,
            tax_category="debt_slab",
            applicable_rate=None,   # slab rate — variable per user
            note="Debt MF acquired on/after 1-Apr-2023 — always taxed at slab rate",
        )

    # Hybrid non-equity: slab
    if txn.asset_category == AssetCategory.HYBRID_NON_EQUITY:
        return GainRecord(
            transaction=txn, holding_days=days, is_long_term=is_lt,
            cost_basis=cost_basis, sale_proceeds=sale_proceeds, gross_gain=gross_gain,
            is_grandfathered=False, is_exempt=False,
            tax_category="debt_slab",  # treated like non-equity
            applicable_rate=None,
            note="Hybrid MF (equity <65%) — taxed at slab rate",
        )

    # Determine tax category
    if txn.asset_category in (AssetCategory.LISTED_EQUITY, AssetCategory.EQUITY_MF, AssetCategory.HYBRID_EQUITY):
        tax_cat = "equity_ltcg" if is_lt else "equity_stcg"
        rate    = EQUITY_LTCG_RATE if is_lt else EQUITY_STCG_RATE
    elif txn.asset_category == AssetCategory.REIT_INVIT:
        tax_cat = "reit_ltcg" if is_lt else "reit_stcg"
        rate    = NON_EQUITY_LTCG_RATE if is_lt else EQUITY_STCG_RATE
    elif txn.asset_category == AssetCategory.SGB_EXCHANGE:
        tax_cat = "sgb_ltcg" if is_lt else "sgb_stcg_slab"
        rate    = NON_EQUITY_LTCG_RATE if is_lt else None
    elif txn.asset_category == AssetCategory.GOLD_ETF:
        tax_cat = "gold_ltcg" if is_lt else "gold_stcg_slab"
        rate    = NON_EQUITY_LTCG_RATE if is_lt else None
    elif txn.asset_category == AssetCategory.DEBT_MF_PRE23:
        tax_cat = "debt_ltcg" if is_lt else "debt_stcg_slab"
        rate    = NON_EQUITY_LTCG_RATE if is_lt else None
    elif txn.asset_category == AssetCategory.BOND:
        tax_cat = "bond_ltcg" if is_lt else "bond_stcg_slab"
        rate    = NON_EQUITY_LTCG_RATE if is_lt else None
    elif txn.asset_category == AssetCategory.PROPERTY:
        tax_cat = "property_ltcg" if is_lt else "property_stcg_slab"
        rate    = NON_EQUITY_LTCG_RATE if is_lt else None
        # Indexation option (proviso to Sec 112): property acquired before
        # 23-Jul-2024 and sold long-term at a gain may elect the LOWER of
        # 12.5% unindexed vs 20% indexed. Elect per-transaction.
        if is_lt and gross_gain > 0 and txn.buy_date < INDEXATION_PROPERTY_CUTOFF:
            idx_cost = indexed_cost(cost_basis, txn.buy_date, txn.sell_date)
            idx_gain = max(0.0, sale_proceeds - idx_cost)
            tax_unindexed = gross_gain * NON_EQUITY_LTCG_RATE       # 12.5%
            tax_indexed   = idx_gain * PROPERTY_INDEXED_LTCG_RATE   # 20%
            if tax_indexed < tax_unindexed:
                return GainRecord(
                    transaction=txn, holding_days=days, is_long_term=True,
                    cost_basis=cost_basis, sale_proceeds=sale_proceeds,
                    gross_gain=idx_gain,  # taxed amount is the indexed gain
                    is_grandfathered=False, is_exempt=False,
                    tax_category="property_ltcg_indexed",
                    applicable_rate=PROPERTY_INDEXED_LTCG_RATE,
                    note=(f"property indexed option elected — 20% on indexed gain "
                          f"₹{idx_gain:,.0f} (indexed cost ₹{idx_cost:,.0f}) beats "
                          f"12.5% on unindexed ₹{gross_gain:,.0f}"),
                    indexed_cost_basis=idx_cost, indexed_gain=idx_gain,
                    indexation_applied=True,
                )
            # else: 12.5% unindexed wins — fall through, but record the comparison.
            gran_note_idx = (f" (12.5% unindexed beats 20%-indexed; indexed cost "
                             f"₹{idx_cost:,.0f})")
            return GainRecord(
                transaction=txn, holding_days=days, is_long_term=True,
                cost_basis=cost_basis, sale_proceeds=sale_proceeds, gross_gain=gross_gain,
                is_grandfathered=False, is_exempt=False,
                tax_category="property_ltcg", applicable_rate=NON_EQUITY_LTCG_RATE,
                note=gran_note_idx,
                indexed_cost_basis=idx_cost, indexed_gain=idx_gain,
                indexation_applied=False,
            )
    elif txn.asset_category == AssetCategory.UNLISTED_EQUITY:
        tax_cat = "unlisted_ltcg" if is_lt else "unlisted_stcg_slab"
        rate    = NON_EQUITY_LTCG_RATE if is_lt else None
    else:
        tax_cat = "unknown_slab"
        rate    = None

    gran_note = " (grandfathered — FMV 31-Jan-2018 used as cost)" if grandfathered else ""
    return GainRecord(
        transaction=txn, holding_days=days, is_long_term=is_lt,
        cost_basis=cost_basis, sale_proceeds=sale_proceeds, gross_gain=gross_gain,
        is_grandfathered=grandfathered, is_exempt=False,
        tax_category=tax_cat, applicable_rate=rate,
        note=gran_note,
    )


# ── Surcharge ─────────────────────────────────────────────────────────────

def _compute_surcharge(base_tax: float, total_income_rs: float) -> float:
    """Surcharge on special-rate capital gains income capped at 15%
    per Finance Act 2023 (Sec 111A / 112A surcharge cap).
    """
    if base_tax <= 0:
        return 0.0
    for threshold, rate in _SURCHARGE_BRACKETS:
        if total_income_rs <= threshold:
            return base_tax * rate
    return base_tax * 0.15  # fallback cap


# ── Main computation ──────────────────────────────────────────────────────

def compute_capital_gains(
    transactions: List[Transaction],
    *,
    slab_rate: float = 0.30,
    brought_forward_losses: Optional[List[BroughtForwardLoss]] = None,
    total_income_rs: float = 0.0,
    taxes_paid: float = 0.0,
    ltcg_exemption_override: Optional[float] = None,
) -> CapitalGainsResult:
    """Compute full capital gains liability for a financial year.

    Args:
        transactions         : all realised sales during the FY
        slab_rate            : marginal income tax slab (0.05 / 0.20 / 0.30)
        brought_forward_losses : assessed losses from prior years
        total_income_rs      : total income (used for surcharge bracket)
        taxes_paid           : TDS + advance tax + self-assessment tax already paid
        ltcg_exemption_override : override the ₹1,25,000 exemption (e.g. partially used)

    Returns: CapitalGainsResult (call .to_dict() for the PDF JSON output)
    """
    result = CapitalGainsResult(slab_rate_used=slab_rate, total_income_rs=total_income_rs)
    bf_losses = brought_forward_losses or []

    # ── Step 1+2: Compute per-transaction gain and classify ──────────────
    gain_records: List[GainRecord] = []
    for txn in transactions:
        gr = compute_single_gain(txn)
        gain_records.append(gr)
        if gr.is_exempt:
            result.sgb_exempt_gain += gr.gross_gain
            continue
        _bucket_gain(result, gr, slab_rate)

    result.gain_records = gain_records

    # ── Step 3: Aggregate — already done in _bucket_gain ────────────────

    # ── Step 4+5: Loss set-off ───────────────────────────────────────────
    # Current-year losses are already separated in result.equity_stcl etc.
    # Aggregate current-year losses first.
    total_stcl = result.equity_stcl + result.other_stcl
    total_ltcl = result.equity_ltcl + result.other_ltcl

    # Aggregate gains for set-off
    stcg_special = result.equity_stcg + result.reit_stcg   # taxed at 20%
    ltcg_equity  = result.equity_ltcg + result.reit_ltcg   # taxed at 12.5% + exemption
    ltcg_other   = (result.debt_ltcg + result.gold_ltcg +
                    result.bond_ltcg + result.property_ltcg +
                    result.unlisted_ltcg + result.debt_stcg_slab)  # 12.5% fixed
    ltcg_prop_indexed = result.property_ltcg_indexed               # 20% on indexed gain
    slab_gains   = (result.debt_slab_gain + result.gold_stcg_slab +
                    result.bond_stcg_slab + result.property_stcg_slab +
                    result.unlisted_stcg_slab)

    # STCL offsets STCG first, then LTCG (per IT Act). Within LTCG we offset
    # the highest-rate pools first (equity-special then 20%-indexed property
    # then 12.5% other) — that minimises tax, which the taxpayer may elect.
    stcl_rem = total_stcl
    if stcl_rem > 0:
        stcg_adj = min(stcl_rem, stcg_special)
        stcg_special -= stcg_adj
        stcl_rem     -= stcg_adj
    for _pool_name in ("equity", "prop_indexed", "other"):
        if stcl_rem <= 0:
            break
        if _pool_name == "equity":
            take = min(stcl_rem, ltcg_equity); ltcg_equity -= take
        elif _pool_name == "prop_indexed":
            take = min(stcl_rem, ltcg_prop_indexed); ltcg_prop_indexed -= take
        else:
            take = min(stcl_rem, ltcg_other); ltcg_other -= take
        stcl_rem -= take

    # LTCL offsets only LTCG (same highest-rate-first ordering).
    ltcl_rem = total_ltcl
    for _pool_name in ("equity", "prop_indexed", "other"):
        if ltcl_rem <= 0:
            break
        if _pool_name == "equity":
            take = min(ltcl_rem, ltcg_equity); ltcg_equity -= take
        elif _pool_name == "prop_indexed":
            take = min(ltcl_rem, ltcg_prop_indexed); ltcg_prop_indexed -= take
        else:
            take = min(ltcl_rem, ltcg_other); ltcg_other -= take
        ltcl_rem -= take

    # Brought-forward losses (Steps 4+5 — prior AY losses, same priority rules)
    bf_applied: List[Dict[str, Any]] = []
    for bfl in bf_losses:
        remaining_bfl = bfl.amount
        applied = 0.0
        if bfl.loss_type == "STCL":
            adj = min(remaining_bfl, stcg_special + ltcg_equity + ltcg_prop_indexed + ltcg_other)
            stcg_adj = min(adj, stcg_special)
            stcg_special -= stcg_adj
            adj -= stcg_adj
            if adj > 0:
                ltcg_eq_adj = min(adj, ltcg_equity)
                ltcg_equity -= ltcg_eq_adj
                adj -= ltcg_eq_adj
            if adj > 0:
                pi_adj = min(adj, ltcg_prop_indexed)
                ltcg_prop_indexed -= pi_adj
                adj -= pi_adj
            if adj > 0:
                ltcg_oth_adj = min(adj, ltcg_other)
                ltcg_other  -= ltcg_oth_adj
                adj -= ltcg_oth_adj
            applied = bfl.amount - remaining_bfl + (bfl.amount - adj)
        elif bfl.loss_type == "LTCL":
            adj = min(remaining_bfl, ltcg_equity + ltcg_prop_indexed + ltcg_other)
            ltcg_eq_adj = min(adj, ltcg_equity)
            ltcg_equity -= ltcg_eq_adj
            adj -= ltcg_eq_adj
            if adj > 0:
                pi_adj = min(adj, ltcg_prop_indexed)
                ltcg_prop_indexed -= pi_adj
                adj -= pi_adj
            if adj > 0:
                ltcg_oth_adj = min(adj, ltcg_other)
                ltcg_other  -= ltcg_oth_adj
            applied = bfl.amount - max(0, remaining_bfl - bfl.amount + adj)
        if applied > 0:
            bf_applied.append({"ay": bfl.ay, "type": bfl.loss_type, "applied": round(applied, 2)})

    result.bf_losses_applied = bf_applied

    # ── Step 6: Equity LTCG exemption ───────────────────────────────────
    exemption_limit = ltcg_exemption_override if ltcg_exemption_override is not None else EQUITY_LTCG_EXEMPTION
    exemption_applied  = min(exemption_limit, max(0, ltcg_equity))
    taxable_equity_ltcg = max(0, ltcg_equity - exemption_applied)

    result.net_stcg_special  = max(0, stcg_special)
    result.net_ltcg_equity   = max(0, ltcg_equity)
    result.net_ltcg_other    = max(0, ltcg_other)
    result.net_property_ltcg_indexed = max(0, ltcg_prop_indexed)
    result.net_slab_gains    = max(0, slab_gains)
    result.equity_ltcg_exemption_applied = exemption_applied
    result.taxable_equity_ltcg = taxable_equity_ltcg

    # ── Step 7: Category-wise tax ────────────────────────────────────────
    stcg_tax       = result.net_stcg_special * EQUITY_STCG_RATE
    ltcg_eq_tax    = taxable_equity_ltcg * EQUITY_LTCG_RATE
    ltcg_other_tax = result.net_ltcg_other * NON_EQUITY_LTCG_RATE
    prop_idx_tax   = result.net_property_ltcg_indexed * PROPERTY_INDEXED_LTCG_RATE
    slab_tax       = result.net_slab_gains * slab_rate

    base_tax = stcg_tax + ltcg_eq_tax + ltcg_other_tax + prop_idx_tax + slab_tax

    result.stcg_tax       = round(stcg_tax, 2)
    result.ltcg_equity_tax = round(ltcg_eq_tax, 2)
    result.ltcg_other_tax  = round(ltcg_other_tax, 2)
    result.property_ltcg_indexed_tax = round(prop_idx_tax, 2)
    result.slab_tax        = round(slab_tax, 2)
    result.base_tax        = round(base_tax, 2)

    # ── Step 8: Surcharge ─────────────────────────────────────────────
    surcharge = _compute_surcharge(base_tax, total_income_rs)
    result.surcharge = round(surcharge, 2)

    # ── Step 9: Cess ─────────────────────────────────────────────────
    cess = (base_tax + surcharge) * CESS_RATE
    result.cess = round(cess, 2)

    # ── Step 10: Net payable ──────────────────────────────────────────
    total_tax = base_tax + surcharge + cess
    result.total_tax       = round(total_tax, 2)
    result.taxes_paid      = round(taxes_paid, 2)
    result.net_tax_payable = round(max(0, total_tax - taxes_paid), 2)

    return result


def _bucket_gain(result: CapitalGainsResult, gr: GainRecord, slab_rate: float) -> None:
    """Accumulate a GainRecord into the appropriate result bucket."""
    g = gr.gross_gain
    tc = gr.tax_category

    if tc == "equity_stcg":
        if g >= 0: result.equity_stcg += g
        else:      result.equity_stcl += abs(g)
    elif tc == "equity_ltcg":
        if g >= 0: result.equity_ltcg += g
        else:      result.equity_ltcl += abs(g)
    elif tc == "reit_stcg":
        if g >= 0: result.reit_stcg += g
        else:      result.equity_stcl += abs(g)   # REIT STCL same priority as equity STCL
    elif tc == "reit_ltcg":
        if g >= 0: result.reit_ltcg += g
        else:      result.equity_ltcl += abs(g)
    elif tc == "debt_slab":
        if g >= 0: result.debt_slab_gain += g
        else:      result.other_stcl += abs(g)
    elif tc == "debt_ltcg":
        if g >= 0: result.debt_ltcg += g
        else:      result.other_ltcl += abs(g)
    elif tc == "debt_stcg_slab":
        if g >= 0: result.debt_stcg_slab += g
        else:      result.other_stcl += abs(g)
    elif tc == "gold_ltcg":
        if g >= 0: result.gold_ltcg += g
        else:      result.other_ltcl += abs(g)
    elif tc in ("gold_stcg_slab", "sgb_stcg_slab"):
        if g >= 0: result.gold_stcg_slab += g
        else:      result.other_stcl += abs(g)
    elif tc == "sgb_ltcg":
        if g >= 0: result.gold_ltcg += g          # SGB exchange LTCG → same bucket as gold LTCG
        else:      result.other_ltcl += abs(g)
    elif tc == "bond_ltcg":
        if g >= 0: result.bond_ltcg += g
        else:      result.other_ltcl += abs(g)
    elif tc == "bond_stcg_slab":
        if g >= 0: result.bond_stcg_slab += g
        else:      result.other_stcl += abs(g)
    elif tc == "property_ltcg":
        if g >= 0: result.property_ltcg += g
        else:      result.other_ltcl += abs(g)
    elif tc == "property_ltcg_indexed":
        # Only ever bucketed for gains (the option is elected only when gain > 0).
        if g >= 0: result.property_ltcg_indexed += g
        else:      result.other_ltcl += abs(g)
    elif tc == "property_stcg_slab":
        if g >= 0: result.property_stcg_slab += g
        else:      result.other_stcl += abs(g)
    elif tc == "unlisted_ltcg":
        if g >= 0: result.unlisted_ltcg += g
        else:      result.other_ltcl += abs(g)
    elif tc == "unlisted_stcg_slab":
        if g >= 0: result.unlisted_stcg_slab += g
        else:      result.other_stcl += abs(g)
    else:   # unknown_slab / fallback
        if g >= 0: result.debt_slab_gain += g
        else:      result.other_stcl += abs(g)
        result.warnings.append(f"Unknown tax_category '{tc}' for {gr.transaction.name!r} — treated as slab")


# ── Convenience wrapper (per-holding quick estimate) ─────────────────────

def quick_tax_estimate(
    holding: Dict[str, Any],
    *,
    ltcg_used: float = 0.0,
    slab_rate: float = 0.30,
    exit_fraction: float = 1.0,
) -> Dict[str, Any]:
    """Convenience wrapper for a single holding.

    Accepts the same dict shape as `services.tax_calculator.calculate_tax_impact()`
    but uses the complete 2025-26 rulebook and returns both the simple per-holding
    estimate AND the full CapitalGainsResult for drill-down.

    Used by the Copilot tax harvest tool and the Action Engine.

    Args:
        holding       : dict with buy_date, buy_price, current_price, quantity,
                        asset_type, name, [equity_allocation_pct, fmv_31jan2018]
        ltcg_used     : ₹ of equity LTCG exemption already consumed in this FY
        slab_rate     : marginal tax slab (0.05 / 0.20 / 0.30)
        exit_fraction : 0-1 fraction of holding to exit (default 1 = full exit)
    """
    try:
        bp  = float(holding.get("buy_price") or 0)
        cp  = float(holding.get("current_price") or 0)
        qty = float(holding.get("quantity") or 0) * exit_fraction
        bd_raw  = holding.get("buy_date") or holding.get("purchase_date")
        name    = holding.get("name") or holding.get("scheme_name") or ""
        atype   = holding.get("asset_type") or ""
        eq_alloc = holding.get("equity_allocation_pct")
        fmv     = holding.get("fmv_31jan2018")

        if bp <= 0 or cp <= 0 or qty <= 0 or not bd_raw:
            return {
                "ok": False,
                "reason": "missing_buy_price_or_date",
                "capital_gain": 0.0,
                "tax_liability": 0.0,
                "tax_impact_pending": True,
            }

        # Parse buy_date
        if isinstance(bd_raw, str):
            bd = datetime.fromisoformat(bd_raw.replace("Z", "+00:00")).date()
        elif isinstance(bd_raw, datetime):
            bd = bd_raw.date()
        elif isinstance(bd_raw, date):
            bd = bd_raw
        else:
            return {"ok": False, "reason": "unparseable_buy_date", "tax_impact_pending": True}

        sell_date = date.today()
        category  = classify_asset(
            atype, name,
            equity_allocation_pct=eq_alloc,
            acquisition_date=bd,
            redemption_via_rbi=holding.get("redemption_via_rbi", False),
        )

        txn = Transaction(
            asset_category=category,
            quantity=qty,
            buy_price=bp,
            sell_price=cp,
            buy_date=bd,
            sell_date=sell_date,
            transfer_expenses=float(holding.get("transfer_expenses") or 0),
            improvement_cost=float(holding.get("improvement_cost") or 0),
            fmv_31jan2018=float(fmv) if fmv is not None else None,
            name=name,
        )
        gr = compute_single_gain(txn)

        # Build minimal single-txn result (skip full portfolio computation)
        capital_gain  = gr.gross_gain
        is_lt         = gr.is_long_term

        if gr.is_exempt:
            return {
                "ok": True,
                "asset_category": category.value,
                "holding_days": gr.holding_days,
                "is_long_term": True,
                "capital_gain": round(capital_gain, 2),
                "taxable_gain": 0.0,
                "tax_liability": 0.0,
                "tax_rate": 0.0,
                "tax_regime": "sgb_rbi_exempt",
                "post_tax_proceeds": round(cp * qty, 2),
                "tax_impact_pending": False,
                "note": gr.note,
            }

        if capital_gain <= 0:
            return {
                "ok": True,
                "asset_category": category.value,
                "holding_days": gr.holding_days,
                "is_long_term": is_lt,
                "capital_gain": round(capital_gain, 2),
                "taxable_gain": 0.0,
                "tax_liability": 0.0,
                "tax_rate": 0.0,
                "tax_regime": gr.tax_category,
                "post_tax_proceeds": round(cp * qty, 2),
                "tax_impact_pending": False,
                "note": "Loss on exit — no tax; can offset other gains",
            }

        # Compute tax
        rate = gr.applicable_rate
        if rate is None:
            rate = slab_rate

        if gr.tax_category in ("equity_ltcg", "reit_ltcg"):
            available_exemption = max(0.0, EQUITY_LTCG_EXEMPTION - ltcg_used)
            taxable_gain = max(0.0, capital_gain - available_exemption)
        else:
            taxable_gain = capital_gain

        base_tax  = taxable_gain * rate
        surcharge = _compute_surcharge(base_tax, float(holding.get("total_income_rs") or 0))
        cess      = (base_tax + surcharge) * CESS_RATE
        total_tax = base_tax + surcharge + cess

        return {
            "ok": True,
            "asset_category": category.value,
            "holding_days": gr.holding_days,
            "is_long_term": is_lt,
            "capital_gain": round(capital_gain, 2),
            "taxable_gain": round(taxable_gain, 2),
            "tax_liability": round(total_tax, 2),
            "base_tax": round(base_tax, 2),
            "surcharge": round(surcharge, 2),
            "cess": round(cess, 2),
            "tax_rate": round(rate, 4),
            "tax_regime": gr.tax_category,
            "post_tax_proceeds": round(cp * qty - total_tax, 2),
            "exit_amount_rs": round(cp * qty, 2),
            "is_grandfathered": gr.is_grandfathered,
            "tax_impact_pending": False,
            "note": gr.note,
        }

    except Exception as exc:
        logger.exception("quick_tax_estimate failed for %r: %s", holding.get("name"), exc)
        return {"ok": False, "reason": str(exc), "tax_impact_pending": True}
