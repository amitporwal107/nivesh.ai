"""The user's Chartink dashboard in the Smart Trading Desk: services/chartink_desk (dashboard, store, refresh, hits), routes/desk_chartink.py,
scripts/refresh_chartink.py and the typed screener client in services/positional_engine/chartink_api.py.

No network and no real database. Everything below is MOCK — not real data: invented scan names ("Mock Alpha ..."), invented clauses, invented symbols
(AAA, BBB ...). No clause or name from any real dashboard appears here. Expected values are computed from the payloads.
"""
from __future__ import annotations

import asyncio
import copy
import html
import io
import json
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import routes.desk_chartink as route
from services import symbol_lookup as sl
from services.chartink_desk import dashboard as dash
from services.chartink_desk import hits as hits_mod
from services.chartink_desk import refresh as rf
from services.chartink_desk import store
from services.positional_engine import chartink_api

NOW = datetime(2026, 10, 20, 11, 0, tzinfo=timezone.utc)          # 16:30 IST, Tuesday: after the close
MORNING = datetime(2026, 10, 20, 5, 0, tzinfo=timezone.utc)       # 10:30 IST: during the session
TODAY = date(2026, 10, 20)
A, B = {"X-Test-User": "user_a"}, {"X-Test-User": "user_b"}
URL = "https://chartink.com/dashboard/123456"


# ── MOCK dashboard pages ─────────────────────────────────────────────────────

SELECT = "select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' "


def widget(wid, name, clause="( {cash} ( latest close > 100 ) )", group="symbol", select=SELECT, **o):
    w = {"id": wid, "name": name, "description": f"{name} description", "query": f"{select}WHERE {clause} GROUP BY {group} ORDER BY 1 desc", "layout": {}}
    w.update(o)
    return w


def stats_widget(wid, name):
    q = ("select groupcount( {cash} 1 where latest close > 1 day ago close ) / groupcount( {cash} 1 ) * 100 as 'Advances', "
         "groupcount( {cash} 1 where latest close < 1 day ago close ) as 'Declines' WHERE {cash} 1 = 1 GROUP BY marketcapname ORDER BY 1 desc")
    return {"id": wid, "name": name, "description": None, "query": q}


def listing_widget(wid, name):
    """Groups by symbol but only lists an index universe: no price column, no condition."""
    return {"id": wid, "name": name, "description": None,
            "query": "select Latest Close as 'Ltp', Latest \"close - 1 candle ago close\" as '% chg' WHERE {99001} 1 = 1 GROUP BY symbol ORDER BY 1 desc"}


def page(widgets, title="Mock Dashboard", quote='"'):
    payload = html.escape(json.dumps(widgets), quote=True)
    return f"<!DOCTYPE html><html><head><title>{title}</title></head><body><div id=app :widgets={quote}{payload}{quote}></div></body></html>"


def standard_widgets():
    return [widget(1001, "Mock Alpha Scan"), widget(1002, "Mock Beta Scan", "( {cash} ( latest rsi( 14 ) > 60 ) )"),
            widget(1003, "Mock Gamma Intraday", "( {cash} ( [0] 15 minute close > [-1] 15 minute high ) )"),
            widget(1004, "Mock Delta Universe", "( {99001} ( latest volume > 1000 ) )"),
            widget(1005, "Mock Epsilon Inline", '( {cash} ( latest {custom_indicator_7_start}"close - low"{custom_indicator_7_end} > 1 ) )'),
            widget(1006, "Mock Zeta Orphan", "( {cash} ( latest {custom_indicator_9_start}\"close - low\" > 1 ) )"),
            stats_widget(1007, "Mock Breadth Stats"), listing_widget(1008, "Mock Index Listing")]


# ── a fake Mongo that knows only what the desk uses ──────────────────────────

def _get(doc, path):
    cur = doc
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _match(doc, q):
    for k, cond in q.items():
        if k == "$or":
            if not any(_match(doc, c) for c in cond):
                return False
            continue
        v = _get(doc, k)
        if isinstance(cond, dict) and any(x.startswith("$") for x in cond):
            for op, arg in cond.items():
                if op == "$lte" and not (v is not None and v <= arg):
                    return False
                if op == "$lt" and not (v is not None and v < arg):
                    return False
                if op == "$in" and v not in arg:
                    return False
        elif v != cond:
            return False
    return True


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction):
        self.docs = sorted(self.docs, key=lambda d: str(d.get(key) or ""), reverse=direction < 0)
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    async def to_list(self, n):
        return self.docs if n is None else self.docs[:n]


class Col:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
        self.writes = 0

    def find(self, q=None):
        return Cursor([copy.deepcopy(d) for d in self.docs if _match(d, q or {})])

    async def find_one(self, q):
        return next((copy.deepcopy(d) for d in self.docs if _match(d, q)), None)

    async def insert_many(self, docs):
        self.writes += 1
        self.docs += [copy.deepcopy(d) for d in docs]

    async def replace_one(self, q, doc, upsert=False):
        self.writes += 1
        for i, d in enumerate(self.docs):
            if _match(d, q):
                self.docs[i] = copy.deepcopy(doc)
                return SimpleNamespace(matched_count=1)
        if upsert:
            self.docs.append(copy.deepcopy(doc))
        return SimpleNamespace(matched_count=0)

    async def update_one(self, q, update):
        assert set(update) == {"$set"}
        for d in self.docs:
            if _match(d, q):
                self.writes += 1
                for path, val in update["$set"].items():
                    parts = path.split(".")
                    cur = d
                    for p in parts[:-1]:
                        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
                    if isinstance(cur, list):
                        cur[int(parts[-1])] = copy.deepcopy(val)
                    else:
                        cur[parts[-1]] = copy.deepcopy(val)
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)

    async def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if _match(d, q):
                self.writes += 1
                del self.docs[i]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    async def delete_many(self, q):
        keep = [d for d in self.docs if not _match(d, q)]
        n = len(self.docs) - len(keep)
        self.docs = keep
        self.writes += 1
        return SimpleNamespace(deleted_count=n)


class FakeDb:
    def __init__(self):
        self.cols = {store.SOURCES: Col(), store.HITS: Col()}

    def __getitem__(self, name):
        assert name in self.cols, f"the Chartink desk touched db[{name!r}]"
        return self.cols[name]

    @property
    def sources(self):
        return self.cols[store.SOURCES]

    @property
    def hits(self):
        return self.cols[store.HITS]


def run(coro):
    return asyncio.run(coro)


def import_standard(db, user="user_a", widgets=None, now=NOW):
    return run(store.put_source(db, user, URL, fetch=lambda url: page(widgets or standard_widgets()), now=now))


def scan_of(doc, wid):
    return next(s for s in doc["scans"] if s["id"] == str(wid))


# ── dashboard URL: SSRF-safe ─────────────────────────────────────────────────

@pytest.mark.parametrize("url", ["https://chartink.com/dashboard/123456", "https://chartink.com/dashboard/123456/", " https://chartink.com/dashboard/7 "])
def test_url_accepted_and_canonicalised(url):
    canon, ident = dash.validate_url(url)
    assert canon == f"https://chartink.com/dashboard/{ident}" and ident.isdigit()


@pytest.mark.parametrize("url", [
    "http://chartink.com/dashboard/1", "https://www.chartink.com/dashboard/1", "https://chartink.com.evil.example/dashboard/1",
    "https://evil.example/https://chartink.com/dashboard/1", "https://chartink.com@evil.example/dashboard/1", "https://user:pw@chartink.com/dashboard/1",
    "https://chartink.com:8443/dashboard/1", "https://chartink.com/dashboard/1?next=http://127.0.0.1", "https://chartink.com/dashboard/1#x",
    "https://chartink.com/dashboard/abc", "https://chartink.com/dashboard/", "https://chartink.com/screener/1", "https://chartink.com/dashboard/1/../../x",
    "https://127.0.0.1/dashboard/1", "file:///etc/passwd", "ftp://chartink.com/dashboard/1", "//chartink.com/dashboard/1", "", "   ", None, 12345, ["x"],
    "https://chartink.com/dashboard/" + "9" * 13, "https://chartink.com/dashboard/1" + "0" * 300])
def test_url_rejected(url):
    with pytest.raises(dash.DashboardError) as e:
        dash.validate_url(url)
    assert e.value.code == "invalid_dashboard_url" and e.value.status == 422


def test_redirects_stay_on_chartink():
    h = dash._SameSiteRedirects()
    req = urllib.request.Request(URL)
    for bad in ("https://evil.example/x", "http://chartink.com/dashboard/1", "https://chartink.com.evil.example/", "https://chartink.com:444/x",
                "https://user@chartink.com/x", "file:///etc/passwd", "https://127.0.0.1/"):
        with pytest.raises(dash.DashboardError) as e:
            h.redirect_request(req, io.BytesIO(), 302, "Found", {}, bad)
        assert e.value.code == "redirect_off_site"
    nxt = h.redirect_request(req, io.BytesIO(), 302, "Found", {}, "https://chartink.com/dashboard/2")
    assert nxt.full_url == "https://chartink.com/dashboard/2"


class FakeResp:
    def __init__(self, data):
        self.data = data

    def read(self, n=-1):
        return self.data[:n] if n >= 0 else self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, result):
        self.result, self.calls = result, []

    def open(self, req, timeout=None):
        self.calls.append((req.full_url, timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return FakeResp(self.result)


def patch_opener(monkeypatch, result):
    op = FakeOpener(result)
    monkeypatch.setattr(dash.urllib.request, "build_opener", lambda *h: op)
    return op


def test_fetch_page_reads_with_a_timeout_and_no_cookies(monkeypatch):
    op = patch_opener(monkeypatch, b"<html>ok</html>")
    assert dash.fetch_page(URL) == "<html>ok</html>" and op.calls == [(URL, dash.FETCH_TIMEOUT_S)]
    seen = []
    monkeypatch.setattr(dash.urllib.request, "build_opener", lambda *h: seen.extend(h) or op)
    dash.fetch_page(URL)
    assert not any(isinstance(x, urllib.request.HTTPCookieProcessor) for x in seen)       # nothing stored, nothing sent back


def test_fetch_page_refuses_a_huge_page_and_reports_typed_errors(monkeypatch):
    patch_opener(monkeypatch, b"x" * (dash.MAX_PAGE_BYTES + 10))
    with pytest.raises(dash.DashboardError) as e:
        dash.fetch_page(URL)
    assert e.value.code == "dashboard_too_large" and e.value.status == 502
    patch_opener(monkeypatch, b"x" * dash.MAX_PAGE_BYTES)                                      # exactly the cap is allowed
    assert len(dash.fetch_page(URL)) == dash.MAX_PAGE_BYTES
    for code, msg in ((404, "not found or is not public"), (403, "refused"), (429, "rate limiting")):
        patch_opener(monkeypatch, urllib.error.HTTPError(URL, code, "x", {}, None))
        with pytest.raises(dash.DashboardError) as e:
            dash.fetch_page(URL)
        assert e.value.code == "dashboard_fetch_failed" and e.value.status == 502 and msg in e.value.message and str(code) in e.value.message
    patch_opener(monkeypatch, TimeoutError("slow"))
    with pytest.raises(dash.DashboardError) as e:
        dash.fetch_page(URL)
    assert e.value.code == "dashboard_fetch_failed" and "TimeoutError" in e.value.message


# ── page parsing ─────────────────────────────────────────────────────────────

def test_parse_page_reads_html_escaped_json_and_the_title():
    ws = [widget(1, "Mock A & B <scan>", "( {cash} ( latest close > 5 ) )"), widget(2, 'Mock "quoted"')]
    title, got = dash.parse_page(page(ws, title="Mock  Dashboard  Title"))
    assert title == "Mock Dashboard Title" and [w["name"] for w in got] == ["Mock A & B <scan>", 'Mock "quoted"']
    assert got[0]["query"] == ws[0]["query"]
    _, again = dash.parse_page(page(ws, quote="'").replace("&quot;", "&#34;"))              # single-quoted attribute, numeric entity for the quote
    assert [w["id"] for w in again] == [1, 2]


@pytest.mark.parametrize("bad", ["<html><body>no widgets here</body></html>", "", '<x :widgets="not json at all">', '<x :widgets="{&quot;a&quot;:1}">',
                                 '<x :widgets="&quot;a string&quot;">'])
def test_parse_page_typed_error_when_the_page_changed(bad):
    with pytest.raises(dash.DashboardError) as e:
        dash.parse_page(bad)
    assert e.value.code == "dashboard_page_changed" and e.value.status == 502


def test_parse_page_ignores_non_object_widgets_and_caps_the_count():
    _, got = dash.parse_page(page([widget(1, "Mock A"), "junk", 5, None, widget(2, "Mock B")]))
    assert [w["id"] for w in got] == [1, 2]
    _, many = dash.parse_page(page([widget(i, f"Mock {i}") for i in range(dash.MAX_WIDGETS + 40)]))
    assert len(many) == dash.MAX_WIDGETS


# ── clause extraction, stock scan versus statistics, support, intraday ───────

def test_clause_is_the_text_between_the_top_level_where_and_group_by():
    q = SELECT + "WHERE ( {cash} (\n   latest close > 100\n   and latest volume > 5000 ) ) GROUP BY symbol ORDER BY 1 desc"
    p = dash.split_query(q)
    assert p["clause"] == "( {cash} ( latest close > 100 and latest volume > 5000 ) )" and p["group_by"] == "symbol"
    assert p["aliases"] == ["% Change", "Price", "Volume"]
    # a lower-case where inside the select (a group function) is not the clause start; keywords in quotes are not keywords
    q2 = "select groupcount( {cash} 1 where latest close > 1 day ago close ) as 'where x' WHERE {cash} 1 = 1 group by marketcapname order by 1 desc"
    p2 = dash.split_query(q2)
    assert p2["clause"] == "{cash} 1 = 1" and p2["group_by"] == "marketcapname" and p2["aliases"] == ["where x"]
    assert dash.split_query("select 1")["clause"] is None and dash.split_query(None)["group_by"] is None


def test_stock_scan_versus_market_statistics_rule():
    s = {x["id"]: x for x in dash.build_scans(standard_widgets())}
    for wid in ("1001", "1002", "1003", "1004", "1005", "1006"):
        assert s[wid]["kind"] == "stock_scan"
    assert s["1007"]["kind"] == "market_stats" and s["1008"]["kind"] == "market_stats"        # grouped by market-cap class; a universe listing without a price column
    for wid in ("1007", "1008"):
        assert s[wid]["supported"] is False and s[wid]["enabled"] is False and s[wid]["direction"] == "neutral"
        assert s[wid]["unsupported_reason"].startswith("market_statistic:") and dash.STOCK_SCAN_RULE in s[wid]["unsupported_reason"]
    # grouping by symbol but selecting a price and having only 1 = 1 is a universe listing, not a scan
    assert not dash.is_stock_scan(dash.split_query(SELECT + "WHERE {cash} 1 = 1 GROUP BY symbol ORDER BY 1 desc"))
    assert not dash.is_stock_scan(dash.split_query(SELECT + "WHERE {cash} 1=1 GROUP BY symbol"))
    # no Price column: not a stock scan
    assert not dash.is_stock_scan(dash.split_query("select latest Close as 'Ltp' WHERE ( {cash} ( latest close > 1 ) ) GROUP BY symbol"))
    assert dash.is_stock_scan(dash.split_query("select latest Close as 'PRICE' WHERE ( {cash} ( latest close > 1 ) ) GROUP BY SYMBOL"))


def test_supported_and_unsupported_detection():
    s = {x["id"]: x for x in dash.build_scans(standard_widgets())}
    assert s["1004"]["supported"] is True                                                       # a saved universe {99001} runs (checked read-only 2026-10-20)
    assert s["1005"]["supported"] is True and s["1005"]["unsupported_reason"] is None           # an inline custom indicator carries its expression
    assert s["1006"]["supported"] is False and s["1006"]["enabled"] is False and s["1006"]["unsupported_reason"].startswith("custom_indicator_reference:")
    assert s["1006"]["kind"] == "stock_scan"
    assert dash.unsupported_reason("( {cash} ( latest close > 1 ) )") is None
    assert dash.unsupported_reason("{custom_indicator_5_start}x{custom_indicator_5_end} + {custom_indicator_6_end}") is not None
    no_where = dash.build_scans([{"id": 5, "name": "Mock NoWhere", "query": "select 1 as 'Price'"}])[0]
    assert no_where["supported"] is False and no_where["clause"] is None and no_where["unsupported_reason"].startswith("no_clause:")
    long = dash.build_scans([widget(6, "Mock Long", "( {cash} ( latest close > " + "1" * 21_000 + " ) )")])[0]
    assert long["supported"] is False and long["unsupported_reason"].startswith("clause_too_long:")


def test_intraday_flag_from_the_clause():
    s = {x["id"]: x for x in dash.build_scans(standard_widgets() + [
        widget(2001, "Mock Hour", "( {cash} ( latest close > 1 hour ago close ) )"), widget(2002, "Mock Five", "( {cash} ( [0] 5 minute close > 1 ) )")])}
    assert s["1003"]["uses_intraday_candles"] and s["2001"]["uses_intraday_candles"] and s["2002"]["uses_intraday_candles"]
    assert not s["1001"]["uses_intraday_candles"] and not s["1002"]["uses_intraday_candles"]
    assert not dash.uses_intraday("( {cash} ( latest close > 1 day ago close and latest volume > 5 ) )")


def test_defaults_enabled_bullish_for_supported_stock_scans_only():
    s = {x["id"]: x for x in dash.build_scans(standard_widgets())}
    for wid in ("1001", "1002", "1003", "1004", "1005"):
        assert s[wid]["enabled"] is True and s[wid]["direction"] == "bullish" and s[wid]["supported"] is True
    assert [s[w]["enabled"] for w in ("1006", "1007", "1008")] == [False, False, False]
    assert s["1001"]["clause"] == "( {cash} ( latest close > 100 ) )" and s["1001"]["description"] == "Mock Alpha Scan description"
    # widgets without an id or a query are skipped, duplicate ids are kept once
    got = dash.build_scans([{"name": "no id", "query": "x"}, {"id": 1, "name": "ok", "query": SELECT + "WHERE ( {cash} ( latest close > 1 ) ) GROUP BY symbol"},
                            {"id": 1, "name": "dup", "query": "x"}, {"id": True, "query": "x"}, {"id": 2}])
    assert [x["id"] for x in got] == ["1"]


# ── import and re-import ─────────────────────────────────────────────────────

def test_import_stores_one_document_per_user_with_the_scans():
    db = FakeDb()
    doc = import_standard(db)
    assert doc["_id"] == "user_a" and doc["dashboard_id"] == "123456" and doc["url"] == URL and doc["title"] == "Mock Dashboard" and len(doc["scans"]) == 8
    assert doc["fetched_at"] == "2026-10-20T11:00:00Z" and len(db.sources.docs) == 1
    import_standard(db)
    assert len(db.sources.docs) == 1                                                            # still one document
    assert not any(k for k in doc if "token" in k.lower() or "cookie" in k.lower() or "password" in k.lower())      # no credential of any kind


def test_reimport_keeps_the_users_choices_by_widget_id():
    db = FakeDb()
    import_standard(db)
    run(store.patch_scan(db, "user_a", "1001", {"enabled": False}))
    run(store.patch_scan(db, "user_a", "1002", {"direction": "bearish"}))
    new = standard_widgets()[:3] + [widget(1009, "Mock Theta New")]                             # 1004-1008 gone, 1009 new
    doc = import_standard(db, widgets=new)
    assert [s["id"] for s in doc["scans"]] == ["1001", "1002", "1003", "1009"]
    assert scan_of(doc, 1001)["enabled"] is False and scan_of(doc, 1001)["direction"] == "bullish"
    assert scan_of(doc, 1002)["direction"] == "bearish" and scan_of(doc, 1002)["enabled"] is True
    assert scan_of(doc, 1003)["enabled"] is True
    assert scan_of(doc, 1009)["enabled"] is True and scan_of(doc, 1009)["direction"] == "bullish"        # a new widget gets the defaults


def test_reimport_cannot_enable_a_scan_that_is_now_unsupported_and_keeps_last_run():
    db = FakeDb()
    import_standard(db)
    run(rf.refresh_user(db, "user_a", scan_fn=ok_scan({}), now=NOW, spacer=quick_spacer()))
    assert scan_of(run(store.get_source(db, "user_a")), 1001)["last_run"]["ok"] is True
    changed = [widget(1001, "Mock Alpha Scan", '( {cash} ( latest {custom_indicator_3_start}"a" > 1 ) )')] + standard_widgets()[1:3]
    doc = import_standard(db, widgets=changed)
    s = scan_of(doc, 1001)
    assert s["supported"] is False and s["enabled"] is False and s["last_run"]["ok"] is True


def test_reimport_of_another_dashboard_resets_choices_and_removes_the_old_hits():
    db = FakeDb()
    import_standard(db)
    run(store.patch_scan(db, "user_a", "1001", {"enabled": False}))
    run(rf.refresh_user(db, "user_a", scan_fn=ok_scan({}), now=NOW, spacer=quick_spacer()))
    db.hits.docs.append({"user_id": "user_b", "scan_date": "2026-10-20", "scan_id": "1001", "symbol": "ZZZ"})
    other = run(store.put_source(db, "user_a", "https://chartink.com/dashboard/777", fetch=lambda u: page(standard_widgets()), now=NOW))
    assert other["dashboard_id"] == "777" and scan_of(other, 1001)["enabled"] is True
    assert [d["user_id"] for d in db.hits.docs] == ["user_b"]                                  # user_a's hits of the old dashboard are gone, user_b's are not


def test_import_typed_errors_for_empty_and_statistics_only_dashboards():
    db = FakeDb()
    for widgets, code in (([], "dashboard_empty"), ([stats_widget(1, "Mock Stats")], "dashboard_empty"), ([{"id": 1}], "dashboard_empty")):
        with pytest.raises(dash.DashboardError) as e:
            run(store.put_source(db, "user_a", URL, fetch=lambda u, w=widgets: page(w)))
        assert e.value.code == code and e.value.status == 422
    assert db.sources.docs == []                                                                # a failed import stores nothing


def test_import_failures_do_not_touch_an_existing_source():
    db = FakeDb()
    import_standard(db)
    before = copy.deepcopy(db.sources.docs)

    def boom(u):
        raise dash.DashboardError("dashboard_fetch_failed", "down", 502)
    with pytest.raises(dash.DashboardError):
        run(store.put_source(db, "user_a", URL, fetch=boom))
    with pytest.raises(dash.DashboardError):
        run(store.put_source(db, "user_a", "https://evil.example/dashboard/1", fetch=boom))
    assert db.sources.docs == before


# ── patch and delete ─────────────────────────────────────────────────────────

def test_patch_scan_enabled_and_direction_with_validation():
    db = FakeDb()
    import_standard(db)
    out = run(store.patch_scan(db, "user_a", "1002", {"enabled": False, "direction": "neutral"}))
    assert out["enabled"] is False and out["direction"] == "neutral"
    s = scan_of(run(store.get_source(db, "user_a")), 1002)
    assert s["enabled"] is False and s["direction"] == "neutral"
    for body, code, status in (({}, "invalid_body", 422), ([1], "invalid_body", 422), ({"name": "x"}, "invalid_body", 422), ({"enabled": "yes"}, "invalid_enabled", 422),
                               ({"direction": "up"}, "invalid_direction", 422), ({"enabled": True, "extra": 1}, "invalid_body", 422)):
        with pytest.raises(store.ChartinkError) as e:
            run(store.patch_scan(db, "user_a", "1001", body))
        assert (e.value.code, e.value.status) == (code, status)
    for wid, code, status in (("1007", "scan_unsupported", 409), ("1006", "scan_unsupported", 409), ("9999", "scan_not_found", 404)):
        with pytest.raises(store.ChartinkError) as e:
            run(store.patch_scan(db, "user_a", wid, {"enabled": True}))
        assert (e.value.code, e.value.status) == (code, status)
    run(store.patch_scan(db, "user_a", "1007", {"enabled": False}))                              # switching an unsupported scan off is harmless
    with pytest.raises(store.ChartinkError) as e:
        run(store.patch_scan(db, "nobody", "1001", {"enabled": False}))
    assert e.value.status == 404


# ── the screener client: typed errors ────────────────────────────────────────

class FakeOpener2:
    def __init__(self, steps):
        self.steps = list(steps)

    def open(self, req, timeout=None):
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return FakeResp(step)


def patch_client(monkeypatch, steps, xsrf="tok%3D"):
    cookies = [SimpleNamespace(name="XSRF-TOKEN", value=xsrf)] if xsrf else []
    monkeypatch.setattr(chartink_api, "CookieJar", lambda: cookies)
    monkeypatch.setattr(chartink_api.urllib.request, "build_opener", lambda *h: FakeOpener2(steps))


def http_error(code):
    return urllib.error.HTTPError("https://chartink.com/x", code, "x", {}, None)


def test_client_returns_rows_and_none_error_on_success(monkeypatch):
    payload = {"data": [{"nsecode": "aaa", "name": "Mock A", "close": 10.5, "per_chg": 2.0, "volume": 1000}]}
    patch_client(monkeypatch, [b"<html/>", json.dumps(payload).encode()])
    rows, err = chartink_api.run_scan_sync_typed("( {cash} ( latest close > 1 ) )")
    assert err is None and rows == [{"symbol": "AAA", "extra": {"name": "Mock A", "close": 10.5, "per_chg": 2.0, "volume": 1000, "bsecode": None}}]
    patch_client(monkeypatch, [b"<html/>", b'{"data": []}'])
    assert chartink_api.run_scan_sync_typed("x") == ([], None)                                  # zero hits is a result, not a failure


@pytest.mark.parametrize("steps,xsrf,code", [
    ([http_error(403)], "t", "http_403"), ([http_error(429)], "t", "http_429"), ([http_error(503)], "t", "http_503"),
    ([TimeoutError()], "t", "timeout"), ([OSError("net down")], "t", "bootstrap_failed"),
    ([b"<html/>"], None, "no_session"),
    ([b"<html/>", http_error(403)], "t", "http_403"), ([b"<html/>", http_error(429)], "t", "http_429"), ([b"<html/>", TimeoutError()], "t", "timeout"),
    ([b"<html/>", OSError("reset")], "t", "scan_failed"),
    ([b"<html/>", b"<html>blocked</html>"], "t", "non_json"),
    ([b"<html/>", b'{"scan_error": "bad clause"}'], "t", "scan_rejected")])
def test_client_typed_errors(monkeypatch, steps, xsrf, code):
    patch_client(monkeypatch, steps, xsrf)
    assert chartink_api.run_scan_sync_typed("x") == (None, code)


def test_the_old_wrapper_keeps_returning_none_on_failure(monkeypatch):
    patch_client(monkeypatch, [http_error(403)])
    assert chartink_api._run_scan_sync("x") is None


# ── refresh ──────────────────────────────────────────────────────────────────

def rows_of(*syms, close=100.0, chg=1.5, vol=1000):
    return [{"symbol": s, "extra": {"close": close, "per_chg": chg, "volume": vol}} for s in syms]


def ok_scan(by_clause: Dict[str, Any], default=None):
    """A scan function: by clause -> (rows, err) or an Exception to raise; unknown clauses answer `default` rows."""
    calls: List[str] = []

    async def fn(clause):
        calls.append(clause)
        r = by_clause.get(clause, (rows_of("AAA", "BBB") if default is None else default, None))
        if isinstance(r, BaseException):
            raise r
        return r
    fn.calls = calls
    return fn


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps: List[float] = []

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.sleeps.append(s)
        self.t += s
        await asyncio.sleep(0)


def quick_spacer():
    c = FakeClock()
    return rf.Spacer(rf.MIN_GAP_S, clock=c, sleep=c.sleep)


def test_refresh_stores_hits_with_the_contract_fields():
    db = FakeDb()
    import_standard(db)
    fn = ok_scan({}, default=[{"symbol": "aaa.ns", "extra": {"close": "101.5", "per_chg": "2.25", "volume": "5000"}}, {"symbol": " BBB ", "extra": {}},
                              {"symbol": "AAA", "extra": {}}, {"symbol": "", "extra": {}}, {"symbol": "-", "extra": {}}])
    r = run(rf.refresh_user(db, "user_a", scan_fn=fn, now=NOW, spacer=quick_spacer()))
    assert r["scan_date"] == "2026-10-20" and r["ran_at"] == "2026-10-20T11:00:00Z" and r["ok_count"] == 5 and r["failed_count"] == 0
    assert [s["id"] for s in r["scans"]] == ["1001", "1002", "1003", "1004", "1005"]            # enabled and supported only
    assert all(set(s) >= {"id", "name", "ok", "hits", "error", "seconds"} and s["ok"] and s["hits"] == 2 and s["error"] is None for s in r["scans"])
    assert r["uses_intraday_candles"] is True
    first = next(d for d in db.hits.docs if d["scan_id"] == "1001" and d["symbol"] == "AAA")
    assert first == {"user_id": "user_a", "scan_date": "2026-10-20", "scan_id": "1001", "scan_name": "Mock Alpha Scan", "direction": "bullish", "symbol": "AAA",
                     "close": 101.5, "pct_change": 2.25, "volume": 5000.0, "fetched_at": "2026-10-20T11:00:00Z"}
    bbb = next(d for d in db.hits.docs if d["symbol"] == "BBB")
    assert bbb["close"] is None and bbb["pct_change"] is None and bbb["volume"] is None         # a missing figure is null, never 0
    assert len(db.hits.docs) == 10
    src = run(store.get_source(db, "user_a"))
    assert scan_of(src, 1001)["last_run"] == {"at": "2026-10-20T11:00:00Z", "ok": True, "hits": 2, "error": None, "seconds": scan_of(src, 1001)["last_run"]["seconds"]}
    assert "1006" not in {s["id"] for s in r["scans"]} and fn.calls and len(fn.calls) == 5


def test_refresh_spacing_and_concurrency_with_a_fake_clock():
    db = FakeDb()
    import_standard(db, widgets=[widget(3000 + i, f"Mock Scan {i}", f"( {{cash}} ( latest close > {i + 1} ) )") for i in range(7)])
    clock = FakeClock()
    starts, live, peak = [], [0], [0]

    class Recording(rf.Spacer):
        async def wait(self):
            await super().wait()
            starts.append(self._last)                                                           # the instant the spacer let this scan start

    async def fn(clause):
        live[0] += 1
        peak[0] = max(peak[0], live[0])
        await asyncio.sleep(0.02)
        live[0] -= 1
        return rows_of("AAA"), None
    r = run(rf.refresh_user(db, "user_a", scan_fn=fn, now=NOW, spacer=Recording(rf.MIN_GAP_S, clock=clock, sleep=clock.sleep)))
    assert r["ok_count"] == 7 and len(starts) == 7
    assert all(b - a >= 1.0 - 1e-9 for a, b in zip(starts, starts[1:]))                         # at least a second between two scan starts
    assert peak[0] == rf.CONCURRENCY == 2                                                       # two at a time, never three


def test_spacer_waits_only_what_is_missing():
    c = FakeClock()
    sp = rf.Spacer(1.0, clock=c, sleep=c.sleep)

    async def go():
        await sp.wait()
        c.t += 0.4
        await sp.wait()
        c.t += 5
        await sp.wait()
    run(go())
    assert [round(x, 2) for x in c.sleeps] == [0.6]


def test_a_scan_failure_never_fails_the_others_and_never_raises():
    db = FakeDb()
    import_standard(db)
    src = run(store.get_source(db, "user_a"))
    cl = {s["id"]: s["clause"] for s in src["scans"]}
    fn = ok_scan({cl["1001"]: (None, "http_429"), cl["1002"]: RuntimeError("boom with secret-clause"), cl["1003"]: (None, None), cl["1004"]: (rows_of("CCC"), None),
                  cl["1005"]: (None, "scan_rejected")})
    r = run(rf.refresh_user(db, "user_a", scan_fn=fn, now=NOW, spacer=quick_spacer()))
    by = {s["id"]: s for s in r["scans"]}
    assert by["1004"]["ok"] and by["1004"]["hits"] == 1
    assert by["1001"]["ok"] is False and by["1001"]["error"].startswith("http_429:") and by["1001"]["error_code"] == "http_429"
    assert by["1002"]["error_code"] == "unexpected" and "secret-clause" not in json.dumps(r)          # an exception text is never echoed
    assert by["1003"]["error_code"] == "scan_failed" and by["1005"]["error_code"] == "scan_rejected" and "unsupported" in by["1005"]["error"]
    assert (r["ok_count"], r["failed_count"], r["degraded"]) == (1, 4, None)
    assert {d["scan_id"] for d in db.hits.docs} == {"1004"}                                       # only the scan that worked stored hits
    lr = {s["id"]: s.get("last_run") for s in run(store.get_source(db, "user_a"))["scans"]}
    assert lr["1001"]["ok"] is False and lr["1001"]["error"].startswith("http_429") and lr["1004"]["ok"] is True


def test_a_scan_over_the_time_limit_is_a_timeout(monkeypatch):
    db = FakeDb()
    import_standard(db, widgets=[widget(1, "Mock Slow"), widget(2, "Mock Quick", "( {cash} ( latest close > 2 ) )")])
    monkeypatch.setattr(rf, "SCAN_TIMEOUT_S", 0.05)
    slow = run(store.get_source(db, "user_a"))["scans"][0]["clause"]

    async def fn(clause):
        if clause == slow:
            await asyncio.sleep(5)
        return rows_of("AAA"), None
    r = run(rf.refresh_user(db, "user_a", scan_fn=fn, now=NOW, spacer=quick_spacer()))
    by = {s["id"]: s for s in r["scans"]}
    assert by["1"]["ok"] is False and by["1"]["error_code"] == "timeout" and "30" in by["1"]["error"] and by["2"]["ok"]


def test_every_scan_failing_degrades_to_ai_scanner_only_with_the_reason():
    db = FakeDb()
    import_standard(db)
    r = run(rf.refresh_user(db, "user_a", scan_fn=lambda c: _fail("http_403"), now=NOW, spacer=quick_spacer()))
    assert r["ok_count"] == 0 and r["failed_count"] == 5 and "AI scanner" in r["degraded"] and db.hits.docs == []
    assert all(s["error"].startswith("http_403:") for s in r["scans"])


async def _fail(code):
    return None, code


def test_cooldown_429_with_retry_after_and_release_after_ten_minutes():
    db = FakeDb()
    import_standard(db)
    run(rf.refresh_user(db, "user_a", scan_fn=ok_scan({}), now=NOW, spacer=quick_spacer()))
    with pytest.raises(store.ChartinkError) as e:
        run(rf.refresh_user(db, "user_a", scan_fn=ok_scan({}), now=NOW + timedelta(seconds=90), spacer=quick_spacer()))
    assert e.value.status == 429 and e.value.code == "refresh_cooldown" and e.value.extra["retry_after_s"] == 510
    with pytest.raises(store.ChartinkError) as e:
        run(rf.refresh_user(db, "user_a", scan_fn=ok_scan({}), now=NOW + timedelta(seconds=599), spacer=quick_spacer()))
    assert e.value.extra["retry_after_s"] == 1
    r = run(rf.refresh_user(db, "user_a", scan_fn=ok_scan({}), now=NOW + timedelta(seconds=600), spacer=quick_spacer()))
    assert r["ok_count"] == 5
    # another user's cooldown is separate
    import_standard(db, user="user_b")
    assert run(rf.refresh_user(db, "user_b", scan_fn=ok_scan({}), now=NOW + timedelta(seconds=601), spacer=quick_spacer()))["ok_count"] == 5


def test_cooldown_claim_is_atomic_so_concurrent_refreshes_run_once():
    db = FakeDb()
    import_standard(db)
    fn = ok_scan({})

    async def both():
        return await asyncio.gather(rf.refresh_user(db, "user_a", scan_fn=fn, now=NOW, spacer=quick_spacer()),
                                    rf.refresh_user(db, "user_a", scan_fn=fn, now=NOW, spacer=quick_spacer()), return_exceptions=True)
    a, b = run(both())
    assert sorted(type(x).__name__ for x in (a, b)) == ["ChartinkError", "dict"] and len(fn.calls) == 5


def test_no_source_is_404_and_nothing_enabled_does_not_use_up_the_slot():
    db = FakeDb()
    with pytest.raises(store.ChartinkError) as e:
        run(rf.refresh_user(db, "user_a", scan_fn=ok_scan({}), now=NOW))
    assert (e.value.status, e.value.code) == (404, "no_source")
    import_standard(db)
    for wid in (1001, 1002, 1003, 1004, 1005):
        run(store.patch_scan(db, "user_a", str(wid), {"enabled": False}))
    fn = ok_scan({})
    r = run(rf.refresh_user(db, "user_a", scan_fn=fn, now=NOW))
    assert r["scans"] == [] and "No scan is enabled" in r["degraded"] and fn.calls == []
    run(store.patch_scan(db, "user_a", "1001", {"enabled": True}))
    assert run(rf.refresh_user(db, "user_a", scan_fn=fn, now=NOW + timedelta(seconds=1), spacer=quick_spacer()))["ok_count"] == 1        # not blocked by a cooldown


def test_at_most_25_scans_per_run():
    db = FakeDb()
    import_standard(db, widgets=[widget(4000 + i, f"Mock Many {i}", f"( {{cash}} ( latest close > {i + 1} ) )") for i in range(28)])
    fn = ok_scan({})
    r = run(rf.refresh_user(db, "user_a", scan_fn=fn, now=NOW, spacer=quick_spacer()))
    assert len(r["scans"]) == rf.MAX_SCANS == 25 == len(fn.calls) and r["skipped_over_cap"] == 3


def test_rerun_replaces_the_same_scan_and_day_and_leaves_other_days_and_users_alone():
    db = FakeDb()
    import_standard(db)
    import_standard(db, user="user_b")
    src = run(store.get_source(db, "user_a"))
    c1 = scan_of(src, 1001)["clause"]
    run(rf.refresh_user(db, "user_a", scan_fn=ok_scan({c1: (rows_of("AAA", "BBB", "CCC"), None)}), now=MORNING, spacer=quick_spacer()))
    run(rf.refresh_user(db, "user_b", scan_fn=ok_scan({}), now=MORNING, spacer=quick_spacer()))
    db.hits.docs.append({"user_id": "user_a", "scan_date": "2026-10-19", "scan_id": "1001", "symbol": "OLD", "fetched_at": "2026-10-19T11:00:00Z"})
    n_b = sum(1 for d in db.hits.docs if d["user_id"] == "user_b")
    run(rf.refresh_user(db, "user_a", scan_fn=ok_scan({c1: (rows_of("BBB", "DDD"), None)}), now=NOW, spacer=rf.Spacer(0, clock=FakeClock(), sleep=FakeClock().sleep),
                        cooldown=False))
    mine = sorted(d["symbol"] for d in db.hits.docs if d["user_id"] == "user_a" and d["scan_id"] == "1001" and d["scan_date"] == "2026-10-20")
    assert mine == ["BBB", "DDD"]                                                               # replaced, not appended
    assert [d["fetched_at"] for d in db.hits.docs if d["symbol"] == "BBB" and d["user_id"] == "user_a" and d["scan_id"] == "1001"] == ["2026-10-20T11:00:00Z"]
    assert any(d["symbol"] == "OLD" for d in db.hits.docs)                                      # yesterday's hits stay
    assert sum(1 for d in db.hits.docs if d["user_id"] == "user_b") == n_b
    # a scan that now lists nothing clears its hits of the day
    run(rf.refresh_user(db, "user_a", scan_fn=ok_scan({c1: ([], None)}), now=NOW, cooldown=False, spacer=quick_spacer()))
    assert not [d for d in db.hits.docs if d["user_id"] == "user_a" and d["scan_id"] == "1001" and d["scan_date"] == "2026-10-20"]


def test_scan_date_is_the_ist_date_of_the_fetch():
    db = FakeDb()
    import_standard(db)
    late = datetime(2026, 10, 20, 19, 0, tzinfo=timezone.utc)                                  # 00:30 IST on the 21st
    r = run(rf.refresh_user(db, "user_a", scan_fn=ok_scan({}), now=late, spacer=quick_spacer()))
    assert r["scan_date"] == "2026-10-21"


def test_refresh_all_runs_every_user_and_one_user_failing_does_not_stop_the_rest(monkeypatch):
    monkeypatch.setattr(rf, "MIN_GAP_S", 0.0)
    db = FakeDb()
    import_standard(db, user="user_a")
    import_standard(db, user="user_b")
    real = rf.refresh_user

    async def flaky(db_, uid, **kw):
        if uid == "user_a":
            raise RuntimeError("storage down")
        return await real(db_, uid, **kw)
    monkeypatch.setattr(rf, "refresh_user", flaky)
    out = run(rf.refresh_all(db, scan_fn=ok_scan({}), now=NOW))
    assert out["users"] == 2 and out["scans_ok"] == 5 and out["per_user"][0]["error"] == "RuntimeError" and out["per_user"][1]["ok"] == 5
    assert "user_a" not in json.dumps(out) and "user_b" not in json.dumps(out)                   # users appear as short hashes only
    dry = run(rf.refresh_all(FakeDb(), dry_run=True))
    assert dry == {"users": 0, "dry_run": True, "scans_ok": 0, "scans_failed": 0, "per_user": []}


# ── the scheduled script ─────────────────────────────────────────────────────

def test_script_runs_all_users_and_dry_run_fetches_and_writes_nothing(monkeypatch):
    monkeypatch.setattr(rf, "MIN_GAP_S", 0.0)                                                    # the real pacing is tested above with a fake clock
    from scripts import refresh_chartink as script
    db = FakeDb()
    import_standard(db)
    fn = ok_scan({})
    dry = run(script.run(db, dry_run=True, scan_fn=fn))
    assert dry["ok"] and dry["per_user"][0]["would_run"] == 5 and fn.calls == [] and db.hits.docs == [] and db.hits.writes == 0
    out = run(script.run(db, scan_fn=ok_scan({}, default=rows_of("AAA"))))
    assert out["ok"] and out["scans_ok"] == 5 and len(db.hits.docs) == 5
    bad = run(script.run(db, scan_fn=lambda c: _fail("http_403")))
    assert bad["ok"] is False and bad["scans_failed"] == 5


def test_cron_and_installer_files():
    root = Path(__file__).resolve().parents[2] / "deploy" / "nivesh-staging"
    cron = (root / "chartink.cron").read_text()
    assert "CRON_TZ=Asia/Kolkata" in cron
    lines = [l for l in cron.splitlines() if l and not l.startswith("#") and "python -m" in l]
    assert [l.split()[:5] for l in lines] == [["5", "16", "*", "*", "1-5"], ["10", "20", "*", "*", "1-5"]]
    assert all("scripts.refresh_chartink" in l for l in lines)
    assert "refresh_chartink" in (root / "install-chartink.sh").read_text() and "chartink.cron" in (root / "install-chartink.sh").read_text()


# ── routes ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(route, "db", db)
    fetched: List[str] = []
    state = {"page": page(standard_widgets()), "scans": ok_scan({}), "scores": {"AAA": 71.2}, "fails": [], "universe": None}

    def fake_fetch(url):
        fetched.append(url)
        if isinstance(state["page"], Exception):
            raise state["page"]
        return state["page"]
    monkeypatch.setattr(dash, "fetch_page", fake_fetch)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}
    monkeypatch.setattr(route, "get_current_user", fake_user)
    orig = rf.refresh_user

    async def with_fake(db_, uid, **kw):
        kw.setdefault("scan_fn", state["scans"])
        kw.setdefault("spacer", quick_spacer())
        return await orig(db_, uid, **kw)
    monkeypatch.setattr(rf, "refresh_user", with_fake)

    async def scores(request):
        return state["scores"], state["fails"]
    monkeypatch.setattr(route, "_scanner_scores", scores)
    rows = [{"symbol": s, "company_name": f"Mock {s} Ltd", "fno_eligible": f, "last_price_date": "2026-10-20", "market_cap_cr": 1000.0 + i}
            for i, (s, f) in enumerate([("AAA", True), ("BBB", False), ("CCC", None), ("AAB", True)])]

    async def uni(force=False):
        if state["universe"] == "down":
            raise RuntimeError("universe unreadable")
        return sl.Universe(rows, "MOCK universe", "2026-10-20", None)
    monkeypatch.setattr(sl, "get_universe", uni)
    app = FastAPI()
    app.include_router(route.router)
    c = TestClient(app)
    c.db, c.state, c.fetched = db, state, fetched
    return c


def put(client, headers=A, url=URL, **kw):
    return client.put("/api/desk/chartink/source", json={"dashboard_url": url}, headers=headers, **kw)


def test_every_route_requires_sign_in(client):
    for method, path, body in (("put", "/source", {"dashboard_url": URL}), ("get", "/source", None), ("patch", "/scans/1001", {"enabled": False}),
                               ("delete", "/source", None), ("post", "/refresh", None), ("get", "/hits", None)):
        r = getattr(client, method)("/api/desk/chartink" + path, **({"json": body} if body is not None else {}))
        assert r.status_code == 401, (method, path)
    assert client.fetched == []


def test_put_source_returns_the_document_without_clauses_by_default(client):
    r = put(client)
    assert r.status_code == 200
    src = r.json()["source"]
    assert src["dashboard_id"] == "123456" and src["url"] == URL and src["title"] == "Mock Dashboard" and len(src["scans"]) == 8
    assert all("clause" not in s for s in src["scans"]) and "( {cash}" not in r.text and '"clause"' not in r.text
    assert set(src["scans"][0]) == {"id", "name", "description", "kind", "supported", "unsupported_reason", "uses_intraday_candles", "enabled", "direction", "last_run"}
    assert src["summary"] == {"scans": 8, "stock_scans": 6, "supported": 5, "enabled": 5} and src["refresh"] == {"last_started_at": None, "retry_after_s": 0}
    assert client.fetched == [URL]
    with_clauses = put(client, params={"include_clauses": 1}).json()["source"]
    assert scan_of({"scans": with_clauses["scans"]}, 1001)["clause"] == "( {cash} ( latest close > 100 ) )"
    g = client.get("/api/desk/chartink/source", headers=A)
    assert g.status_code == 200 and '"clause"' not in g.text and "( {cash}" not in g.text
    assert client.get("/api/desk/chartink/source?include_clauses=1", headers=A).json()["source"]["scans"][0]["clause"]
    assert client.get("/api/desk/chartink/source?include_clauses=2", headers=A).status_code == 422


def test_get_source_is_null_without_a_source_and_per_user(client):
    assert client.get("/api/desk/chartink/source", headers=A).json() == {"source": None}
    put(client)
    assert client.get("/api/desk/chartink/source", headers=A).json()["source"]["dashboard_id"] == "123456"
    assert client.get("/api/desk/chartink/source", headers=B).json() == {"source": None}


@pytest.mark.parametrize("url", ["http://chartink.com/dashboard/1", "https://evil.example/dashboard/1", "https://chartink.com/dashboard/1?x=1", "https://chartink.com@evil.example/dashboard/1",
                                 "https://chartink.com/dashboard/x"])
def test_put_rejects_ssrf_urls_before_any_fetch(client, url):
    r = put(client, url=url)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_dashboard_url"
    assert client.fetched == [] and client.db.sources.docs == []


def test_put_body_problems(client):
    assert client.put("/api/desk/chartink/source", data="{not json", headers=A).status_code == 422
    r = client.put("/api/desk/chartink/source", json=[1], headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_body"
    r = client.put("/api/desk/chartink/source", json={}, headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_dashboard_url"


def test_put_typed_upstream_errors_and_nothing_stored(client):
    client.state["page"] = "<html>a login page</html>"
    r = put(client)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "dashboard_page_changed"
    client.state["page"] = dash.DashboardError("dashboard_fetch_failed", "Chartink answered HTTP 404: the dashboard was not found or is not public.", 502)
    r = put(client)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "dashboard_fetch_failed" and "404" in r.json()["detail"]["message"]
    client.state["page"] = page([stats_widget(1, "Mock Stats")])
    r = put(client)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "dashboard_empty"
    client.state["page"] = dash.DashboardError("redirect_off_site", "redirected", 502)
    assert put(client).json()["detail"]["code"] == "redirect_off_site"
    assert client.db.sources.docs == []


def test_patch_route_and_ownership_404(client):
    put(client)
    put(client, headers=B, url="https://chartink.com/dashboard/555")
    client.state["page"] = page([widget(9001, "Mock Only B")])
    put(client, headers=B, url="https://chartink.com/dashboard/555")
    r = client.patch("/api/desk/chartink/scans/1001", json={"enabled": False, "direction": "bearish"}, headers=A)
    assert r.status_code == 200 and r.json()["scan"]["enabled"] is False and r.json()["scan"]["direction"] == "bearish" and "clause" not in r.text
    # user B has no scan 1001; user A has no scan 9001: both answer 404, the same as a missing one
    assert client.patch("/api/desk/chartink/scans/1001", json={"enabled": True}, headers=B).status_code == 404
    assert client.patch("/api/desk/chartink/scans/9001", json={"enabled": True}, headers=A).status_code == 404
    assert client.patch("/api/desk/chartink/scans/" + "9" * 80, json={"enabled": True}, headers=A).status_code == 404
    assert client.get("/api/desk/chartink/source", headers=A).json()["source"]["scans"][0]["enabled"] is False
    assert client.patch("/api/desk/chartink/scans/1007", json={"enabled": True}, headers=A).status_code == 409
    assert client.patch("/api/desk/chartink/scans/1001", json={"direction": "sideways"}, headers=A).json()["detail"]["code"] == "invalid_direction"
    assert client.patch("/api/desk/chartink/scans/1001", data="nope", headers=A).status_code == 422
    r = client.patch("/api/desk/chartink/scans/1001", json={"enabled": True}, headers={"X-Test-User": "nobody"})
    assert r.status_code == 404


def test_refresh_route_cooldown_and_results(client, monkeypatch):
    assert client.post("/api/desk/chartink/refresh", headers=A).status_code == 404
    assert client.post("/api/desk/chartink/refresh", headers=A).json()["detail"]["code"] == "no_source"
    put(client)
    now = {"t": NOW}
    monkeypatch.setattr(store, "utcnow", lambda: now["t"])
    r = client.post("/api/desk/chartink/refresh", headers=A)
    assert r.status_code == 200
    body = r.json()
    assert body["ok_count"] == 5 and all(set(s) >= {"id", "name", "ok", "hits", "error", "seconds"} for s in body["scans"])
    r = client.post("/api/desk/chartink/refresh", headers=A)
    assert r.status_code == 429 and r.json()["detail"]["retry_after_s"] == 600 and r.json()["detail"]["code"] == "refresh_cooldown" and r.headers["Retry-After"] == "600"
    assert r.json()["retry_after_s"] == 600 and r.json()["code"] == "refresh_cooldown" and r.json()["status"] == 429 and "Try again in 600 seconds" in r.json()["message"]
    now["t"] = NOW + timedelta(seconds=240)
    assert client.post("/api/desk/chartink/refresh", headers=A).json()["detail"]["retry_after_s"] == 360
    assert client.post("/api/desk/chartink/refresh", headers=B).status_code == 404            # B has no source: no cooldown shared with A
    src = client.get("/api/desk/chartink/source", headers=A).json()["source"]
    assert src["refresh"]["last_started_at"] == "2026-10-20T11:00:00Z" and src["refresh"]["retry_after_s"] == 360
    assert src["scans"][0]["last_run"]["ok"] is True


def test_delete_removes_the_source_and_only_that_users_hits(client, monkeypatch):
    put(client)
    put(client, headers=B)
    monkeypatch.setattr(store, "utcnow", lambda: NOW)
    client.post("/api/desk/chartink/refresh", headers=A)
    client.post("/api/desk/chartink/refresh", headers=B)
    assert {d["user_id"] for d in client.db.hits.docs} == {"user_a", "user_b"}
    r = client.delete("/api/desk/chartink/source", headers=A)
    assert r.status_code == 200 and r.json() == {"deleted": True, "hits_deleted": 10}
    assert {d["user_id"] for d in client.db.hits.docs} == {"user_b"} and [d["_id"] for d in client.db.sources.docs] == ["user_b"]
    assert client.get("/api/desk/chartink/source", headers=A).json() == {"source": None}
    assert client.delete("/api/desk/chartink/source", headers=A).json() == {"deleted": False, "hits_deleted": 0}


# ── hits ─────────────────────────────────────────────────────────────────────

def seed_hits(client, monkeypatch, by_scan: Dict[str, Any], now=NOW):
    put(client)
    monkeypatch.setattr(store, "utcnow", lambda: now)
    src = client.db.sources.docs[0]
    clauses = {s["id"]: s["clause"] for s in src["scans"]}
    client.state["scans"] = ok_scan({clauses[k]: v for k, v in by_scan.items()}, default=[])
    return client.post("/api/desk/chartink/refresh", headers=A)


def test_hits_grouped_by_symbol_with_the_join(client, monkeypatch):
    seed_hits(client, monkeypatch, {"1001": (rows_of("AAA", "BBB", close=100.0, chg=2.0, vol=5000), None), "1002": (rows_of("AAA", close=101.0, chg=2.5, vol=6000), None),
                                    "1003": (rows_of("AAA", "CCC", "NOTATICKER"), None)})
    r = client.get("/api/desk/chartink/hits", headers=A)
    assert r.status_code == 200
    h = r.json()
    assert h["as_of_date"] == "2026-10-20" and h["fetched_at"] == "2026-10-20T11:00:00Z" and h["mode"] == "end_of_day_snapshot" and h["is_today"] is True
    assert [s["id"] for s in h["scans"]] == ["1001", "1002", "1003", "1004", "1005"]
    assert [(s["id"], s["hits"], s["ok"], s["error"]) for s in h["scans"]] == [("1001", 2, True, None), ("1002", 1, True, None), ("1003", 3, True, None),
                                                                              ("1004", 0, True, None), ("1005", 0, True, None)]
    assert [s["uses_intraday_candles"] for s in h["scans"]] == [False, False, True, False, False]
    syms = h["symbols"]
    assert [s["symbol"] for s in syms] == ["AAA", "BBB", "CCC"]                                  # by scan count, then symbol; NOTATICKER is not here
    aaa = syms[0]
    assert aaa["count"] == 3 and [x["id"] for x in aaa["scans"]] == ["1001", "1002", "1003"] and all(x["direction"] == "bullish" for x in aaa["scans"])
    assert aaa["name"] == "Mock AAA Ltd" and aaa["fno_eligible"] is True and aaa["in_ai_scanner"] is True and aaa["ai_score"] == 71.2
    assert (aaa["close"], aaa["pct_change"], aaa["volume"]) == (100.0, 1.5, 1000)                # the last hit of the group (scan 1003, default rows)
    bbb, ccc = syms[1], syms[2]
    assert bbb["in_ai_scanner"] is False and bbb["ai_score"] is None and bbb["fno_eligible"] is False and bbb["count"] == 1
    assert ccc["fno_eligible"] is None                                                           # unknown in the universe stays null
    assert h["source_failures"] == [] and h["empty_reason"] is None


def test_unknown_symbols_are_listed_with_suggestions_never_dropped(client, monkeypatch):
    seed_hits(client, monkeypatch, {"1001": (rows_of("AAA", "AAAA", "12345", "NOTATICKER"), None), "1002": (rows_of("12345"), None)})
    h = client.get("/api/desk/chartink/hits", headers=A).json()
    assert [s["symbol"] for s in h["symbols"]] == ["AAA"]
    unk = {u["symbol"]: u for u in h["unknown_symbols"]}
    assert set(unk) == {"AAAA", "12345", "NOTATICKER"} and unk["12345"]["count"] == 2 and [x["id"] for x in unk["12345"]["scans"]] == ["1001", "1002"]
    assert unk["AAAA"]["suggestions"] and unk["AAAA"]["suggestions"][0]["symbol"] in ("AAA", "AAB") and "not in the nse stock symbol master" in unk["AAAA"]["note"].lower()
    assert unk["NOTATICKER"]["suggestions"] == [] and unk["NOTATICKER"]["suggested"] is None
    assert unk["12345"]["suggestions"] == [] and unk["12345"]["suggested"] is None              # digits only: the lookup finds nothing, still listed
    total = len(h["symbols"]) + len(h["unknown_symbols"])
    assert total == len({d["symbol"] for d in client.db.hits.docs})                              # every stored symbol is accounted for


def test_hits_degrade_honestly_when_the_scanner_or_the_universe_cannot_be_read(client, monkeypatch):
    seed_hits(client, monkeypatch, {"1001": (rows_of("AAA", "ZZZ"), None)})
    client.state["scores"], client.state["fails"] = None, ["watchlist: HTTP 503: down", "picks: HTTP 503: down"]
    h = client.get("/api/desk/chartink/hits", headers=A).json()
    assert [(s["symbol"], s["in_ai_scanner"], s["ai_score"]) for s in h["symbols"]] == [("AAA", None, None), ("ZZZ", None, None)] or h["unknown_symbols"]
    assert h["source_failures"][:2] == client.state["fails"]
    client.state["scores"], client.state["fails"], client.state["universe"] = {}, [], "down"
    h = client.get("/api/desk/chartink/hits", headers=A).json()
    assert [s["symbol"] for s in h["symbols"]] == ["AAA", "ZZZ"] and all(s["name"] is None and s["fno_eligible"] is None for s in h["symbols"])
    assert h["unknown_symbols"] == [] and any("symbol universe" in f for f in h["source_failures"])      # nothing is called unknown when the universe is unreadable


def test_mode_end_of_day_snapshot_versus_fetched_at(client, monkeypatch):
    seed_hits(client, monkeypatch, {"1001": (rows_of("AAA"), None)}, now=MORNING)
    h = client.get("/api/desk/chartink/hits", headers=A).json()
    assert h["mode"] == "fetched_at" and h["fetched_at"] == "2026-10-20T05:00:00Z"
    assert hits_mod.is_eod("2026-10-20", "2026-10-20T10:09:59Z") is False                        # 15:39:59 IST
    assert hits_mod.is_eod("2026-10-20", "2026-10-20T10:10:00Z") is True                         # 15:40 IST
    assert hits_mod.is_eod("2026-10-20", "2026-10-21T03:00:00Z") is True                         # next morning still holds the closed session
    assert hits_mod.is_eod("2026-10-20", None) is False and hits_mod.is_eod("2026-10-20", "garbage") is False


def test_latest_date_default_date_param_and_stale_flag(client, monkeypatch):
    seed_hits(client, monkeypatch, {"1001": (rows_of("AAA"), None)}, now=NOW - timedelta(days=2))
    monkeypatch.setattr(store, "utcnow", lambda: NOW)
    old = client.get("/api/desk/chartink/hits", headers=A).json()
    assert old["as_of_date"] == "2026-10-18" and old["is_today"] is False and old["age_days"] == 2 and "2 day(s) before today" in old["stale_note"]
    client.db.hits.docs.append({"user_id": "user_a", "scan_date": "2026-10-20", "scan_id": "1002", "scan_name": "Mock Beta Scan", "direction": "bullish", "symbol": "BBB",
                                "close": 5.0, "pct_change": 1.0, "volume": 10.0, "fetched_at": "2026-10-20T11:00:00Z"})
    latest = client.get("/api/desk/chartink/hits", headers=A).json()
    assert latest["as_of_date"] == "2026-10-20" and [s["symbol"] for s in latest["symbols"]] == ["BBB"]
    assert [s["symbol"] for s in client.get("/api/desk/chartink/hits?date=2026-10-18", headers=A).json()["symbols"]] == ["AAA"]
    none = client.get("/api/desk/chartink/hits?date=2026-01-01", headers=A).json()
    assert none["symbols"] == [] and none["as_of_date"] == "2026-01-01" and "No hits are stored" in none["empty_reason"]
    for bad in ("2026-13-45", "yesterday", "2026-1-1", "20261020"):
        assert client.get("/api/desk/chartink/hits?date=" + bad, headers=A).status_code == 422


def test_hits_follow_the_users_current_enabled_and_direction_choices(client, monkeypatch):
    seed_hits(client, monkeypatch, {"1001": (rows_of("AAA", "BBB"), None), "1002": (rows_of("AAA"), None)})
    client.patch("/api/desk/chartink/scans/1002", json={"direction": "bearish"}, headers=A)
    client.patch("/api/desk/chartink/scans/1001", json={"enabled": False}, headers=A)
    h = client.get("/api/desk/chartink/hits", headers=A).json()
    assert [s["id"] for s in h["scans"]] == ["1002", "1003", "1004", "1005"]
    assert [(s["symbol"], [(x["id"], x["direction"]) for x in s["scans"]]) for s in h["symbols"]] == [("AAA", [("1002", "bearish")])]


def test_hits_report_a_failed_scan_with_its_error_and_empty_states(client):
    assert client.get("/api/desk/chartink/hits", headers=A).json()["empty_reason"] == "No Chartink dashboard is connected."
    put(client)
    h = client.get("/api/desk/chartink/hits", headers=A).json()
    assert h["symbols"] == [] and h["as_of_date"] is None and h["empty_reason"] == "No scan has been refreshed yet." and len(h["scans"]) == 5
    assert all(s["ok"] is None and s["hits"] == 0 for s in h["scans"])
    assert client.get("/api/desk/chartink/hits", headers=B).json()["symbols"] == []


def test_a_failed_scan_shows_ok_false_and_its_error_in_the_hits_view(client, monkeypatch):
    seed_hits(client, monkeypatch, {"1001": (None, "http_429"), "1002": (rows_of("AAA"), None)})
    h = client.get("/api/desk/chartink/hits", headers=A).json()
    s1 = next(s for s in h["scans"] if s["id"] == "1001")
    assert s1["ok"] is False and s1["error"].startswith("http_429:") and s1["hits"] == 0
    assert [s["symbol"] for s in h["symbols"]] == ["AAA"]


# ── the hit index the Strategy Builder reads ─────────────────────────────────

def test_read_index_states(client, monkeypatch):
    db = client.db
    idx = run(hits_mod.read_index(db, "user_a", TODAY))
    assert idx["state"] == "no_source" and idx["symbols"] == {} and "No Chartink dashboard" in idx["reason"]
    import_standard(db)
    idx = run(hits_mod.read_index(db, "user_a", TODAY))
    assert idx["state"] == "not_refreshed" and "has been refreshed" in idx["reason"]
    run(rf.refresh_user(db, "user_a", scan_fn=ok_scan({}, default=rows_of("AAA", "BBB")), now=NOW, spacer=quick_spacer()))
    idx = run(hits_mod.read_index(db, "user_a", TODAY))
    assert idx["state"] == "ok" and idx["scan_date"] == "2026-10-20" and idx["fetched_at"] == "2026-10-20T11:00:00Z" and idx["mode"] == "end_of_day_snapshot"
    assert sorted(idx["symbols"]) == ["AAA", "BBB"] and idx["symbols"]["AAA"]["count"] == 5 and idx["dashboard_id"] == "123456"
    stale = run(hits_mod.read_index(db, "user_a", TODAY + timedelta(days=hits_mod.STALE_AFTER_CALENDAR_DAYS + 1)))
    assert stale["state"] == "stale" and stale["symbols"] == {} and "refresh" in stale["reason"]
    ok_still = run(hits_mod.read_index(db, "user_a", TODAY + timedelta(days=hits_mod.STALE_AFTER_CALENDAR_DAYS)))
    assert ok_still["state"] == "ok"


def test_read_index_zero_hits_is_ok_but_all_failed_is_failed():
    db = FakeDb()
    import_standard(db)
    run(rf.refresh_user(db, "user_a", scan_fn=ok_scan({}, default=[]), now=NOW, spacer=quick_spacer()))
    idx = run(hits_mod.read_index(db, "user_a", TODAY))
    assert idx["state"] == "ok" and idx["symbols"] == {} and idx["scan_date"] == "2026-10-20"       # the scans ran and listed nothing
    run(rf.refresh_user(db, "user_a", scan_fn=lambda c: _fail("http_403"), now=NOW, cooldown=False, spacer=quick_spacer()))
    idx = run(hits_mod.read_index(db, "user_a", TODAY))
    assert idx["state"] == "failed" and "http_403" in idx["reason"] and idx["symbols"] == {}


# ── honesty: no orders, no brokers, no credentials ───────────────────────────

def test_no_order_or_broker_code_in_the_chartink_modules():
    root = Path(__file__).resolve().parents[1]
    files = [*(root / "services" / "chartink_desk").glob("*.py"), root / "routes" / "desk_chartink.py", root / "scripts" / "refresh_chartink.py"]
    assert len(files) >= 7
    for f in files:
        text = f.read_text()
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        assert not re.search(r"(place|modify|cancel|submit)[_ ]?order", code, re.I), f
        assert not re.search(r"^\s*(from|import)\s+\S*(brokers|kite|openalgo|broker_native)", code, re.M), f
        assert not re.search(r"\b(password|api_key|secret|token)\s*=", code, re.I), f
        assert "logger" not in code or "clause" not in " ".join(re.findall(r"logger\.\w+\([^)]*\)", code)), f      # no clause is ever logged
