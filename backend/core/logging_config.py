"""Structured JSON logging for the nivesh.ai backend.

Every log record emits a single JSON line to stdout, ingested by Cloud Logging
automatically from stdout on GCE/Cloud Run.

Standard log fields (GCP Cloud Logging compatible):

    timestamp       ISO-8601 UTC
    severity        DEBUG / INFO / WARNING / ERROR / CRITICAL   (mapped from Python level)
    application     nivesh-main-app | nidp-console | admin-app  (from context)
    environment     dev | staging | prod                        (from APP_ENV / ENVIRONMENT)
    service         python module service name                  (configured at startup)
    version         release version / git sha                   (from APP_VERSION)
    correlationId   per-request ID propagated via X-Correlation-ID
    traceId         Google Cloud Trace ID (from X-Cloud-Trace-Context)
    userId          anonymised user identifier                  (from request context)
    endpoint        /api/path                                   (from request context)
    httpStatus      200 / 400 / 500 …                          (from request context)
    responseTimeMs  elapsed milliseconds                        (from request context)
    eventType       BUSINESS_EVENT | AUTH_FAILURE | JOB_RUN …  (caller-supplied)
    exceptionClass  ExceptionName                               (auto-filled on exc_info)
    jobName         scheduler job name                         (caller-supplied)
    msg             human-readable message
    logger          dotted logger name
    exc             formatted traceback (errors only)

Usage
-----
    from core.logging_config import configure_logging
    configure_logging(service="api")          # once at process startup

    import logging
    log = logging.getLogger(__name__)
    log.info("portfolio loaded", extra={
        "eventType": "BUSINESS_EVENT",
        "portfolio_id": pid,
        "responseTimeMs": 42,
    })
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
import time
from typing import Any

# ── Per-request context variables ────────────────────────────────────────────
# Set by RequestLoggingMiddleware for each inbound request; available to all
# log statements executed during that request without explicit passing.

_correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)
_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)
_user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "user_id", default=""
)
_application_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "application", default=""
)
_endpoint_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "endpoint", default=""
)

# ── Getters / setters ─────────────────────────────────────────────────────────

def get_correlation_id() -> str:
    return _correlation_id_var.get()

def set_correlation_id(cid: str) -> contextvars.Token:
    return _correlation_id_var.set(cid)

def reset_correlation_id(token: contextvars.Token) -> None:
    _correlation_id_var.reset(token)

def get_trace_id() -> str:
    return _trace_id_var.get()

def get_user_id() -> str:
    return _user_id_var.get()

def get_application() -> str:
    return _application_var.get()


def set_request_context(
    *,
    correlation_id: str = "",
    trace_id: str = "",
    user_id: str = "",
    application: str = "",
    endpoint: str = "",
) -> list[contextvars.Token]:
    """Set all per-request context vars atomically.  Returns tokens for reset."""
    return [
        _correlation_id_var.set(correlation_id),
        _trace_id_var.set(trace_id),
        _user_id_var.set(user_id),
        _application_var.set(application),
        _endpoint_var.set(endpoint),
    ]


def reset_request_context(tokens: list[contextvars.Token]) -> None:
    vars_ = [_correlation_id_var, _trace_id_var, _user_id_var, _application_var, _endpoint_var]
    for var, token in zip(vars_, tokens):
        var.reset(token)


# ── Sensitive field masking ───────────────────────────────────────────────────

_SENSITIVE_PATTERNS = re.compile(
    r"(password|passwd|secret|token|credential|otp|cvv|pan|aadhaar|"
    r"account.?num|card.?num|session|auth|api.?key|private.?key|"
    r"refresh.?token|access.?token|bearer|ssn)",
    re.IGNORECASE,
)
_MASK = "***REDACTED***"


def _mask_value(key: str, value: Any) -> Any:
    if isinstance(key, str) and _SENSITIVE_PATTERNS.search(key):
        return _MASK
    return value


def mask_email(email: str) -> str:
    """Partially mask an email for log output:  john.doe@example.com → jo***@example.com"""
    if not email or "@" not in email:
        return _MASK
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        return f"{local[0]}***@{domain}"
    return f"{local[:2]}***@{domain}"


def mask_pan(pan: str) -> str:
    """Mask PAN: ABCDE1234F → *****1234F"""
    if not pan or len(pan) < 5:
        return _MASK
    return "*" * (len(pan) - 4) + pan[-4:]


# ── Python level → GCP severity mapping ──────────────────────────────────────

_SEVERITY_MAP = {
    "DEBUG":    "DEBUG",
    "INFO":     "INFO",
    "WARNING":  "WARNING",
    "ERROR":    "ERROR",
    "CRITICAL": "CRITICAL",
}

# ── Reserved stdlib attributes (never re-emitted as extras) ──────────────────

_STDLIB_RESERVED = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname",
    "filename", "module", "exc_info", "exc_text", "stack_info",
    "lineno", "funcName", "created", "msecs", "relativeCreated",
    "thread", "threadName", "processName", "process", "message",
    "asctime", "taskName",
})


# ── JSON Formatter ────────────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """Emit one structured JSON line per log record.

    Emits all 14 standard fields required by the GCP Cloud Logging dashboard
    spec.  Fields are omitted when empty so log entries stay lean for the
    common case (no exception, no job context, etc.).
    """

    def __init__(self, service: str = "", env: str = "", version: str = "") -> None:
        super().__init__()
        self._service = service
        self._env = env
        self._version = version

    def format(self, record: logging.LogRecord) -> str:
        ts = (
            time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z"
        )
        severity = _SEVERITY_MAP.get(record.levelname, record.levelname)

        # Collect per-record extras first (caller-supplied overrides context).
        extras: dict[str, Any] = {}
        for key, val in record.__dict__.items():
            if key in _STDLIB_RESERVED or key.startswith("_"):
                continue
            extras[key] = _mask_value(key, val)

        # ── Required standard fields ──────────────────────────────────────────
        payload: dict[str, Any] = {
            "timestamp":   ts,
            "severity":    severity,
            "logger":      record.name,
            "msg":         record.getMessage(),
        }

        # Process-level fields (always present after configure_logging())
        if self._service:
            payload["service"] = self._service
        if self._env:
            payload["environment"] = self._env
        if self._version:
            payload["version"] = self._version

        # Per-request context (injected by RequestLoggingMiddleware)
        app = extras.pop("application", None) or _application_var.get()
        if app:
            payload["application"] = app

        cid = extras.pop("correlationId", None) or _correlation_id_var.get()
        if cid:
            payload["correlationId"] = cid

        tid = extras.pop("traceId", None) or _trace_id_var.get()
        if tid:
            payload["traceId"] = tid
            # Cloud Logging trace field for automatic trace correlation.
            project = os.environ.get("GCP_PROJECT", "")
            if project:
                payload["logging.googleapis.com/trace"] = (
                    f"projects/{project}/traces/{tid}"
                )

        uid = extras.pop("userId", None) or _user_id_var.get()
        if uid:
            payload["userId"] = uid

        endpoint = extras.pop("endpoint", None) or _endpoint_var.get()
        if endpoint:
            payload["endpoint"] = endpoint

        # Optional per-log fields (caller-supplied via extra={})
        for field in ("httpStatus", "responseTimeMs", "eventType", "jobName"):
            val = extras.pop(field, None)
            if val is not None:
                payload[field] = val

        # Exception class — auto-fill from exc_info
        exc_class = extras.pop("exceptionClass", None)
        if record.exc_info and record.exc_info[1] is not None and not exc_class:
            exc_class = type(record.exc_info[1]).__name__
        if exc_class:
            payload["exceptionClass"] = exc_class

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        # Remaining caller-supplied extras
        payload.update(extras)

        return json.dumps(payload, default=str, separators=(",", ":"))


# ── Public API ────────────────────────────────────────────────────────────────

def configure_logging(
    service: str = "api",
    *,
    level: str | None = None,
    env: str | None = None,
    version: str | None = None,
) -> None:
    """Configure the root logger to emit structured JSON on stdout.

    Call exactly once at process start, before any other import that acquires
    a logger.  Subsequent calls re-apply the same configuration (idempotent).
    """
    resolved_level = (
        level
        or os.environ.get("LOG_LEVEL")
        or ("DEBUG" if os.environ.get("DEBUG") else "INFO")
    ).upper()
    resolved_env = env or os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT", "dev")
    resolved_version = version or os.environ.get("APP_VERSION", "")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(
        service=service,
        env=resolved_env,
        version=resolved_version,
    ))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(resolved_level)

    # Suppress very chatty third-party loggers.
    for noisy in ("uvicorn.access", "motor", "asyncio", "httpcore", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
