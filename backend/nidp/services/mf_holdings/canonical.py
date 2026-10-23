"""Canonical fund identity for MF holdings — the Python mirror of migration 182.

WHY THIS EXISTS IN PYTHON AT ALL
The canonical layer itself is SQL (nidp.v_mf_holdings_canonical): the dedupe has to happen where
the 1.7M rows live. But the rule it encodes — "a holding stored once per plan/option variant is
ONE holding" — is the thing that must never silently regress, and a rule that can only be checked
by querying the warehouse cannot be checked in CI. So the same rule is implemented here, over
plain rows, and `backend/nidp/tests/services/test_mf_holdings_reconciliation.py` runs it against
a committed extract of real staging rows.

The two implementations are kept honest by construction: the regexes below are the same patterns,
in the same order, as the ones in migration 182, and the migration's own numbers (duplication
factor 4.09x, 99.906% single-quantity groups, Nifty 500 coverage median 0.56) are asserted here
against the fixture. If someone edits one side only, the test's duplication factor or coverage
band moves and the test fails.

WHAT THE RULE IS
  base scheme  the scheme name with the plan suffix (`- Direct/Regular Plan - ...`) and then the
               option suffix (`- Growth`, `- Monthly IDCW Option`, ...) removed, lower-cased,
               whitespace-squeezed. Case matters: the same fund appears in the feed as both
               'ADITYA BIRLA SUN LIFE ARBITRAGE FUND - ...' and 'Aditya Birla Sun Life ...'.
  amc          nidp.mf_scheme_master.amc_id where known, else derived from the `source` (one
               source = one AMC). QUANT_MF_PORTFOLIO_XLSX keys rows by scheme NAME, so without
               that fallback quant's book is counted twice.
  leg          an expiry-named row ('ICICI Bank Ltd.-OCT2026'), a written option
               ('... (CALL Option)') or a negative quantity is a DERIVATIVE leg. A short future
               is not share ownership and must not be netted against the cash leg: it is
               excluded from the count and reported separately.
  shares       the largest positive quantity among the group's equity-cash rows — never their
               sum. Variants are copies; the sum is the defect.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

# ── the canonical-name rule (same patterns, same order, as migration 182) ───────────────────
# Stage 1: from a dash-delimited plan marker to the end. The marker must be followed by the end
# of the string or another dash, so a fund whose NAME contains 'Regular'/'Direct' is not cut
# mid-name.
_PLAN_SUFFIX = re.compile(r"\s*[-–]\s*(direct|regular)(\s*plan)?\s*([-–].*)?$", re.I)
# Stage 2: a trailing dash-delimited option, applied three times (names stack up to three).
_OPTION_SUFFIX = re.compile(
    r"\s*[-–]\s*"
    r"((daily|weekly|fortnightly|monthly|quarterly|half[\s-]*yearly|annual|adhoc)\s*)?"
    r"(growth|idcw|dividend|bonus|payout|re-?investment|appreciation|cumulative)"
    r"([^-–]*)?$",
    re.I,
)
_OPTION_PASSES = 3
_WS = re.compile(r"\s+")

# ── the leg rule ────────────────────────────────────────────────────────────────────────────
_EXPIRY_SUFFIX = re.compile(
    r"[-–]\s*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s*[-/ ]?\d{2,4}\s*$",
    re.I,
)
_WRITTEN_OPTION = re.compile(r"\((CALL|PUT)\s*OPTION\)", re.I)

LEG_EQUITY = "equity_cash"
LEG_DERIVATIVE = "derivative"
LEG_NO_QUANTITY = "no_quantity"


def base_scheme_name(scheme_name: str) -> str:
    """The plan/option-free, case-folded fund name used as the canonical key."""
    s = _PLAN_SUFFIX.sub("", scheme_name or "")
    for _ in range(_OPTION_PASSES):
        s = _OPTION_SUFFIX.sub("", s)
    return _WS.sub(" ", s).strip().lower()


def leg_class(security_name: str, quantity: Optional[float]) -> str:
    """Which instrument leg a holdings row describes. See the module docstring."""
    if quantity is None:
        return LEG_NO_QUANTITY
    name = security_name or ""
    if _EXPIRY_SUFFIX.search(name) or _WRITTEN_OPTION.search(name):
        return LEG_DERIVATIVE
    if quantity < 0:
        return LEG_DERIVATIVE
    return LEG_EQUITY


def source_amc_map(rows: Iterable[Mapping]) -> dict:
    """source -> amc_id, derived from the rows whose scheme_code resolved to the master.

    Same derivation as nidp.v_mf_holdings_source_amc: a source is one adapter against one AMC,
    so the amc_id of its resolvable rows is the amc_id of its unresolvable ones. Raises if a
    source carries two houses, because then the fallback would attribute holdings to the wrong
    fund family rather than fail loudly.
    """
    seen = defaultdict(set)
    for r in rows:
        amc = (r.get("amc_id") or "").strip()
        if amc:
            seen[r["source"]].add(amc)
    out = {}
    for src, amcs in seen.items():
        if len(amcs) > 1:
            raise ValueError(f"source {src!r} maps to several amc_ids: {sorted(amcs)}")
        out[src] = next(iter(amcs))
    return out


@dataclass
class CanonicalHolding:
    """One fund's holding of one security in one reporting month."""

    amc_id: str
    base_scheme: str
    security_isin: str
    shares: float
    variant_rows: int = 0
    qty_variants: int = 0
    naive_sum_quantity: float = 0.0
    derivative_rows: int = 0
    derivative_net_quantity: float = 0.0
    variant_scheme_codes: list = field(default_factory=list)
    sources: list = field(default_factory=list)

    @property
    def canonical_fund_key(self) -> str:
        return f"{self.amc_id}|{self.base_scheme}"


def canonical_holdings(rows: Sequence[Mapping],
                       source_amc: Optional[Mapping] = None) -> list:
    """Collapse holdings rows to one row per (amc_id, base_scheme, security_isin).

    `rows` are dicts with scheme_code, source, scheme_name (may be None), amc_id (may be None),
    security_isin, security_name, quantity — i.e. nidp.mf_holdings_monthly joined to
    nidp.mf_scheme_master, for ONE as_of_month.

    `source_amc` is the source -> amc_id map. Pass it whenever `rows` is a SUBSET of the table:
    the map is a warehouse-wide fact (nidp.v_mf_holdings_source_amc) and cannot be derived from a
    few stocks' rows. Getting this wrong does not fail loudly, it silently splits one AMC in two
    and un-does part of the dedupe — a 15-stock extract of 2026-09 carries no resolvable
    QUANT_MF_PORTFOLIO_XLSX scheme code, so deriving the map from it counted quant twice
    (+18 funds, +16.5m shares on ADANIENT alone).
    """
    src_amc = dict(source_amc) if source_amc is not None else source_amc_map(rows)
    groups: dict = {}
    for r in rows:
        isin = (r.get("security_isin") or "").strip()
        if not isin:
            continue                      # cannot be attributed to an instrument (§26.2)
        amc = (r.get("amc_id") or "").strip() or src_amc.get(r["source"]) \
            or f"unmapped_source:{r['source']}"
        base = base_scheme_name(r.get("scheme_name") or r["scheme_code"])
        key = (amc, base, isin)
        g = groups.get(key)
        if g is None:
            g = groups[key] = CanonicalHolding(amc, base, isin, shares=0.0)
        qty = r.get("quantity")
        leg = leg_class(r.get("security_name"), qty)
        if leg == LEG_DERIVATIVE:
            g.derivative_rows += 1
            g.derivative_net_quantity += float(qty)
            continue
        if leg == LEG_NO_QUANTITY:
            continue
        qty = float(qty)
        g.variant_rows += 1
        g.naive_sum_quantity += qty       # the pre-dedupe sum, kept for audit only
        if qty > g.shares:
            g.shares = qty                # representative: the largest positive, never the sum
        if r["scheme_code"] not in g.variant_scheme_codes:
            g.variant_scheme_codes.append(r["scheme_code"])
        if r["source"] not in g.sources:
            g.sources.append(r["source"])
    # qty_variants is the count of DISTINCT positive quantities in the group: > 1 means the
    # variants disagreed (0.094% of groups on staging 2026-09) and the representative is a choice
    # rather than a copy. Recomputed in a second pass so the first can stay single-pass.
    distinct: dict = defaultdict(set)
    for r in rows:
        isin = (r.get("security_isin") or "").strip()
        if not isin:
            continue
        qty = r.get("quantity")
        if leg_class(r.get("security_name"), qty) != LEG_EQUITY:
            continue
        amc = (r.get("amc_id") or "").strip() or src_amc.get(r["source"]) \
            or f"unmapped_source:{r['source']}"
        base = base_scheme_name(r.get("scheme_name") or r["scheme_code"])
        distinct[(amc, base, isin)].add(float(qty))
    for key, g in groups.items():
        g.qty_variants = len(distinct.get(key, ()))
    # A group whose only rows were derivative legs or value-less rows holds no shares we can
    # count. It is dropped rather than published as 0 — absence is not zero.
    return [g for g in groups.values() if g.variant_rows > 0]


@dataclass
class StockReconciliation:
    """How our deduplicated share count compares with what the company disclosed."""

    security_isin: str
    symbol: Optional[str]
    canonical_shares: float
    naive_shares: float
    funds: int
    amcs: int
    expected_shares: Optional[float]

    @property
    def coverage_ratio(self) -> Optional[float]:
        if not self.expected_shares:
            return None
        return self.canonical_shares / self.expected_shares

    @property
    def naive_ratio(self) -> Optional[float]:
        if not self.expected_shares:
            return None
        return self.naive_shares / self.expected_shares


def expected_mf_shares(mf_pct: float, total_shares: float) -> float:
    """Shares the mutual funds held per the company's own shareholding filing."""
    return total_shares * mf_pct / 100.0


# ── ScanX extension (migration 184) — Python mirror of nidp.v_mf_holdings_canonical_scanx /
# nidp.v_mf_holdings_canonical_ext ─────────────────────────────────────────────────────────────
# nidp.scanx_mf_holdings covers 51 AMCs (the 11 above plus ~40 ScanX-only), with its primary key
# (scheme_slug, as_of_month, security_isin) already guaranteeing one row per actual fund — verified
# against real staging data (migration 184 header) to have NO plan/option fan-out, so there is
# nothing here for canonical_holdings()'s grouping/representative-quantity logic to do. What IS
# shared, so the two layers cannot drift apart: base_scheme_name() (reused, not reinvented) and the
# "never sum two sources for one AMC" rule (combine_extended_holdings() below).

# The equity-like asset classes: real, positive cash share counts comparable to a company's own
# mf_pct x total_shares filing. 'Arbitrage' is the long cash leg of an arbitrage scheme (the same
# thing canonical_holdings() keeps as LEG_EQUITY for an AMC-file arbitrage fund) — verified ScanX
# carries zero negative share counts anywhere, so there is no short leg to net out here. The other
# 20 asset classes (Debenture, Bonds, REITs, InvITs, Preference Shares, ...) are debt/other
# instruments and are excluded, the same way canonical_holdings() excludes derivative/no-quantity
# rows: never summed, never silently dropped.
SCANX_EQUITY_ASSET_CLASSES = frozenset({"Equity", "Arbitrage"})


@dataclass
class ScanxCanonicalHolding:
    """One ScanX-sourced fund's holding of one security in one reporting month."""

    amc_id: str
    base_scheme: str
    security_isin: str
    as_of_month: str
    shares: float
    weight_pct: Optional[float] = None

    @property
    def canonical_fund_key(self) -> str:
        return f"{self.amc_id}|{self.base_scheme}"


def scanx_canonical_holdings(rows: Sequence[Mapping],
                              amc_id_map: Mapping[str, str]) -> list:
    """Collapse ScanX holdings rows to the canonical (amc_id, base_scheme, isin, month) grain.

    `rows` are dicts with amc (ScanX's full AMC name), scheme_name, security_isin, as_of_month,
    shares, weight_pct, asset_class — i.e. nidp.scanx_mf_holdings rows.
    `amc_id_map` is ScanX full name -> amc_id, the Python copy of nidp.v_scanx_amc_id (a
    warehouse-wide fact derived from nidp.mf_amc_master; cannot be derived from a few rows, same
    reason canonical_holdings() takes source_amc as a parameter rather than deriving it locally).

    Unlike canonical_holdings(), this does not need to GROUP rows: scanx_mf_holdings' primary key
    (scheme_slug, as_of_month, security_isin) already guarantees one row per fund x ISIN x month
    (verified against real staging data — see migration 184's header), so shares is passed
    through, never summed. A disclosed 0 is kept as a real zero (migration 184's "zero row" note),
    never dropped — only a genuinely missing `shares` (None) or an unmapped AMC/ISIN is excluded.
    """
    out = []
    for r in rows:
        if r.get("asset_class") not in SCANX_EQUITY_ASSET_CLASSES:
            continue
        isin = (r.get("security_isin") or "").strip()
        if not isin:
            continue
        amc_id = amc_id_map.get(r.get("amc"))
        if not amc_id:
            continue
        shares = r.get("shares")
        if shares is None:
            continue
        out.append(ScanxCanonicalHolding(
            amc_id=amc_id,
            base_scheme=base_scheme_name(r.get("scheme_name") or ""),
            security_isin=isin,
            as_of_month=r["as_of_month"],
            shares=float(shares),
            weight_pct=r.get("weight_pct"),
        ))
    return out


@dataclass
class ExtendedStockHoldings:
    """Per-stock totals over the EXTENDED panel (amc-file + ScanX-only AMCs), with the two
    sources kept separate rather than blended into one count — the same safeguard migration
    182/183 keep for duplication vs coverage."""

    security_isin: str = ""
    mf_shares: float = 0.0
    naive_mf_shares: float = 0.0
    funds: int = 0
    funds_scanx: int = 0
    amcs_amc_file: set = field(default_factory=set)
    amcs_scanx: set = field(default_factory=set)

    @property
    def amcs(self) -> int:
        return len(self.amcs_amc_file | self.amcs_scanx)


def combine_extended_holdings(amc_file_groups: Sequence[CanonicalHolding],
                               scanx_groups: Sequence[ScanxCanonicalHolding]) -> dict:
    """Per-stock totals over nidp.v_mf_holdings_canonical (amc_file_groups) union ScanX-only AMCs
    (scanx_groups) — the Python mirror of migration 184's nidp.v_mf_holdings_canonical_ext /
    nidp.v_mf_stock_shares_monthly_ext.

    ScanX rows whose amc_id is already present in amc_file_groups are EXCLUDED, never summed with
    the amc-file figure for that AMC — the two sources are never blended into one ratio.
    amcs_amc_file / amcs_scanx / funds_scanx stay separate so a caller can always tell which side
    a figure came from, which is the point of reporting duplication and coverage separately.
    """
    out: dict = defaultdict(ExtendedStockHoldings)
    amc_file_amcs = {g.amc_id for g in amc_file_groups}
    for g in amc_file_groups:
        acc = out[g.security_isin]
        acc.security_isin = g.security_isin
        acc.mf_shares += g.shares
        acc.naive_mf_shares += g.naive_sum_quantity
        acc.funds += 1
        acc.amcs_amc_file.add(g.amc_id)
    for h in scanx_groups:
        if h.amc_id in amc_file_amcs:
            continue
        acc = out[h.security_isin]
        acc.security_isin = h.security_isin
        acc.mf_shares += h.shares
        acc.naive_mf_shares += h.shares
        acc.funds += 1
        acc.funds_scanx += 1
        acc.amcs_scanx.add(h.amc_id)
    return dict(out)


def reconcile(rows: Sequence[Mapping],
              expected: Mapping[str, Mapping],
              source_amc: Optional[Mapping] = None) -> list:
    """Per security: canonical vs naive share count vs the disclosed MF holding.

    `expected` maps security_isin -> {symbol, mf_pct, total_shares}. An ISIN with no entry gets
    expected_shares None, and its ratios are None — never 0, and never assumed to be 1.
    `source_amc` is passed through to canonical_holdings; see its docstring.
    """
    per_isin: dict = defaultdict(lambda: {"shares": 0.0, "naive": 0.0, "funds": 0, "amcs": set()})
    for g in canonical_holdings(rows, source_amc):
        acc = per_isin[g.security_isin]
        acc["shares"] += g.shares
        acc["naive"] += g.naive_sum_quantity
        acc["funds"] += 1
        acc["amcs"].add(g.amc_id)
    out = []
    for isin, acc in sorted(per_isin.items()):
        exp = expected.get(isin)
        out.append(StockReconciliation(
            security_isin=isin,
            symbol=(exp or {}).get("symbol"),
            canonical_shares=acc["shares"],
            naive_shares=acc["naive"],
            funds=acc["funds"],
            amcs=len(acc["amcs"]),
            expected_shares=(expected_mf_shares(exp["mf_pct"], exp["total_shares"])
                             if exp else None),
        ))
    return out
