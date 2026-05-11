"""Query helpers that run small read-only Python scripts on the NIDP VM
via the SSH bridge. Used for surfaces (like `nidp.job_log`) that aren't
exposed by the VM's DaaS HTTP API.

Pattern:
    1. Build a small inline Python script that:
       - reads env from /opt/nidp/nidp.env (sourced by the wrapper)
       - opens an asyncpg connection
       - runs the query, returns rows as JSON to stdout
    2. Ship the script to the VM via base64-stdin, execute synchronously
       (NOT detached), capture stdout, parse as JSON.
    3. Surface as a regular FastAPI endpoint.

This avoids redeploying the DaaS API on the VM every time we need a new
read-only surface. Limits: only run small, fast queries (< 5s); for
anything heavy, add a proper /v1/* endpoint on the VM side.
"""
from __future__ import annotations

import base64
import json
import logging
import shlex
from typing import Any, Dict, List

from services.nidp_vm_ssh import ssh_exec

logger = logging.getLogger(__name__)


async def run_pg_query(script_body: str, *, timeout: float = 25.0) -> Any:
    """Execute `script_body` on the VM as user `nidp` with /opt/nidp/nidp.env
    sourced. The script must `print(json.dumps(...))` on success. Returns the
    parsed JSON, or raises ValueError on any non-zero exit / parse error.

    `script_body` is base64-encoded to bypass nested-shell quoting issues.
    """
    full_script = (
        "import asyncio, asyncpg, json, os, sys\n"
        "DSN = (os.environ.get('NIDP_PG_DSN') or "
        "os.environ.get('NIDP_POSTGRES_URL') or "
        "os.environ.get('POSTGRES_URL') or "
        "'postgresql://postgres:postgres@localhost:5433/nidp')\n"
        + script_body
    )

    b64 = base64.b64encode(full_script.encode("utf-8")).decode("ascii")
    wrapper = (
        f"echo {b64} | base64 -d | "
        f"sudo -u nidp -H bash -c "
        f"'set -a; source /opt/nidp/nidp.env; set +a; /opt/nidp/venv/bin/python'"
    )

    rc, out, err = await ssh_exec(wrapper, timeout=timeout)
    if rc != 0:
        raise ValueError(
            f"VM PG query failed (rc={rc}): {(err or out)[:600]}"
        )
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"VM PG query returned non-JSON. stdout[:400]={out[:400]!r} stderr[:400]={err[:400]!r}"
        ) from e


# ─────────────────────────────────────────────────────────────────
# `nidp.job_log` reader — used by the rolling backfill tracker.
# ─────────────────────────────────────────────────────────────────
async def fetch_job_log(
    *, limit: int = 50, ingester: str | None = None, status: str | None = None,
    since_hours: int = 24,
) -> List[Dict[str, Any]]:
    """Return the most recent rows of `nidp.job_log`."""
    # Validate scalars before composing the SQL — even though psycopg
    # parameterises, keeping the SQL stable simplifies the inline script.
    limit = max(1, min(int(limit), 500))
    since_hours = max(1, min(int(since_hours), 24 * 30))

    where = ["started_at >= NOW() - INTERVAL '{h} hours'".format(h=since_hours)]
    params: List[Any] = []
    if ingester:
        params.append(ingester)
        where.append(f"ingester = ${len(params)}")
    if status:
        params.append(status)
        where.append(f"status = ${len(params)}")

    where_sql = " AND ".join(where)
    params_repr = ", ".join(repr(p) for p in params)

    body = (
        "async def main():\n"
        "    c = await asyncpg.connect(DSN)\n"
        "    try:\n"
        f"        rows = await c.fetch('''SELECT run_id::text, ingester, target_date::text, status,\n"
        f"            started_at, finished_at, duration_ms, rows_fetched, rows_inserted,\n"
        f"            rows_skipped, error_message, error_class, source_url\n"
        f"            FROM nidp.job_log WHERE {where_sql}\n"
        f"            ORDER BY started_at DESC LIMIT {limit}''', {params_repr})\n"
        "    finally:\n"
        "        await c.close()\n"
        "    out = []\n"
        "    for r in rows:\n"
        "        d = dict(r)\n"
        "        for k in ('started_at', 'finished_at'):\n"
        "            if d.get(k) is not None:\n"
        "                d[k] = d[k].isoformat()\n"
        "        out.append(d)\n"
        "    print(json.dumps(out))\n"
        "asyncio.run(main())\n"
    )

    return await run_pg_query(body)
