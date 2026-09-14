"""A4 event timestamp gate: an event is known for T only if intimated at or before 15:30 IST on T."""
from datetime import date

import pandas as pd

from nidp.tests.services.tpd_model.conftest import IST, NOT_IMPLEMENTED, ist

pytestmark = NOT_IMPLEMENTED

T = date(2026, 9, 11)
D = date(2026, 9, 15)


def _events(ts):
    """intimated_at is timestamptz in nidp.event_calendar, so the column stays tz-aware even when NULL."""
    return pd.DataFrame({
        "symbol": ["ACME"],
        "event_date": [pd.Timestamp(D)],
        "intimated_at": pd.Series([ts], dtype="datetime64[ns, Asia/Kolkata]"),
    })


def test_cutoff_is_1530_ist_on_T():
    from nidp.services.tpd_model.event_gate import cutoff_ist

    c = cutoff_ist(T)
    assert c == ist(T, 15, 30)
    assert c.utcoffset() == IST.utcoffset(c)


def test_intimation_at_exactly_1530_is_known():
    from nidp.services.tpd_model.event_gate import results_flag

    ts = ist(T, 15, 30, 0)
    assert results_flag(_events(ts), "ACME", T, D) == (True, ts)


def test_intimation_one_second_after_cutoff_is_not_known():
    from nidp.services.tpd_model.event_gate import results_flag

    assert results_flag(_events(ist(T, 15, 30, 1)), "ACME", T, D) == (False, None)


def test_null_timestamp_gives_null_not_a_proxy_date():
    from nidp.services.tpd_model.event_gate import results_flag

    assert results_flag(_events(pd.NaT), "ACME", T, D) == (None, None)


def test_no_event_is_false():
    from nidp.services.tpd_model.event_gate import results_flag

    assert results_flag(_events(ist(T, 9, 0)), "OTHER", T, D) == (False, None)


def test_regression_bm_data_319_evening_intimation_leak():
    """Research gated on `ts < meeting_date` (bm_data.py:319): a 19:05 intimation on T passed that check
    and fed the prediction made at T's 15:30 cutoff. The new gate must exclude it."""
    from nidp.services.tpd_model.event_gate import results_flag

    evening = ist(T, 19, 5)
    old_rule_includes = evening < pd.Timestamp(D).tz_localize(IST)
    assert old_rule_includes  # documents the leak
    assert results_flag(_events(evening), "ACME", T, D) == (False, None)
