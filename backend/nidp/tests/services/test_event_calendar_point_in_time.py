"""event_calendar must be able to say when a meeting became known.

fetched_at was overwritten on every refresh (median 7 days AFTER the meeting
on 2026-09-11). Now: intimated_at = NSE's bm_timestamp, first_seen_at is set
once on insert, and backfills never touch live-captured fields.
"""
from datetime import date, datetime, timedelta, timezone

from nidp.services.event_calendar import writer
from nidp.services.event_calendar.fetcher import board_meeting_event, stamp_intimations

_IST = timezone(timedelta(hours=5, minutes=30))

ROW = {"bm_symbol": "ajmera ", "bm_date": "10-Sep-2026", "bm_purpose": "Board Meeting Intimation",
       "bm_desc": "Ajmera Realty has informed the Exchange about Board Meeting to be held on 10-Sep-2026 "
                  "to consider and approve the Quarterly Unaudited Financial results for the quarter ended June 30, 2026",
       "bm_timestamp": "04-Sep-2026 18:40:31", "sm_name": "Ajmera Realty & Infra India Limited",
       "sm_indusrty": "Construction"}


def test_board_meeting_row_reads_type_from_description_and_keeps_intimation_time():
    ev = board_meeting_event(ROW)
    assert ev["symbol"] == "AJMERA"
    assert ev["event_type"] == "quarterly_results"          # generic purpose, results in bm_desc
    assert ev["event_date"] == date(2026, 9, 10)
    assert ev["intimated_at"] == datetime(2026, 9, 4, 18, 40, 31, tzinfo=_IST)
    assert ev["_industry"] == "Construction"


def test_missing_symbol_or_date_is_dropped():
    assert board_meeting_event({**ROW, "bm_symbol": ""}) is None
    assert board_meeting_event({**ROW, "bm_date": "not a date"}) is None


def test_stamp_uses_earliest_intimation_for_the_meeting():
    early = board_meeting_event(ROW)
    late = board_meeting_event({**ROW, "bm_timestamp": "08-Sep-2026 09:00:00"})
    events = [{"symbol": "AJMERA", "event_date": date(2026, 9, 10)},
              {"symbol": "OTHER", "event_date": date(2026, 9, 10)}]
    assert stamp_intimations(events, [late, early]) == 1
    assert events[0]["intimated_at"] == early["intimated_at"]
    assert "intimated_at" not in events[1]


def test_first_seen_at_is_insert_only_and_backfill_only_fills_intimated_at():
    live_update = writer._LIVE_SQL.split("DO UPDATE SET", 1)[1]
    assert "first_seen_at" not in live_update
    assert "COALESCE(nidp.event_calendar.intimated_at" in live_update
    backfill_update = writer._BACKFILL_SQL.split("DO UPDATE SET", 1)[1]
    assert backfill_update.strip().startswith("intimated_at") and "purpose" not in backfill_update
    assert writer._BACKFILL_SQL.split("VALUES", 1)[1].split(")", 1)[0].rstrip().endswith("NULL")
