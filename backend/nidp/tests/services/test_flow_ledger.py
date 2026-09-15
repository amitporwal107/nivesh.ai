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
                  reason=fl.BULK_DEAL_NO_DEALS)
    assert s["filled"] is False
    assert s["evidence"] is None
    assert "observation, not a gap" in s["unavailable_reason"]


def test_filled_stream_has_no_reason():
    s = fl.stream("S1", 30, "FII stake, quarterly", filled=True,
                  evidence="Q0 -147bps", source="nidp.shareholding_pattern")
    assert s["unavailable_reason"] is None
    assert s["source_dataset"] == "nidp.shareholding_pattern"


@pytest.mark.parametrize("reason", [
    fl.BULK_DEAL_NO_DEALS, fl.MF_MONTHLY_LIMIT,
    fl.NSDL_NO_SECTOR, fl.NSDL_TOO_SHORT,
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
            "Nifty Private Bank", "Nifty Realty", "Nifty Capital Goods",
            "Nifty Chemicals", "Nifty Consumer Durables", "Nifty Consumer Services",
            "Nifty Construction", "Nifty Cement", "Nifty Power",
            "Nifty Healthcare Index"}
    assert set(fl.SECTOR_INDEX.values()) <= live
    assert fl.BENCHMARK_INDEX == "Nifty 50"


def test_no_sector_is_mapped_to_an_approximate_index():
    """These four have no clean counterpart — Telecom only appears inside
    'Nifty MidSmall IT & Telecom' (two sectors blended) and Services only inside
    'Nifty Commercial & Transport Services' (a subset). A wrong denominator would
    corrupt both relative strength AND the AUC-minus-index residual, which is worse
    than an absent stream the tracker already knows how to renormalise around."""
    for sector in fl.UNMAPPED_BY_DESIGN:
        assert sector not in fl.SECTOR_INDEX


def test_healthcare_maps_to_healthcare_not_pharma():
    """sector_master's Healthcare includes hospitals and diagnostics, which Nifty
    Pharma excludes."""
    assert fl.SECTOR_INDEX["Healthcare"] == "Nifty Healthcare Index"


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


# ── NSDL fortnight streak ───────────────────────────────────────────────────

def test_streak_counts_from_the_latest_fortnight_not_the_longest_run():
    """Real Automobile reading on staging: in, OUT x6 (newest first).

    The honest answer is a 1-fortnight INFLOW. Reporting the 6-fortnight outflow
    behind it would describe a regime that has already turned — and the tracker
    scores 6 fortnights at -90 versus +18 for one, so the difference is the whole
    stream.
    """
    assert fl.fortnight_streak([120, -50, -80, -30, -90, -40, -60]) == ("in", 1)


def test_a_genuine_run_is_counted_in_full():
    assert fl.fortnight_streak([-50, -80, -30, -90, 40]) == ("out", 4)


def test_zero_ends_a_streak_rather_than_extending_it():
    """A fortnight with no net movement is not evidence the prior direction held."""
    assert fl.fortnight_streak([-50, -80, 0, -30]) == ("out", 2)


def test_a_leading_zero_has_no_direction():
    assert fl.fortnight_streak([0, -80, -30]) is None


@pytest.mark.parametrize("flows", [[], [None], [None, -50]])
def test_no_readable_flow_yields_none(flows):
    assert fl.fortnight_streak(flows) is None


def test_streak_stops_at_a_missing_fortnight():
    """A gap is not a continuation — NSDL revises, and a hole in the series must not
    be read as the direction persisting through it."""
    assert fl.fortnight_streak([-50, -80, None, -30]) == ("out", 2)


def test_direction_codes_are_the_trackers_own():
    """These strings go straight into the tracker's ftDir select."""
    assert fl.fortnight_streak([10])[0] == "in"
    assert fl.fortnight_streak([-10])[0] == "out"


# ── S3: FPI counterparty classification ─────────────────────────────────────
# The stream needs FPI PORTFOLIO flow. Three populations share the deal lists and
# only one is the subject; getting that wrong reads a promoter block exit as a
# distribution pattern.

@pytest.mark.parametrize("name", [
    "GQG PARTNERS EMERGING MARKETS EQUITY FUND",
    "FMRC FIDELITY ADVISOR INTERNATIONAL CAPITAL APPRECIATION FUND",
    "SMALLCAP WORLD FUND INC",
    "NOMURA INDIA INVESTMENT FUND MOTHER FUND",
    "CITIGROUP GLOBAL MARKETS SINGAPORE PTE LIMITED",
    "GOLDMAN SACHS BANK EUROPE SE",
    "MORGAN STANLEY ASIA SINGAPORE PTE",
    "BOFA SECURITIES EUROPE SA",
    "SOCIETE GENERALE",
    "GOVERNMENT OF SINGAPORE",
])
def test_real_fpi_portfolio_investors_are_recognised(name):
    """Every one of these is a real counterparty in nidp_staging's deal lists,
    2026-08-19. An earlier reading of this data missed them by ranking on deal count
    and matching a narrow geography regex."""
    assert fl.is_fpi_house(name) is True, name


@pytest.mark.parametrize("name", [
    "BAYER AG",                                   # promoter of Bayer CropScience
    "MYLAN INC.",                                 # strategic holder
    "TWIN STAR HOLDINGS LIMITED",                 # Vedanta's Mauritius holdco
    "BC INVESTMENTS IV LIMITED",                  # Baring PE
    "EIGHT ROADS INVESTMENTS MAURITIUS II LIMITED",
    "CLAYMORE INVESTMENTS (MAURITIUS) PTE.LTD.",
    "MACRITCHIE INVESTMENTS PTE LIMITED",
    "ARDOUR INVESTMENT HOLDING LTD",
    "RESILIENT ASSET MANAGEMENT B V",
])
def test_foreign_strategic_and_pe_holdings_are_not_counted_as_fpi_flow(name):
    """Foreign, SEBI-registered as FPIs, and NOT portfolio flow. A one-off PE or
    promoter block exit scored as 'heavy FII selling' would misread a structural
    trade as a distribution pattern — which is exactly why the house list is a
    whitelist and not an offshore-name heuristic."""
    assert fl.is_fpi_house(name) is False, name


@pytest.mark.parametrize("name", [
    "QE SECURITIES LLP", "HRTI PRIVATE LIMITED",
    "JUNOMONETA FINSOL PRIVATE LIMITED", "GRAVITON RESEARCH CAPITAL LLP",
    "NK SECURITIES RESEARCH PRIVATE LIMITED", "IRAGE BROKING SERVICES LLP",
    "MICROCURVES TRADING PRIVATE LIMITED",
])
def test_domestic_prop_and_hft_desks_are_excluded(name):
    """These dominate the lists by count AND by value, sit on both sides of the
    book, and net to roughly nothing. Counting them would drown the signal."""
    assert fl.is_fpi_house(name) is False, name


def test_missing_counterparty_is_not_an_fpi():
    assert fl.is_fpi_house(None) is False
    assert fl.is_fpi_house("") is False


# ── S3: direction ───────────────────────────────────────────────────────────

def test_one_sided_selling_is_heavy():
    code, net, gross = fl.deal_direction(buy_cr=0, sell_cr=120)
    assert code == "hs" and net == -120.0 and gross == 120.0


def test_one_sided_buying_is_heavy():
    assert fl.deal_direction(buy_cr=200, sell_cr=0)[0] == "hb"


def test_rotation_is_not_distribution():
    """500 in and 480 out is a fund rotating, not exiting. Scoring the -20 net as
    selling would turn ordinary churn into a signal."""
    assert fl.deal_direction(buy_cr=500, sell_cr=480)[0] == "n"


def test_a_clear_lean_scores_moderate_not_heavy():
    assert fl.deal_direction(buy_cr=20, sell_cr=80)[0] == "s"      # -60/100
    assert fl.deal_direction(buy_cr=80, sell_cr=20)[0] == "b"


def test_a_tiny_print_never_reads_as_heavy():
    """One 2cr trade is not evidence of anything at this weight."""
    assert fl.deal_direction(buy_cr=0, sell_cr=2)[0] == "n"


def test_no_activity_is_neutral_not_a_crash():
    assert fl.deal_direction(buy_cr=0, sell_cr=0) == ("n", 0.0, 0.0)


def test_codes_are_the_trackers_own_option_values():
    """These strings go straight into the tracker's deal select."""
    valid = {"hs", "s", "n", "b", "hb"}
    for b, sl in [(0, 100), (10, 90), (50, 50), (90, 10), (100, 0)]:
        assert fl.deal_direction(b, sl)[0] in valid


@pytest.mark.parametrize("name", [
    "HSBC MUTUAL FUND",
    "INVESCO MUTUAL FUND",
    "FRANKLIN TEMPLETON MUTUAL FUND",
    "NIPPON INDIA MUTUAL FUND",
])
def test_indian_arms_of_global_brands_are_dii_not_fii(name):
    """All real counterparties in nidp_staging. The global brand matches the house
    list, but an India-domiciled mutual fund is DII by definition — counting one as
    FII flow would invert the reading of the stream."""
    assert fl.is_fpi_house(name) is False, name


def test_the_offshore_arm_of_the_same_brand_still_counts():
    """The exclusion must be about the VEHICLE, not the brand."""
    assert fl.is_fpi_house("HSBC BANK (SINGAPORE) LIMITED") is True
    assert fl.is_fpi_house("FRANKLIN TEMPLETON INVESTMENT FUNDS") is True


@pytest.mark.parametrize("name", [
    "ALLIANZ GLOBAL INVESTORS GMBH ACTING ON BEHALF OF ALLIANZ EEE FONDS",
    "POLAR CAPITAL FUNDS PLC-HEALTHCARE OPPORTUNITIES FUND",
    "JUPITER INDIA FUND",
    "POLUNIN EMERGING MARKETS SMALL CAP FUND LLC",
    "VIRIDIAN ASIA OPPORTUNITIES MASTER FUND",
    "OXBOW MASTER FUND LIMITED",
])
def test_offshore_funds_the_first_run_missed_are_now_recognised(name):
    """The first live run printed Allianz in the evidence line and did not count it.
    That is the whitelist's failure mode, and the reason the evidence always names
    counterparties — it is what made the miss visible within one run."""
    assert fl.is_fpi_house(name) is True, name


@pytest.mark.parametrize("name", [
    "HDFC LIFE INSURANCE COMPANY LIMITED",
    "SBI LIFE INSURANCE COMPANY LIMITED",
    "ICICI PRUDENTIAL LIFE INSURANCE COMPANY LIMITED",
    "TATA AIA LIFE INSURANCE COMPANY LIMITED",
    "NUVAMA CROSSOVER OPPORTUNITIES FUND - SERIES III",
    "360 ONE PIPE FUND",
])
def test_indian_institutions_with_fund_like_names_stay_dii(name):
    """All real counterparties. Indian insurers and AIFs read like funds and some
    share a global brand; every one of them is DII."""
    assert fl.is_fpi_house(name) is False, name
