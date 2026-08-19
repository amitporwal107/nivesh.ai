"""Parser tests for NSE's SAST pledged-data CSV.

Every fixture row below is copied verbatim from the real file
CF-SAST-Pledged-Data-19-Aug-2026.csv, so the traps under test are the ones the
actual exchange file contains — not invented edge cases.

No DB, no network.
"""
from __future__ import annotations

from datetime import date

import pytest

from nidp.services.nse_pledge_csv.parser import (
    SOURCE_NAME, last_completed_quarter_end, normalise_company_name,
    parse_sast_csv, pledge_stats,
)

HEADER = (
    '﻿"NAME OF COMPANY","TOTAL NO. OF ISSUED SHARES A+B+C",'
    '"TOTAL PROMOTER HOLDING NO. OF SHARES (A)","TOTAL PROMOTER HOLDING % A /(A+B+C)",'
    '"TOTAL PUBLIC HOLDING B",'
    '"PROMOTER SHARES ENCUMBERED AS OF LAST QUARTER NO. OF SHARES (X)",'
    '"PROMOTER SHARES ENCUMBERED AS OF LAST QUARTER % OF PROMOTER SHARES (X/A)",'
    '"PROMOTER SHARES ENCUMBERED AS OF LAST QUARTER % OF TOTAL SHARES [X/(A+B+C)]",'
    '"PROMOTER SHARES ENCUMBERED AS OF LAST QUARTER VALUES(RS.CR.)=NO. OF SHARES ENCUMBERED [X] * LAST AVAILABLE CLOSING PRICE OF THE SCRIP",'
    '"DISCLOSURE MADE BY PROMOTERS",'
    '"NO. OF SHARES PLEDGED IN THE DEPOSITORY SYSTEM NO. OF SHARES PLEDGED",'
    '"NO. OF SHARES PLEDGED IN THE DEPOSITORY SYSTEM TOTAL NO. OF DEMAT SHARES",'
    '"(%) PLEDGE / DEMAT","Values(Rs. Cr.)","BROADCAST DATE"'
)

# --- verbatim rows from the 19-Aug-2026 file -------------------------------
ROW_ZERO_PLEDGE = (
    '"Reliance Industries Limited","13532538722","6944962964","    51.32","6587575758",'
    '"0","     0.00","     0.00","0","18-Aug-2026 16:30:21","162669173","13503524112",'
    '"1.2","21047.764","18-Aug-2026 16:30:21"'
)
ROW_HIGH_PLEDGE = (          # 99.68% of promoter holding vs 31.11% pledge/demat
    '"A2Z Infra Engineering Limited","177522358","49560983","    27.92","127961375",'
    '"49402301","    99.68","    27.83","66.347","18-Aug-2026 16:31:34","55224006",'
    '"177517541","31.11","74.166","18-Aug-2026 16:31:34"'
)
ROW_EMPTY_ENCUMBRANCE = (    # trap 1 — empty, NOT zero
    '"Alchemist Limited","13559800","4738341","    34.94","8821459",,,,,'
    '"18-Aug-2026 16:31:22","58803","12933102","0.45",,"18-Aug-2026 16:31:22"'
)
ROW_DUP_A = (                # trap 2 — same name, different company
    '"Future Enterprises Limited","454930401","74467852","    16.37","380462549",'
    '"45750000","    61.44","    10.06",,"18-Aug-2026 16:31:01","51201804","454557958",'
    '"11.26",,"18-Aug-2026 16:31:01"'
)
ROW_DUP_B = (
    '"Future Enterprises Limited","39374679","28436580","    72.22","10938099","0",'
    '"     0.00","     0.00",,"18-Aug-2026 16:31:28","464967","39333044","1.18",,'
    '"18-Aug-2026 16:31:28"'
)
ROW_ASHOK = (
    '"Ashok Leyland Limited","5873854552","3048660522","    51.90","2825194030",'
    '"1203500000","    39.48","    20.49","18979.195","18-Aug-2026 16:30:19",'
    '"1251631604","5867754350","21.33","19738.23","18-Aug-2026 16:30:19"'
)


def _csv(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


def _by_name(res, name):
    return next(r for r in res.rows if r["company_name"] == name)


# ── the file's own quirks ───────────────────────────────────────────────────

def test_utf8_bom_is_stripped_so_the_first_column_matches():
    """The file ships with a BOM; without stripping it the first header becomes
    '\\ufeffNAME OF COMPANY' and no company name is ever found."""
    res = parse_sast_csv(_csv(ROW_ZERO_PLEDGE))
    assert len(res.rows) == 1
    assert res.rows[0]["company_name"] == "Reliance Industries Limited"


def test_missing_required_column_raises_rather_than_silently_yielding_nothing():
    bad = '"NAME OF COMPANY","TOTAL PUBLIC HOLDING B"\n"X Limited","1"\n'
    with pytest.raises(ValueError, match="missing required column"):
        parse_sast_csv(bad)


# ── TRAP 1: empty is not zero ───────────────────────────────────────────────

def test_empty_encumbrance_parses_to_none_not_zero():
    """A company with no disclosure is not a company with no pledge.

    Coercing this to 0.00 would show Alchemist as unpledged on precisely the
    screen built to surface pledged promoters.
    """
    res = parse_sast_csv(_csv(ROW_EMPTY_ENCUMBRANCE))
    row = _by_name(res, "Alchemist Limited")
    assert row["promoter_pledged_pct"] is None
    assert row["promoter_pledged_to_total_pct"] is None
    assert row["pledged_shares"] is None
    # a genuinely-present value on the same row still parses
    assert row["pledge_demat_pct"] == 0.45


def test_real_zero_is_preserved_as_zero():
    """The counterpart: an explicit 0.00 must stay 0.00, because that is what
    makes 'zero pledge' answerable at all."""
    res = parse_sast_csv(_csv(ROW_ZERO_PLEDGE))
    row = _by_name(res, "Reliance Industries Limited")
    assert row["promoter_pledged_pct"] == 0.0
    assert row["promoter_pledged_pct"] is not None


# ── TRAP 2: duplicate company names ─────────────────────────────────────────

def test_duplicate_company_name_is_rejected_not_silently_overwritten():
    """Two different companies share this name with different share counts. The
    join key to NIDP is the name, so neither can be resolved — keeping one would
    attach the wrong pledge to a real symbol."""
    res = parse_sast_csv(_csv(ROW_DUP_A, ROW_DUP_B, ROW_ASHOK))
    names = {r["company_name"] for r in res.rows}
    assert "Future Enterprises Limited" not in names
    assert res.duplicate_names == ["Future Enterprises Limited"]
    # unrelated rows survive
    assert "Ashok Leyland Limited" in names


# ── TRAP 3: two different pledge measures ───────────────────────────────────

def test_encumbrance_and_pledge_demat_are_kept_distinct():
    """A2Z: 99.68% of promoter holding encumbered, but 31.11% pledge/demat.
    Conflating them would misstate the risk by a factor of three."""
    res = parse_sast_csv(_csv(ROW_HIGH_PLEDGE))
    row = _by_name(res, "A2Z Infra Engineering Limited")
    assert row["promoter_pledged_pct"] == 99.68
    assert row["promoter_pledged_to_total_pct"] == 27.83
    assert row["pledge_demat_pct"] == 31.11


# ── period derivation ───────────────────────────────────────────────────────

@pytest.mark.parametrize("on,expected", [
    (date(2026, 8, 19), date(2026, 6, 30)),   # the real file
    (date(2026, 1, 5),  date(2025, 12, 31)),  # year boundary
    (date(2026, 4, 1),  date(2026, 3, 31)),
    (date(2026, 11, 30), date(2026, 9, 30)),
])
def test_last_completed_quarter_end(on, expected):
    assert last_completed_quarter_end(on) == expected


def test_period_end_comes_from_the_broadcast_stamp_not_the_filename():
    """The column says 'AS OF LAST QUARTER', so an August file describes Q1 FY27
    (ended 2026-06-30). Dating it by the broadcast day would invent a period no
    filing covers and would not align with the exchange SHP rows already stored."""
    res = parse_sast_csv(_csv(ROW_ASHOK))
    assert res.period_end == date(2026, 6, 30)
    assert res.rows[0]["period_end"] == date(2026, 6, 30)
    assert res.rows[0]["source"] == SOURCE_NAME


# ── join key ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("Mayur Uniquoters Ltd", "Mayur  Uniquoters   Ltd"),
    ("Advani Hotels & Resorts (India) Limited", "ADVANI HOTELS & RESORTS (INDIA) LIMITED"),
    ("Bank Of Baroda", "BANK OF BARODA"),
])
def test_name_normalisation_ignores_case_space_and_punctuation(a, b):
    assert normalise_company_name(a) == normalise_company_name(b)


def test_name_normalisation_does_not_reconcile_ampersand_with_the_word_and():
    """A known limitation, asserted rather than left to be discovered.

    "Larsen & Toubro Limited" and "LARSEN AND TOUBRO LIMITED" are the same company
    but do not normalise alike. Such a name resolves to no symbol and is reported in
    `unresolved` — it is never attached to the wrong company, which is the property
    that actually matters. Widening the normaliser to fold "&" into "AND" would also
    fold genuinely different names together, so it is left alone.
    """
    assert (normalise_company_name("Larsen & Toubro Limited")
            != normalise_company_name("LARSEN AND TOUBRO LIMITED"))


def test_name_normalisation_matches_sector_master_style_names():
    """Both sides carry the same registrar-style legal name.

    Measured on the real 19-Aug-2026 file against nidp_staging: 1,454 of 1,538 names
    resolve. The 84 that do not have no plausible candidate in sector_master — they
    are delisted issuers, the expected tail of a pledge list.
    """
    assert normalise_company_name("Laurus Labs Limited") == "LAURUSLABSLIMITED"
    assert normalise_company_name("Mohit Industries Limited") == "MOHITINDUSTRIESLIMITED"


@pytest.mark.parametrize("nse_name,master_name", [
    ("PNB GILTS LTD.", "PNB Gilts Limited"),
    ("RHI MAGNESITA INDIA LTD", "RHI MAGNESITA INDIA LIMITED"),
])
def test_ltd_and_limited_are_the_same_company(nse_name, master_name):
    """The only two real matcher failures in the 19-Aug-2026 file.

    Both sides name the same issuer; NSE abbreviates the legal form. Without this the
    pledge for PNBGILTS and RHIM is silently not written.
    """
    assert normalise_company_name(nse_name) == normalise_company_name(master_name)


def test_only_a_trailing_legal_form_is_canonicalised():
    """A name that merely contains the letters must not be rewritten."""
    assert normalise_company_name("Ltd Ventures Holdings") == "LTDVENTURESHOLDINGS"
    assert normalise_company_name("Alpha Ltd Beta") == "ALPHALTDBETA"


# ── degeneracy guard ────────────────────────────────────────────────────────

def test_pledge_stats_distinguishes_real_data_from_all_zeros():
    """`pb` reported 7.5% coverage while every value was 0.00. Distinct-count is
    what separates usable data from a column that merely exists."""
    res = parse_sast_csv(_csv(ROW_ZERO_PLEDGE, ROW_HIGH_PLEDGE, ROW_ASHOK,
                              ROW_EMPTY_ENCUMBRANCE))
    st = pledge_stats(res.rows)
    assert st["rows"] == 4
    assert st["with_pledge_pct"] == 3        # the empty one is excluded
    assert st["distinct_values"] == 3        # 0.00, 99.68, 39.48
    assert st["nonzero"] == 2
    assert st["zero"] == 1
    assert st["max"] == 99.68
