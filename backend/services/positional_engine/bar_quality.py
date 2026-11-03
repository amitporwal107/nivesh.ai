"""Data-quality checks for the scanner's bar store (`stock_ohlcv`), shared by the evening job and the repair tool.

Checks, each reported as a count plus sample symbols or dates:

  missing_sessions   warehouse sessions the store has no bars for
  extra_dates        store dates that are not warehouse sessions (a holiday or weekend "session")
  copied_sessions    store dates whose bars repeat the previous stored date for >= COPIED_SESSION_SHARE of symbols
  duplicate_bars     bars identical (open, high, low, close, volume) to the same symbol's previous bar
  stale_symbols      symbols with bars in the window but none on its last date
  invalid_ohlc       high < low, open or close outside [low, high], or a price <= 0 / missing
  zero_volume        bars with zero or missing volume

The checker is fed one date at a time (oldest first) so a year of bars never sits in memory.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Dict, Iterable, List, Optional, Set, Tuple

COPIED_SESSION_SHARE = 0.9   # a real session never repeats the previous one for 90% of symbols
SAMPLE = 10

Bar = Tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[int]]   # o, h, l, c, v


def _invalid(bar: Bar) -> Optional[str]:
    o, h, l, c, _v = bar
    if any(x is None for x in (o, h, l, c)):
        return "price_missing"
    if min(o, h, l, c) <= 0:
        return "price_not_positive"
    if h < l:
        return "high_below_low"
    if not (l <= o <= h):
        return "open_outside_range"
    if not (l <= c <= h):
        return "close_outside_range"
    return None


class BarQuality:
    def __init__(self, sessions: Optional[Set[date]] = None, *, sample: int = SAMPLE):
        self.sessions = sessions
        self.sample = sample
        self.dates: List[date] = []
        self.rows = 0
        self._prev_date: Optional[date] = None
        self._prev_rows: Dict[str, Bar] = {}
        self._last_bar: Dict[str, Bar] = {}
        self._last_seen: Dict[str, date] = {}
        self.per_date: List[dict] = []
        self.duplicates: List[Tuple[date, str]] = []
        self.invalid: List[Tuple[date, str, str]] = []
        self.zero_volume: List[Tuple[date, str]] = []

    def add_date(self, d: date, rows: Dict[str, Bar]) -> None:
        """Feed every bar of one date (dates must arrive oldest first)."""
        if self.dates and d <= self.dates[-1]:
            raise ValueError(f"dates must be fed in ascending order ({d} after {self.dates[-1]})")
        identical = 0
        for sym, bar in rows.items():
            if self._prev_rows.get(sym) == bar:
                identical += 1
            if self._last_bar.get(sym) == bar:
                self.duplicates.append((d, sym))
            why = _invalid(bar)
            if why:
                self.invalid.append((d, sym, why))
            if not bar[4]:
                self.zero_volume.append((d, sym))
            self._last_bar[sym] = bar
            self._last_seen[sym] = d
        self.per_date.append({"date": d, "rows": len(rows), "prev_date": self._prev_date,
                              "identical_to_prev": identical,
                              "all_symbols_on_prev": all(s in self._prev_rows for s in rows)})
        self.dates.append(d)
        self.rows += len(rows)
        self._prev_date, self._prev_rows = d, rows

    def copied_dates(self) -> List[dict]:
        out = []
        for r in self.per_date:
            if r["prev_date"] and r["rows"] and r["identical_to_prev"] / r["rows"] >= COPIED_SESSION_SHARE:
                out.append({**r, "share": round(r["identical_to_prev"] / r["rows"], 4)})
        return out

    def report(self) -> dict:
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        copied = self.copied_dates()
        copied_set = {r["date"] for r in copied}
        store = set(self.dates)
        out: dict = {
            "window": [iso(self.dates[0]) if self.dates else None, iso(self.dates[-1]) if self.dates else None],
            "dates": len(self.dates),
            "rows": self.rows,
            "symbols": len(self._last_seen),
            "copied_sessions": {
                "count": len(copied),
                "dates": [{"date": iso(r["date"]), "prev_date": iso(r["prev_date"]), "rows": r["rows"],
                           "identical": r["identical_to_prev"], "share": r["share"]} for r in copied],
            },
        }
        if self.sessions is not None and self.dates:
            lo, hi = self.dates[0], self.dates[-1]
            in_window = {d for d in self.sessions if lo <= d <= hi}
            missing = sorted(in_window - store)
            extra = sorted(store - self.sessions)
            out["missing_sessions"] = {"count": len(missing), "dates": [iso(d) for d in missing]}
            out["extra_dates"] = {"count": len(extra), "dates": [iso(d) for d in extra]}
        dup_outside = [(d, s) for d, s in self.duplicates if d not in copied_set]
        out["duplicate_bars"] = {
            "count": len(self.duplicates),
            "on_copied_sessions": len(self.duplicates) - len(dup_outside),
            "outside_copied_sessions": len(dup_outside),
            "sample": [f"{s} {iso(d)}" for d, s in dup_outside[:self.sample]],
        }
        last = self.dates[-1] if self.dates else None
        position = {d: i for i, d in enumerate(self.dates)}
        stale = sorted(((s, d) for s, d in self._last_seen.items() if last and d < last),
                       key=lambda t: (t[1], t[0]), reverse=True)
        behind = Counter()
        for _s, d in stale:
            n = len(self.dates) - 1 - position[d]
            behind["1" if n == 1 else "2-5" if n <= 5 else ">5"] += 1
        out["stale_symbols"] = {
            "count": len(stale), "sessions_behind": dict(behind),
            "sample": [{"symbol": s, "last_bar": iso(d), "sessions_behind": len(self.dates) - 1 - position[d]}
                       for s, d in stale[:self.sample]],
        }
        out["invalid_ohlc"] = {
            "count": len(self.invalid), "by_rule": dict(Counter(w for _d, _s, w in self.invalid)),
            "sample": [f"{s} {iso(d)} {w}" for d, s, w in self.invalid[:self.sample]],
        }
        out["zero_volume"] = {"count": len(self.zero_volume),
                              "sample": [f"{s} {iso(d)}" for d, s in self.zero_volume[:self.sample]]}
        return out


def is_clean(report: dict) -> Tuple[bool, List[str]]:
    """(clean, problems) for the market-wide checks a run must not score through: missing sessions, non-session
    dates, copied sessions, invalid OHLC. Stale symbols, per-symbol duplicates and zero volume are reported only."""
    problems = []
    for key in ("missing_sessions", "extra_dates", "copied_sessions", "invalid_ohlc"):
        n = (report.get(key) or {}).get("count", 0)
        if n:
            problems.append(f"{key}={n}")
    return not problems, problems


async def store_dates(conn, start: date, end: date) -> List[date]:
    rows = await conn.fetch(
        "SELECT DISTINCT bar_date FROM stock_ohlcv WHERE bar_date BETWEEN $1 AND $2 ORDER BY bar_date", start, end)
    return [r["bar_date"] for r in rows]


async def bars_on(conn, d: date) -> Dict[str, Bar]:
    rows = await conn.fetch(
        "SELECT nse_symbol, open_price::float8 o, high_price::float8 h, low_price::float8 l, close_price::float8 c,"
        " volume v FROM stock_ohlcv WHERE bar_date = $1", d)
    return {r["nse_symbol"]: (r["o"], r["h"], r["l"], r["c"], r["v"]) for r in rows}


async def check_store(pool, start: date, end: date, sessions: Optional[Set[date]] = None,
                      skip_dates: Iterable[date] = ()) -> dict:
    """Run every check over stock_ohlcv in [start, end] (read-only). `sessions` are the authoritative sessions for the
    missing/extra checks (None skips those two); `skip_dates` are left out entirely (e.g. phantom dates, to check the
    store as it would be after a repair)."""
    skip = set(skip_dates)
    q = BarQuality(sessions)
    async with pool.acquire() as conn:
        for d in await store_dates(conn, start, end):
            if d not in skip:
                q.add_date(d, await bars_on(conn, d))
    return q.report()
