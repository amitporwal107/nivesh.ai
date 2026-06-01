"""Grafana alert webhook receiver and active-alerts query endpoint.

POST /api/internal/grafana-alerts   — receives Grafana Unified Alerting webhook,
                                      stores each alert in monitoring.alert_events
                                      (TimescaleDB) and in Redis for fast lookup.

GET  /api/admin/grafana-alerts       — returns currently FIRING alerts (Redis cache,
                                      fallback TimescaleDB).  Used by the frontend
                                      alert banner.

GRAFANA_WEBHOOK_SECRET env var must match the Authorization: Bearer value configured
in the Grafana contact point.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["grafana-alerts"])

_WEBHOOK_SECRET = os.environ.get("GRAFANA_WEBHOOK_SECRET", "")


def _check_secret(authorization: str | None = Header(default=None)) -> None:
    if not _WEBHOOK_SECRET:
        return  # not configured → allow (dev / initial setup)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing auth")
    if authorization.removeprefix("Bearer ").strip() != _WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token")


# ── Webhook receiver ──────────────────────────────────────────────────────────

@router.post("/internal/grafana-alerts", status_code=200)
async def receive_grafana_alert(
    request: Request,
    _: None = Depends(_check_secret),
) -> dict:
    """Receive a Grafana Unified Alerting webhook payload and persist it."""
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    alerts: list[dict] = payload.get("alerts", [])
    if not alerts:
        return {"stored": 0}

    now = datetime.now(timezone.utc)
    stored = 0

    # Lazy imports — use same module-level clients as the rest of the backend
    try:
        from services import redis_client as _rc
        redis = await _rc.get_client()
    except Exception:
        redis = None

    try:
        from nidp.shared.storage.pg import get_pool as _get_nidp_pool
        nidp_pool = await _get_nidp_pool()
    except Exception:
        nidp_pool = None

    for alert in alerts:
        labels      = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alert_name  = labels.get("alertname") or payload.get("title", "unknown")
        state       = alert.get("status", "firing")
        severity    = labels.get("severity")
        environment = labels.get("environment")
        gen_url     = alert.get("generatorURL", "")

        # ── Redis: live FIRING set (TTL 4h) ──────────────────────────────────
        if redis:
            try:
                redis_key = f"grafana:alert:{alert_name}"
                if state == "firing":
                    await redis.setex(
                        redis_key, 4 * 3600,
                        json.dumps({
                            "alert_name":  alert_name,
                            "state":       "firing",
                            "severity":    severity,
                            "environment": environment,
                            "summary":     annotations.get("summary", ""),
                            "description": annotations.get("description", ""),
                            "fired_at":    now.isoformat(),
                        }),
                    )
                else:
                    await redis.delete(redis_key)
            except Exception as exc:
                logger.warning("Redis alert write failed: %s", exc)

        # ── TimescaleDB: durable event log ────────────────────────────────────
        if nidp_pool:
            try:
                async with nidp_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO monitoring.alert_events
                            (received_at, alert_name, state, severity,
                             labels, annotations, generator_url, environment)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                        """,
                        now, alert_name, state, severity,
                        json.dumps(labels), json.dumps(annotations),
                        gen_url, environment,
                    )
                stored += 1
            except Exception as exc:
                logger.error("TimescaleDB alert insert failed: %s", exc)

    logger.info("Received %d Grafana alert(s), stored %d", len(alerts), stored)
    return {"stored": stored}


# ── Active alerts query ───────────────────────────────────────────────────────

@router.get("/admin/grafana-alerts")
async def get_active_alerts() -> dict:
    """Return currently firing Grafana alerts for the frontend alert banner."""
    firing: list[dict] = []

    try:
        from services import redis_client as _rc
        redis = await _rc.get_client()
        if redis:
            keys = await redis.keys("grafana:alert:*")
            for key in keys:
                raw = await redis.get(key)
                if raw:
                    firing.append(json.loads(raw))
    except Exception as exc:
        logger.warning("Redis alert read failed: %s", exc)

    if not firing:
        try:
            from nidp.shared.storage.pg import get_pool as _get_nidp_pool
            nidp_pool = await _get_nidp_pool()
            async with nidp_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT ON (alert_name)
                        alert_name, state, severity, environment,
                        annotations->>'summary'     AS summary,
                        annotations->>'description' AS description,
                        received_at
                    FROM monitoring.alert_events
                    WHERE received_at >= now()-interval'4 hours'
                    ORDER BY alert_name, received_at DESC
                    """
                )
                firing = [dict(r) for r in rows if r["state"] == "firing"]
        except Exception as exc:
            logger.error("TimescaleDB alert query failed: %s", exc)

    critical = [a for a in firing if a.get("severity") == "critical"]
    warnings  = [a for a in firing if a.get("severity") == "warning"]

    return {
        "firing_count":   len(firing),
        "critical_count": len(critical),
        "warning_count":  len(warnings),
        "alerts":         firing,
    }
