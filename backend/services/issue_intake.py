"""Interactive error intake — file a work_issue when an error/exception surfaces
in a user's session logs (Settings → Logs & Diagnostics).

Complements backend/scripts/error_triage.py: that sweeps Cloud Logging hourly for
the AMBIENT error stream; this handles the INTERACTIVE stream — errors a user
reproduces while session logging is on. Both upsert the same `work_issues`
collection using the SAME `sig` algorithm, so an interactively-surfaced server
error and its ambient twin collapse into one issue (no duplicates).

Everything here is best-effort: it must never raise into the request path.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from deps import db

logger = logging.getLogger(__name__)
_COLLECTION = "work_issues"

# ── Signature normalization — MUST match backend/scripts/error_triage.py ──────
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_NUM_RE = re.compile(r"\b\d+\b")
_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*")
_PATH_PARAM_RE = re.compile(r"/[0-9a-f]{8,}|/\d+")


def _normalize_msg(msg: str) -> str:
    if not msg:
        return ""
    s = msg.lower()
    s = _UUID_RE.sub("<uuid>", s)
    s = _TIMESTAMP_RE.sub("<ts>", s)
    s = _NUM_RE.sub("<n>", s)
    return s[:120]


def _normalize_endpoint(ep: str) -> str:
    if not ep:
        return ""
    return _PATH_PARAM_RE.sub("/<id>", ep)


def _sig(exception_class: str, target: str, norm_msg: str) -> str:
    key = (exception_class or "<no-exc>", target or "<unknown>", norm_msg)
    return hashlib.sha1("|".join(key).encode()).hexdigest()[:16]


def _severity_to_priority(severity: str) -> str:
    return {"CRITICAL": "P1", "ERROR": "P2", "WARNING": "P3"}.get(severity.upper(), "P2")


_EXC_LINE_RE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Warning))\b")


def _exc_class_from_traceback(tb: str) -> str:
    """Best-effort: pull the exception class from the last line of a traceback."""
    if not tb:
        return ""
    for line in reversed(tb.strip().splitlines()):
        m = _EXC_LINE_RE.match(line.strip())
        if m:
            return m.group(1).split(".")[-1]
    return ""


async def _next_issue_id() -> str:
    last = await db[_COLLECTION].find_one({}, {"issue_id": 1}, sort=[("created_at", -1)])
    last_n = 0
    if last and str(last.get("issue_id", "")).startswith("WORK-"):
        try:
            last_n = int(last["issue_id"].split("-")[1])
        except (ValueError, IndexError):
            pass
    return f"WORK-{last_n + 1:04d}"


async def _upsert(
    *,
    sig: str,
    title: str,
    severity: str,
    source: str,
    exception_class: str,
    endpoint: str,
    http_status: Optional[int],
    sample_message: str,
    sample_traceback: str,
    applications: list[str],
    count: int,
) -> Optional[str]:
    now = datetime.now(timezone.utc)
    existing = await db[_COLLECTION].find_one({"sig": sig}, {"issue_id": 1, "status": 1})
    if existing:
        # Recurrence — bump counters; if it had been resolved, reopen it (regression).
        set_fields: dict[str, Any] = {"last_seen": now, "updated_at": now}
        if existing.get("status") == "resolved":
            set_fields["status"] = "open"
            set_fields["resolved_at"] = None
        await db[_COLLECTION].update_one(
            {"sig": sig},
            {"$set": set_fields, "$inc": {"recurrence_count": 1, "count_24h": count}},
        )
        return existing.get("issue_id")

    issue_id = await _next_issue_id()
    doc = {
        "issue_id": issue_id,
        "sig": sig,
        "title": title,
        "severity": severity,
        "priority": _severity_to_priority(severity),
        "status": "open",
        "source": source,
        "exception_class": exception_class,
        "endpoint": endpoint,
        "job_name": "",
        "http_status": http_status,
        "sample_message": (sample_message or "")[:500],
        "sample_traceback": (sample_traceback or "")[:1000],
        "first_seen": now,
        "last_seen": now,
        "count_24h": count,
        "applications": applications,
        "rca": None,
        "labels": [],
        "assignee": None,
        "comments": [],
        "recurrence_count": 1,
        "classification": "unclassified",
        "rca_document": None,
        "test_document": None,
        "screenshots": [],
        "remediation": None,
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
    }
    await db[_COLLECTION].insert_one(doc)
    logger.info("issue_intake filed %s (source=%s sig=%s)", issue_id, source, sig)
    return issue_id


async def intake_error(
    *,
    severity: str,
    source: str,
    message: str,
    exception_class: str = "",
    endpoint: str = "",
    http_status: Optional[int] = None,
    traceback: str = "",
    application: str = "",
    client: bool = False,
) -> Optional[str]:
    """File (or bump) a single work_issue for one error. Returns issue_id or None.

    Only ERROR / CRITICAL are filed — warnings and below are ignored.
    """
    try:
        if (severity or "").upper() not in ("ERROR", "CRITICAL"):
            return None
        exc = exception_class or _exc_class_from_traceback(traceback)
        target = "<client>" if client else (_normalize_endpoint(endpoint) or "<unknown>")
        sig = _sig(exc or "<no-exc>", target, _normalize_msg(message))
        where = endpoint or ("(client)" if client else "(unknown)")
        title = f"{exc or 'Error'} at {where}"
        return await _upsert(
            sig=sig, title=title, severity=severity.upper(), source=source,
            exception_class=exc, endpoint=endpoint, http_status=http_status,
            sample_message=message, sample_traceback=traceback,
            applications=[application] if application else [], count=1,
        )
    except Exception as e:  # noqa: BLE001 — intake must never break the caller
        logger.warning("issue_intake.intake_error failed: %s", e)
        return None


async def intake_from_server_entries(
    entries: Iterable[dict],
    *,
    application: str = "nivesh-main-app",
) -> list[str]:
    """Batch-intake ERROR/CRITICAL entries captured server-side during a debug
    session. Entries are the shape produced by SessionCaptureHandler
    (ts, severity, logger, msg, correlationId, endpoint, httpStatus, exc).
    Deduped within the batch so one request bumps a counter once, not per line.
    """
    grouped: dict[str, dict] = {}
    try:
        for e in entries:
            sev = str(e.get("severity", "")).upper()
            if sev not in ("ERROR", "CRITICAL"):
                continue
            exc = _exc_class_from_traceback(str(e.get("exc", "")))
            endpoint = str(e.get("endpoint", "") or "")
            target = _normalize_endpoint(endpoint) or "<unknown>"
            msg = str(e.get("msg", "") or "")
            sig = _sig(exc or "<no-exc>", target, _normalize_msg(msg))
            g = grouped.get(sig)
            if g:
                g["count"] += 1
                if sev == "CRITICAL":
                    g["severity"] = "CRITICAL"
            else:
                grouped[sig] = {
                    "sig": sig, "severity": sev, "exc": exc, "endpoint": endpoint,
                    "http_status": e.get("httpStatus"), "msg": msg,
                    "exc_text": str(e.get("exc", "") or ""), "count": 1,
                }
        out: list[str] = []
        for sig, g in grouped.items():
            where = g["endpoint"] or "(unknown)"
            iid = await _upsert(
                sig=sig, title=f"{g['exc'] or 'Error'} at {where}", severity=g["severity"],
                source="session_server", exception_class=g["exc"], endpoint=g["endpoint"],
                http_status=g["http_status"], sample_message=g["msg"],
                sample_traceback=g["exc_text"], applications=[application], count=g["count"],
            )
            if iid:
                out.append(iid)
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("issue_intake.intake_from_server_entries failed: %s", e)
        return []
