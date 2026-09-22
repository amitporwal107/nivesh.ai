"""Date-effective capital-gains tax engine for listed (STT-paid) Indian equity.

Loads rules/tax-equity-v1.json (see that file's `usage_note` and per-record `note` fields for
sourcing and the exact 23-Jul-2024 STCG/LTCG regime switch). Nothing here mixes tax into the
transaction-cost return series: `compute_tax()` takes a `taxable_gain` that engine.py computes
separately, and callers are responsible for keeping Series A (net trading return, pre-tax) and
Series B (after-tax) reported apart, per the PRD.

Taxable gain = sale − acquisition − eligible transfer expenses (Section 48). This module treats
BROKERAGE (both legs) as the eligible transfer/acquisition expense by default, because it is
judicially recognised as "expenditure incurred wholly and exclusively in connection with the
transfer"/cost of acquisition, while STT is expressly EXCLUDED from that deduction by the proviso
to Section 48 -- so the default `eligible_components` set below deliberately omits "stt" (and
"exchange_txn"/"sebi"/"gst"/"stamp", which are not brokerage and whose deductibility this module
does not assert). This is a configurable convention, not a universal rule; callers may pass a
different `eligible_components` set, and every choice is recorded on the returned TaxResult so it
is never a silent assumption.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from research.costs.rule_loader import load_rule_file, resolve_record

PAISA = Decimal("0.01")
DEFAULT_ELIGIBLE_COMPONENTS = ("brokerage",)


def money(x: Decimal) -> Decimal:
    return x.quantize(PAISA, rounding=ROUND_HALF_UP)


class TaxError(ValueError):
    pass


@dataclass(frozen=True)
class TaxResult:
    term: str  # "SHORT" | "LONG"
    taxable_gain: Decimal
    tax_before_cess: Decimal
    surcharge: Decimal
    cess: Decimal
    total_tax: Decimal
    rate_pct: Decimal
    surcharge_pct: Decimal
    cess_pct: Decimal
    tax_rule_version: str
    eligible_components: tuple
    notes: tuple


def classify_term(buy_date: dt.date, sell_date: dt.date, *, rule_set: dict) -> str:
    """LONG only if held for MORE than 12 months (Section 2(42A)): sold after the first anniversary
    of the buy date. Calendar-exact, so a leap year does not turn an exactly-12-month hold into a
    long-term one. `rule_set` is kept for the signature; the 12-month rule is not date-effective."""
    try:
        anniversary = buy_date.replace(year=buy_date.year + 1)
    except ValueError:  # bought on 29 Feb
        anniversary = dt.date(buy_date.year + 1, 3, 1)
    return "LONG" if sell_date > anniversary else "SHORT"


def taxable_gain(sale_value: Decimal, acquisition_value: Decimal, cost_components: dict,
                  eligible_components: tuple = DEFAULT_ELIGIBLE_COMPONENTS) -> Decimal:
    """sale − acquisition − eligible transfer expenses. `cost_components` is the same
    {"brokerage": ..., "stt": ..., ...} breakdown engine.py produces for the round trip (summed
    over both legs); only the keys named in `eligible_components` are deducted."""
    eligible = sum((Decimal(str(cost_components[k])) for k in eligible_components if k in cost_components),
                   Decimal(0))
    return Decimal(str(sale_value)) - Decimal(str(acquisition_value)) - eligible


def compute_tax(gain: Decimal, *, term: str, on_date: dt.date, total_income_inr: Optional[Decimal] = None,
                 ltcg_exemption_available_inr: Decimal = Decimal(0),
                 surcharge_regime: str = "listed_equity_111a_112a",
                 eligible_components: tuple = DEFAULT_ELIGIBLE_COMPONENTS,
                 rule_id: str = "tax-equity-v1") -> TaxResult:
    """Tax on one already-computed `gain` (may be negative -- a loss produces zero tax here; loss
    set-off/carry-forward against OTHER gains is LossLedger's job, not this function's). `on_date`
    resolves the date-effective STCG/LTCG rate.

    The 112A exemption is an ANNUAL allowance shared by all of a taxpayer's long-term gains in the
    financial year, not a per-trade one: this function applies only `ltcg_exemption_available_inr`
    (the caller's unused allowance for that year, capped at the year's threshold), default 0.
    Applying the full threshold to every trade would under-state tax for any strategy with more
    than one long-term trade a year.
    """
    if term not in ("SHORT", "LONG"):
        raise TaxError(f"term must be SHORT or LONG, got {term!r}")
    rs = load_rule_file(rule_id)
    notes = []
    gain = Decimal(str(gain))
    if gain <= 0:
        return TaxResult("SHORT" if term == "SHORT" else "LONG", gain, Decimal(0), Decimal(0), Decimal(0),
                          Decimal(0), Decimal(0), Decimal(0), Decimal(0), rs["version"] and f"{rule_id}@{rs['version']}",
                          tuple(eligible_components), ("gain <= 0: no tax (see LossLedger for set-off/carry-forward)",))
    if term == "SHORT":
        rate_rec = resolve_record(rs["rates"]["stcg_111a"], on_date)
        rate_pct = Decimal(rate_rec.record["pct"])
        taxable = gain
        notes.append(rate_rec.note or "")
    else:
        rate_rec = resolve_record(rs["rates"]["ltcg_112a"], on_date)
        rate_pct = Decimal(rate_rec.record["pct"])
        threshold = Decimal(rate_rec.record["exemption_threshold_inr"])
        exemption = min(max(Decimal(str(ltcg_exemption_available_inr)), Decimal(0)), threshold)
        taxable = max(gain - exemption, Decimal(0))
        notes.append(f"LTCG exemption Rs {exemption} applied (annual threshold Rs {threshold}). {rate_rec.note or ''}")
    tax_before_cess = money(taxable * rate_pct / 100)
    surcharge_pct = Decimal(0)
    if total_income_inr is not None:
        surch = _resolve_surcharge_pct(rs, surcharge_regime, on_date, total_income_inr)
        surcharge_pct = surch
    surcharge_amt = money(tax_before_cess * surcharge_pct / 100)
    cess_rec = resolve_record(rs["cess"], on_date)
    cess_pct = Decimal(cess_rec.record["pct"])
    cess_amt = money((tax_before_cess + surcharge_amt) * cess_pct / 100)
    total = tax_before_cess + surcharge_amt + cess_amt
    return TaxResult(term, gain, tax_before_cess, surcharge_amt, cess_amt, total, rate_pct, surcharge_pct,
                      cess_pct, f"{rule_id}@{rs['version']}", tuple(eligible_components), tuple(notes))


def _resolve_surcharge_pct(rule_set: dict, regime: str, on_date: dt.date, total_income_inr: Decimal) -> Decimal:
    records = rule_set["surcharge"]["records"]
    matches = [r for r in records if r["regime"] == regime and
               (r.get("effective_from") is None or dt.date.fromisoformat(r["effective_from"]) <= on_date) and
               (r.get("effective_to") is None or on_date < dt.date.fromisoformat(r["effective_to"]))]
    if not matches:
        raise TaxError(f"no surcharge record for regime={regime!r} on {on_date}")
    rec = matches[0]
    total_income_inr = Decimal(str(total_income_inr))
    slab_pct = Decimal(0)
    for slab in rec["slabs_inr_total_income"]:
        over = Decimal(slab["over"])
        upto = Decimal(slab["upto"]) if slab["upto"] is not None else None
        if total_income_inr > over and (upto is None or total_income_inr <= upto):
            slab_pct = Decimal(slab["pct"])
    # the cap is a ceiling on the slab rate, not a flat rate for every income
    return min(slab_pct, Decimal(rec["max_pct"])) if "max_pct" in rec else slab_pct


@dataclass
class LossLedger:
    """Explicit, configurable loss set-off / carry-forward assumptions (never a silent default
    baked into compute_tax). Tracks short-term and long-term losses by the assessment year they
    arose, and offers them against later gains per rules/tax-equity-v1.json's
    loss_set_off_and_carry_forward.default_assumptions (overridable at construction)."""

    short_term_can_offset: tuple = ("SHORT", "LONG")
    long_term_can_offset: tuple = ("LONG",)
    carry_forward_years: int = 8
    _short_losses: dict = field(default_factory=dict)   # {assessment_year: Decimal}
    _long_losses: dict = field(default_factory=dict)

    def record_loss(self, assessment_year: int, term: str, amount: Decimal) -> None:
        amount = Decimal(str(amount))
        if amount < 0:
            raise TaxError("record_loss expects a non-negative magnitude")
        book = self._short_losses if term == "SHORT" else self._long_losses
        book[assessment_year] = book.get(assessment_year, Decimal(0)) + amount

    def offset(self, assessment_year: int, term: str, gain: Decimal) -> tuple:
        """Returns (gain_after_offset, amount_offset). Applies the OLDEST eligible loss first (FIFO),
        including losses of the same assessment year, and skips anything older than
        `carry_forward_years`. Trades must be fed in date order; a loss later in the year does not
        reach back to a gain already offset, so a per-year total is only exact if the caller nets
        the whole year first."""
        gain = Decimal(str(gain))
        if gain <= 0:
            return gain, Decimal(0)
        books = []
        if term in self.short_term_can_offset:
            books.append(self._short_losses)
        if term in self.long_term_can_offset:
            books.append(self._long_losses)
        offset_total = Decimal(0)
        for book in books:
            for ay in sorted(book):
                # same-year losses set off first (Sections 70/71); carried-forward ones for 8 years (74)
                if ay > assessment_year or assessment_year - ay > self.carry_forward_years:
                    continue
                avail = book[ay]
                if avail <= 0 or gain <= 0:
                    continue
                take = min(avail, gain)
                book[ay] -= take
                gain -= take
                offset_total += take
        return gain, offset_total
