"""Helpers for picking the right "as-of" trading date.

Indian market data sources (NSE bhavcopy, delivery, index closes,
fii_dii, etc.) publish their EOD files after market close, around
18:00 IST. A job run at any time before that will 404 on "today's"
file because it doesn't exist yet — and on weekends/holidays there
is no file at all.

`default_target_date()` returns the safest "yesterday IST" date —
always already published, never inflight. Callers that explicitly
want today (e.g. a scheduled 19:00 IST run) should pass `--date`.

The helper does NOT walk through weekends/holidays; it just goes
back one calendar day. The ingester layer is expected to handle
404 / empty file gracefully (BaseIngester already does — finalizes
as FAILED with error_class=HTTP and a clean job_log row).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def default_target_date() -> date:
    """Yesterday in IST. Used as the default for any ingester whose
    upstream publishes after Indian market close."""
    return (datetime.now(IST) - timedelta(days=1)).date()


def today_ist() -> date:
    """Today in IST (rarely the right default — most NSE files lag).
    Use this only for jobs scheduled to run after 18:00 IST."""
    return datetime.now(IST).date()
