"""Buyer- / seller-initiated trades from TrueData ticks (services/scan_builder/tick_flow.py) — the "10x volume first 5 min"
widget's trade-side condition.

MOCK — not real data: every tick below is hand-made; TrueData, Redis and the clock are fakes."""
import asyncio
from datetime import datetime, timedelta, timezone

from nidp.shared.sources import truedata as td
from services.scan_builder import intraday as iv
from services.scan_builder import tick_flow as tf

IST = timezone(timedelta(hours=5, minutes=30))
OPEN_1005 = datetime(2026, 11, 3, 10, 5, tzinfo=IST)          # a Tuesday, session open


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self, at: datetime):
        self.t = at.timestamp()

    def wall(self) -> float:
        return self.t

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.t, timezone.utc)

    async def sleep(self, d: float) -> None:
        self.t += max(0.0, d)
        await asyncio.sleep(0)


def tick(ts, ltp, vol, bid=None, ask=None):
    return {"timestamp": ts, "ltp": ltp, "volume": vol, "oi": 0, "bid": bid, "bidqty": 10, "ask": ask, "askqty": 10}


class FakeTD:
    """Stands in for TrueDataClient.ticks: answers the rows inside [start, end] (naive IST), records each call."""

    def __init__(self, data, clock=None, configured=True, errors=None, gate=None):
        self.data, self.clock, self.configured = data, clock, configured
        self.errors = errors or {}
        self.calls = []
        self.gate = gate

    def ticks(self, symbol, start, end, bidask=True):
        self.calls.append((symbol, start, end, self.clock.wall() if self.clock else None))
        if self.gate is not None and not self.gate.is_set():
            raise AssertionError("gate not used with run_sync")
        if symbol in self.errors:
            code = self.errors[symbol]
            raise td.TrueDataError(code, f"MOCK {code}")
        rows = [r for r in self.data.get(symbol, []) if start <= datetime.fromisoformat(r["timestamp"]) <= end]
        if not rows:
            raise td.TrueDataError(td.EMPTY_RESPONSE, "No data exists for MOCK")
        return [dict(r) for r in rows]


async def direct(fn, *args):
    return fn(*args)


def service(clock, client, store=None, first_wait=3.0, run_sync=direct):
    return tf.TickFlow(client=client, store=store if store is not None else iv.LocalStore(clock.wall), wall=clock.wall,
                       sleep=clock.sleep, now=clock.now, run_sync=run_sync, first_wait_s=first_wait)


# ── classification ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_lee_ready_classification():
    c = tf.classify
    assert c(101.0, 100.0, 101.0, None, 0) == 1           # at the ask
    assert c(101.5, 100.0, 101.0, None, 0) == 1           # through the ask
    assert c(100.0, 100.0, 101.0, None, 0) == -1          # at the bid
    assert c(100.8, 100.0, 101.0, None, 0) == 1           # inside, above the mid
    assert c(100.2, 100.0, 101.0, None, 0) == -1          # inside, below the mid
    assert c(100.5, 100.0, 101.0, 100.4, -1) == 1         # at the mid: tick test, up
    assert c(100.5, 100.0, 101.0, 100.6, 1) == -1         # at the mid: tick test, down
    assert c(100.5, 100.0, 101.0, 100.5, -1) == -1        # at the mid, unchanged: the previous side
    assert c(100.5, 100.0, 101.0, None, 0) == 0           # at the mid, nothing before: unknown
    assert c(100.5, None, None, 100.0, 0) == 1            # no bid/ask: tick test
    assert c(100.5, 0, 0, 101.0, 0) == -1                 # zero bid/ask: tick test
    assert c(100.5, 101.0, 100.0, 100.0, 0) == 1          # crossed book: tick test


def test_auction_print_and_marker_rows_are_left_out():
    rows = [
        tick("2026-11-03T09:15:00", 1284.3, 37626, 1284.3, 1286.0),     # opening auction print
        tick("2026-11-03T09:15:00", 1284.3, 1, 1284.3, 1286.0),         # marker
        tick("2026-11-03T09:15:11", 1293.3, 656688, 1292.7, 1293.3),    # at the ask → buyer
        tick("2026-11-03T09:15:11", 1299.0, 1, 1292.7, 1293.3),         # marker (outside the spread, 1 share)
        tick("2026-11-03T09:15:11", 1282.5, 1, 1292.7, 1293.3),         # marker
        tick("2026-11-03T09:15:20", 1285.1, 222983, 1285.1, 1285.9),    # at the bid → seller
        tick("2026-11-03T09:15:21", 1285.5, 500, 1285.1, 1285.9),       # at the mid, up from 1285.1 → buyer
        tick("2026-11-03T09:15:22", 1285.5, 300, None, None),           # no quote, unchanged → previous side (buyer)
        tick("2026-11-03T09:15:23", None, 300, 1285.1, 1285.9),         # no price
    ]
    st = tf.apply_rows(tf.FlowState(day="2026-11-03", fetched_at=0.0), rows)
    assert (st.buy_trades, st.sell_trades, st.unclassified) == (3, 1, 0)
    assert st.buy_volume == 656688 + 500 + 300 and st.sell_volume == 222983
    assert st.last_ts == "2026-11-03T09:15:23" and st.last_counted_ts == "2026-11-03T09:15:22"


def test_a_second_split_across_two_reads_counts_once():
    rows = [tick("2026-11-03T09:20:00", 100.0, 10, 99.9, 100.0), tick("2026-11-03T09:20:01", 100.0, 20, 99.9, 100.0),
            tick("2026-11-03T09:20:01", 99.9, 30, 99.9, 100.0), tick("2026-11-03T09:20:01", 99.95, 40, 99.9, 100.0),
            tick("2026-11-03T09:20:02", 100.1, 50, 100.0, 100.1), tick("2026-11-03T09:20:03", 100.0, 60, 100.0, 100.1)]
    whole = tf.apply_rows(tf.FlowState(day="2026-11-03", fetched_at=0.0), rows)
    part = tf.apply_rows(tf.FlowState(day="2026-11-03", fetched_at=0.0), rows[:3])     # 09:20:01 read half-way
    assert part.last_ts == "2026-11-03T09:20:01" and part.seen_at_last == 2
    part = tf.apply_rows(part, rows[1:])                  # the next read starts AT 09:20:01 (TrueData's `from` is inclusive)
    for f in ("buy_trades", "sell_trades", "buy_volume", "sell_volume", "unclassified", "last_ltp", "last_side", "last_ts"):
        assert getattr(part, f) == getattr(whole, f), f
    assert (whole.buy_trades, whole.sell_trades) == (4, 2)  # 99.95 sits at the mid of 99.9/100.0 and is up from 99.9 → buyer


# ── the service ────────────────────────────────────────────────────────────────────────────────────────────────────

def day_rows(n=300, start="2026-11-03T09:15:01"):
    """A buyer-heavy stream: 2 of every 3 ticks at the ask."""
    t0 = datetime.fromisoformat(start)
    out = []
    for i in range(n):
        ts = (t0 + timedelta(seconds=i)).isoformat()
        out.append(tick(ts, 101.0 if i % 3 else 100.0, 100 + i, 100.0, 101.0))
    return out


def test_first_read_then_cache_then_an_incremental_read():
    async def go():
        clock = Clock(OPEN_1005)
        client = FakeTD({"AAA": day_rows(), "BBB": day_rows(30)}, clock)
        svc = service(clock, client)
        r1 = await svc.counts(["AAA", "BBB"])
        assert sorted(c[0] for c in client.calls) == ["AAA", "BBB"] and r1.missing == []
        assert client.calls[0][1] == datetime(2026, 11, 3, 9, 15)          # the session from 09:15
        assert r1.values["AAA"]["buy_trades"] == 200 and r1.values["AAA"]["sell_trades"] == 100
        assert r1.as_of == "2026-11-03T09:20:00+05:30"                       # aware ISO, IST
        clock.t += 30
        r2 = await svc.counts(["AAA", "BBB"])
        assert len(client.calls) == 2 and r2.values == r1.values          # fresh for 60 s
        client.data["AAA"] += [tick("2026-11-03T10:05:20", 101.0, 999, 100.0, 101.0)]
        clock.t += 31
        await svc.counts(["AAA"])
        await svc._task
        last = [c for c in client.calls if c[0] == "AAA"][-1]
        assert last[1] == datetime(2026, 11, 3, 9, 20, 0)                   # from the last second read, not 09:15
        r3 = await svc.counts(["AAA"])
        assert r3.values["AAA"]["buy_trades"] == 201 and r3.values["AAA"]["buy_volume"] == r1.values["AAA"]["buy_volume"] + 999
        return True
    assert run(go())


def test_a_second_worker_uses_the_first_workers_counts():
    async def go():
        clock = Clock(OPEN_1005)
        store = iv.LocalStore(clock.wall)
        client = FakeTD({"AAA": day_rows()}, clock)
        w1, w2 = service(clock, client, store), service(clock, client, store)
        r1 = await w1.counts(["AAA"])
        r2 = await w2.counts(["AAA"])
        assert len(client.calls) == 1 and r2.values == r1.values
        return True
    assert run(go())


def test_truedata_calls_are_spaced_across_workers():
    async def go():
        clock = Clock(OPEN_1005)
        store = iv.LocalStore(clock.wall)
        syms = [f"S{i}" for i in range(9)]
        client = FakeTD({s: day_rows(20) for s in syms}, clock)
        workers = [service(clock, client, store) for _ in range(3)]
        for i, s in enumerate(syms):                      # the workers take turns, as uvicorn's would
            await workers[i % 3]._refresh_one(s)
        for s in syms:                                    # a symbol another worker just read is not read again
            await workers[(syms.index(s) + 1) % 3]._refresh_one(s)
        times = [c[3] for c in client.calls]
        assert [c[0] for c in client.calls] == syms
        assert all(b - a >= tf.SPACING_S - 1e-6 for a, b in zip(times, times[1:]))      # epoch floats: µs tolerance
        return True
    assert run(go())


def test_not_configured_reads_nothing_and_says_so():
    async def go():
        clock = Clock(OPEN_1005)
        client = FakeTD({"AAA": day_rows()}, clock, configured=False)
        r = await service(clock, client).counts(["AAA"])
        assert r.values == {} and r.missing == ["AAA"] and client.calls == []
        assert r.warnings[0].startswith("No TrueData login")
        return True
    assert run(go())


def test_truedata_errors_leave_the_symbol_missing_with_the_reason_and_never_raise():
    async def go():
        clock = Clock(OPEN_1005)
        client = FakeTD({"AAA": day_rows(), "QQQ": []}, clock,
                        errors={"BBB": td.RATE_LIMITED, "ZZZ": td.IDENTIFIER_NOT_RESOLVED})
        svc = service(clock, client)
        r = await svc.counts(["AAA", "BBB", "ZZZ", "QQQ"])
        assert set(r.values) == {"AAA"} and sorted(r.missing) == ["BBB", "QQQ", "ZZZ"]
        text = " | ".join(r.warnings)
        assert "loading (1 of 4 stocks)" in text and "quota" in text
        assert "does not know ZZZ" in text and "no ticks on 2026-11-03 for QQQ" in text
        client.errors.pop("BBB")
        client.data["BBB"] = day_rows(10)
        clock.t += 61
        await svc.counts(["BBB"])
        await svc._task
        assert (await svc.counts(["BBB"])).values["BBB"]["buy_trades"] > 0       # retried next cycle
        return True
    assert run(go())


def test_first_call_waits_briefly_then_lists_the_rest_as_loading():
    async def go():
        clock = Clock(OPEN_1005)
        client = FakeTD({"AAA": day_rows()}, clock)
        release = asyncio.Event()

        async def slow(fn, *args):
            await release.wait()
            return fn(*args)
        svc = service(clock, client, first_wait=0.05, run_sync=slow)
        r = await svc.counts(["AAA"])
        assert r.values == {} and r.missing == ["AAA"] and r.warnings[0] == "trade-side ticks are loading (1 of 1 stocks)"
        release.set()
        await svc._task
        assert (await svc.counts(["AAA"])).values["AAA"]["buy_trades"] == 200
        return True
    assert run(go())


def test_after_the_close_the_day_is_read_once_more_then_kept():
    async def go():
        clock = Clock(datetime(2026, 11, 3, 15, 31, tzinfo=IST))
        rows = day_rows(20) + [tick("2026-11-03T15:29:59", 101.0, 77, 100.0, 101.0), tick("2026-11-03T15:45:00", 101.0, 88, 100.0, 101.0)]
        client = FakeTD({"AAA": rows}, clock)
        svc = service(clock, client)
        r1 = await svc.counts(["AAA"])
        assert client.calls[-1][2] == datetime(2026, 11, 3, 15, 30)         # up to the close, not the post-close session
        assert "Market closed" in r1.warnings[-1]
        clock.t += 300                                                     # 15:36: the 15:31 read was before the close settled
        await svc.counts(["AAA"])
        await svc._task
        n = len(client.calls)
        clock.t += 3600
        await svc.counts(["AAA"])
        assert len(client.calls) == n == 2                                 # then kept
        return True
    assert run(go())


def test_before_the_open_the_counts_are_the_last_sessions():
    async def go():
        clock = Clock(datetime(2026, 11, 3, 8, 0, tzinfo=IST))             # Tuesday 08:00 → Monday's session
        client = FakeTD({"AAA": day_rows(20, start="2026-11-02T09:15:01")}, clock)
        r = await service(clock, client).counts(["AAA"])
        assert client.calls[0][1] == datetime(2026, 11, 2, 9, 15) and client.calls[0][2] == datetime(2026, 11, 2, 15, 30)
        assert r.values["AAA"]["buy_trades"] > 0 and r.as_of.startswith("2026-11-02T")
        return True
    assert run(go())
