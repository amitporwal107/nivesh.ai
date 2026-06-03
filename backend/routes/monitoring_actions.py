"""Monitoring operator actions webhook.

POST /api/admin/monitoring/action
    Execute start/stop/restart/run-now/pause/resume on a service or cron job.
    All actions are SSH'd to the target VM via docker compose (containers) or
    routed to the NIDP Query API (cron jobs).
    Every action writes an audit row to monitoring.operator_actions.

GET  /api/admin/monitoring/actions
    Return the last 100 operator action audit entries.

Auth: same MONITORING_ACTION_SECRET Bearer token as the Grafana webhook.
RBAC: placeholder — all authenticated requests are accepted in v1.
      Full role-based restriction is Phase 3.2 (deferred per plan).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
from datetime import datetime, timezone
from typing import Any, Literal

import asyncpg
from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/monitoring", tags=["monitoring-actions"])

_ACTION_SECRET = os.environ.get("MONITORING_ACTION_SECRET") or os.environ.get("GRAFANA_WEBHOOK_SECRET", "")

# Valid action verbs
_VALID_ACTIONS = {"restart", "start", "stop", "run-now", "pause", "resume"}

# Container names that can be controlled on each VM.
# "run-now" on a cron job is routed to the NIDP Query API instead of SSH.
_NIDP_CONTAINERS = {
    "nidp-postgres", "nidp-loki", "nidp-promtail", "nidp-grafana",
    "nidp-minio", "nidp-prometheus", "nidp-redis", "nidp-redpanda",
    "nidp-node-exporter", "nidp-alertmanager",
}
_NIVESH_CONTAINERS = {
    "nivesh-backend", "nivesh-frontend", "nivesh-mongo",
    "nivesh-postgres", "nivesh-redis", "nivesh-node-exporter",
}
# Systemd services on nidp-stack-vm (not docker compose — use systemctl)
_NIDP_SYSTEMD = {"nidp-daas-api", "nidp-query-api"}

# VM SSH details (SSH key injected via environment in production)
_NIDP_VM_HOST = "10.160.0.3"   # same host; use localhost for docker commands
_NIVESH_VM_HOST = "10.160.0.5"
_SSH_KEY_PATH = os.environ.get("MONITORING_SSH_KEY_PATH", "/opt/nidp/keys/monitoring_ssh_key")


class ActionRequest(BaseModel):
    action: str
    target: str
    environment: str = "prod"

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in _VALID_ACTIONS:
            raise ValueError(f"action must be one of {_VALID_ACTIONS}")
        return v

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", v):
            raise ValueError("target contains invalid characters")
        return v

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        if v not in {"prod", "staging"}:
            raise ValueError("environment must be prod or staging")
        return v


def _verify_token(authorization: str | None) -> None:
    if not _ACTION_SECRET:
        return  # secret not configured — open in dev
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")
    if authorization.removeprefix("Bearer ") != _ACTION_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token")


async def _write_audit(
    db_url: str,
    actor: str,
    action: str,
    target: str,
    environment: str,
    vm: str | None,
    outcome: str,
    request_metadata: dict[str, Any],
) -> None:
    try:
        conn = await asyncpg.connect(db_url)
        await conn.execute(
            """
            INSERT INTO monitoring.operator_actions
                (actor, action, target, environment, vm, outcome, request_metadata, timestamp)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            """,
            actor, action, target, environment, vm, outcome,
            json.dumps(request_metadata), datetime.now(timezone.utc),
        )
        await conn.close()
    except Exception as exc:
        logger.error("Failed to write operator audit log: %s", exc)


async def _ssh_exec(host: str, cmd: str) -> tuple[int, str]:
    """Run a command on a remote host via SSH. Returns (returncode, output)."""
    try:
        import asyncssh  # type: ignore[import-not-found]
    except ImportError:
        return 1, "asyncssh not installed — SSH execution unavailable"

    key_path = _SSH_KEY_PATH
    try:
        async with asyncssh.connect(
            host,
            username="devops",
            client_keys=[key_path] if os.path.exists(key_path) else [],
            known_hosts=None,
            connect_timeout=10,
        ) as conn:
            result = await conn.run(cmd, check=False, timeout=30)
            return result.returncode, (result.stdout or "") + (result.stderr or "")
    except Exception as exc:
        return 1, f"SSH error: {exc}"


async def _nidp_run_now(target: str) -> tuple[int, str]:
    """Trigger a cron job via the NIDP Query API run-now endpoint."""
    import httpx
    nidp_query_url = os.environ.get("NIDP_QUERY_API_URL", "http://localhost:8001")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{nidp_query_url}/feeds/{target}/execute")
        return resp.status_code, resp.text
    except Exception as exc:
        return 1, f"HTTP error: {exc}"


@router.post("/action")
async def execute_action(
    body: ActionRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_token(authorization)

    actor = authorization.removeprefix("Bearer ") if authorization else "anonymous"
    target = body.target
    action = body.action
    environment = body.environment

    db_url = os.environ.get(
        "NIDP_DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5433/nidp",
    )
    request_metadata = {"action": action, "target": target, "environment": environment}

    # Determine which VM and execution path
    vm: str | None = None
    outcome = "pending"

    try:
        if target in _NIDP_CONTAINERS or target in _NIDP_SYSTEMD:
            vm = "nidp-stack-vm"
            if target in _NIDP_SYSTEMD:
                # systemctl on the NIDP VM — SSH to localhost (same machine via SSH)
                verb = {"restart": "restart", "start": "start", "stop": "stop"}.get(action, action)
                cmd = f"sudo systemctl {verb} {shlex.quote(target)}"
                rc, out = await _ssh_exec(_NIDP_VM_HOST, cmd)
            else:
                # docker compose on NIDP VM
                compose_file = "/opt/nidp/repo/backend/nidp/deploy/vm/docker-compose.infra.yml"
                verb = {"restart": "restart", "start": "start", "stop": "stop",
                        "pause": "pause", "resume": "unpause"}.get(action, action)
                cmd = f"docker compose -f {shlex.quote(compose_file)} {verb} {shlex.quote(target)}"
                rc, out = await _ssh_exec(_NIDP_VM_HOST, cmd)

        elif target in _NIVESH_CONTAINERS:
            vm = "nivesh-app-vm"
            compose_file = "/opt/nivesh/deploy/docker-compose.prod.yml"
            verb = {"restart": "restart", "start": "start", "stop": "stop",
                    "pause": "pause", "resume": "unpause"}.get(action, action)
            cmd = f"docker compose -f {shlex.quote(compose_file)} {verb} {shlex.quote(target)}"
            rc, out = await _ssh_exec(_NIVESH_VM_HOST, cmd)

        elif action == "run-now":
            # Cron job — route to NIDP Query API
            vm = "nidp-stack-vm"
            rc, out = await _nidp_run_now(target)

        elif action in {"pause", "resume"}:
            # Cron registry pause/resume via DB flag
            vm = "nidp-stack-vm"
            enabled = action == "resume"
            conn = await asyncpg.connect(db_url)
            rows = await conn.execute(
                "UPDATE monitoring.cron_registry SET enabled=$1 WHERE job_name=$2",
                enabled, target,
            )
            await conn.close()
            rc = 0 if "UPDATE 1" in rows else 1
            out = rows

        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown target '{target}' — not in known container or cron job lists",
            )

        outcome = "success" if rc == 0 else f"error: {out[:200]}"

    except HTTPException:
        raise
    except Exception as exc:
        outcome = f"error: {exc}"
        out = str(exc)
        rc = 1

    await _write_audit(db_url, actor, action, target, environment, vm, outcome, request_metadata)

    if rc != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"outcome": outcome, "output": out[:500]},
        )

    return {"status": "ok", "outcome": outcome, "vm": vm, "target": target, "action": action}


@router.get("/actions")
async def list_actions(
    authorization: str | None = Header(default=None),
    limit: int = 100,
) -> list[dict[str, Any]]:
    _verify_token(authorization)

    db_url = os.environ.get(
        "NIDP_DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5433/nidp",
    )
    conn = await asyncpg.connect(db_url)
    rows = await conn.fetch(
        """
        SELECT id, actor, action, target, environment, vm, outcome, timestamp
        FROM monitoring.operator_actions
        ORDER BY timestamp DESC
        LIMIT $1
        """,
        limit,
    )
    await conn.close()
    return [dict(r) for r in rows]
