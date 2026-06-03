#!/usr/bin/env python3
"""Service Health Collector — HTTP-probes all known REST endpoints for both VMs
and writes results to monitoring.service_health.

Runs every minute via cron on nidp-stack-vm.  Because it probes external URLs
(niveshcopilot.com, staging.niveshcopilot.com) it provides health visibility for
both VMs from a single location.

Crontab entry:
  * * * * *  nidp  /opt/nidp/venv/bin/python /opt/nidp/repo/backend/nidp/deploy/vm/service_health_collector.py >> /opt/nidp/logs/service_health.log 2>&1
"""
from __future__ import annotations

import asyncio
import http.client
import logging
import os
import time
import urllib.parse
from datetime import datetime, timezone
from typing import NamedTuple

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("service_health")

PG_DSN = (
    os.environ.get("NIDP_POSTGRES_URL")
    or os.environ.get("POSTGRES_URL")
    or "postgresql://postgres:postgres@localhost:5433/nidp"
)

# Timeout for each HTTP probe (seconds)
HTTP_TIMEOUT = 5


class ServiceDef(NamedTuple):
    vm: str
    service_name: str
    url: str
    environment: str = "prod"


# All known endpoints — probed from nidp-stack-vm every minute.
# localhost entries hit services on this VM directly; HTTPS entries cross-probe
# the Nivesh App VM and its staging stack.
SERVICES: list[ServiceDef] = [
    # ── nidp-stack-vm: shared infra ────────────────────────────────────────
    ServiceDef("nidp-stack-vm", "nginx",      "https://data.niveshcopilot.com/health"),
    ServiceDef("nidp-stack-vm", "grafana",    "http://127.0.0.1:3000/api/health"),
    ServiceDef("nidp-stack-vm", "prometheus", "http://127.0.0.1:9090/-/healthy"),
    ServiceDef("nidp-stack-vm", "minio",      "http://127.0.0.1:9001/minio/health/live"),

    # ── nidp-stack-vm: prod services ──────────────────────────────────────
    ServiceDef("nidp-stack-vm", "daas-api",   "http://127.0.0.1:8083/v1/health"),
    ServiceDef("nidp-stack-vm", "query-api",  "http://127.0.0.1:8090/v1/health"),
    ServiceDef("nidp-stack-vm", "loki",       "http://127.0.0.1:3100/ready"),
    ServiceDef("nidp-stack-vm", "promtail",   "http://127.0.0.1:9080/ready"),

    # ── nidp-stack-vm: staging services ───────────────────────────────────
    ServiceDef("nidp-stack-vm", "daas-api-staging",   "http://127.0.0.1:8084/health",      environment="staging"),
    ServiceDef("nidp-stack-vm", "loki-staging",       "http://127.0.0.1:3101/ready",       environment="staging"),
    ServiceDef("nidp-stack-vm", "promtail-staging",   "http://127.0.0.1:9081/ready",       environment="staging"),

    # ── nidp-stack-vm: postgres — use pg_isready subprocess (not raw TCP) ─
    ServiceDef("nidp-stack-vm", "timescaledb-prod",   "pg://localhost:5433/nidp",           environment="prod"),
    ServiceDef("nidp-stack-vm", "timescaledb-stg",    "pg://localhost:5434/nidp_staging",   environment="staging"),

    # ── nivesh-app-vm: prod stack (probed externally) ─────────────────────
    ServiceDef("nivesh-app-vm", "backend-prod",      "https://niveshcopilot.com/api/"),
    ServiceDef("nivesh-app-vm", "frontend-prod",     "https://niveshcopilot.com/"),
    ServiceDef("nivesh-app-vm", "frontend-v5-prod",  "https://niveshcopilot.com/v5/"),

    # ── nivesh-app-vm: staging stack ──────────────────────────────────────
    ServiceDef("nivesh-app-vm", "backend-staging",      "https://staging.niveshcopilot.com/api/",  environment="staging"),
    ServiceDef("nivesh-app-vm", "frontend-staging",     "https://staging.niveshcopilot.com/",       environment="staging"),
    ServiceDef("nivesh-app-vm", "frontend-v5-staging",  "https://staging.niveshcopilot.com/v5/",    environment="staging"),
]


def _probe(svc: ServiceDef) -> dict:
    """Probe a single service and return a result dict."""
    url = svc.url
    parsed = urllib.parse.urlparse(url)
    is_up = False
    http_status = None
    response_ms = None
    error_msg = None

    # pg:// scheme — use pg_isready (correct postgres health check)
    if parsed.scheme == "pg":
        import subprocess
        host = parsed.hostname or "127.0.0.1"
        port = str(parsed.port or 5432)
        t0 = time.monotonic()
        try:
            result = subprocess.run(
                ["pg_isready", "-h", host, "-p", port, "-q"],
                capture_output=True, timeout=HTTP_TIMEOUT,
            )
            is_up = result.returncode == 0
            response_ms = int((time.monotonic() - t0) * 1000)
            if not is_up:
                error_msg = result.stdout.decode()[:200] or result.stderr.decode()[:200]
        except FileNotFoundError:
            # pg_isready not installed — fall back to TCP connect
            import socket
            try:
                t0 = time.monotonic()
                with socket.create_connection((host, int(port)), timeout=HTTP_TIMEOUT):
                    is_up = True
                    response_ms = int((time.monotonic() - t0) * 1000)
            except Exception as e:
                error_msg = str(e)[:200]
        except Exception as e:
            error_msg = str(e)[:200]
        return {"vm": svc.vm, "service_name": svc.service_name, "url": url,
                "environment": svc.environment, "is_up": is_up,
                "http_status": None, "response_ms": response_ms, "error_msg": error_msg}

    try:
        t0 = time.monotonic()
        if parsed.scheme == "https":
            conn = http.client.HTTPSConnection(
                parsed.netloc, timeout=HTTP_TIMEOUT,
                context=__import__("ssl")._create_unverified_context(),
            )
        else:
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 80
            conn = http.client.HTTPConnection(f"{host}:{port}", timeout=HTTP_TIMEOUT)
        path = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
        conn.request("GET", path, headers={"User-Agent": "nidp-health-collector/1.0"})
        resp = conn.getresponse()
        elapsed = int((time.monotonic() - t0) * 1000)
        http_status = resp.status
        response_ms = elapsed
        is_up = 200 <= resp.status < 500  # 4xx are up (app-level errors); 5xx = down
    except Exception as e:
        error_msg = str(e)[:200]

    return {
        "vm":           svc.vm,
        "service_name": svc.service_name,
        "url":          url,
        "environment":  svc.environment,
        "is_up":        is_up,
        "http_status":  http_status,
        "response_ms":  response_ms,
        "error_msg":    error_msg,
    }


async def _insert(results: list[dict]) -> int:
    conn = await asyncpg.connect(PG_DSN)
    try:
        now = datetime.now(timezone.utc)
        rows = [
            (r["vm"], r["service_name"], r["url"], r["environment"],
             r["is_up"], r["http_status"], r["response_ms"], r["error_msg"], now)
            for r in results
        ]
        await conn.executemany(
            """
            INSERT INTO monitoring.service_health
                (vm, service_name, url, environment, is_up, http_status,
                 response_ms, error_msg, collected_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            """,
            rows,
        )
        await conn.execute(
            "DELETE FROM monitoring.service_health WHERE collected_at < now() - interval '7 days'"
        )
        return len(rows)
    finally:
        await conn.close()


def main():
    results = [_probe(svc) for svc in SERVICES]
    up   = sum(1 for r in results if r["is_up"])
    down = sum(1 for r in results if not r["is_up"])
    logger.info("Probed %d services: %d up, %d down", len(results), up, down)
    for r in results:
        if not r["is_up"]:
            logger.warning("DOWN: %s (%s) — %s", r["service_name"], r["vm"],
                           r.get("error_msg") or f"HTTP {r['http_status']}")

    count = asyncio.run(_insert(results))
    logger.info("Persisted %d rows", count)


if __name__ == "__main__":
    main()
