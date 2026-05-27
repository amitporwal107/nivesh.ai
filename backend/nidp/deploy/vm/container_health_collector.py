#!/usr/bin/env python3
"""Container Health Collector — writes Docker container status to monitoring.container_health.

Runs every minute via cron on nidp-stack-vm. Classifies containers as
prod / staging / infra based on name patterns.

Crontab:
  * * * * *  nidp  /opt/nidp/venv/bin/python /opt/nidp/repo/backend/nidp/deploy/vm/container_health_collector.py 2>>/opt/nidp/logs/container_health.log
"""
from __future__ import annotations

import json
import logging
import os
import re
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

# Classify containers by name pattern
_STAGING_PAT = re.compile(r"staging", re.IGNORECASE)
_INFRA_PAT = re.compile(r"grafana|prometheus|loki|promtail|minio|redis|redpanda|schema.registry", re.IGNORECASE)


def _classify(name: str) -> str:
    if _STAGING_PAT.search(name):
        return "staging"
    if _INFRA_PAT.search(name):
        return "infra"
    return "prod"


def _parse_uptime(status_str: str) -> int | None:
    """Rough parse of Docker status string to seconds."""
    if not status_str:
        return None
    s = status_str.lower()
    if "exited" in s or "dead" in s:
        return 0
    # "Up 3 hours", "Up 2 days", "Up 45 seconds", "Up About an hour"
    m = re.search(r"up\s+(?:about\s+)?(\d+)\s*(second|minute|hour|day|week|month)", s)
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    mult = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800, "month": 2592000}
    return val * mult.get(unit, 1)


def _get_health(inspect_health: str) -> str:
    """Extract health from docker inspect Health.Status or status string."""
    if not inspect_health:
        return "none"
    h = inspect_health.lower().strip()
    if h in ("healthy", "unhealthy", "starting"):
        return h
    return "none"


def collect() -> list[dict]:
    """Run docker ps -a and parse output."""
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
        containers.append({
            "container_name": name,
            "container_image": image,
            "status": state,          # running, exited, paused, etc.
            "health": "none",         # will enrich below
            "uptime_seconds": _parse_uptime(status_str),
            "ports": ports or None,
            "environment": _classify(name),
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
                parts = line.split("\t")
                if len(parts) >= 2:
                    cname = parts[0].lstrip("/")
                    health_map[cname] = _get_health(parts[1])
            for c in containers:
                c["health"] = health_map.get(c["container_name"], "none")
        except Exception:
            pass  # health enrichment is best-effort

    return containers


def persist(containers: list[dict]) -> int:
    """Insert rows into monitoring.container_health."""
    import asyncio
    import asyncpg

    async def _insert():
        conn = await asyncpg.connect(PG_DSN)
        try:
            now = datetime.now(timezone.utc)
            rows = [
                (c["container_name"], c["container_image"], c["status"],
                 c["health"], c["uptime_seconds"], c["ports"],
                 c["environment"], now)
                for c in containers
            ]
            await conn.executemany(
                """
                INSERT INTO monitoring.container_health
                    (container_name, container_image, status, health,
                     uptime_seconds, ports, environment, collected_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                rows,
            )
            # Cleanup: keep only 7 days
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
    logger.info("Collected %d containers", count)


if __name__ == "__main__":
    main()
