"""Source-adapter layer (the user's design 2026-09-16): a registry with three ingestion modes (api / http / browser),
routes with automatic PRIMARY → SECONDARY → BROWSER fallback, granular observed statuses instead of a permanent
'blocked', an honest SOURCE_COVERAGE_SCORE (a proxy-served source is never LIVE), per-source health with memory,
and a file-based browser-job queue so fetching can leave the analytics VM. Written before the implementation."""
import json
from datetime import date, datetime
from pathlib import Path

import pytest

FX = Path(__file__).parent / "fixtures"


def test_registry_has_modes_slas_and_granular_statuses():
    from nidp.services.catalyst_intel.registry import MODES, RUNNABLE, SOURCES, STATUSES, get_source, routes_for

    assert {"api", "http", "browser"} == set(MODES)
    for must in ("live", "live_secondary", "degraded", "blocked_temporary", "waf_blocked", "captcha_gated", "session_required", "js_rendered", "endpoint_unknown", "not_built"):
        assert must in STATUSES
    assert "blocked" not in STATUSES and "listing" not in STATUSES               # retired: too coarse
    for s in SOURCES:
        assert s.mode in MODES and s.status in STATUSES and s.sla_hours > 0, s.id
        if s.status in RUNNABLE:
            assert routes_for(s), s.id
            assert all(r.adapter and r.mode in MODES and r.egress in ("primary", "secondary") for r in routes_for(s)), s.id
    # Phase 1 (user priority): NHAI + PIB + eProcure are wired on real endpoints found 2026-09-16
    assert get_source("nhai_press_release").status == "live" and get_source("nhai_press_release").mode == "api"
    assert get_source("nhai_tenders").status == "live" and get_source("nhai_news").status == "live"
    assert get_source("pib").status == "live" and get_source("pib").mode == "http"
    assert get_source("cppp_tenders").status == "live" and get_source("cppp_corrigendums").status == "live"
    assert get_source("cppp_awards").status == "captcha_gated" and get_source("cppp_awards").mode == "browser"
    # DGFT / MCA: CloudFront 403 from BOTH cloud egresses (this VM and app-vm) → a browser route on another egress, not 'blocked'
    assert get_source("dgft").status == "waf_blocked" and get_source("dgft").mode == "browser"
    assert get_source("mca").status == "waf_blocked"
    # FDA: structured feeds, never scraping
    assert get_source("openfda_drug_enforcement").status == "live" and get_source("openfda_drug_enforcement").mode == "api"
    assert get_source("fda_recalls_rss").status == "live"
    assert get_source("fda_warning_letters").status == "degraded"        # xlsx export is unordered and 5 months stale; ajax view 503 from here
    assert get_source("sec_edgar_6k").status == "live" and get_source("sec_edgar_6k").mode == "api"


def test_a_source_without_explicit_routes_derives_one_from_its_url_and_adapter():
    from nidp.services.catalyst_intel.registry import get_source, routes_for

    r = routes_for(get_source("rbi_press"))
    assert len(r) == 1 and r[0].url == get_source("rbi_press").url and r[0].adapter == "parse_rss" and r[0].fetch == "get" and r[0].egress == "primary"


class _Resp:
    def __init__(self, status=200, body=b"", headers=None, url="https://x/", egress="primary"):
        self.status, self.body, self.headers, self.url, self.egress = status, body, {k.lower(): v for k, v in (headers or {}).items()}, url, egress


def test_failure_classification_is_granular_not_a_permanent_blocked():
    from nidp.services.catalyst_intel.transports import classify

    assert classify(_Resp(403, b"", {"Server": "CloudFront", "X-Cache": "Error from cloudfront"})) == "waf_blocked"
    assert classify(_Resp(403, b"<html>Access Denied</html>", {"Server": "AkamaiGHost"})) == "waf_blocked"
    assert classify(_Resp(403, b"forbidden", {})) == "forbidden"
    assert classify(_Resp(404, (FX / "fda_abuse_detection.html").read_bytes(), {}, url="https://www.accessdata.fda.gov/apology_objects/abuse-detection-apology.html")) == "blocked_temporary"
    assert classify(_Resp(429, b"")) == "blocked_temporary" and classify(_Resp(503, b"")) == "blocked_temporary"
    assert classify(_Resp(200, b"")) == "empty_response"
    assert classify(_Resp(200, (FX / "cppp_results_captcha.html").read_bytes())) == "ok"                # a captcha alone proves nothing at HTTP level
    from nidp.services.catalyst_intel.transports import captcha_gated
    assert captcha_gated((FX / "cppp_results_captcha.html").read_bytes(), [])                             # captcha form AND the adapter found no rows
    assert not captcha_gated((FX / "cppp_latest_tenders.html").read_bytes(), [{"title": "row"}])         # captcha widget next to a readable table
    assert not captcha_gated((FX / "heavyind.html").read_bytes(), [{"title": "row"}]) and b"captcha" in (FX / "heavyind.html").read_bytes().lower()
    assert classify(_Resp(200, (FX / "eprocure_session_expired.html").read_bytes())) == "session_required"
    assert classify(_Resp(404, b"nope")) == "not_found"
    assert classify(_Resp(500, b"The website encountered an unexpected error.")) == "server_error"
    assert classify(ConnectionError("timed out")) == "unreachable"


def test_fallback_runs_routes_in_order_and_a_proxy_served_source_is_live_secondary_never_live(tmp_path):
    from nidp.services.catalyst_intel.monitor import fetch_source
    from nidp.services.catalyst_intel.registry import Route, Source

    src = Source("t_fallback", "fallback test", "government", "P0", "https://primary.example/feed", "live", mode="http", sla_hours=24, routes=(
        Route("http", "get", "https://primary.example/feed", "parse_rss"),
        Route("http", "get", "https://primary.example/feed", "parse_rss", egress="secondary"),
        Route("browser", "browser_job", "https://primary.example/feed", "parse_rss"),
    ))
    rss = (FX / "sebi.xml").read_bytes()
    log = []

    class T:
        def request(self, route, url, **kw):
            log.append((route.egress, url))
            if route.egress == "primary":
                return _Resp(403, b"", {"Server": "CloudFront", "X-Cache": "Error from cloudfront"}, url=url)
            return _Resp(200, rss, url=url, egress="secondary")

    res = fetch_source(src, [date(2026, 9, 15)], datetime(2026, 9, 15, 23, 0), transport=T(), home=tmp_path)
    assert len(res.events) >= 5 and res.route.egress == "secondary" and res.observed == "live_secondary"
    assert res.attempts[0]["observed"] == "waf_blocked" and res.attempts[1]["observed"] == "live_secondary"
    assert [e for e, _ in log] == ["primary", "secondary"]                      # the browser route was not needed


def test_when_every_http_route_fails_the_browser_route_enqueues_a_job_and_the_status_is_the_most_specific_failure(tmp_path):
    from nidp.services.catalyst_intel.monitor import fetch_source
    from nidp.services.catalyst_intel.registry import Route, Source

    src = Source("t_allfail", "all fail", "government", "P0", "https://wall.example/", "waf_blocked", mode="browser", sla_hours=24, routes=(
        Route("http", "get", "https://wall.example/", "parse_listing"),
        Route("http", "get", "https://wall.example/", "parse_listing", egress="secondary"),
        Route("browser", "browser_job", "https://wall.example/", "parse_listing"),
    ))

    class T:
        def request(self, route, url, **kw):
            return _Resp(403, b"", {"Server": "CloudFront"}, url=url, egress=route.egress)

    res = fetch_source(src, [date(2026, 9, 15)], datetime(2026, 9, 15, 23, 0), transport=T(), home=tmp_path)
    assert res.events == [] and res.observed == "waf_blocked" and res.route is None
    jobs = list((tmp_path / "browser_jobs" / "pending").glob("*.json"))
    assert len(jobs) == 1
    job = json.loads(jobs[0].read_text())
    assert job["source_id"] == "t_allfail" and job["url"] == "https://wall.example/" and job["adapter"] == "parse_listing" and job["reason"] == "waf_blocked"
    # a second run does not duplicate the pending job
    fetch_source(src, [date(2026, 9, 15)], datetime(2026, 9, 15, 23, 5), transport=T(), home=tmp_path)
    assert len(list((tmp_path / "browser_jobs" / "pending").glob("*.json"))) == 1


def test_coverage_score_is_honest_secondary_egress_and_degraded_sources_earn_partial_credit_blocked_and_unbuilt_earn_none():
    from nidp.services.catalyst_intel.monitor import coverage_score
    from nidp.services.catalyst_intel.registry import Source

    reg = [Source("a", "a", "regulator", "P0", "u", "live", mode="http", sla_hours=24), Source("b", "b", "government", "P0", "u", "live", mode="http", sla_hours=24),
           Source("c", "c", "government", "P1", "u", "degraded", mode="http", sla_hours=24), Source("d", "d", "government", "P1", "u", "not_built", mode="http", sla_hours=24),
           Source("e", "e", "news", "P2", "u", "waf_blocked", mode="browser", sla_hours=24)]
    observed = {"a": "live", "b": "live_secondary", "c": "degraded", "e": "waf_blocked"}
    cov = coverage_score(reg, observed)
    # weights P0=4, P1=2, P2=1: (4*1.0 + 4*0.75 + 2*0.5 + 2*0 + 1*0) / (4+4+2+2+1) = 8/13
    assert cov["score"] == pytest.approx(8 / 13, abs=1e-6) and cov["denominator"] == 13
    assert cov["by_status"]["live"] == 1 and cov["by_status"]["live_secondary"] == 1 and cov["by_status"]["not_built"] == 1
    # faking LIVE through a proxy would have scored higher: the score must not reward it
    assert cov["score"] < coverage_score(reg, {**observed, "b": "live"})["score"]


def test_health_rollup_remembers_last_ok_and_counts_consecutive_failures(tmp_path):
    from nidp.services.catalyst_intel.monitor import Health

    h = Health(tmp_path)
    h.record("x", observed="live", fetched=10, at=datetime(2026, 9, 15, 9, 0), route="primary")
    h.record("x", observed="blocked_temporary", fetched=0, at=datetime(2026, 9, 15, 9, 15), route=None, error="HTTP 503")
    h.record("x", observed="blocked_temporary", fetched=0, at=datetime(2026, 9, 15, 9, 30), route=None, error="HTTP 503")
    h.save()
    again = Health(tmp_path)
    x = again.get("x")
    assert x["consecutive_failures"] == 2 and x["last_ok_at"].startswith("2026-09-15T09:00") and x["last_observed"] == "blocked_temporary" and x["last_error"] == "HTTP 503"
    again.record("x", observed="live", fetched=3, at=datetime(2026, 9, 15, 9, 45), route="primary")
    assert again.get("x")["consecutive_failures"] == 0 and again.get("x")["last_route"] == "primary"


def test_empty_feed_within_sla_is_fine_but_past_sla_is_stale():
    from nidp.services.catalyst_intel.monitor import observe

    assert observe(fetched=0, http_ok=True, route_egress="primary", last_ok_at=datetime(2026, 9, 15, 8, 0), now=datetime(2026, 9, 15, 9, 0), sla_hours=24) == "empty"
    assert observe(fetched=0, http_ok=True, route_egress="primary", last_ok_at=datetime(2026, 9, 10, 8, 0), now=datetime(2026, 9, 15, 9, 0), sla_hours=24) == "stale"
    assert observe(fetched=7, http_ok=True, route_egress="secondary", last_ok_at=None, now=datetime(2026, 9, 15, 9, 0), sla_hours=24) == "live_secondary"
    assert observe(fetched=7, http_ok=True, route_egress="primary", last_ok_at=None, now=datetime(2026, 9, 15, 9, 0), sla_hours=24) == "live"


def test_browser_results_are_ingested_through_the_same_adapters_and_blocked_results_only_update_health(tmp_path):
    from nidp.services.catalyst_intel.browser_jobs import enqueue, ingest_results
    from nidp.services.catalyst_intel.monitor import Health
    from nidp.services.catalyst_intel.registry import Route, Source
    from nidp.services.catalyst_intel.store import EventStore

    src = Source("t_browser", "browser src", "government", "P0", "https://wall.example/list", "waf_blocked", mode="browser", sla_hours=24,
                 routes=(Route("browser", "browser_job", "https://wall.example/list", "parse_rss"),))
    home = tmp_path
    p = enqueue(home, src, src.routes[0], reason="waf_blocked", at=datetime(2026, 9, 15, 9, 0))
    assert p.exists() and json.loads(p.read_text())["mode"] == "browser"
    done = home / "browser_jobs" / "done"; done.mkdir(parents=True, exist_ok=True)
    (done / p.name).write_text(json.dumps({"source_id": "t_browser", "url": src.url, "adapter": "parse_rss", "status": "ok", "http_status": 200,
                                          "fetched_at": "2026-09-15T09:30:00+05:30", "egress": "browser:laptop", "body_b64": __import__("base64").b64encode((FX / "sebi.xml").read_bytes()).decode()}))
    (done / "blocked.json").write_text(json.dumps({"source_id": "t_browser", "url": src.url, "adapter": "parse_rss", "status": "waf_blocked", "http_status": 403,
                                                   "fetched_at": "2026-09-15T09:31:00+05:30", "egress": "browser:laptop", "body_b64": ""}))
    st = EventStore(home); h = Health(home)
    summary = ingest_results(home, st, h, registry={"t_browser": src})
    assert summary["ingested"] == 1 and summary["new_events"] >= 5 and summary["failed"] == 1
    assert h.get("t_browser")["last_observed"] in ("waf_blocked", "live_browser") and not list(done.glob("*.json"))    # results are archived after ingestion
    assert list((home / "browser_jobs" / "archive").glob("*.json"))
    assert st.query(source_id="t_browser")[0]["received_at"].startswith("2026-09-15T09:30")   # received_at is the browser's fetch time, not ingestion time


def test_run_manifest_carries_route_observed_status_and_coverage(tmp_path):
    from nidp.services.catalyst_intel.monitor import run_sources
    from nidp.services.catalyst_intel.registry import get_source
    from nidp.services.catalyst_intel.store import EventStore
    from nidp.services.catalyst_intel import adapters

    def ok(source, days, received_at): return adapters.parse_rss((FX / "sebi.xml").read_bytes(), received_at=received_at, source_id="sebi_rss")
    def boom(source, days, received_at): raise ConnectionError("timeout")
    m = run_sources([get_source("sebi_rss"), get_source("rbi_press")], EventStore(tmp_path), {"sebi_rss": ok, "rbi_press": boom}, today=date(2026, 9, 15))
    assert m["sources"]["sebi_rss"]["observed"] == "live" and m["sources"]["rbi_press"]["observed"] == "unreachable"
    assert 0 < m["coverage"]["score"] < 1 and "denominator" in m["coverage"]
    assert (tmp_path / "health.json").exists()


def test_a_degraded_source_is_never_promoted_to_live_and_browser_only_sources_are_reprobed_on_a_cadence(tmp_path):
    from nidp.services.catalyst_intel.monitor import Health, due_for_reprobe, fetch_source, run_sources
    from nidp.services.catalyst_intel.registry import Route, Source
    from nidp.services.catalyst_intel.store import EventStore

    rss = (FX / "sebi.xml").read_bytes()
    deg = Source("t_deg", "degraded src", "global", "P0", "https://d.example/x", "degraded", mode="http", sla_hours=24, routes=(Route("http", "get", "https://d.example/x", "parse_rss"),))

    class T:
        def request(self, route, url, **kw): return _Resp(200, rss, url=url)

    res = fetch_source(deg, [date(2026, 9, 15)], datetime(2026, 9, 15, 9, 0), transport=T(), home=tmp_path)
    assert len(res.events) >= 5 and res.observed == "degraded"
    h = Health(tmp_path)
    assert due_for_reprobe(h, "t_wall", datetime(2026, 9, 15, 9, 0))
    wall = Source("t_wall", "wall", "government", "P0", "https://wall.example/", "waf_blocked", mode="browser", sla_hours=24,
                  routes=(Route("http", "get", "https://wall.example/", "parse_listing"), Route("browser", "browser_job", "https://wall.example/", "parse_listing")))

    class W:
        def __init__(self): self.calls = 0
        def request(self, route, url, **kw): self.calls += 1; return _Resp(403, b"", {"Server": "CloudFront"}, url=url)

    w = W(); st = EventStore(tmp_path)
    m1 = run_sources([wall], st, today=date(2026, 9, 15), transport=w)
    assert w.calls == 1 and m1["sources"]["t_wall"]["observed"] == "waf_blocked" and m1["queued"] == 0 and m1["failed"] == 1
    m2 = run_sources([wall], st, today=date(2026, 9, 15), transport=w)           # minutes later: no second probe, job stays queued
    assert w.calls == 1 and m2["sources"]["t_wall"]["observed"] == "queued" and m2["queued"] == 1
    assert Health(tmp_path).get("t_wall")["last_observed"] == "queued" and Health(tmp_path).get("t_wall")["consecutive_failures"] == 1
