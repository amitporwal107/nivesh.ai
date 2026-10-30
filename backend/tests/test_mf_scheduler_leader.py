"""The scheduled jobs run in ONE process (services/mf_scheduler.py leader lock; audit of 30 Oct: staging runs
`uvicorn --workers 4` and each worker started its own scheduler, so the 17:30 broker sync ran about four times at once).

A second process holding the lock is a real separate Python process (subprocess), as a second uvicorn worker is.
Every job in that scheduler is covered: either the process runs all of them, or none.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time

import pytest

from services import mf_scheduler as sched

HOLDER = (
    "import fcntl, os, sys, time\n"
    "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)\n"
    "fcntl.flock(fd, fcntl.LOCK_EX)\n"
    "print('held', flush=True)\n"
    "time.sleep(60)\n"
)


@pytest.fixture
def lock_path(tmp_path, monkeypatch):
    path = tmp_path / "mf-scheduler.lock"
    monkeypatch.setenv(sched.LOCK_PATH_ENV, str(path))
    yield str(path)
    sched.stop()


def _start_and_read():
    async def go():
        sched.start()
        running = sched._scheduler is not None and sched._scheduler.running
        ids = sorted(j.id for j in sched._scheduler.get_jobs()) if running else []
        return running, ids, sched.status()
    return asyncio.run(go())


def test_ls1_the_first_starter_runs_every_job(lock_path):
    running, ids, status = _start_and_read()
    assert running and sched.is_leader()
    assert "broker_holdings_sync_daily" in ids and len(ids) == 14
    assert status["running"] is True


def test_ls2_a_second_process_holding_the_lock_means_no_jobs_here(lock_path):
    other = subprocess.Popen([sys.executable, "-c", HOLDER, lock_path], stdout=subprocess.PIPE, text=True)
    try:
        assert other.stdout.readline().strip() == "held"
        running, ids, status = _start_and_read()
        assert not running and ids == [] and not sched.is_leader()
        assert status["running"] is False and "does not run the scheduled jobs" in status["note"]
        sched.start()                                    # an admin "start" in this worker changes nothing either
        assert sched._scheduler is None
    finally:
        other.kill()
        other.wait()
    # The holder exited: the kernel dropped its lock, so the next start here takes over.
    time.sleep(0.05)
    running, ids, _ = _start_and_read()
    assert running and sched.is_leader() and len(ids) == 14


def test_ls3_stop_releases_the_lock_for_another_process(lock_path):
    _start_and_read()
    sched.stop()
    assert not sched.is_leader()
    probe = subprocess.run([sys.executable, "-c",
                            "import fcntl, os, sys\n"
                            "fd = os.open(sys.argv[1], os.O_RDWR)\n"
                            "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                            "print('got it')\n", lock_path], capture_output=True, text=True, timeout=10)
    assert probe.stdout.strip() == "got it", probe.stderr
