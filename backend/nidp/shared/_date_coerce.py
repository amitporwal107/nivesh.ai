"""Date-string coercion for asyncpg `executemany` binders.

asyncpg's `executemany` uses prepared-statement binary protocol — the
$N::date SQL cast doesn't help, because encoding to the destination
type happens client-side BEFORE the cast can run server-side. So the
Python value bound to a DATE column must already be a `datetime.date`
object, not an ISO string.

Single `execute()` doesn't have this constraint (it goes through a
text-protocol path that respects the cast). That's why bulk_deals /
block_deals (which use per-row execute) didn't hit this — but every
NIDP writer using `executemany` has the latent bug.

Use `to_date(value)` in writer arg-generation to coerce strings to
date objects before passing to `executemany`.
"""
from __future__ import annotations

from datetime import date as _date_t, datetime as _datetime_t
from typing import Any, Optional


def to_date(value: Any) -> Optional[_date_t]:
    """Coerce input to `datetime.date` for asyncpg binding.

    None passes through.
    Already-a-date passes through.
    datetime → date.
    Anything else → parsed via `date.fromisoformat(str(value))`.
    """
    if value is None:
        return None
    if isinstance(value, _date_t) and not isinstance(value, _datetime_t):
        return value
    if isinstance(value, _datetime_t):
        return value.date()
    return _date_t.fromisoformat(str(value))
