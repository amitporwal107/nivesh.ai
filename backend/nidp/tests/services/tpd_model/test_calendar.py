"""A9 next session: NSE CM holidays, weekend special sessions, Muhurat (K6), unknown calendar."""
from datetime import date

import pytest


GANESH = date(2026, 9, 14)


def test_2026_09_11_close_targets_2026_09_15():
    from nidp.services.tpd_model.calendar import next_trading_day

    session, skipped = next_trading_day(date(2026, 9, 11), holidays={GANESH}, known_until=date(2026, 12, 31))
    assert session == date(2026, 9, 15)
    assert skipped == [GANESH]


def test_weekends_are_not_reported_as_skipped_holidays():
    from nidp.services.tpd_model.calendar import next_trading_day

    session, skipped = next_trading_day(date(2026, 9, 4), holidays=set(), known_until=date(2026, 12, 31))
    assert (session, skipped) == (date(2026, 9, 7), [])


def test_only_cm_segment_rows_count_as_holidays():
    """023_nidp_market_session.sql:58 matches a holiday in ANY segment; the CM filter must not."""
    from nidp.services.tpd_model.calendar import cm_holidays

    rows = [
        {"holiday_date": GANESH, "segment": "CM"},
        {"holiday_date": GANESH, "segment": "FO"},
        {"holiday_date": date(2026, 10, 2), "segment": "COM"},
    ]
    assert cm_holidays(rows) == {GANESH}


def test_weekend_special_session_is_a_trading_day():
    from nidp.services.tpd_model.calendar import next_trading_day

    session, _ = next_trading_day(date(2026, 1, 30), holidays=set(), special_sessions={date(2026, 2, 1)},
                                  known_until=date(2026, 12, 31))
    assert session == date(2026, 2, 1)


def test_muhurat_session_is_never_a_target():
    from nidp.services.tpd_model.calendar import next_trading_day

    diwali = date(2026, 11, 9)
    session, skipped = next_trading_day(date(2026, 11, 6), holidays={diwali}, muhurat_sessions={diwali},
                                        known_until=date(2026, 12, 31))
    assert session == date(2026, 11, 10)
    assert skipped == [diwali]


def test_beyond_known_calendar_refuses_instead_of_assuming_weekdays():
    from nidp.services.tpd_model.calendar import CalendarUnknownError, next_trading_day

    with pytest.raises(CalendarUnknownError):
        next_trading_day(date(2026, 12, 31), holidays=set(), known_until=date(2026, 12, 31))
