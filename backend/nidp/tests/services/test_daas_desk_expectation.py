"""DaaS /v1/desk/events-calendar/expectation (nidp/services/daas_api/routers/desk_expectation.py).

No live Postgres. Every fixture is MOCK — not real data (hand-computable numbers); the real-data runs are in
test_reports/desk_results_expectation_backend_20261021.md.

Worked example (hand-checked), revenue of one stock, ₹ crore, target quarter Dec 2026:
  same quarter last year (Dec 2025)  110        last quarter (Sep 2026) 145.6, a year earlier (Sep 2025) 130  → g1 = +12 %
  quarter before (Jun 2026)          129.6      a year earlier (Jun 2025) 120                                  → g2 = +8 %
  g = (12 % + 8 %) ÷ 2 = 10 %       expected = 110 × 1.10 = 121.0
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from nidp.services.daas_api.routers import desk_expectation as dx

D = date
UTC = timezone.utc
H = {"X-API-Key": "nvd_t_token"}


def qrow(sym, pe, rev, pat, eps=None, cons=True, bc=None, src="trendlyne_mcp"):
    return {"symbol": sym, "period_end": pe, "consolidated": cons, "revenue_from_ops_cr": rev, "pat_cr": pat, "eps_basic": eps,
            "broadcast_at": bc, "source": src, "ingested_at": datetime(2026, 10, 20, tzinfo=UTC)}


# Dec 2024 … Sep 2026 (8 quarters). Revenue: Dec-25 110, Sep-25 130, Jun-25 120, Sep-26 145.6, Jun-26 129.6.
PES = [D(2024, 12, 31), D(2025, 3, 31), D(2025, 6, 30), D(2025, 9, 30), D(2025, 12, 31), D(2026, 3, 31), D(2026, 6, 30), D(2026, 9, 30)]
REV = [100, 110, 120, 130, 110, 121, 129.6, 145.6]
PAT = [10, 11, 12, 13, 11, 12.1, 12.96, 14.56]
EPS = [1.0, 1.1, 1.2, 1.3, 1.1, 1.21, 1.296, 1.456]


def rows_for(sym="ABC", rev=REV, pat=PAT, eps=EPS, cons=True, drop=(), src="trendlyne_mcp"):
    return [qrow(sym, pe, rev[i], pat[i], eps[i], cons, bc=datetime(pe.year, pe.month, 28, tzinfo=UTC) + timedelta(days=30), src=src)
            for i, pe in enumerate(PES) if i not in drop]


def store_of(*row_sets):
    return dx.build_store([r for rs in row_sets for r in rs])


# ── TC-1 / TC-2: the reporting period ────────────────────────────────────────

@pytest.mark.parametrize("purpose,ev,want,inferred", [
    ("To consider and approve the financial results for the period ended September 30, 2026", D(2026, 10, 23), D(2026, 9, 30), False),
    ("To consider and approve the financial results for the period ended Jun 30, 2026", D(2026, 7, 9), D(2026, 6, 30), False),
    ("To consider and approve the quarterly audited financial results for the period ended December 31, 2025", D(2026, 1, 12), D(2025, 12, 31), False),
    ("quarter ended 30th September 2026", D(2026, 10, 23), D(2026, 9, 30), False),
    ("Approval of the Financial Results and consideration of declaration of second interim dividend", D(2026, 10, 8), D(2026, 9, 30), True),
    (None, D(2026, 1, 12), D(2025, 12, 31), True),
    ("results", D(2026, 5, 20), D(2026, 3, 31), True),
])
def test_period_end_is_read_from_the_purpose_else_inferred(purpose, ev, want, inferred):
    assert dx.parse_period_end(purpose, ev) == (want, inferred)


def test_period_label_is_the_indian_fiscal_quarter():
    assert dx.period_label(D(2026, 9, 30)) == "Q2 FY27 (Jul–Sep 2026)"
    assert dx.period_label(D(2026, 3, 31)) == "Q4 FY26 (Jan–Mar 2026)"
    assert dx.period_label(D(2026, 6, 30)) == "Q1 FY27 (Apr–Jun 2026)"


def test_shift_quarters_crosses_years():
    assert dx.shift_quarters(D(2026, 12, 31), -4) == D(2025, 12, 31)
    assert dx.shift_quarters(D(2026, 3, 31), -5) == D(2024, 12, 31)
    assert dx.shift_quarters(D(2025, 12, 31), 1) == D(2026, 3, 31)


# ── TC-3: the arithmetic ─────────────────────────────────────────────────────

def test_expected_is_same_quarter_last_year_times_average_of_the_last_two_growth_rates():
    rev = list(REV)
    rev[7], rev[6] = 145.6, 129.6          # g1 = 145.6/130 − 1 = 12 %, g2 = 129.6/120 − 1 = 8 %
    st = store_of(rows_for(rev=rev))
    f, why = dx.forecast_metric(st["ABC"][True], "revenue", D(2026, 12, 31), None)
    assert why is None
    assert f["g1"] == pytest.approx(0.12) and f["g2"] == pytest.approx(0.08) and f["g"] == pytest.approx(0.10)
    assert f["mid"] == pytest.approx(121.0)
    assert f["base"] == 110 and f["prev"] == 145.6


# ── TC-4 / TC-5: no leakage ──────────────────────────────────────────────────

def test_quarters_known_after_the_cutoff_are_not_used():
    st = store_of(rows_for())
    by = st["ABC"][True]
    p1_known = by[D(2026, 9, 30)]["known_at"]
    f, why = dx.forecast_metric(by, "revenue", D(2026, 12, 31), p1_known)        # cutoff = the moment the t−1 filing was broadcast
    assert f is None and "only 4 of the 5" in why
    f, why = dx.forecast_metric(by, "revenue", D(2026, 12, 31), p1_known + timedelta(seconds=1))
    assert why is None


def test_a_quarter_without_a_broadcast_time_is_known_sixty_days_after_its_end():
    rows = [dict(r, broadcast_at=None) for r in rows_for()]
    by = dx.build_store(rows)["ABC"][True]
    assert by[D(2026, 9, 30)]["known_at"] == datetime(2026, 11, 29, tzinfo=UTC)
    assert dx.known_at(D(2026, 9, 30), None) == datetime(2026, 11, 29, tzinfo=UTC)
    f, why = dx.forecast_metric(by, "revenue", D(2026, 12, 31), datetime(2026, 11, 28, tzinfo=UTC))
    assert f is None                                                           # Sep-26 not yet known on 28 Nov under the 60-day rule


def test_a_declared_expectation_ignores_the_target_filing_and_anything_after_it():
    """The target's own row exists in the store; the expectation computed 'as of its broadcast' must equal the one computed without it."""
    full = store_of(rows_for())
    target = D(2026, 9, 30)
    cut = full["ABC"][True][target]["known_at"]
    with_target, _ = dx.forecast_metric(full["ABC"][True], "revenue", target, cut)
    without = store_of(rows_for(drop=(7,)))
    without_target, _ = dx.forecast_metric(without["ABC"][True], "revenue", target, cut)
    assert with_target["mid"] == without_target["mid"]
    assert with_target["mid"] == pytest.approx(REV[3] * (1 + ((REV[6] / REV[2] - 1) + (REV[5] / REV[1] - 1)) / 2))


# ── TC-6 / TC-7: when there is no number ─────────────────────────────────────

def test_negative_or_zero_profit_in_a_quarter_the_method_divides_by_gives_no_number():
    pat = list(PAT); pat[3] = -2                                               # Sep-25 loss: the base of g1
    by = store_of(rows_for(pat=pat))["ABC"][True]
    f, why = dx.forecast_metric(by, "pat", D(2026, 12, 31), None)
    assert f is None and "zero or negative" in why


def test_near_zero_profit_base_is_not_used():
    pat = list(PAT); pat[4] = 0.02                                             # Dec-25 profit 0.02 on revenue 110 (< 0.5 %)
    by = store_of(rows_for(pat=pat))["ABC"][True]
    f, why = dx.forecast_metric(by, "pat", D(2026, 12, 31), None)
    assert f is None and "under 0.5 %" in why


def test_growth_beyond_100_percent_gives_no_number():
    rev = list(REV); rev[7], rev[6] = 400, 400
    f, why = dx.forecast_metric(store_of(rows_for(rev=rev))["ABC"][True], "revenue", D(2026, 12, 31), None)
    assert f is None and "beyond ±100 %" in why


def test_fewer_than_the_needed_quarters_gives_no_number_and_says_how_many():
    by = store_of(rows_for(drop=(0, 1)))["ABC"][True]                          # Dec-24 and Mar-25 missing: t−6 (Jun-25 is index 2) stays, t−5 for Dec-26 is Sep-25
    f, why = dx.forecast_metric(by, "revenue", D(2027, 3, 31), None)           # needs Mar-26(t−4)? yes; Dec-26 (t−1) is missing
    assert f is None and "of the 5 earlier quarters" in why


# ── TC-8: basis ──────────────────────────────────────────────────────────────

def test_consolidated_is_used_when_complete_and_standalone_when_it_is_not():
    cons_ok = store_of(rows_for(cons=True), rows_for(cons=False))["ABC"]
    assert dx.pick_basis(cons_ok, D(2026, 12, 31), None) == (True, 5)
    cons_gap = store_of(rows_for(cons=True, drop=(4,)), rows_for(cons=False))["ABC"]
    assert dx.pick_basis(cons_gap, D(2026, 12, 31), None) == (False, 5)
    only_partial = store_of(rows_for(cons=True, drop=(4,)))["ABC"]
    assert dx.pick_basis(only_partial, D(2026, 12, 31), None) == (True, 4)


def test_answer_names_the_basis():
    models = dx.build_models(rows_for(cons=False))
    a = dx.answer(models, "ABC", D(2027, 1, 12), "period ended December 31, 2026", D(2027, 1, 5), [])
    assert a["basis"] == "standalone" and a["status"] == "upcoming"


# ── TC-9: banks / a missing revenue series ───────────────────────────────────

def test_missing_revenue_makes_only_revenue_unreliable_profit_is_still_computed():
    rev = [None] * 8
    models = dx.build_models(rows_for(rev=rev))
    # calibrate with a larger synthetic universe so a band exists
    models = dx.build_models(rows_for(rev=rev) + universe_rows(150))
    a = dx.answer(models, "ABC", D(2027, 1, 12), "period ended December 31, 2026", D(2027, 1, 5), [])
    by = {m["key"]: m for m in a["metrics"]}
    assert by["revenue"]["reliable"] is False and by["revenue"]["expected"] is None and "earlier quarters" in by["revenue"]["note"]
    assert by["pat"]["reliable"] is True and by["pat"]["expected"]["mid"] == pytest.approx(11 * (1 + ((14.56 / 13 - 1) + (12.96 / 12 - 1)) / 2), abs=0.06)


# ── TC-10: EPS ───────────────────────────────────────────────────────────────

def test_expected_eps_follows_expected_profit_on_the_latest_share_base():
    models = dx.build_models(rows_for() + universe_rows(150))
    a = dx.answer(models, "ABC", D(2027, 1, 12), "period ended December 31, 2026", D(2027, 1, 5), [])
    pat = next(m for m in a["metrics"] if m["key"] == "pat")["expected"]
    eps = next(m for m in a["metrics"] if m["key"] == "eps")
    ratio = 1.456 / 14.56
    assert eps["expected"]["mid"] == pytest.approx(pat["mid"] * ratio, abs=0.01) and eps["reliable"] is True
    assert "share base" in eps["note"]


def test_expected_eps_is_null_when_the_latest_profit_is_not_positive():
    pat = list(PAT); pat[7] = -1
    models = dx.build_models(rows_for(pat=pat) + universe_rows(150))
    a = dx.answer(models, "ABC", D(2027, 1, 12), "period ended December 31, 2026", D(2027, 1, 5), [])
    eps = next(m for m in a["metrics"] if m["key"] == "eps")
    assert eps["expected"] is None and eps["reliable"] is False


# ── TC-11 / TC-12: the band and the backtest ─────────────────────────────────

def universe_rows(n, seed=0):
    """n synthetic stocks whose 8 quarters grow at slightly different rates, so the method has non-zero errors (MOCK)."""
    import random
    rnd = random.Random(seed)
    rows = []
    for k in range(n):
        g = rnd.uniform(-0.05, 0.30)
        base = [100 * (1 + g * (i / 4)) for i in range(8)]
        noise = [rnd.uniform(-0.06, 0.06) for _ in range(8)]
        rev = [b * (1 + e) for b, e in zip(base, noise)]
        rows += rows_for(f"S{k}", rev=rev, pat=[r * 0.1 for r in rev], eps=[r * 0.01 for r in rev])
    return rows


def test_backtest_tests_every_stock_on_quarters_known_before_the_tested_one():
    st = dx.build_store(universe_rows(20))
    recs = dx.run_backtest(st, "revenue")
    assert recs and all(r["target"] in (D(2026, 6, 30), D(2026, 9, 30)) for r in recs)   # 8 quarters → exactly 2 testable targets
    assert {r["symbol"] for r in recs} == {f"S{k}" for k in range(20)}
    assert len(recs) == 40


def test_backtest_error_is_actual_over_expected_minus_one():
    rows = rows_for("Z")
    recs = dx.run_backtest(dx.build_store(rows), "revenue")
    sep = next(r for r in recs if r["target"] == D(2026, 9, 30))
    mid = REV[3] * (1 + ((REV[6] / REV[2] - 1) + (REV[5] / REV[1] - 1)) / 2)
    assert sep["error_pct"] == pytest.approx((REV[7] / mid - 1) * 100)
    assert sep["instability"] == pytest.approx(abs((REV[6] / REV[2] - 1) - (REV[5] / REV[1] - 1)))


def test_band_is_the_quantiles_of_past_errors_with_a_minimum_width():
    recs = [{"symbol": f"S{i}", "target": D(2026, 9, 30), "instability": 0.05, "error_pct": float(e)} for i, e in enumerate(range(-50, 51))]
    cal = dx.Calibration(recs, "revenue")
    b = cal.band(200.0, 0.05)
    # pooled (101 records < 3 buckets × 100): 10th and 90th percentile of −50…+50 are −40 and +40
    assert b["low"] == pytest.approx(200 * 0.6) and b["high"] == pytest.approx(200 * 1.4) and b["mid"] == 200.0
    tight = [{"symbol": "a", "target": D(2026, 9, 30), "instability": 0.0, "error_pct": 0.1} for _ in range(10)]
    b2 = dx.Calibration(tight, "revenue").band(100.0, 0.0)
    assert b2["low"] <= 99.0 and b2["high"] >= 101.0                           # ±1 % minimum for revenue
    b3 = dx.Calibration(tight, "pat").band(100.0, 0.0)
    assert b3["low"] <= 97.0 and b3["high"] >= 103.0                           # ±3 % minimum for profit


def test_a_more_unstable_stock_gets_a_wider_band():
    recs = []
    for i in range(300):
        inst = i / 300
        recs.append({"symbol": f"S{i}", "target": D(2026, 9, 30), "instability": inst, "error_pct": (-1 if i % 2 else 1) * (1 + 40 * inst)})
    cal = dx.Calibration(recs, "pat")
    calm, wild = cal.band(100.0, 0.01), cal.band(100.0, 0.95)
    assert (wild["high"] - wild["low"]) > 3 * (calm["high"] - calm["low"])


def test_universe_backtest_reports_accuracy_the_naive_benchmark_and_out_of_sample_checks():
    models = dx.build_models(universe_rows(400, seed=3))
    u = models["universe"]["revenue"]
    assert u["n"] == 800 and u["median_abs_err_pct"] > 0 and u["naive_flat_median_abs_err_pct"] > 0
    assert u["held_out_stocks"]["calibrated_on_n"] + u["held_out_stocks"]["tested_n"] == 800
    assert 0 <= u["held_out_stocks"]["within_band_pct"] <= 100 and u["within_band_pct"] == u["held_out_stocks"]["within_band_pct"]
    assert u["latest_quarter"]["tested_on"] == "2026-09-30" and u["latest_quarter"]["calibrated_on"] == ["2026-06-30"]
    assert u["latest_quarter"]["tested_n"] == 400
    assert 75 <= u["in_sample_within_band_pct"] <= 85                          # a 10–90 band covers about 80 % of its own errors
    assert 70 <= u["held_out_stocks"]["within_band_pct"] <= 90                 # and about that much of stocks it never saw


def test_backtest_records_carry_the_naive_flat_error():
    recs = dx.run_backtest(dx.build_store(rows_for("Z")), "revenue")
    sep = next(r for r in recs if r["target"] == D(2026, 9, 30))
    assert sep["naive_error_pct"] == pytest.approx((REV[7] / REV[3] - 1) * 100)


# ── TC-13: declared ──────────────────────────────────────────────────────────

def test_declared_event_compares_the_filing_with_an_expectation_made_before_it():
    models = dx.build_models(rows_for() + universe_rows(400, seed=3))
    a = dx.answer(models, "ABC", D(2026, 10, 8), "period ended September 30, 2026", D(2026, 10, 21), [])
    assert a["status"] == "declared" and a["compared_with"] == "vs Nivesh baseline, not vs consensus"
    rev = next(m for m in a["metrics"] if m["key"] == "revenue")
    mid = REV[3] * (1 + ((REV[6] / REV[2] - 1) + (REV[5] / REV[1] - 1)) / 2)
    assert rev["filed"]["value"] == 145.6 and rev["expected"]["mid"] == pytest.approx(mid, abs=0.06)
    assert rev["vs_mid_pct"] == pytest.approx((145.6 / mid - 1) * 100, abs=0.1)
    assert rev["within_band"] in (True, False) and rev["filed"]["audit_status"] == "not recorded"
    assert a["expected_as_of"] <= (datetime(2026, 9, 30, tzinfo=UTC) + timedelta(days=60)).isoformat()


def test_a_passed_date_without_stored_figures_is_declared_with_no_filed_value_and_a_gap():
    models = dx.build_models(rows_for(drop=(7,)) + universe_rows(150))
    a = dx.answer(models, "ABC", D(2026, 10, 8), "period ended September 30, 2026", D(2026, 10, 21), [])
    assert a["status"] == "declared" and all(m["filed"] is None for m in a["metrics"])
    assert any("filed figures are not in the stored results" in g for g in a["gaps"])


# ── TC-14: audit ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("purpose,want", [
    ("To consider and approve Unaudited Standalone and Consolidated Financial Results for the quarter ended 30th June, 2026.", "unaudited"),
    ("To consider and approve the un-audited financial results", "unaudited"),
    ("To consider and approve the quarterly audited financial results for the period ended December 31, 2025", "audited"),
    ("Unaudited results for the quarter and audited results for the year ended March 31, 2026", "mixed"),
    ("To consider and approve the financial results for the period ended Jun 30, 2026", "not recorded"),
    (None, "not recorded"),
])
def test_audit_status_comes_only_from_the_companys_own_notice(purpose, want):
    status, basis = dx.audit_from_notice(purpose)
    assert status == want
    assert ("board-meeting notice" in basis) or status == "not recorded"


def test_audit_status_is_not_recorded_when_the_notice_is_silent_and_never_inferred():
    models = dx.build_models(rows_for() + universe_rows(150))
    a = dx.answer(models, "ABC", D(2026, 10, 8), "period ended September 30, 2026", D(2026, 10, 21), [])
    assert a["audit_status"] == "not recorded"
    assert all(m["filed"] is None or m["filed"]["audit_status"] == "not recorded" for m in a["metrics"])
    b = dx.answer(models, "ABC", D(2026, 10, 8), "Unaudited results for the period ended September 30, 2026", D(2026, 10, 21), [])
    assert b["audit_status"] == "unaudited" and all(m["filed"]["audit_status"] == "unaudited" for m in b["metrics"] if m["filed"])
    assert any("only where the company's own board-meeting notice states it" in g for g in b["gaps"])


def test_no_consensus_and_no_sentiment_anywhere():
    models = dx.build_models(rows_for() + universe_rows(150))
    a = dx.answer(models, "ABC", D(2027, 1, 12), "period ended December 31, 2026", D(2027, 1, 5), [])
    text = repr(a).lower()
    assert any("no analyst consensus" in g for g in a["gaps"])
    for word in ("bullish", "bearish", "sentiment", "impact_score"):
        assert word not in text


# ── TC-15: evidence ──────────────────────────────────────────────────────────

def _ann(day, subject, cat, sub="", url="https://nsearchives.nseindia.com/x.pdf"):
    return {"filed_at": datetime(2026, 10, day, 10, tzinfo=UTC), "subject": subject, "event_category": cat, "subcategory": sub, "attachment_url": url}


def test_evidence_puts_business_filings_first_drops_noise_dedupes_and_carries_no_score():
    rows = [_ann(1, "Press Release", "capex"), _ann(1, "Press Release", "capex"), _ann(9, "Outcome of Board Meeting", "management"),
            _ann(8, "Award of Order / Receipt of Order", "orders"), _ann(7, "Disclosures under Reg. 29(2)", "regulatory"),
            _ann(6, "Analyst / Investor Meet", "other", "Analyst / Investor Meet"), _ann(5, "Newspaper Publication", "other"),
            _ann(3, "Credit Rating", "rating")]
    out = dx.rank_evidence(rows)
    titles = [e["title"] for e in out]
    assert titles.count("Press Release") == 1 and "Disclosures under Reg. 29(2)" not in titles and "Newspaper Publication" not in titles
    assert titles[-1] == "Outcome of Board Meeting" or "Outcome of Board Meeting" in titles
    assert [e["date"] for e in out] == sorted((e["date"] for e in out), reverse=True)
    for e in out:
        assert set(e) == {"date", "title", "category", "source", "url"} and e["url"].startswith("https://nsearchives")


def test_evidence_is_capped():
    rows = [_ann(d, f"Award of Order {d}", "orders") for d in range(1, 29)]
    assert len(dx.rank_evidence(rows)) == dx.EVIDENCE_LIMIT


# ── TC-16: the route ─────────────────────────────────────────────────────────

class _Conn:
    def __init__(self, db):
        self.db = db

    async def fetchrow(self, q, *a):
        assert "nidp.event_calendar" in q
        return self.db.get("event")

    async def fetch(self, q, *a):
        if "nidp.nse_financials_quarterly" in q:
            return self.db["quarters"]
        if "nidp.corporate_announcements" in q:
            return self.db.get("evidence", [])
        raise AssertionError("unexpected query: " + q[:80])


class _Pool:
    def __init__(self, db):
        self.conn = _Conn(db)

    def acquire(self):
        conn = self.conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _CM()


@pytest.fixture
def make_client(monkeypatch):
    from nidp.services.daas_api import auth, keys, ratelimit

    def _make(db):
        dx._cache.update({"at": 0.0, "value": None})
        pool = _Pool(db)

        async def _get_pool():
            return pool
        monkeypatch.setattr(dx, "get_pool", _get_pool)
        rec = keys.KeyRecord(key_id="00000000-0000-0000-0000-000000000009", key_prefix="nvd_t", name="t", owner_email="t@nivesh",
                             plan="internal", rate_limit_rpm=1500, daily_quota=None, status="active", expires_at=None)

        async def _resolve(_t):
            return rec
        monkeypatch.setattr(auth, "_resolve", _resolve)

        async def _consume(key_id, *, limit_rpm, daily_quota):
            return ratelimit.LimitDecision(allowed=True, limit_rpm=limit_rpm, remaining_rpm=limit_rpm - 1, reset_seconds=60,
                                           daily_quota=daily_quota, daily_used=1, daily_remaining=None, reason=None)
        monkeypatch.setattr(ratelimit, "consume", _consume)
        app = FastAPI()

        @app.exception_handler(RequestValidationError)
        async def _validation(_request, exc):
            return JSONResponse(status_code=400, content={"error": {"status": 400, "message": "validation_error"}})

        app.include_router(dx.router, prefix="/v1")
        return TestClient(app)
    return _make


EVENT = {"symbol": "ABC", "event_date": D(2027, 1, 12), "period": None,
         "purpose": "To consider and approve the financial results for the period ended December 31, 2026", "intimated_at": None}


def test_route_answers_for_an_upcoming_results_meeting(make_client, monkeypatch):
    monkeypatch.setattr(dx, "_today", lambda: D(2027, 1, 5))
    c = make_client({"event": EVENT, "quarters": rows_for() + universe_rows(150), "evidence": [_ann(1, "Press Release", "capex")]})
    r = c.get("/v1/desk/events-calendar/expectation?symbol=abc&date=2027-01-12", headers=H)
    assert r.status_code == 200
    b = r.json()
    assert (b["symbol"], b["period_end"], b["basis"], b["status"]) == ("ABC", "2026-12-31", "consolidated", "upcoming")
    assert [m["key"] for m in b["metrics"]] == ["revenue", "pat", "eps"]
    assert b["evidence"][0]["title"] == "Press Release" and b["method"]["universe_backtest"]["n"] > 0
    assert b["label"].startswith("A baseline from the company's own published quarters")


def test_route_404_when_there_is_no_results_meeting_that_day(make_client):
    c = make_client({"event": None, "quarters": []})
    assert c.get("/v1/desk/events-calendar/expectation?symbol=ABC&date=2026-12-21", headers=H).status_code == 404


@pytest.mark.parametrize("qs", ["symbol=ABC&date=2026-13-01", "symbol=ABC&date=oct", "symbol=ABC&date=2026-1-5"])
def test_route_400_on_a_bad_date(make_client, qs):
    c = make_client({"event": EVENT, "quarters": []})
    assert c.get("/v1/desk/events-calendar/expectation?" + qs, headers=H).status_code == 400


@pytest.mark.parametrize("qs", ["", "date=2027-01-12", "symbol=ABC"])
def test_route_400_on_missing_params(make_client, qs):
    c = make_client({"event": EVENT, "quarters": []})
    assert c.get("/v1/desk/events-calendar/expectation?" + qs, headers=H).status_code == 400


def test_route_without_a_key_is_401(make_client):
    c = make_client({"event": EVENT, "quarters": []})
    assert c.get("/v1/desk/events-calendar/expectation?symbol=ABC&date=2027-01-12").status_code in (401, 403)


def test_a_symbol_with_no_stored_quarters_says_so_and_shows_no_numbers():
    models = dx.build_models(rows_for() + universe_rows(150))
    a = dx.answer(models, "NOPE", D(2027, 1, 12), "period ended December 31, 2026", D(2027, 1, 5), [])
    assert a["basis"] is None and all(m["expected"] is None for m in a["metrics"])
    assert any("no published quarterly results" in g for g in a["gaps"])


# ── the band by company size ─────────────────────────────────────────────────

def test_a_larger_company_gets_a_narrower_band_than_a_small_one_when_its_past_errors_were_smaller():
    recs = []
    for i in range(600):
        big = i % 2 == 0
        spread = 5 if big else 40
        recs.append({"symbol": f"S{i}", "target": D(2026, 9, 30), "instability": 0.05, "size": 50000.0 if big else 50.0,
                     "error_pct": (-1 if i % 4 < 2 else 1) * spread * ((i % 7) + 1) / 7})
    cal = dx.Calibration(recs, "revenue")
    big, small = cal.band(100.0, 0.05, 50000.0), cal.band(100.0, 0.05, 50.0)
    assert (big["high"] - big["low"]) < (small["high"] - small["low"]) / 3
    assert cal.band_pct(0.05, 50000.0)[3] == "similar size and growth stability"
    assert cal.band_pct(0.05, None)[3] == "similar growth stability"           # size unknown → the stability group


def test_a_thin_cell_falls_back_to_the_wider_group_then_to_all_stocks():
    recs = [{"symbol": f"S{i}", "target": D(2026, 9, 30), "instability": 0.05, "size": 100.0, "error_pct": float(i % 21 - 10)} for i in range(40)]
    cal = dx.Calibration(recs, "pat")
    assert cal.band_pct(0.05, 100.0)[3] == "all stocks"                          # 40 < 100 in every group


# ── EPS comparability, evidence kinds and window ─────────────────────────────

def test_last_years_eps_is_hidden_when_the_share_count_changed():
    pes_eps = list(EPS)
    pes_eps[4] = 5.5                                                             # Dec-25 EPS 5.5 on profit 11 → 2 shares; Sep-26 EPS 1.456 on 14.56 → 10 shares (a 5:1 bonus in between)
    models = dx.build_models(rows_for(eps=pes_eps) + universe_rows(150))
    a = dx.answer(models, "ABC", D(2027, 1, 12), "period ended December 31, 2026", D(2027, 1, 5), [])
    eps = next(m for m in a["metrics"] if m["key"] == "eps")
    assert eps["same_quarter_last_year"] is None and "share count changed" in eps["last_year_note"]
    assert eps["expected"] is not None                                           # the derived expectation stays on the latest share base
    ok = dx.answer(dx.build_models(rows_for() + universe_rows(150)), "ABC", D(2027, 1, 12), "period ended December 31, 2026", D(2027, 1, 5), [])
    assert next(m for m in ok["metrics"] if m["key"] == "eps")["same_quarter_last_year"] == 1.1


def test_evidence_kind_comes_from_the_subject_else_the_classifier_label():
    assert dx.evidence_kind("Analysts/Institutional Investor Meet/Con. Call Updates", "regulatory") == "analyst / investor meet"
    assert dx.evidence_kind("Press Release", "capex") == "press release"
    assert dx.evidence_kind("Award of Order / Receipt of Order", "orders") == "order"
    assert dx.evidence_kind("General Updates", "mna") == "mna"
    assert dx.evidence_kind("General Updates", None) == "other"


def test_route_evidence_for_a_declared_meeting_stops_before_the_meeting_day(make_client, monkeypatch):
    seen = {}

    class _C(_Conn):
        async def fetch(self, q, *a):
            if "nidp.corporate_announcements" in q:
                seen["args"] = a
                return []
            return await super().fetch(q, *a)

    pool_conn = _C({"event": dict(EVENT, event_date=D(2026, 10, 8), purpose="period ended September 30, 2026"), "quarters": rows_for() + universe_rows(150)})
    c = make_client({"event": None, "quarters": []})
    monkeypatch.setattr(dx, "_today", lambda: D(2026, 10, 21))

    class _P(_Pool):
        def __init__(self):
            self.conn = pool_conn
    async def _gp():
        return _P()
    monkeypatch.setattr(dx, "get_pool", _gp)
    r = c.get("/v1/desk/events-calendar/expectation?symbol=ABC&date=2026-10-08", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "declared"
    _sym, lo, hi = seen["args"]
    assert hi == datetime(2026, 10, 7, 18, 30, tzinfo=UTC) and (hi - lo).days == dx.EVIDENCE_DAYS
