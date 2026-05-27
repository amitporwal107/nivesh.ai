"""Prometheus metrics for NIDP services.

Each service exposes a /metrics endpoint via prometheus_client's HTTP
server when started under its CLI. Standard metric set (one per
ingester):
    nidp_ingester_runs_total{service, status}            counter
    nidp_ingester_duration_seconds{service}              histogram
    nidp_ingester_rows_total{service, kind}              counter
        kind ∈ {fetched, inserted, skipped}
    nidp_source_fetch_total{source, status}              counter
    nidp_source_fetch_duration_seconds{source}           histogram
    nidp_kafka_publish_total{topic, status}              counter

Degrades to no-op stubs if prometheus_client is not installed
(local-dev convenience).
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from prometheus_client import (  # type: ignore[import-not-found]
        Counter, Histogram, start_http_server, REGISTRY,
    )
    _AVAILABLE = True
except ImportError:                                     # pragma: no cover
    _AVAILABLE = False

if _AVAILABLE:
    INGESTER_RUNS = Counter(
        "nidp_ingester_runs_total",
        "Ingester runs by status",
        ["service", "status"],
    )
    INGESTER_DURATION = Histogram(
        "nidp_ingester_duration_seconds",
        "Ingester wallclock duration",
        ["service"],
        buckets=(0.1, 0.5, 1, 5, 10, 30, 60, 120, 300, 600),
    )
    INGESTER_ROWS = Counter(
        "nidp_ingester_rows_total",
        "Rows by stage",
        ["service", "kind"],
    )
    SOURCE_FETCH = Counter(
        "nidp_source_fetch_total",
        "Source HTTP fetches by status",
        ["source", "status"],
    )
    SOURCE_FETCH_DURATION = Histogram(
        "nidp_source_fetch_duration_seconds",
        "Source HTTP fetch wallclock",
        ["source"],
        buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
    )
    KAFKA_PUBLISH = Counter(
        "nidp_kafka_publish_total",
        "Kafka publish attempts by status",
        ["topic", "status"],
    )
    GATE_VERDICTS = Counter(
        "nidp_dq_gate_verdicts_total",
        "DQ gate verdicts by gate, feed, and verdict",
        ["gate", "feed", "verdict"],
    )
else:
    class _NoOp:
        def labels(self, *_, **__): return self
        def inc(self, *_, **__): pass
        def observe(self, *_, **__): pass
    INGESTER_RUNS = INGESTER_DURATION = INGESTER_ROWS = _NoOp()
    SOURCE_FETCH = SOURCE_FETCH_DURATION = KAFKA_PUBLISH = GATE_VERDICTS = _NoOp()


@contextmanager
def time_ingester(service: str):
    import time as _t
    t0 = _t.monotonic()
    try:
        yield
    finally:
        if _AVAILABLE:
            INGESTER_DURATION.labels(service=service).observe(_t.monotonic() - t0)


@contextmanager
def time_fetch(source: str):
    import time as _t
    t0 = _t.monotonic()
    try:
        yield
    finally:
        if _AVAILABLE:
            SOURCE_FETCH_DURATION.labels(source=source).observe(_t.monotonic() - t0)


def start_metrics_server(port: Optional[int] = None) -> None:
    """Start the Prometheus HTTP exporter. No-op if disabled."""
    if not _AVAILABLE:
        logger.info("prometheus_client not installed — metrics server disabled")
        return
    p = port or int(os.environ.get("NIDP_METRICS_PORT", "9100"))
    start_http_server(p)
    logger.info("Prometheus metrics serving on :%d", p)
