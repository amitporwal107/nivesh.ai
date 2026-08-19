"""Pure-logic tests for the FLOW LEDGER auto-fill.

The SQL is verified against staging. What is worth testing without a DB is the
classification and differencing — where a wrong answer is not an error, it is a
plausible-looking number pointing the opposite way.

No DB, no network.
"""
from __future__ import annotations

import pytest

from nidp.services.daas_api import flow_ledger as fl


# ── F&O quadrant ────────────────────────────────────────────────────────────
# The tracker scores these very differently: short buildup -100 vs long unwinding
# -40, long buildup +100 vs short covering +40. Getting the OI sign wrong moves a
# stream by 60 points without looking wrong.

@pytest.mark.parametrize("price,oi,expected,meaning", [
    (-5.0,  1000, "sb", "price down + OI up  = short buildup"),
    (-5.0, -1000, "lu", "price down + OI down = long unwinding"),
    ( 5.0, -1000, "sc", "price up + OI down   = short covering"),
    ( 5.0,  1000, "lb", "price up + OI up     = long buildup"),
])
def test_fo_quadrant(price, oi, expected, meaning):
    assert fl.fo_quadrant(price, oi) == expected, meaning


def test_fo_quadrant_matches_the_real_reliance_reading():
    """From nidp_staging 2026-08-18: close 1327.4 -> 1320.5, OI 106,994,000 ->
    102,734,500. Both falling = long unwinding."""
    assert fl.fo_quadrant(1320.5 - 1327.4, 102734500 - 106994000) == "lu"


@pytest.mark.parametrize("price,oi", [(0, 500), (5, 0), (0, 0)])
def test_flat_leg_is_no_clear_pattern_not_a_direction(price, oi):
    assert fl.fo_quadrant(price, oi) == "n"


@pytest.mark.parametrize("price,oi", [(None, 500), (5, None), (None, None)])
def test_missing_leg_yields_none_not_a_guess(price, oi):
    assert fl.fo_quadrant(price, oi) is None


# ── QoQ differencing ────────────────────────────────────────────────────────

def test_qoq_bps_matches_the_real_reliance_series():
    """nidp_staging: 17.20, 18.67, 19.09, 18.65, 19.21 (newest first).

    The tracker's own hardcoded RELIANCE row is [-148, -42]; NIDP computes
    [-147, -42] from the exchange filings. The 1bp gap is rounding in the source
    the hardcoded row came from, not a differencing error.
    """
    assert fl.qoq_bps([17.20, 18.67, 19.09, 18.65, 19.21]) == [-147, -42, 44, -56]


def test_a_single_quarter_yields_no_change():
    """One filing is a level, not a move. It must not read as zero change."""
    assert fl.qoq_bps([17.20]) == []


def test_a_gap_is_not_bridged():
    """Differencing across a missing quarter would report a two-quarter move as
    one — the same magnitude error as a doubled print."""
    assert fl.qoq_bps([17.20, None, 19.09]) == [None, None]


def test_sign_convention_is_change_in_holding():
    assert fl.qoq_bps([20.0, 19.0]) == [100]     # stake rose  -> positive
    assert fl.qoq_bps([19.0, 20.0]) == [-100]    # stake fell  -> negative


# ── field shaping ───────────────────────────────────────────────────────────

def test_as_field_pads_to_the_trackers_four_boxes():
    assert fl.as_field([-147, -42]) == ["-147", "-42", "", ""]


def test_as_field_truncates_rather_than_overflowing():
    assert fl.as_field([1, 2, 3, 4, 5, 6]) == ["1", "2", "3", "4"]


def test_as_field_keeps_a_real_zero():
    """0 bps means measured-and-unchanged; "" means not measured. The tracker
    treats them completely differently."""
    assert fl.as_field([0, None]) == ["0", "", "", ""]


# ── the "no fabricated neutral" rule ────────────────────────────────────────

def test_an_unfilled_stream_must_carry_a_reason():
    """The tracker excludes unfilled streams and renormalises weights, so a
    fabricated neutral would dilute the streams that ARE real."""
    with pytest.raises(ValueError, match="must carry a reason"):
        fl.stream("S3", 20, "Bulk / block deals", filled=False)


def test_unfilled_stream_reports_its_reason_and_no_evidence():
    s = fl.stream("S3", 20, "Bulk / block deals", filled=False,
                  reason=fl.BULK_DEAL_LIMIT)
    assert s["filled"] is False
    assert s["evidence"] is None
    assert "beneficial owner" in s["unavailable_reason"]


def test_filled_stream_has_no_reason():
    s = fl.stream("S1", 30, "FII stake, quarterly", filled=True,
                  evidence="Q0 -147bps", source="nidp.shareholding_pattern")
    assert s["unavailable_reason"] is None
    assert s["source_dataset"] == "nidp.shareholding_pattern"


@pytest.mark.parametrize("reason", [
    fl.BULK_DEAL_LIMIT, fl.MF_MONTHLY_LIMIT,
    fl.NSDL_FORTNIGHT_LIMIT, fl.NSDL_AUC_LIMIT,
])
def test_every_limit_explains_itself_in_plain_words(reason):
    """A user seeing a blank stream must learn why from the message alone."""
    assert len(reason) > 40
    assert not reason.endswith(".")


# ── sector mapping ──────────────────────────────────────────────────────────

def test_sector_index_map_only_names_indices_that_exist():
    """Measured on nidp_staging 2026-08-19 — index_eod carries these 14 sector
    indices. An index that is merely close would put a wrong denominator into the
    relative-strength score."""
    live = {"Nifty Auto", "Nifty Bank", "Nifty Energy", "Nifty FMCG",
            "Nifty Financial Services", "Nifty Financial Services 25/50",
            "Nifty Financial Services Ex-Bank", "Nifty IT", "Nifty Media",
            "Nifty Metal", "Nifty PSU Bank", "Nifty Pharma",
            "Nifty Private Bank", "Nifty Realty"}
    assert set(fl.SECTOR_INDEX.values()) <= live
    assert fl.BENCHMARK_INDEX == "Nifty 50"


def test_sector_keys_match_sector_master_spelling():
    """These are the live values of nidp.sector_master.sector; a typo here silently
    yields 'no index for this sector' forever."""
    assert "Information Technology" in fl.SECTOR_INDEX
    assert "Automobile" in fl.SECTOR_INDEX          # not "Auto"
    assert "Oil Gas" in fl.SECTOR_INDEX             # not "Oil & Gas"


# ── returns ─────────────────────────────────────────────────────────────────

def test_pct_return_matches_the_real_nifty_auto_reading():
    """Staging 3M window: Nifty Auto +13.88%, Nifty 50 +2.27%."""
    assert fl.pct_return(29264.55, 25697.00) == 13.88


def test_pct_return_guards_a_zero_base():
    assert fl.pct_return(100.0, 0) is None
    assert fl.pct_return(100.0, None) is None
    assert fl.pct_return(None, 100.0) is None
