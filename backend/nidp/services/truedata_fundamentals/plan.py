"""Load planning: offers + the warehouse rows they meet → the exact writes. Pure, so dry-run and the real load share it.

The rules are the supervised load's (2 Nov 2026), unchanged:
  * balance sheet: fill ONLY NULL columns, on every existing row of (symbol, period_end, consolidated) whatever its
    period_type; a fiscal-year balance sheet whose date has NO row at all gets one new row (period_type 'annual',
    source 'truedata'); a half-year balance sheet never creates a row.
  * cash flow (fiscal-year filings only, see transform): a new row when (symbol, period_end, consolidated) has none;
    on an existing row, only NULL columns are filled. Nothing is ever overwritten.
  * finance costs: finance_costs_cr filled where NULL on the matching existing QUARTERLY row; never a new row.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .transform import BS_COLUMNS, CF_COLUMNS, FC_COLUMNS, Offer

QUARTERLY = "nse_financials_quarterly"
CASHFLOW = "nse_financials_cashflow"
Q_COLUMNS = BS_COLUMNS + FC_COLUMNS               # the fillable columns of nse_financials_quarterly
INSERT_SOURCE = "truedata"


@dataclass(frozen=True)
class Row:
    """An existing warehouse row, with the current values of the columns this job may fill."""
    table: str
    symbol: str
    period_end: date
    consolidated: bool
    period_type: str                       # 'annual' for the cash-flow table
    source: Optional[str]
    values: Mapping[str, Optional[Decimal]]


@dataclass
class Action:
    op: str                                # 'fill' | 'insert'
    table: str
    kind: str                              # offer kind
    symbol: str
    period_end: date
    consolidated: bool
    period_type: str
    row_source: Optional[str]
    values: Dict[str, Decimal]             # columns written (fill: only previously NULL ones)
    offer: Offer


@dataclass
class Plan:
    actions: List[Action] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)

    def summary(self) -> Dict[str, Any]:
        c = Counter()
        for a in self.actions:                     # the same keys loader.apply_plan reports after writing
            c[f"{a.kind}_{a.op}_rows"] += 1
            c[f"{a.kind}_columns_written"] += len(a.values)
        return {**dict(sorted(c.items())), **{k: v for k, v in sorted(self.counts.items())}}


def offer_keys(offers: Iterable[Offer]) -> List[Tuple[str, date, bool]]:
    return sorted({(o.symbol, o.period_end, o.consolidated) for o in offers})


def build_plan(offers: Sequence[Offer], q_rows: Iterable[Row], cf_rows: Iterable[Row]) -> Plan:
    plan = Plan()
    q_index: Dict[Tuple[str, date, bool], List[Row]] = defaultdict(list)
    for r in q_rows:
        q_index[(r.symbol, r.period_end, r.consolidated)].append(r)
    cf_index = {(r.symbol, r.period_end, r.consolidated): r for r in cf_rows}

    for o in offers:
        key = (o.symbol, o.period_end, o.consolidated)
        if not o.values:
            plan.counts[f"{o.kind}_no_values"] += 1
            continue
        if o.kind == "balance_sheet":
            rows = q_index.get(key, [])
            if rows:
                for r in sorted(rows, key=lambda r: r.period_type):
                    fills = {c: v for c, v in o.values.items() if c in BS_COLUMNS and r.values.get(c) is None}
                    if fills:
                        plan.actions.append(Action("fill", QUARTERLY, o.kind, o.symbol, o.period_end, o.consolidated,
                                                   r.period_type, r.source, fills, o))
                    else:
                        plan.counts["balance_sheet_row_already_full"] += 1
            elif o.may_insert:
                plan.actions.append(Action("insert", QUARTERLY, o.kind, o.symbol, o.period_end, o.consolidated,
                                           "annual", INSERT_SOURCE,
                                           {c: v for c, v in o.values.items() if c in BS_COLUMNS}, o))
            else:
                plan.counts["balance_sheet_half_year_no_row"] += 1
        elif o.kind == "cash_flow":
            r = cf_index.get(key)
            if r is None:
                plan.actions.append(Action("insert", CASHFLOW, o.kind, o.symbol, o.period_end, o.consolidated,
                                           "annual", INSERT_SOURCE,
                                           {c: v for c, v in o.values.items() if c in CF_COLUMNS}, o))
            else:
                fills = {c: v for c, v in o.values.items() if c in CF_COLUMNS and r.values.get(c) is None}
                if fills:
                    plan.actions.append(Action("fill", CASHFLOW, o.kind, o.symbol, o.period_end, o.consolidated,
                                               "annual", r.source, fills, o))
                else:
                    plan.counts["cash_flow_row_already_full"] += 1
        elif o.kind == "finance_costs":
            rows = [r for r in q_index.get(key, []) if r.period_type == "quarterly"]
            if not rows:
                plan.counts["finance_costs_no_quarterly_row"] += 1
            for r in rows:
                if r.values.get("finance_costs_cr") is None:
                    plan.actions.append(Action("fill", QUARTERLY, o.kind, o.symbol, o.period_end, o.consolidated,
                                               r.period_type, r.source,
                                               {"finance_costs_cr": o.values["finance_costs_cr"]}, o))
                else:
                    plan.counts["finance_costs_already_set"] += 1
        else:
            raise ValueError(f"unknown offer kind {o.kind!r}")
    return plan
