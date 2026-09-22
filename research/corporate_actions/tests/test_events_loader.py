"""events_for_symbol() filtering behaviour, against a hand-built synthetic pool (not the
stored CSV) so this test is independent of whatever the build script currently produces.
"""
from datetime import date

from research.corporate_actions.events import DemergerEvent, events_for_symbol


def _event(symbol, ex_date, category="DEMERGER", verified=True) -> DemergerEvent:
    return DemergerEvent(
        symbol=symbol, ex_date=ex_date, date_type="EX_DATE", record_date=ex_date,
        category=category, resulting_entity="", resulting_symbol="",
        source="TEST", source_reference="TEST", retrieved_at="2026-01-01T00:00:00Z",
        verified=verified, gap_pct_kite=None, review_reason="",
    )


def test_a_symbol_with_no_matching_events_returns_empty():
    pool = [_event("A", date(2024, 1, 1))]
    assert events_for_symbol("B", pool) == ()


def test_only_confirmed_demergers_by_default():
    pool = [
        _event("X", date(2024, 1, 1), category="DEMERGER", verified=True),
        _event("X", date(2024, 2, 1), category="DEMERGER", verified=False),
        _event("X", date(2024, 3, 1), category="NCRPS_BONUS_SCHEME", verified=True),
    ]
    result = events_for_symbol("X", pool)
    assert len(result) == 1
    assert result[0].ex_date == date(2024, 1, 1)


def test_only_confirmed_demergers_false_returns_everything_for_the_symbol():
    pool = [
        _event("X", date(2024, 1, 1), category="DEMERGER", verified=True),
        _event("X", date(2024, 2, 1), category="DEMERGER", verified=False),
        _event("X", date(2024, 3, 1), category="NCRPS_BONUS_SCHEME", verified=True),
    ]
    result = events_for_symbol("X", pool, only_confirmed_demergers=False)
    assert len(result) == 3


def test_results_are_sorted_ascending_by_ex_date_regardless_of_input_order():
    pool = [
        _event("Y", date(2024, 6, 1)),
        _event("Y", date(2024, 1, 1)),
        _event("Y", date(2024, 3, 1)),
    ]
    result = events_for_symbol("Y", pool)
    assert [e.ex_date for e in result] == [date(2024, 1, 1), date(2024, 3, 1), date(2024, 6, 1)]


def test_default_pool_loads_from_the_stored_csv_when_events_not_supplied():
    # No `events=` argument -- exercises the real on-disk demergers.csv loader path.
    result = events_for_symbol("SIEMENS")
    assert len(result) == 1
    assert result[0].verified is True
