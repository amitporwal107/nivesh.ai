import datetime as dt
import json

import pytest

import tl_cache as T

IST = T.IST


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class FakeStore:
    def __init__(self, clock):
        self.clock, self.d, self.h = clock, {}, {}

    def _live(self, k):
        v = self.d.get(k)
        if v and v[1] > self.clock():
            return v[0]
        self.d.pop(k, None)
        return None

    def mget(self, keys):
        return [self._live(k) for k in keys]

    def get(self, k):
        return self._live(k)

    def set_many(self, items):
        for k, (v, ttl) in items.items():
            self.d[k] = (v, self.clock() + dt.timedelta(seconds=ttl))

    def incr(self, k, ttl):
        n = int(self._live(k) or 0) + 1
        self.d[k] = (str(n), self.clock() + dt.timedelta(seconds=ttl))
        return n

    def hgetall(self, k):
        return dict(self.h.get(k, {}))

    def hset_many(self, k, mapping, ttl):
        self.h.setdefault(k, {}).update(mapping)

    def scan(self, pattern):
        import fnmatch
        return [k for k in list(self.d) if fnmatch.fnmatch(k, pattern) and self._live(k) is not None]

    def delete(self, keys):
        for k in keys:
            self.d.pop(k, None)


LABELS = {"roea": "ROE Ann. %", "prompct": "Promoter holding latest %", "pettm": "PE TTM", "currentprice": "LTP",
          "npqgrowth": "Net Profit Qtr Growth YoY %", "cvolday": "Consolidated EOD Volume"}


class FakeServer:
    """Mimics get_stock_parameter_values: limits, whole-batch rejection, header + label blocks."""

    def __init__(self, n=30):
        self.stocks = {f"S{i:02d}": {"isin": f"INE{i:03d}X01010", "bse": str(500000 + i)} for i in range(n)}
        self.calls = []

    def value(self, code, p):
        return f"{code}-{p}"

    def call(self, tool, args):
        self.calls.append((tool, json.loads(json.dumps(args))))
        cs, ps = args["stock_codes"], args["parameters"]
        if len(cs) > 10:
            return json.dumps({"status": "error", "message": "Maximum 10 stock codes allowed per call. [code:1012]"})
        if len(ps) > 50:
            return json.dumps({"status": "error", "message": "Maximum 50 parameters allowed per call. [code:1012]"})
        by = {}
        for c in cs:
            hit = next((k for k, v in self.stocks.items() if c in (k, v["isin"], v["bse"])), None)
            by[c] = hit
        bad = [c for c, h in by.items() if h is None]
        if bad:
            return json.dumps({"status": "error", "message": f"Could not resolve stock code(s): {';'.join(bad)}. [code:1012]"})
        head = "\n".join(f"1|Name {h}|{h}|{self.stocks[h]['bse']}|2026-09-18" for h in by.values())
        blocks = [LABELS[p] + "\n" + "\n".join(f"{h}:{self.value(h, p)}" for h in by.values()) for p in reversed(ps)]
        return json.dumps({"status": "success", "data": head + "\n\n" + "\n\n---\n\n".join(blocks) + "\n\n---"})


@pytest.fixture
def env(tmp_path):
    clock = Clock(dt.datetime(2026, 9, 19, 9, 40, tzinfo=IST))  # Saturday, outside filing season
    store, srv = FakeStore(clock), FakeServer()
    c = T.TLCache(srv, store, daily_cap=100, now=clock, archive_dir=str(tmp_path / "archive"))
    c.seed_labels(LABELS)
    return clock, store, srv, c


def test_classify():
    for lab in ["LTP", "PE TTM", "Market Cap", "Price to Sales TTM", "1Yr High", "Month Chg %", "Delivery% Vol. Avg Week",
                "Durability Score", "Day RSI"]:
        assert T.classify(lab) == "eod", lab
    for lab in ["ROE Ann. %", "Promoter holding latest %", "Promoter holding change QoQ %", "Net Profit Qtr Growth YoY %",
                "Total Debt to Total Equity Annual", "Cash Flow from Operations Annual", "Net Debt Ann."]:
        assert T.classify(lab) == "filing", lab


def test_expiry_rules():
    sat = dt.datetime(2026, 9, 19, 9, 40, tzinfo=IST)
    assert T.next_0700_ist(sat) == dt.datetime(2026, 9, 20, 7, 0, tzinfo=IST)
    assert T.next_0700_ist(sat.replace(hour=6)) == dt.datetime(2026, 9, 19, 7, 0, tzinfo=IST)
    oct15 = dt.datetime(2026, 10, 15, 20, 0, tzinfo=IST)  # results season: quarterly data is still NOT refetched daily
    assert T.expiry("filing", sat) == T.expiry("filing", oct15) == T.expiry("event", oct15) == 7 * T.DAY
    assert T.expiry("eod", oct15) == 11 * 3600


def test_second_request_makes_no_calls(env):
    _, _, srv, c = env
    codes, ps = [f"S{i:02d}" for i in range(25)], list(LABELS)
    first = c.get_params(codes, ps)
    assert len(srv.calls) == 3 and all(len(a["stock_codes"]) <= 10 for _, a in srv.calls)
    assert first["S07"]["roea"] == "S07-roea" and first["S24"]["cvolday"] == "S24-cvolday"
    again = c.get_params(codes, ps)
    assert len(srv.calls) == 3 and again == first


def test_only_missing_stocks_are_fetched(env):
    _, _, srv, c = env
    c.get_params([f"S{i:02d}" for i in range(12)], list(LABELS))
    n = len(srv.calls)
    c.get_params([f"S{i:02d}" for i in range(15)], list(LABELS))
    assert len(srv.calls) == n + 1 and sorted(srv.calls[-1][1]["stock_codes"]) == ["S12", "S13", "S14"]


def test_next_day_refetches_only_eod_parameters(env):
    clock, _, srv, c = env
    c.get_params(["S01", "S02"], list(LABELS))
    clock.t = dt.datetime(2026, 9, 20, 7, 5, tzinfo=IST)  # past 07:00; outside filing season -> filing still cached
    out = c.get_params(["S01", "S02"], list(LABELS))
    assert sorted(srv.calls[-1][1]["parameters"]) == ["currentprice", "cvolday", "pettm"]
    assert out["S01"]["prompct"] == "S01-prompct"


def test_unresolvable_code_is_dropped_and_remembered(env):
    _, _, srv, c = env
    out = c.get_params(["S01", "BOGUS", "S02"], ["roea"])
    assert set(out) == {"S01", "S02"} and len(srv.calls) == 2 and c.stats["rejected"] == 1
    c.get_params(["S01", "BOGUS", "S02"], ["roea"])
    assert len(srv.calls) == 2  # cached values + cached 'unresolvable' -> no call


def test_isin_request_is_attributed(env):
    _, _, srv, c = env
    out = c.get_params(["INE003X01010", "S05"], ["roea"])
    assert out["INE003X01010"]["roea"] == "S03-roea" and out["S05"]["roea"] == "S05-roea"


def test_daily_cap_stops_calls(env):
    _, _, srv, c = env
    c.daily_cap = 1
    c.get_params(["S01"], ["roea"])
    with pytest.raises(T.BudgetExceeded):
        c.get_params(["S02"], ["roea"])
    assert len(srv.calls) == 1 and c.calls_today() == 1


def test_unmapped_parameter_is_not_cached_as_blank(env):
    _, store, srv, c = env
    LABELS.update(zzz="Something Else Entirely", yyy="Another Unrelated Metric")
    try:
        c.get_params(["S01"], ["zzz", "yyy"])  # two unknown labels, no confident match -> neither is cached
        assert c.stats.get("unmapped") == {"zzz", "yyy"}
        assert store.get(f"{T.PREFIX}pv:S01:zzz") is None
    finally:
        LABELS.pop("zzz")
        LABELS.pop("yyy")


def test_unresolved_codes_parser():
    from tl_client import unresolved_codes
    assert unresolved_codes("Could not resolve stock code(s): BOGUS. [code:1012]", ["S01", "BOGUS"]) == ["BOGUS"]
    msg = "Could not resolve stock code(s): GAYAPROJ;SINDHUTRAD. [code:1012]"
    assert unresolved_codes(msg, ["GAYAPROJ;SINDHUTRAD", "SINDHU"]) == ["GAYAPROJ;SINDHUTRAD"]
    assert unresolved_codes("Maximum 10 stock codes allowed per call. [code:1012]", ["S01"]) == []


def test_ingest_keeps_original_expiry(env):
    clock, store, srv, c = env
    text = srv.call("get_stock_parameter_values", {"stock_codes": ["S01"], "parameters": ["roea", "pettm"]})
    fetched = dt.datetime(2026, 9, 19, 9, 0, tzinfo=IST)
    assert c.ingest(["S01"], ["roea", "pettm"], text, fetched) == 2
    n = len(srv.calls)
    assert c.get_params(["S01"], ["roea", "pettm"]) == {"S01": {"roea": "S01-roea", "pettm": "S01-pettm"}}
    assert len(srv.calls) == n
    clock.t = dt.datetime(2026, 9, 20, 7, 1, tzinfo=IST)  # the eod value (PE) expired at 07:00, the filing one did not
    assert store.get(f"{T.PREFIX}pv:S01:pettm") is None and store.get(f"{T.PREFIX}pv:S01:roea") is not None


def test_partly_cached_stocks_share_one_call(env):
    _, _, srv, c = env
    c.get_params(["S01"], ["roea", "pettm"])
    n = len(srv.calls)
    out = c.get_params(["S01", "S02", "S03"], list(LABELS))  # S01 misses 4 params, S02/S03 miss all 6 -> one call
    assert len(srv.calls) == n + 1 and out["S03"]["cvolday"] == "S03-cvolday"


def test_plan_batches_limits():
    miss = {f"C{i:02d}": {f"p{j}" for j in range(60)} for i in range(3)}
    b = T.plan_batches(miss)
    assert all(len(cs) <= 10 and len(ps) <= 50 for cs, ps in b)
    assert sorted((c, p) for cs, ps in b for c in cs for p in ps if p in miss[c]) == sorted((c, p) for c in miss for p in miss[c])
    assert len(T.plan_batches({f"C{i:02d}": {"a"} for i in range(25)})) == 3


def test_every_fetch_is_archived_once_and_readable(env):
    clock, _, srv, c = env
    c.get_params(["S01", "S02"], ["roea", "pettm"])
    c.get_params(["S01", "S02"], ["roea", "pettm"])  # served from cache -> not archived again
    recs = list(T.read_archive("param_values", c.archive_dir))
    assert len(recs) == 1 and recs[0]["values"]["S02"]["pettm"] == "S02-pettm" and recs[0]["asof"]["S01"] == "2026-09-18"
    clock.t = dt.datetime(2026, 9, 20, 7, 5, tzinfo=IST)  # next day: the eod value is refetched and archived again
    c.get_params(["S01", "S02"], ["roea", "pettm"])
    days = [r["fetched_at"][:10] for r in T.read_archive("param_values", c.archive_dir)]
    assert days == ["2026-09-19", "2026-09-20"]
    assert list(T.read_archive("param_values", c.archive_dir, start="2026-09-20"))[0]["params"] == ["pettm"]


def test_exact_label_beats_lookalikes_and_restore_recaches(env):
    clock, store, srv, c = env
    LABELS.update(sma20="Day SMA20", sma200="Day SMA200", sma50="Day SMA50")
    try:
        c.seed_param_text({"sma20": "Day SMA20", "sma200": "Day SMA200", "sma50": "Day SMA50"})
        out = c.get_params(["S01"], ["sma20", "sma200", "sma50"])
        assert out["S01"] == {"sma20": "S01-sma20", "sma200": "S01-sma200", "sma50": "S01-sma50"}
        rec = list(T.read_archive("param_values", c.archive_dir))[-1]
        for k in list(store.d):
            if ":pv:" in k:
                store.d.pop(k)
        n = len(srv.calls)
        assert c.restore(rec) == 3 and c.get_params(["S01"], ["sma50"])["S01"]["sma50"] == "S01-sma50"
        assert len(srv.calls) == n and len(list(T.read_archive("param_values", c.archive_dir))) == 1
    finally:
        for k in ("sma20", "sma200", "sma50"):
            LABELS.pop(k)


def test_invalidate_filing_refetches_only_that_stock(env):
    clock, _, srv, c = env
    c.get_params(["S01", "S02", "S03"], list(LABELS))
    n = len(srv.calls)
    assert c.invalidate("S02", "filing") >= 3
    out = c.get_params(["S01", "S02", "S03"], list(LABELS))
    assert len(srv.calls) == n + 1
    assert srv.calls[-1][1]["stock_codes"] == ["S02"] and sorted(srv.calls[-1][1]["parameters"]) == ["npqgrowth", "prompct", "roea"]
    assert out["S02"]["roea"] == "S02-roea"


def test_news_triggers():
    news = ("newsList:\n  NSEcode | pubDate | title | description\n"
            "  X | 2026-09-18T06:00:00+00:00 | X Ltd - Outcome of Board Meeting | Financial results for the quarter\n"
            "  X | 2026-09-18T07:00:00+00:00 | X Ltd - Record Date for Dividend | Interim dividend\n"
            "  X | 2026-09-01T07:00:00+00:00 | X Ltd - Shareholding Pattern | old item\n")
    hits, newest = T.news_triggers(news, "2026-09-17")
    assert hits == {"filing", "event"} and newest == "2026-09-18T07:00:00+00:00"
    assert T.news_triggers(news, newest) == (set(), newest)  # already processed -> no second trigger
    assert T.news_triggers(news, "2026-09-19")[0] == set()


def test_monthly_cap(env):
    _, store, srv, c = env
    c.monthly_cap = 1
    c.get_params(["S01"], ["roea"])
    with pytest.raises(T.BudgetExceeded, match="monthly"):
        c.get_params(["S02"], ["roea"])
