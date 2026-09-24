"""Run observability for a long study — progress, liveness, resource guards and fail-fast gates.

WHY
---
`study/execute.py` contains exactly one `print`, at the very end. That is deliberate for a CLI that
must never leak a metric into stdout (its own docstring: "never prints a metric"), but it makes a
7.8-hour unattended run a black box: it either produces `report.json` eventually or it does not, and
there is no way to tell a run that is working from one that is wedged.

Three separate jobs, which a single log line does not cover:

1. **Progress and liveness.** `run_status.json` is rewritten at every stage boundary and throttled
   during long stages, so `cat` answers "where is it and is it moving" at any moment. `run.log` is
   the append-only narrative for afterwards.

2. **Resource guards.** This box also runs prod Postgres. The failure that matters is not the study
   dying — it is the study taking the host down with it, which the Ray backfill's own docstring
   records happening on 2026-07-17 ("OOM-killed ... taking SSH, code-server and prod Postgres' host
   down"). `check_resources` raises BEFORE that point, so the run aborts and prod does not.

3. **Fail-fast gates.** A run that will produce nothing should say so in minute 20, not hour 7.
   `require` records the check and its result either way, so a passing gate is evidence too.

Nothing here computes or prints a study metric. Counts of events and families are run bookkeeping —
the same things `study_manifest.json` already records — not results.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


class ResourceGuard(Exception):
    """Raised when continuing would risk the host rather than merely the run."""


class FailFast(Exception):
    """Raised when the run cannot produce a usable result, detected early."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rss_gb() -> float:
    try:
        with open(f"/proc/{os.getpid()}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return 0.0


def disk_free_gb(path: str = "/") -> float:
    try:
        return shutil.disk_usage(path).free / 1024 ** 3
    except OSError:
        return 0.0


class Heartbeat:
    """Progress, liveness and guard rails for one study run.

    `max_rss_gb` and `min_disk_gb` default to values sized for this host: 15 GB total RAM with prod
    Postgres resident, and a root filesystem that has been the cause of prod outages when it filled.
    They are deliberately conservative — aborting a run costs hours, taking the host down costs
    more.
    """

    def __init__(self, out_dir, *, max_rss_gb: float = 8.0, min_disk_gb: float = 3.0,
                 throttle_seconds: float = 20.0, echo: bool = True):
        self.dir = Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.status_path = self.dir / "run_status.json"
        self.log_path = self.dir / "run.log"
        self.max_rss_gb, self.min_disk_gb = max_rss_gb, min_disk_gb
        self.throttle, self.echo = throttle_seconds, echo

        self.started = time.time()
        self.stage_name = "starting"
        self.stage_started = self.started
        self._last_write = 0.0
        self.notes: dict = {}
        self.stages: list = []
        self.gates: list = []
        self._write(force=True)

    # ── narrative ───────────────────────────────────────────────────────────────────────────────

    def log(self, message: str) -> None:
        line = f"{_now()}  {message}"
        with open(self.log_path, "a") as f:
            f.write(line + "\n")
        if self.echo:
            print(line, flush=True)

    def stage(self, name: str) -> None:
        """Close the previous stage (recording how long it really took) and open a new one."""
        if self.stage_name != "starting":
            elapsed = time.time() - self.stage_started
            self.stages.append({"stage": self.stage_name, "seconds": round(elapsed, 1)})
            self.log(f"[done] {self.stage_name} in {elapsed / 60:.1f} min")
        self.stage_name = name
        self.stage_started = time.time()
        self.log(f"[stage] {name}")
        self._write(force=True)

    def note(self, key: str, value: Any) -> None:
        self.notes[key] = value
        self.log(f"  {key} = {value}")
        self._write(force=True)

    def progress(self, done: int, total: int, unit: str = "") -> None:
        """Throttled — called per chunk, so it must not itself become the cost."""
        self._done, self._total, self._unit = done, total, unit
        if time.time() - self._last_write < self.throttle and done < total:
            return
        elapsed = time.time() - self.stage_started
        rate = done / elapsed if elapsed > 0 else 0.0
        eta = (total - done) / rate if rate > 0 else None
        self.log(f"  {self.stage_name}: {done:,}/{total:,} {unit}"
                 f" | {elapsed / 60:.1f} min elapsed"
                 + (f" | ETA {eta / 60:.1f} min" if eta is not None else "")
                 + f" | RSS {rss_gb():.2f} GB")
        self._write(force=True)

    # ── guards ──────────────────────────────────────────────────────────────────────────────────

    def check_resources(self) -> None:
        """Abort the RUN before the HOST is at risk. Called at every stage boundary and chunk."""
        rss, free = rss_gb(), disk_free_gb()
        if rss > self.max_rss_gb:
            raise ResourceGuard(
                f"run is using {rss:.2f} GB RSS, over the {self.max_rss_gb} GB ceiling. Aborting "
                f"rather than risk the host — prod Postgres runs here."
            )
        if free < self.min_disk_gb:
            raise ResourceGuard(
                f"only {free:.2f} GB disk free, under the {self.min_disk_gb} GB floor. Aborting: a "
                f"full disk on this host has caused prod outages."
            )

    def require(self, name: str, condition: bool, detail: str = "") -> None:
        """A fail-fast gate. Recorded whether it passes or fails, so a green gate is evidence too."""
        self.gates.append({"gate": name, "passed": bool(condition), "detail": detail,
                           "at": _now()})
        self._write(force=True)
        if condition:
            self.log(f"  [gate OK] {name}" + (f" — {detail}" if detail else ""))
            return
        self.log(f"  [GATE FAILED] {name} — {detail}")
        raise FailFast(f"{name}: {detail}")

    # ── status file ─────────────────────────────────────────────────────────────────────────────

    def _write(self, force: bool = False) -> None:
        if not force and time.time() - self._last_write < self.throttle:
            return
        self._last_write = time.time()
        elapsed = time.time() - self.started
        payload = {
            "state": "running",
            "stage": self.stage_name,
            "started_at": datetime.fromtimestamp(self.started, timezone.utc)
                                  .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_at": _now(),
            "elapsed_minutes": round(elapsed / 60, 1),
            "stage_elapsed_minutes": round((time.time() - self.stage_started) / 60, 1),
            "progress": {"done": getattr(self, "_done", None), "total": getattr(self, "_total", None),
                         "unit": getattr(self, "_unit", "")},
            "resources": {"rss_gb": round(rss_gb(), 2), "disk_free_gb": round(disk_free_gb(), 2),
                          "rss_ceiling_gb": self.max_rss_gb, "disk_floor_gb": self.min_disk_gb},
            "stages_completed": self.stages,
            "gates": self.gates,
            "notes": self.notes,
            "pid": os.getpid(),
        }
        tmp = self.status_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        tmp.replace(self.status_path)          # atomic: a reader never sees a half-written file

    def finish(self, state: str, detail: str = "") -> None:
        if self.stage_name != "starting":
            self.stages.append({"stage": self.stage_name,
                                "seconds": round(time.time() - self.stage_started, 1)})
        self.log(f"[{state}] {detail}" if detail else f"[{state}]")
        self._write(force=True)
        payload = json.loads(self.status_path.read_text())
        payload["state"] = state
        payload["detail"] = detail
        payload["total_minutes"] = round((time.time() - self.started) / 60, 1)
        self.status_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
