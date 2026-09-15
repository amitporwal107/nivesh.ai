"""Executable contract for the stock screener — authored BEFORE implementation.

`.claude/VERIFICATION_PROTOCOL.md` §1 requires test cases to exist after API design
and before code. This is that artifact for plan step 6 (contract freeze).

Prose contract: `.claude/workspace/stock-screener/contracts/screener-api-contract.md`
TS mirror:      `.claude/workspace/stock-screener/contracts/screener.contract.ts`

`validate_screen_response()` below is the single source of truth for the response
invariants. It runs here against fixture payloads, and is intended to run unchanged
against real staging responses once `POST /v1/stocks/screen` exists (see the live
test at the bottom, which skips until then).

Every invariant traces to an acceptance criterion in `spec.md`. Numbers in the
fixtures are the real ones measured on nidp_staging 2026-08-17
(see `phase0-measurements.md`) so the fixtures cannot drift into fantasy.
"""
from __future__ import annotations

import os
from typing import Any

import pytest


# Metrics measured degenerate or absent on 2026-08-17. A4 forbids OFFERING these.
BARRED_METRICS = {
    "pb",                # 177 non-null, distinct_non_null == 1, all 0.0000
    "piotroski_score",   # 0% populated
    "current_ratio",     # 0% populated
    "cfo_pat_ratio",     # 0% populated
    "sma200",            # 0% populated
}

# A3: no symbol has >= 252 bars (max observed 206 across 4,737 symbols), so no
# metric may be SERVED under a 1Y/3Y label.
BARRED_METRIC_SUFFIXES = ("_1y", "_3y", "return_1y", "return_3y")

IMPLEMENTED_EVENT_CATEGORIES = {
    "other", "regulatory", "management", "earnings", "mna", "dividend",
    "qip", "rating", "orders", "litigation", "capex", "buyback",
}


class ContractViolation(AssertionError):
    """Raised with the acceptance-criterion id so failures name what broke."""


def _fail(criterion: str, msg: str) -> None:
    raise ContractViolation(f"[{criterion}] {msg}")


def validate_screen_response(payload: dict[str, Any], *, applied_filters: list[dict] | None = None,
                             event_filters_applied: bool = False) -> None:
    """Assert a /v1/stocks/screen payload satisfies the frozen contract.

    Intentionally strict: each check corresponds to a criterion that would
    otherwise fail silently and look like a working screener.
    """
    applied_filters = applied_filters or []
    data = payload.get("data")
    if not isinstance(data, dict):
        _fail("contract", "response has no `data` object")

    # A1 — the as-of the UI must display.
    if not data.get("as_of_date"):
        _fail("A1", "as_of_date is missing")

    # A2/B1 — the field the legacy endpoint never sends. Without it, a caller
    # cannot distinguish "12 matches" from "12 shown of an unknown number".
    total = data.get("total")
    if total is None:
        _fail("A2", "`total` is null — pagination.total is always null on the legacy "
                    "endpoint (stock_scores.py:194-202); A2 and B1 cannot pass")
    if not isinstance(total, int) or total < 0:
        _fail("A2", f"`total` must be a non-negative int, got {total!r}")

    # A4 — a barred metric must never be OFFERED.
    offered = set(data.get("offered_metrics") or [])
    leaked = offered & BARRED_METRICS
    if leaked:
        _fail("A4", f"degenerate/absent metrics offered: {sorted(leaked)}")
    mislabelled = {m for m in offered if m.endswith(BARRED_METRIC_SUFFIXES)}
    if mislabelled:
        _fail("A3", f"1Y/3Y metrics offered but no symbol has >=252 bars: {sorted(mislabelled)}")

    # A4 — every hidden metric explains itself with a measurement.
    for h in data.get("hidden_metrics") or []:
        if not h.get("reason"):
            _fail("A4", f"hidden metric {h.get('key')!r} has no reason")
        if not isinstance(h.get("measured"), dict) or not h["measured"]:
            _fail("A4", f"hidden metric {h.get('key')!r} has no measured evidence")

    rows = data.get("rows")
    if not isinstance(rows, list):
        _fail("contract", "`rows` must be a list")

    filtered_keys = [f["key"] for f in applied_filters]
    for row in rows:
        cells = row.get("cells") or {}

        # B4 — a null cell must say why. A bare em-dash is the UI half of this.
        for key, cell in cells.items():
            if cell.get("value") is None and not cell.get("null_reason"):
                _fail("B4", f"{row.get('symbol')}.{key} is null with no null_reason")

        # C4 — one match entry per applied filter, carrying this row's actual value.
        matched = row.get("matched") or []
        if len(matched) != len(applied_filters):
            _fail("C4", f"{row.get('symbol')}: {len(matched)} match chips for "
                        f"{len(applied_filters)} applied filters")

        # C5 — every filtered metric appears as a column.
        for key in filtered_keys:
            if key not in cells:
                _fail("C5", f"{row.get('symbol')}: filtered on {key!r} but it is not a column")

        # C2 — price-derived cells carry the bar count they were computed from.
        for key, cell in cells.items():
            if key.startswith("deliv_") and cell.get("value") is not None:
                if cell.get("bar_count") is None:
                    _fail("C2", f"{row.get('symbol')}.{key}: price-derived cell has no bar_count")

        # C3 — an event ref must be openable and its identity join auditable.
        for ev in row.get("events") or []:
            if ev.get("category") not in IMPLEMENTED_EVENT_CATEGORIES:
                _fail("S6", f"event category {ev.get('category')!r} is not implemented")
            if ev.get("resolved_via") not in {"ticker", "isin", "norm_name"}:
                _fail("C3", "event ref lacks a valid resolved_via — 38.9% of filings are "
                            "scrip-only, so the join provenance is required")
            if not ev.get("filed_at"):
                _fail("C3", "event ref has no filed_at — an event chip without a date is a rumour")

    # B6-A / B6-B — guidance exactly when there is nothing to show, and never otherwise.
    fi = data.get("filter_impact")
    if total == 0 and applied_filters:
        if not fi:
            _fail("B6-A", "zero results with no filter_impact — a bare 'no results' is a FAIL")
        if not any(f.get("most_restrictive") for f in fi):
            _fail("B6-A", "filter_impact never marks most_restrictive")
        for f in fi:
            if f.get("suggested_value") is not None and f.get("would_return") is None:
                _fail("B6-A", f"{f.get('key')}: suggested_value without a verified would_return")
    elif total > 0 and fi:
        _fail("B6-B", "filter_impact present on a non-empty result — the leave-one-out pass "
                      "must not run on the normal path (protects B5's p95)")

    # S6 — an event-filtered response must disclose how much of the window is searchable.
    if event_filters_applied:
        cov = data.get("event_coverage")
        if not cov or cov.get("classified_pct") is None:
            _fail("S6", "event filter applied without event_coverage — users must be told what "
                        "fraction of the window has actually been categorised")


# ── fixtures: the frozen shape, using measured 2026-08-17 values ────────────

def _good_response() -> dict[str, Any]:
    return {
        "data": {
            "as_of_date": "2026-08-17",
            "registry_version": "1.0.0",
            "universe": {"name": "all", "size": 2373},
            "total": 179,
            "rows": [{
                "symbol": "TITAN", "name": "Titan Company Limited",
                "cells": {
                    "roe_pct": {"value": 29.52, "formula": "PAT (TTM) / Avg Equity x 100",
                                "source_dataset": "nidp.nse_financials_quarterly",
                                "period": "Q1 FY27", "basis": "consolidated",
                                "as_of": "2026-08-17"},
                    "deliv_pct_avg_20": {"value": 61.4, "source_dataset": "nidp.prices_eod",
                                         "as_of": "2026-08-17", "bar_count": 20},
                },
                "matched": [{"key": "roe_pct", "op": "gte", "threshold": 18, "actual": 29.52}],
                "events": [], "flags": [],
            }],
            "offered_metrics": ["roe_pct", "pe_ttm", "debt_to_equity",
                                "market_cap_cr", "deliv_pct_avg_20"],
            "hidden_metrics": [
                {"key": "pb", "reason": "No usable values — all 177 readings are 0.00",
                 "measured": {"covered_pct": 7.5, "distinct_non_null": 1}},
            ],
            "coverage_notice": {"metric": "roe_pct", "covered": 170, "universe": 2373,
                                "text": "170 of 2,373 companies have this metric."},
            "filter_impact": None,
            "event_coverage": None,
        },
        "pagination": {"limit": 50, "offset": 0, "total": 179},
    }


ONE_FILTER = [{"key": "roe_pct", "op": "gte", "value": 18}]


def test_frozen_shape_validates():
    validate_screen_response(_good_response(), applied_filters=ONE_FILTER)


def test_null_total_is_rejected():
    """The exact defect on the legacy endpoint today."""
    r = _good_response()
    r["data"]["total"] = None
    with pytest.raises(ContractViolation, match=r"\[A2\]"):
        validate_screen_response(r, applied_filters=ONE_FILTER)


@pytest.mark.parametrize("metric", sorted(BARRED_METRICS))
def test_degenerate_metric_may_not_be_offered(metric):
    r = _good_response()
    r["data"]["offered_metrics"].append(metric)
    with pytest.raises(ContractViolation, match=r"\[A4\]"):
        validate_screen_response(r, applied_filters=ONE_FILTER)


def test_one_year_metric_may_not_be_offered():
    """0 of 4,737 symbols have >=252 bars (max observed: 206)."""
    r = _good_response()
    r["data"]["offered_metrics"].append("return_1y")
    with pytest.raises(ContractViolation, match=r"\[A3\]"):
        validate_screen_response(r, applied_filters=ONE_FILTER)


def test_null_cell_without_reason_is_rejected():
    r = _good_response()
    r["data"]["rows"][0]["cells"]["pe_ttm"] = {"value": None}
    with pytest.raises(ContractViolation, match=r"\[B4\]"):
        validate_screen_response(r, applied_filters=ONE_FILTER)


def test_match_chip_count_must_equal_filter_count():
    r = _good_response()
    with pytest.raises(ContractViolation, match=r"\[C4\]"):
        validate_screen_response(r, applied_filters=ONE_FILTER + [
            {"key": "debt_to_equity", "op": "lte", "value": 0.5}])


def test_filtered_metric_must_be_a_column():
    r = _good_response()
    r["data"]["rows"][0]["matched"].append(
        {"key": "market_cap_cr", "op": "gte", "threshold": 1000, "actual": 39528.5})
    with pytest.raises(ContractViolation, match=r"\[C5\]"):
        validate_screen_response(r, applied_filters=ONE_FILTER + [
            {"key": "market_cap_cr", "op": "gte", "value": 1000}])


def test_price_cell_without_bar_count_is_rejected():
    r = _good_response()
    del r["data"]["rows"][0]["cells"]["deliv_pct_avg_20"]["bar_count"]
    with pytest.raises(ContractViolation, match=r"\[C2\]"):
        validate_screen_response(r, applied_filters=ONE_FILTER)


def test_zero_results_require_filter_impact():
    r = _good_response()
    r["data"]["total"] = 0
    r["data"]["rows"] = []
    r["pagination"]["total"] = 0
    with pytest.raises(ContractViolation, match=r"\[B6-A\]"):
        validate_screen_response(r, applied_filters=ONE_FILTER)


def test_zero_results_with_filter_impact_passes():
    r = _good_response()
    r["data"]["total"] = 0
    r["data"]["rows"] = []
    r["pagination"]["total"] = 0
    r["data"]["filter_impact"] = [{
        "key": "roe_pct", "op": "gte", "value": 18,
        "leave_one_out_count": 41, "suggested_value": 12.4,
        "would_return": 14, "most_restrictive": True,
    }]
    validate_screen_response(r, applied_filters=ONE_FILTER)


def test_filter_impact_must_not_run_on_normal_path():
    """B6-B — the leave-one-out pass is expensive; it must not touch B5's p95."""
    r = _good_response()
    r["data"]["filter_impact"] = [{
        "key": "roe_pct", "op": "gte", "value": 18, "leave_one_out_count": 41,
        "suggested_value": 12.4, "would_return": 14, "most_restrictive": True,
    }]
    with pytest.raises(ContractViolation, match=r"\[B6-B\]"):
        validate_screen_response(r, applied_filters=ONE_FILTER)


def test_event_ref_requires_resolved_via():
    """38.9% of filings are scrip-only; the join provenance must be auditable."""
    r = _good_response()
    r["data"]["rows"][0]["events"] = [{
        "announcement_id": "abc", "source": "BSE", "filed_at": "2026-08-14T11:02:00+05:30",
        "category": "orders", "impact": "high", "sentiment": "positive",
        "attachment_url": None,
    }]
    r["data"]["event_coverage"] = {"window_days": 90, "rows_in_window": 62474,
                                   "classified_pct": 41.3, "text": "..."}
    with pytest.raises(ContractViolation, match=r"\[C3\]"):
        validate_screen_response(r, applied_filters=ONE_FILTER, event_filters_applied=True)


def test_event_filter_requires_coverage_disclosure():
    r = _good_response()
    with pytest.raises(ContractViolation, match=r"\[S6\]"):
        validate_screen_response(r, applied_filters=ONE_FILTER, event_filters_applied=True)


def test_unimplemented_event_category_is_rejected():
    """The PRD names 70+ event types; the classifier implements 12."""
    r = _good_response()
    r["data"]["rows"][0]["events"] = [{
        "announcement_id": "abc", "source": "NSE", "filed_at": "2026-08-14T11:02:00+05:30",
        "category": "auditor_resignation", "impact": "high", "sentiment": "negative",
        "attachment_url": None, "resolved_via": "ticker",
    }]
    r["data"]["event_coverage"] = {"window_days": 90, "rows_in_window": 62474,
                                   "classified_pct": 41.3, "text": "..."}
    with pytest.raises(ContractViolation, match=r"\[S6\]"):
        validate_screen_response(r, applied_filters=ONE_FILTER, event_filters_applied=True)


@pytest.mark.skipif(not os.environ.get("NIDP_DAAS_BASE_URL") or not os.environ.get("SCREENER_LIVE"),
                    reason="live conformance: set NIDP_DAAS_BASE_URL + SCREENER_LIVE=1 "
                           "(endpoint does not exist yet — plan step 13)")
def test_live_staging_conformance():  # pragma: no cover - runs only against a real endpoint
    """Same validator, real payload. Expected to fail until step 13 ships `total`."""
    import json
    import urllib.request

    base = os.environ["NIDP_DAAS_BASE_URL"].rstrip("/")
    key = os.environ.get("NIDP_DAAS_API_KEY") or os.environ.get("NIDP_DAAS_INTERNAL_TOKEN", "")
    body = json.dumps({"filters": [{"key": "roe_pct", "op": "gte", "value": 18}],
                       "page": {"limit": 10, "offset": 0}}).encode()
    req = urllib.request.Request(f"{base}/v1/stocks/screen", data=body,
                                 headers={"X-API-Key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read())
    validate_screen_response(payload, applied_filters=[{"key": "roe_pct", "op": "gte", "value": 18}])
