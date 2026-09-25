"""Logging configuration for a study run — configured ONCE, here, at the entry point.

Modules in this package only ever call `logging.getLogger(__name__)`; nothing below this file
touches the root logger or adds a handler. That keeps the hierarchy (`research.charting.study.*`,
`research.charting.events.*`) configurable per module, and means importing the package as a library
never hijacks someone else's logging.

WHY THIS REPLACED `print`
-------------------------
`study/heartbeat.py` used `print`, which has no levels, no timestamps and no way to turn down. A
multi-hour run then produces either a flood or a void, with no middle setting. It also meant the
per-chunk progress lines and a genuine failure looked identical in the log.

WHAT IS DELIBERATELY NOT LOGGED
-------------------------------
No study metric ever reaches a log record. Counts, stages, durations and resource figures are run
bookkeeping; a hit rate, a net return or an AUC belongs in `report.json`, read deliberately. The
CLI's own rule ("never prints a metric") extends to the logs, and `tests/test_heartbeat.py` asserts
it. Nor do credentials: this package handles none, and the filter below is a backstop for the day
something changes.
"""
from __future__ import annotations

import logging
import logging.config
import re
from pathlib import Path
from typing import Optional

#: Patterns redacted from any record that reaches a handler. A defence in depth, not a licence to
#: log secrets: the right fix is never to pass them to a logger in the first place.
_REDACT = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|authorization|bearer)\b\s*[=:]\s*\S+"
)


class RedactingFilter(logging.Filter):
    """Masks anything that looks like a credential in the formatted message."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:                       # a bad format string must not kill the run
            return True
        if _REDACT.search(msg):
            record.msg = _REDACT.sub(r"\1=<redacted>", msg)
            record.args = ()
        return True


def configure(log_dir: Optional[Path] = None, *, level: str = "INFO",
              console: bool = True, rotate_bytes: int = 64 * 1024 * 1024,
              backups: int = 5) -> None:
    """Configure logging for a run. Call once, from the driver — never from a library module.

    `log_dir` adds a rotating file handler (`study.log`), so a multi-hour run cannot fill the disk
    that the run itself is trying to write results to. Console output goes to stdout so a systemd
    unit or container collects it without extra plumbing.
    """
    handlers: dict = {}
    handler_names: list = []

    if console:
        handlers["console"] = {
            "class": "logging.StreamHandler",
            "formatter": "std",
            "filters": ["redact"],
            "stream": "ext://sys.stdout",
        }
        handler_names.append("console")

    if log_dir is not None:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "std",
            "filters": ["redact"],
            "filename": str(Path(log_dir) / "study.log"),
            "maxBytes": rotate_bytes,
            "backupCount": backups,
            "encoding": "utf-8",
        }
        handler_names.append("file")

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "std": {"format": "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%SZ"},
        },
        "filters": {"redact": {"()": RedactingFilter}},
        "handlers": handlers,
        "loggers": {
            "research.charting": {"level": level},
            # Quiet the dependencies that would otherwise dominate an INFO log.
            "matplotlib": {"level": "WARNING"},
            "urllib3": {"level": "WARNING"},
            "botocore": {"level": "WARNING"},
            "google": {"level": "WARNING"},
        },
        "root": {"level": "WARNING", "handlers": handler_names},
    })
