"""Unit test for RequestMetricsMiddleware (T4.2)."""
from __future__ import annotations

import logging


def test_middleware_logs_request_event(client, caplog):
    caplog.set_level(logging.INFO, logger="portfolio_ingestion.middleware")
    r = client.get("/api/healthz")
    assert r.status_code == 200
    events = [rec for rec in caplog.records if getattr(rec, "eventType", None) == "HTTP_REQUEST"]
    assert events, "expected at least one HTTP_REQUEST log record"
    rec = events[-1]
    assert rec.method == "GET"
    assert rec.path == "/api/healthz"
    assert rec.status_code == 200
    assert isinstance(rec.latency_ms, int)
    assert rec.latency_ms >= 0
