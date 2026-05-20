"""Vocabulary contract: enricher labels ↔ NIDP SEBI category master.

The 2026-05-21 architecture decision: `nidp.sebi_category_master` (added
by migration 061) is the single source of truth for valid SEBI category
strings. Any (category, sub_category) string the enricher can EMIT must
exist in the seed; otherwise the enricher silently produces values no
downstream system can resolve (benchmark lookup → NULL, scoring → wrong
bucket).

This test parses the SQL seed directly so the contract holds without
needing a live Postgres. If a future migration adds/removes/renames
SEBI categories, update both the seed AND the enricher patterns; if
the test fails, that's the contract enforcing itself.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Set, Tuple

import pytest

from services.mf_category_enricher import (
    _DEBT_PATTERNS,
    _EQUITY_PATTERNS,
    _HYBRID_PATTERNS,
    _INDEX_INDEX_NAMES,
    _SCHEME_CATEGORY_REWRITES,
    _SECTORAL_PATTERNS,
    _SOLUTION_PATTERNS,
)


MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "nidp" / "migrations" / "061_nidp_sebi_category_master.sql"
)


def _parse_seed_rows() -> Set[Tuple[str, str | None]]:
    """Extract (category, sub_category) pairs from the migration's
    INSERT...VALUES blocks. Pure regex — no SQL engine needed.

    Each VALUES tuple is `('cat', NULL|'sub', 'parent', ...)`.
    """
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    # Match a 5-element VALUES tuple (cat, sub, parent, bench_name, bench_sym, desc)
    # SQL escapes embedded apostrophes as ''; capture and unescape.
    row_pattern = re.compile(
        r"\(\s*"
        r"'((?:[^']|'')*)'"     # category
        r"\s*,\s*"
        r"(NULL|'((?:[^']|'')*)')"  # sub_category (NULL or quoted)
        r"\s*,\s*"
        r"'(?:[^']|'')*'"        # parent_class
        r".*?"                   # rest of the row
        r"\)",
        re.DOTALL,
    )
    out: Set[Tuple[str, str | None]] = set()
    for m in row_pattern.finditer(sql):
        cat = m.group(1).replace("''", "'")
        sub_raw = m.group(2)
        if sub_raw == "NULL":
            sub = None
        else:
            sub = m.group(3).replace("''", "'")
        out.add((cat, sub))
    return out


SEED_PAIRS: Set[Tuple[str, str | None]] = _parse_seed_rows()


# ── 1. The seed must parse and contain a reasonable number of rows ──
def test_seed_parses_at_least_40_rows():
    """Sanity check: if the seed parser breaks, every downstream test
    here silently passes because the set is empty."""
    assert len(SEED_PAIRS) >= 40, (
        f"only parsed {len(SEED_PAIRS)} rows — seed parser likely broken"
    )


# ── 2. The seed must include the parent_class anchors ──────────────
def test_seed_includes_each_parent_class_anchor():
    """One canary per parent_class so we know all families are seeded."""
    anchors = [
        ("Large Cap",          None),   # Equity
        ("Liquid",             None),   # Debt
        ("Aggressive Hybrid",  None),   # Hybrid
        ("Retirement Fund",    None),   # Solution
        ("Gold ETF",           None),   # Other
        ("Index Fund",         "Nifty 50"),  # Other / sub
    ]
    for pair in anchors:
        assert pair in SEED_PAIRS, f"seed missing anchor {pair}"


# ── 3. Every label the enricher can emit must be in the seed ────────
def _enricher_primary_labels() -> Set[str]:
    """All primary `sebi_category` strings the enricher can emit via
    its pattern tables. Sub-categories handled separately below."""
    labels: Set[str] = set()
    labels.update(lbl for _, lbl in _EQUITY_PATTERNS)
    labels.update(lbl for _, lbl in _DEBT_PATTERNS)
    labels.update(lbl for _, lbl in _HYBRID_PATTERNS)
    labels.update(lbl for _, lbl in _SOLUTION_PATTERNS)
    # SECTORAL_PATTERNS map to SUB-categories under "Sectoral/Thematic"
    # — primary handled by parse_sebi_from_name returning that literal.
    labels.add("Sectoral/Thematic")
    # Hard-coded primaries from parse_sebi_from_name
    labels.update({"International Fund", "Index Fund", "Gold ETF", "Fund of Funds"})
    # Rewrites table (NIDP scheme_category normaliser)
    labels.update(lbl for _, lbl in _SCHEME_CATEGORY_REWRITES)
    return labels


def test_every_enricher_primary_label_exists_in_seed():
    """Lock: any string the enricher can emit as `sebi_category` must
    appear at least once in the seed as a primary `category`."""
    seed_primaries: Set[str] = {cat for cat, _ in SEED_PAIRS}
    missing = _enricher_primary_labels() - seed_primaries
    assert not missing, (
        f"enricher emits these primary labels but seed has no row for them: "
        f"{sorted(missing)}"
    )


def test_every_index_subcategory_exists_in_seed():
    """For Index Fund sub-categories, each enricher label must have a
    (category='Index Fund', sub_category=<label>) row in the seed."""
    seed_index_subs: Set[str] = {
        sub for cat, sub in SEED_PAIRS if cat == "Index Fund" and sub is not None
    }
    enricher_subs = {lbl for _, lbl in _INDEX_INDEX_NAMES}
    missing = enricher_subs - seed_index_subs
    assert not missing, (
        f"enricher's Index sub-categories not in seed: {sorted(missing)}"
    )


def test_every_sectoral_subcategory_exists_in_seed():
    """For Sectoral/Thematic sub-categories (Banking, Pharma, IT, …)."""
    seed_sectoral_subs: Set[str] = {
        sub for cat, sub in SEED_PAIRS if cat == "Sectoral/Thematic" and sub is not None
    }
    enricher_subs = {lbl for _, lbl in _SECTORAL_PATTERNS}
    missing = enricher_subs - seed_sectoral_subs
    assert not missing, (
        f"enricher's Sectoral sub-categories not in seed: {sorted(missing)}"
    )


# ── 4. No reverse drift: the enricher must not have retired labels ──
def test_enricher_does_not_emit_legacy_income_label():
    """SEBI's 2017 re-categorisation retired 'Income' as a primary debt
    category. The seed intentionally omits it; the enricher must too."""
    assert "Income" not in _enricher_primary_labels(), (
        "enricher still emits legacy 'Income' label — remove it; "
        "funds previously labelled 'Income' are now Dynamic Bond / "
        "Medium Duration etc."
    )


# ── 5. parent_class is non-NULL for every seeded row ───────────────
def test_every_seeded_row_has_parent_class():
    """parent_class is the filter dimension callers will GROUP BY.
    A NULL would break that grouping silently."""
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    # Find each tuple and confirm the 3rd field is a quoted string
    bad = re.findall(
        r"\(\s*'(?:[^']|'')*'\s*,\s*(?:NULL|'(?:[^']|'')*')\s*,\s*NULL",
        sql,
    )
    assert not bad, f"found rows with NULL parent_class: {bad}"
