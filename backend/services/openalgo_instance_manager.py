"""Per-account OpenAlgo subprocess manager.

OpenAlgo's upstream design pegs **one broker** to **one deployment** via
the `REDIRECT_URL` and `BROKER_API_KEY` env vars. To let each Nivesh user
connect any broker independently, we run an OpenAlgo subprocess **per
broker_account row** — same shared venv, but its own port, data dir,
.env, and broker app credentials.

The shared singleton on port 5000 (the supervisor-managed `openalgo`
service) stays as the admin/diagnostic instance and isn't used for end-
user broker traffic. Per-account instances live in
`/app/openalgo_instances/<account_id>/` and listen on ports allocated
from `OPENALGO_PORT_RANGE_START`..`OPENALGO_PORT_RANGE_END`
(default 5100..5999).

Lifecycle:
    POST /connect-hosted  → launch(account_id, ...) → returns base_url
    POST /sync            → ensure_running(account_id), then call API
    DELETE /accounts/{id} → stop(account_id), wipes data dir

State is mirrored into Mongo collection `openalgo_instances` so it
survives backend restarts: on a stale process discovery (PID gone), the
manager re-launches lazily on next access. No supervisord conf written
at runtime — we use plain `subprocess.Popen` and reap on demand.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Hosting config — defaults are fine for preview; override via env in prod.
INSTANCES_ROOT = os.environ.get("OPENALGO_INSTANCES_DIR", "/app/openalgo_instances")
OPENALGO_REPO = os.environ.get("OPENALGO_REPO_DIR", "/app/openalgo")
PYTHON_BIN = os.environ.get(
    "OPENALGO_PYTHON_BIN", os.path.join(OPENALGO_REPO, ".venv", "bin", "python")
)
PORT_RANGE_START = int(os.environ.get("OPENALGO_PORT_RANGE_START", "5100"))
PORT_RANGE_END = int(os.environ.get("OPENALGO_PORT_RANGE_END", "5999"))
WAIT_READY_SECONDS = 25
HEALTH_PROBE_TIMEOUT = 1.5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Port allocation ──────────────────────────────────────────────────────
def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


async def _allocate_port(db) -> int:
    used = set()
    cursor = db.openalgo_instances.find(
        {"port": {"$exists": True}}, {"_id": 0, "port": 1},
    )
    async for d in cursor:
        if d.get("port"):
            used.add(int(d["port"]))
    for port in range(PORT_RANGE_START, PORT_RANGE_END + 1):
        if port in used:
            continue
        if _port_in_use(port):
            continue
        return port
    raise RuntimeError(
        f"No free port in [{PORT_RANGE_START}, {PORT_RANGE_END}] — increase the range."
    )


# ── Per-instance .env synthesis ──────────────────────────────────────────
_BROKER_REQUIRES_SECRET = {
    "fyers", "upstox", "angel", "iifl", "iiflcapital", "compositedge",
    "fivepaisa", "fivepaisaxts", "kotak", "samco", "groww", "indmoney",
    "motilal", "mstock", "definedge",
}


def _broker_app_secret(broker: str, key: str) -> str:
    """Look up an admin-set per-broker secret like BROKER_ZERODHA_API_KEY.

    These are the broker's *app* credentials (Kite Connect app key, etc.)
    that the operator registers with each broker — NOT user credentials.
    Empty string when not configured.
    """
    name = f"BROKER_{broker.upper()}_{key.upper()}"
    try:
        from helpers import secrets as _s
        return (_s.get(name) or "").strip()
    except Exception:  # noqa: BLE001
        return (os.environ.get(name) or "").strip()


def _management_token() -> str:
    try:
        from helpers import secrets as _s
        return (_s.get("OPENALGO_MANAGEMENT_TOKEN") or "").strip()
    except Exception:  # noqa: BLE001
        return (os.environ.get("OPENALGO_MANAGEMENT_TOKEN") or "").strip()


def _write_instance_env(data_dir: Path, port: int, broker: str) -> None:
    """Write a customised .env for this instance.

    Starts from `.sample.env` and **replaces** keys inline (not appends)
    because python-dotenv keeps the *first* occurrence of each key in a
    file. Loaded with `override=True`, these win over the inherited env
    vars in the subprocess. Per-instance DBs and ports keep concurrent
    instances isolated.
    """
    sample_lines = Path(OPENALGO_REPO, ".sample.env").read_text().splitlines()
    api_key = _broker_app_secret(broker, "API_KEY")
    api_secret = _broker_app_secret(broker, "API_SECRET")
    mgmt = _management_token()

    # Map of key → replacement value. Quoting matches python-dotenv's
    # `'value'` form already used throughout .sample.env.
    overrides: Dict[str, str] = {
        "FLASK_PORT": str(port),
        "FLASK_HOST_IP": "127.0.0.1",
        "REDIRECT_URL": f"http://127.0.0.1:{port}/{broker}/callback",
        "HOST_SERVER": f"http://127.0.0.1:{port}",
        "BROKER_API_KEY": api_key or "PLACEHOLDER_NOT_CONFIGURED",
        "BROKER_API_SECRET": api_secret or "PLACEHOLDER_NOT_CONFIGURED",
        "OPENALGO_MANAGEMENT_TOKEN": mgmt,
        # Per-instance DB paths so SQLite locking doesn't collide.
        "DATABASE_URL": f"sqlite:///{data_dir}/db/openalgo.db",
        "LATENCY_DATABASE_URL": f"sqlite:///{data_dir}/db/latency.db",
        "LOGS_DATABASE_URL": f"sqlite:///{data_dir}/db/logs.db",
        "HEALTH_DATABASE_URL": f"sqlite:///{data_dir}/db/health.db",
        "SANDBOX_DATABASE_URL": f"sqlite:///{data_dir}/db/sandbox.db",
        "HISTORIFY_DATABASE_URL": f"{data_dir}/db/historify.duckdb",
        # WebSocket port = HTTP port + 3000 (e.g. 5101 → 8101) — keeps
        # multiple instances from colliding on the singleton's 8765.
        "WEBSOCKET_PORT": str(port + 3000),
        # Per OpenAlgo's startup check — only allow the broker we
        # actually configured. Stops React picker from showing other
        # brokers this instance can't auth.
        "VALID_BROKERS": broker,
    }

    # Walk the sample, rewriting any line that defines a key in our
    # override map. Match `KEY = 'value'` and `KEY='value'` and quoteless.
    key_pat = re.compile(r"^(\s*)([A-Z_][A-Z0-9_]*)(\s*=\s*).*$")
    written: Dict[str, bool] = {k: False for k in overrides}
    out: List[str] = []
    for line in sample_lines:
        m = key_pat.match(line)
        if m:
            key = m.group(2)
            if key in overrides:
                out.append(f"{m.group(1)}{key}={_dotenv_quote(overrides[key])}")
                written[key] = True
                continue
        out.append(line)

    # Any keys we couldn't replace inline (e.g., not present in sample)
    # get appended — first-occurrence rule still satisfied.
    extras = [
        f"{k}={_dotenv_quote(v)}" for k, v in overrides.items() if not written[k]
    ]
    if extras:
        out.append("")
        out.append("# === Nivesh per-account additions ===")
        out.extend(extras)

    (data_dir / ".env").write_text("\n".join(out) + "\n")


def _dotenv_quote(value: str) -> str:
    """Single-quote per python-dotenv conventions; escape stray quotes."""
    safe = value.replace("'", "\\'")
    return f"'{safe}'"


def _provision_data_dir(account_id: str, broker: str) -> Path:
    data_dir = Path(INSTANCES_ROOT) / account_id
    (data_dir / "db").mkdir(parents=True, exist_ok=True)
    (data_dir / "log").mkdir(parents=True, exist_ok=True)
    _write_instance_env(data_dir, port=_PLACEHOLDER_PORT, broker=broker)
    return data_dir


_PLACEHOLDER_PORT = 0  # Filled in by launch().


def _spawn(data_dir: Path, port: int, account_id: str) -> int:
    """Start `python app.py` from OPENALGO_REPO with the per-instance
    data_dir as cwd. Returns the PID. Process is detached from supervisor
    — backend restart leaves it running; we re-discover by PID liveness.

    `OPENALGO_URL_PREFIX` is set per-instance so OpenAlgo's WSGI
    DispatcherMiddleware mounts the Flask app at the same prefix the
    Nivesh proxy uses publicly. Without it, every redirect / url_for
    would emit unprefixed URLs that 404 through the proxy.
    """
    log_out = open(data_dir / "log" / "stdout.log", "ab")
    log_err = open(data_dir / "log" / "stderr.log", "ab")
    env = os.environ.copy()
    env["FLASK_PORT"] = str(port)
    env["PYTHONUNBUFFERED"] = "1"
    env["OPENALGO_URL_PREFIX"] = f"/api/openalgo/c/{account_id}"
    # Make OpenAlgo's env_check.py load OUR per-instance .env (not the
    # singleton's at OPENALGO_REPO/.env). The patch in env_check honours
    # this path override.
    env["OPENALGO_DOTENV_PATH"] = str(data_dir / ".env")
    # OpenAlgo loads .env from cwd, so cwd MUST be data_dir; but the code
    # lives in OPENALGO_REPO. We use cwd=data_dir and pass the script as
    # an absolute path. OpenAlgo's `load_and_check_env_variables()` reads
    # `.env` from cwd (verified in /app/openalgo/utils/env_check.py).
    proc = subprocess.Popen(
        [PYTHON_BIN, os.path.join(OPENALGO_REPO, "app.py")],
        cwd=str(data_dir),
        env=env,
        stdout=log_out,
        stderr=log_err,
        start_new_session=True,
    )
    return proc.pid


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


async def _wait_for_ready(port: int, timeout: float = WAIT_READY_SECONDS) -> bool:
    """Poll `/auth/check-setup` until OpenAlgo responds or timeout."""
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/auth/check-setup"
    async with httpx.AsyncClient(timeout=HEALTH_PROBE_TIMEOUT) as client:
        while time.monotonic() < deadline:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    return True
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
                pass
            time.sleep(0.5)
    return False


# ── Public API ───────────────────────────────────────────────────────────
async def launch(db, account_id: str, user_id: str, broker: str) -> Dict[str, Any]:
    """Idempotent: returns the running instance record for this account,
    starting one if needed.
    """
    existing = await db.openalgo_instances.find_one(
        {"account_id": account_id}, {"_id": 0},
    )
    if existing and existing.get("pid") and _pid_alive(int(existing["pid"])):
        existing["last_seen"] = _now_iso()
        await db.openalgo_instances.update_one(
            {"account_id": account_id}, {"$set": {"last_seen": existing["last_seen"]}},
        )
        return existing

    # Allocate fresh port, create dirs.
    port = await _allocate_port(db)
    data_dir = Path(INSTANCES_ROOT) / account_id
    (data_dir / "db").mkdir(parents=True, exist_ok=True)
    (data_dir / "log").mkdir(parents=True, exist_ok=True)
    _write_instance_env(data_dir, port=port, broker=broker)

    pid = _spawn(data_dir, port, account_id)
    record = {
        "account_id": account_id,
        "user_id": user_id,
        "broker": broker,
        "port": port,
        "data_dir": str(data_dir),
        "pid": pid,
        "status": "starting",
        "base_url": f"http://127.0.0.1:{port}",
        "started_at": _now_iso(),
        "last_seen": _now_iso(),
    }
    await db.openalgo_instances.update_one(
        {"account_id": account_id},
        {"$set": record}, upsert=True,
    )
    logger.info(
        "openalgo_instance_manager: launched account=%s broker=%s port=%d pid=%d",
        account_id, broker, port, pid,
    )

    ready = await _wait_for_ready(port)
    record["status"] = "running" if ready else "starting"
    await db.openalgo_instances.update_one(
        {"account_id": account_id}, {"$set": {"status": record["status"]}},
    )
    if not ready:
        logger.warning(
            "openalgo_instance_manager: %s did not become ready in %ds",
            account_id, WAIT_READY_SECONDS,
        )
    return record


async def stop(db, account_id: str) -> bool:
    rec = await db.openalgo_instances.find_one(
        {"account_id": account_id}, {"_id": 0},
    )
    if not rec:
        return False
    pid = int(rec.get("pid") or 0)
    if pid and _pid_alive(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        # Give it a couple seconds to clean up SQLite/sockets.
        for _ in range(20):
            if not _pid_alive(pid):
                break
            time.sleep(0.1)
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    # Wipe the per-instance data dir to release the port + reclaim disk.
    data_dir = rec.get("data_dir")
    if data_dir and os.path.isdir(data_dir):
        try:
            shutil.rmtree(data_dir)
        except Exception as e:  # noqa: BLE001
            logger.warning("openalgo_instance_manager: rmtree %s failed: %s", data_dir, e)

    await db.openalgo_instances.delete_one({"account_id": account_id})
    logger.info("openalgo_instance_manager: stopped account=%s pid=%s", account_id, pid)
    return True


async def get_base_url(db, account_id: str) -> Optional[str]:
    """Return the per-instance base URL, or None if the row is missing
    or the process died. Used by the proxy + sync routes.
    """
    rec = await db.openalgo_instances.find_one(
        {"account_id": account_id}, {"_id": 0, "base_url": 1, "pid": 1},
    )
    if not rec:
        return None
    if rec.get("pid") and not _pid_alive(int(rec["pid"])):
        return None
    return rec.get("base_url") or None
