#!/usr/bin/env python3
"""Container Health Collector — writes Docker container status + resource metrics
to monitoring.container_health.

Runs every minute via cron on nidp-stack-vm (and optionally on nivesh-app-vm).
Classifies containers as prod / staging / infra based on name patterns.
Also collects CPU % and memory usage via `docker stats --no-stream`.

Crontab (nidp-stack-vm):
  * * * * *  nidp  /opt/nidp/repo/backend/nidp/deploy/vm/run_collector.sh >> /opt/nidp/logs/container_health.log 2>&1

Env vars:
  NIDP_VM_HOSTNAME   — override default VM name reported in the `vm` column
                       default: read from /etc/hostname, fallback 'nidp-stack-vm'
  NIDP_POSTGRES_URL  — DSN for monitoring schema
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("container_health")

PG_DSN = (
    os.environ.get("NIDP_POSTGRES_URL")
    or os.environ.get("POSTGRES_URL")
    or "postgresql://postgres:postgres@localhost:5433/nidp"
)

_VM_NAME = (
    os.environ.get("NIDP_VM_HOSTNAME")
    or (open("/etc/hostname").read().strip() if os.path.exists("/etc/hostname") else None)
    or "nidp-stack-vm"
)

# Classify containers by name pattern
_STAGING_PAT = re.compile(r"staging", re.IGNORECASE)
_INFRA_PAT   = re.compile(
    r"grafana|prometheus|loki|promtail|minio|redis|redpanda|schema.registry",
    re.IGNORECASE,
)

# Known HTTP health URLs per container name pattern (exact match first, then prefix)
_CONTAINER_URLS: dict[str, str] = {
    "nidp-grafana":                  "http://127.0.0.1:3000/api/health",
    "nidp-postgres":                 None,   # TCP, not HTTP
    "nidp-staging-postgres":         None,
    "nidp-loki":                     "http://127.0.0.1:3100/ready",
    "nidp-promtail":                 "http://127.0.0.1:9080/ready",
    "nidp-prometheus":               "http://127.0.0.1:9090/-/healthy",
    "nidp-minio":                    "http://127.0.0.1:9001/minio/health/live",
    "nivesh-backend":                "http://127.0.0.1:8001/api/",
    "nivesh-staging-app-backend":    "http://127.0.0.1:8002/api/",
    "nivesh-frontend":               "http://127.0.0.1:80/",
    "nidp-daas-api":                 "http://127.0.0.1:8083/health",
    "nidp-query-api":                "http://127.0.0.1:8090/health",
}


def _classify(name: str) -> str:
    if _STAGING_PAT.search(name):
        return "staging"
    if _INFRA_PAT.search(name):
        return "infra"
    return "prod"


def _parse_uptime(status_str: str) -> int | None:
    if not status_str:
        return None
    s = status_str.lower()
    if "exited" in s or "dead" in s:
        return 0
    m = re.search(r"up\s+(?:about\s+)?(\d+)\s*(second|minute|hour|day|week|month)", s)
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    mult = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800, "month": 2592000}
    return val * mult.get(unit, 1)


def _get_health(inspect_health: str) -> str:
    if not inspect_health:
        return "none"
    h = inspect_health.lower().strip()
    if h in ("healthy", "unhealthy", "starting"):
        return h
    return "none"


def _collect_stats() -> dict[str, tuple[float | None, float | None, float | None]]:
    """Run docker stats --no-stream and return {name: (cpu_pct, mem_mb, limit_mb)}."""
    stats: dict[str, tuple] = {}
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format",
             "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as e:
        logger.warning("docker stats failed: %s", e)
        return stats

    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name, cpu_str, mem_str = parts[0], parts[1], parts[2]
        cpu: float | None = None
        mem_used: float | None = None
        mem_limit: float | None = None

        # cpu_str like "0.15%"
        try:
            cpu = float(cpu_str.rstrip("%"))
        except (ValueError, AttributeError):
            pass

        # mem_str like "128MiB / 2GiB" or "1.23GiB / 3.84GiB"
        def _parse_bytes(s: str) -> float | None:
            s = s.strip()
            m = re.match(r"([\d.]+)\s*(B|kB|MiB|GiB|MB|GB|KB|KiB|TiB|TB)", s, re.IGNORECASE)
            if not m:
                return None
            val, unit = float(m.group(1)), m.group(2).upper()
            mult = {"B": 1, "KB": 1e3, "KIB": 1024, "MB": 1e6, "MIB": 1024**2,
                    "GB": 1e9, "GIB": 1024**3, "TB": 1e12, "TIB": 1024**4}
            return val * mult.get(unit, 1) / (1024**2)  # → MiB

        if "/" in mem_str:
            used_s, limit_s = mem_str.split("/", 1)
            mem_used  = _parse_bytes(used_s)
            mem_limit = _parse_bytes(limit_s)

        stats[name] = (cpu, mem_used, mem_limit)
    return stats


def _http_check(url: str | None) -> tuple[int | None, int | None]:
    """HEAD/GET the URL, return (status_code, response_ms). Returns (None, None) on no URL."""
    if not url:
        return None, None
    import http.client
    import time
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    try:
        t0 = time.monotonic()
        if parsed.scheme == "https":
            conn = http.client.HTTPSConnection(parsed.netloc, timeout=3)
        else:
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 80
            conn = http.client.HTTPConnection(f"{host}:{port}", timeout=3)
        path = parsed.path or "/"
        conn.request("GET", path)
        resp = conn.getresponse()
        elapsed = int((time.monotonic() - t0) * 1000)
        return resp.status, elapsed
    except Exception:
        return None, None


def collect() -> list[dict]:
    stats = _collect_stats()

    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format",
             "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.State}}"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        logger.error("docker ps failed: %s", e)
        return []

    containers = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        name, image, status_str, ports, state = parts

        cpu, mem_used, mem_limit = stats.get(name, (None, None, None))
        http_url = _CONTAINER_URLS.get(name)
        http_status, http_ms = _http_check(http_url) if state == "running" else (None, None)

        containers.append({
            "vm":               _VM_NAME,
            "container_name":   name,
            "container_image":  image,
            "status":           state,
            "health":           "none",
            "uptime_seconds":   _parse_uptime(status_str),
            "ports":            ports or None,
            "environment":      _classify(name),
            "cpu_percent":      cpu,
            "mem_usage_mb":     mem_used,
            "mem_limit_mb":     mem_limit,
            "http_url":         http_url,
            "http_status_code": http_status,
            "http_response_ms": http_ms,
        })

    # Enrich with health status from docker inspect
    if containers:
        names = [c["container_name"] for c in containers]
        try:
            insp = subprocess.run(
                ["docker", "inspect", "--format",
                 "{{.Name}}\t{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}"]
                + names,
                capture_output=True, text=True, timeout=10,
            )
            health_map = {}
            for line in insp.stdout.strip().splitlines():
                ps = line.split("\t")
                if len(ps) >= 2:
                    health_map[ps[0].lstrip("/")] = _get_health(ps[1])
            for c in containers:
                c["health"] = health_map.get(c["container_name"], "none")
        except Exception:
            pass

    return containers


def persist(containers: list[dict]) -> int:
    import asyncio
    import asyncpg

    async def _insert():
        conn = await asyncpg.connect(PG_DSN)
        try:
            now = datetime.now(timezone.utc)
            rows = [
                (c["vm"], c["container_name"], c["container_image"], c["status"],
                 c["health"], c["uptime_seconds"], c["ports"], c["environment"],
                 c["cpu_percent"], c["mem_usage_mb"], c["mem_limit_mb"],
                 c["http_url"], c["http_status_code"], c["http_response_ms"], now)
                for c in containers
            ]
            await conn.executemany(
                """
                INSERT INTO monitoring.container_health
                    (vm, container_name, container_image, status, health,
                     uptime_seconds, ports, environment,
                     cpu_percent, mem_usage_mb, mem_limit_mb,
                     http_url, http_status_code, http_response_ms,
                     collected_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                """,
                rows,
            )
            await conn.execute(
                "DELETE FROM monitoring.container_health WHERE collected_at < now() - interval '7 days'"
            )
            return len(rows)
        finally:
            await conn.close()

    return asyncio.run(_insert())


def main():
    containers = collect()
    if not containers:
        logger.warning("No containers found")
        sys.exit(0)
    count = persist(containers)
    logger.info("Collected %d containers from %s", count, _VM_NAME)


if __name__ == "__main__":
    main()
