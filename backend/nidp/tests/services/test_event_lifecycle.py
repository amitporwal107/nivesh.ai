"""Corporate-transaction lifecycle: family, stage and transaction grouping.

Every rule under test was derived from the real subject vocabulary in
nidp.corporate_announcements over 2026-01-19..2026-09-25. The exclusions carry
as much weight as the matches: each one is a filing that mentions the family but
is not part of its lifecycle, and including it would stretch a transaction's
lifespan or fabricate an event.
"""
from __future__ import annotations

from datetime import date

from nidp.services.event_lifecycle.lifecycle import (BUYBACK, QIP_PREF,
                                                     classify_family,
                                                     classify_stage,
                                                     group_transactions,
                                                     is_confounded)


# ── family ───────────────────────────────────────────────────────────
def test_recognises_the_two_phase1_families():
    assert classify_family("Announcement under Regulation 30 (LODR)-Public "
                           "Announcement-Buyback of Shares") == BUYBACK
    assert classify_family("Buy-Back Of Equity Shares Of The Company") == BUYBACK
    assert classify_family("Announcement under Regulation 30 (LODR)-Qualified "
                           "Institutional Placement") == QIP_PREF
    assert classify_family("Announcement under Regulation 30 (LODR)-"
                           "Preferential Issue") == QIP_PREF


def test_a_debt_buyback_is_not_a_share_buyback():
    """Real filing. A commercial-paper buyback is a money-market operation with
    no equity effect; a naive LIKE '%buyback%' sweeps it into the cohort."""
    assert classify_family("Buyback Of Commercial Papers") is None
    assert classify_family("Buy-back of Non-Convertible Debentures") is None


def test_post_issue_compliance_is_not_lifecycle():
    """Reg-32 deviation statements are filed EVERY QUARTER for years after a
    raise. Treating one as a lifecycle stage would extend the transaction
    indefinitely and invent events long after the fact."""
    assert classify_family("Statement Of Deviation Or Variation In Utilisation "
                           "Of Funds Raised Through Preferential Issue") is None
    assert classify_family("Statement Of Nil Deviation/Variation In Utilisation "
                           "Of Proceeds Raised Through Preferential Issue") is None


def test_warrant_conversion_is_its_own_event():
    """Warrants issued preferentially convert over ~18 months. Each conversion
    is a separate event, not a late stage of the original issue."""
    assert classify_family("Board Meeting Outcome for Allotment Of 50,00,000 "
                           "Shares Upon Conversion Of Warrants Issued On "
                           "Preferential Basis") is None


def test_unrelated_filings_are_not_claimed():
    assert classify_family("Board Meeting Intimation for Audited Results") is None
    assert classify_family("") is None


# ── stage ────────────────────────────────────────────────────────────
def test_buyback_stages_in_lifecycle_order():
    """The MATRIMONY buyback, 2026-01-20..02-26, as actually filed."""
    seq = [
        ("Board Meeting Intimation for Proposal Of Buyback Of Equity Shares", "PROPOSED"),
        ("Board Resolution For Buyback Of Equity Shares Of The Company", "APPROVED"),
        ("Announcement under Regulation 30 (LODR)-Public Announcement-Buyback of Shares", "ANNOUNCED"),
        ("Intimation Of Record Date For Buyback Of Equity Shares", "RECORD_DATE"),
        ("Despatch Of Letter Of Offer For Buyback Of Equity Shares", "OFFER_OPEN"),
        ("Announcement under Regulation 30 (LODR)-Post Buyback Public Announcement", "OFFER_CLOSED"),
        ("Certificate Of Extinguishment Of Equity Shares Pursuant To Buy-Back", "COMPLETED"),
    ]
    assert [classify_stage(s) for s, _ in seq] == [want for _, want in seq]


def test_most_specific_stage_wins():
    """Subjects stack markers. 'Board Meeting Outcome ... Public Announcement'
    must not be read as merely APPROVED, and a POST-buyback announcement must
    not be read as the opening ANNOUNCED."""
    assert classify_stage("Announcement under Regulation 30 (LODR)-Post Buyback "
                          "Public Announcement") == "OFFER_CLOSED"
    assert classify_stage("Board Meeting Outcome for Outcome Of The Meeting Of "
                          "The Board Of Directors - Buyback Of Shares") == "APPROVED"


def test_a_bare_subject_is_update_not_a_guess():
    """NSE files this literally as 'Buyback' for every stage of the offer, so
    there is nothing to read. UPDATE says 'in-family, stage unknown' — inventing
    a stage here would put filings in the wrong lifecycle position."""
    assert classify_stage("Buyback") == "UPDATE"
    assert classify_stage("Announcement under Regulation 30 (LODR)-"
                          "Preferential Issue") == "UPDATE"


def test_unknown_for_no_text():
    assert classify_stage("") == "UNKNOWN"


# ── confounding (PRD 7.5) ────────────────────────────────────────────
def test_results_bundled_with_the_event_is_flagged():
    """Real filing. Indian board meetings bundle results with everything else;
    the event study must be able to exclude these."""
    assert is_confounded(
        "Board Meeting Intimation for Consideration And Approval Of The Audited "
        "Financial Results For The Quarter And Year Ended March 2026, "
        "Recommendation Of Dividend, If Any And Proposal For Buyback Of Equity Shares")


def test_results_alone_is_not_confounded():
    """Confounding needs BOTH — a results filing with no family event is simply
    not our event."""
    assert not is_confounded("Board Meeting Intimation for Audited Financial Results")
    assert not is_confounded("Buyback - Letter Of Offer")


# ── transaction grouping ─────────────────────────────────────────────
def _f(sym, fam, d):
    return {"nse_symbol": sym, "family": fam, "filed_on": date.fromisoformat(d)}


def test_one_run_of_filings_is_one_transaction():
    rows = group_transactions([
        _f("MATRIMONY", BUYBACK, "2026-01-20"), _f("MATRIMONY", BUYBACK, "2026-01-22"),
        _f("MATRIMONY", BUYBACK, "2026-02-03"), _f("MATRIMONY", BUYBACK, "2026-02-26"),
    ])
    assert {r["txn_ordinal"] for r in rows} == {1}


def test_a_long_gap_starts_a_new_transaction():
    """JSW Energy ran two separate preferential/QIP transactions in 2026 —
    Jan 20-21 and May 20-25. Merging them would pool two different events into
    one cohort member."""
    rows = group_transactions([
        _f("JSWENERGY", QIP_PREF, "2026-01-20"), _f("JSWENERGY", QIP_PREF, "2026-01-21"),
        _f("JSWENERGY", QIP_PREF, "2026-05-20"), _f("JSWENERGY", QIP_PREF, "2026-05-25"),
    ])
    by_date = {r["filed_on"].isoformat(): r["txn_ordinal"] for r in rows}
    assert by_date["2026-01-20"] == by_date["2026-01-21"] == 1
    assert by_date["2026-05-20"] == by_date["2026-05-25"] == 2


def test_families_and_symbols_never_share_a_transaction():
    rows = group_transactions([
        _f("AAA", BUYBACK, "2026-01-20"), _f("AAA", QIP_PREF, "2026-01-21"),
        _f("BBB", BUYBACK, "2026-01-20"),
    ])
    assert len({(r["nse_symbol"], r["family"], r["txn_ordinal"]) for r in rows}) == 3


def test_the_gap_threshold_is_the_boundary():
    """Measured: 110 within-transaction gaps of 0-28 days, 7 of 30-49, and one
    of 92 days that separates two distinct buybacks."""
    rows = group_transactions([_f("X", BUYBACK, "2026-01-01"),
                               _f("X", BUYBACK, "2026-03-01")],  # 59 days
                              max_gap_days=60)
    assert {r["txn_ordinal"] for r in rows} == {1}
    rows = group_transactions([_f("X", BUYBACK, "2026-01-01"),
                               _f("X", BUYBACK, "2026-04-03")],  # 92 days
                              max_gap_days=60)
    assert sorted(r["txn_ordinal"] for r in rows) == [1, 2]


def test_grouping_does_not_depend_on_input_order():
    early, late = _f("X", BUYBACK, "2026-01-01"), _f("X", BUYBACK, "2026-01-05")
    a = {r["filed_on"]: r["txn_ordinal"] for r in group_transactions([early, late])}
    b = {r["filed_on"]: r["txn_ordinal"] for r in group_transactions([late, early])}
    assert a == b
