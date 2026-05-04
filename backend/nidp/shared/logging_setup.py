"""Structured JSON logging for NIDP services.

Every log record emits one line of JSON to stdout, ELK/Logstash
ingest-friendly. Includes a `run_id` and `service` field that callers
can bind via `bind_context()` so every line for an ingester run is
correlatable.

Usage:
    from nidp.shared.logging_setup import setup_logging, bind_context
    setup_logging(service="bulk_deals")
    bind_context(run_id=str(run.run_id), target_date="2026-05-04")
    log = logging.getLogger(__name__)
    log.info("fetched", extra={"rows": 42})
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

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname",
    "filename", "module", "exc_info", "exc_text", "stack_info",
    "lineno", "funcName", "created", "msecs", "relativeCreated",
    "thread", "threadName", "processName", "process", "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Bound context
        ctx = _ctx.get()
        if ctx:
            payload.update(ctx)
        # Per-record extras
        for k, v in record.__dict__.items():
            if k in _RESERVED or k.startswith("_") or k in payload:
                continue
            payload[k] = v
        return json.dumps(payload, default=str, separators=(",", ":"))


def setup_logging(service: str, level: str | None = None) -> None:
    lvl = (level or os.environ.get("NIDP_LOG_LEVEL") or "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(lvl)
    bind_context(service=service)


def bind_context(**kv: Any) -> None:
    cur = dict(_ctx.get())
    cur.update({k: v for k, v in kv.items() if v is not None})
    _ctx.set(cur)


def clear_context() -> None:
    _ctx.set({})
