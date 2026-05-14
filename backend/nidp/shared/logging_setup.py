"""Structured JSON logging for NIDP services.

Every log record emits one JSON line to stdout — automatically ingested by
Cloud Logging from Cloud Run Jobs and GCE.

Standard fields emitted on every record:

    timestamp       ISO-8601 UTC
    severity        DEBUG / INFO / WARNING / ERROR / CRITICAL
    application     nidp-console  (fixed for all NIDP services)
    environment     dev | staging | prod  (from NIDP_ENV / APP_ENV)
    service         ingester service name (e.g. "bulk_deals")
    version         APP_VERSION / build tag
    correlationId   run_id bound by bind_context()
    traceId         optional trace ID
    jobName         scheduled job / ingester name
    eventType       JOB_RUN | JOB_FAILURE | PIPELINE_EVENT | DATA_EVENT …
    msg             human-readable message
    logger          dotted module name
    exc             formatted traceback (error records only)

Usage:
    from nidp.shared.logging_setup import setup_logging, bind_context
    setup_logging(service="bulk_deals")
    bind_context(run_id=str(run.run_id), target_date="2026-05-04")
    log = logging.getLogger(__name__)
    log.info("fetched rows", extra={"rows": 42, "eventType": "DATA_EVENT"})
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import time
from typing import Any

_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar("nidp_log_ctx", default={})

_RESERVED = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname",
    "filename", "module", "exc_info", "exc_text", "stack_info",
    "lineno", "funcName", "created", "msecs", "relativeCreated",
    "thread", "threadName", "processName", "process", "message",
    "asctime", "taskName",
})

# Python level → GCP severity mapping
_SEVERITY_MAP = {
    "DEBUG":    "DEBUG",
    "INFO":     "INFO",
    "WARNING":  "WARNING",
    "ERROR":    "ERROR",
    "CRITICAL": "CRITICAL",
}


class JsonFormatter(logging.Formatter):
    """GCP Cloud Logging-compatible JSON formatter for NIDP services."""

    def __init__(self, env: str = "", version: str = "") -> None:
        super().__init__()
        self._env = env
        self._version = version

    def format(self, record: logging.LogRecord) -> str:
        ts = (
            time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z"
        )
        payload: dict[str, Any] = {
            "timestamp":   ts,
            "severity":    _SEVERITY_MAP.get(record.levelname, record.levelname),
            "application": "nidp-console",
            "logger":      record.name,
            "msg":         record.getMessage(),
        }

        if self._env:
            payload["environment"] = self._env
        if self._version:
            payload["version"] = self._version

        # Cloud Logging trace field (auto-correlates with Cloud Trace)
        project = os.environ.get("GCP_PROJECT", "")
        ctx = _ctx.get()
        trace_id = ctx.get("traceId") or ctx.get("run_id", "")
        if trace_id and project:
            payload["logging.googleapis.com/trace"] = (
                f"projects/{project}/traces/{trace_id}"
            )

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
            if record.exc_info[1] is not None:
                payload["exceptionClass"] = type(record.exc_info[1]).__name__

        # Bound context (service, run_id, target_date, job_name, etc.)
        if ctx:
            for k, v in ctx.items():
                if k not in payload:
                    payload[k] = v

        # Per-record extras
        for k, v in record.__dict__.items():
            if k in _RESERVED or k.startswith("_") or k in payload:
                continue
            payload[k] = v

        return json.dumps(payload, default=str, separators=(",", ":"))


def setup_logging(service: str, level: str | None = None) -> None:
    """Configure root logger for a NIDP service.

    Call once at the top of each ingester/job entrypoint before any log calls.
    """
    lvl = (level or os.environ.get("NIDP_LOG_LEVEL") or os.environ.get("LOG_LEVEL") or "INFO").upper()
    env = os.environ.get("NIDP_ENV") or os.environ.get("APP_ENV", "dev")
    version = os.environ.get("APP_VERSION", "")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(env=env, version=version))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(lvl)

    # Bind service name and application into every record automatically.
    bind_context(service=service, application="nidp-console", jobName=service)


def bind_context(**kv: Any) -> None:
    """Merge key-value pairs into the thread-local log context."""
    cur = dict(_ctx.get())
    cur.update({k: v for k, v in kv.items() if v is not None})
    _ctx.set(cur)


def clear_context() -> None:
    _ctx.set({})
