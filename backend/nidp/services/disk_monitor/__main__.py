"""python -m nidp.services.disk_monitor

Off-DB disk-space alarm. Exits 1 if any path is at/below the CRITICAL threshold
(so a monitoring cron that checks exit codes flags it), else 0. Run from a
dedicated cron line — NOT run_service.sh (which would retry it).
"""
from __future__ import annotations

import sys

from nidp.shared.logging_setup import setup_logging

from .service import run


def main() -> None:
    setup_logging(service="disk_monitor")
    report = run()
    findings = report["findings"]
    crit = [f for f in findings if f["severity"] == "CRITICAL"]
    print(f"disk_monitor: {len(findings)} breach(es) "
          f"({len(crit)} critical) across {len(report['paths'])} path(s)")
    sys.exit(1 if crit else 0)


if __name__ == "__main__":
    main()
