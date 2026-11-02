"""TrueData fundamentals job orchestration — TC-28..TC-30 of test_reports/truedata_fundamentals_job_TESTCASES.md.

No network, no database: a fake TrueData client, a fake warehouse and a fake job log. Payloads are SYNTHETIC.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from nidp.services.truedata_fundamentals import __main__ as cli
from nidp.services.truedata_fundamentals import service as S
from nidp.services.truedata_fundamentals import transform as T
from nidp.services.truedata_fundamentals.cache import RawCache
from nidp.services.truedata_fundamentals.loader import References
from nidp.shared import deploy_env
from nidp.shared import market_data_source as mds
from nidp.shared.sources import truedata as td

CREDS = {"TRUEDATA_USERNAME": "u", "TRUEDATA_PASSWORD": "p"}
SHADOW = mds.resolve({"source": "shadow"}, CREDS)
CURRENT = mds.resolve({"source": "current"}, CREDS)
TODAY = date(2026, 11, 2)

from .test_truedata_fundamentals_transform import al, cf, pl   # noqa: E402  (synthetic builders)


class Clock:
    def __init__(self, step=0.0):
        self.t, self.step, self.sleeps = 0.0, step, []

    def now(self):
        self.t += self.step
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class FakeClient:
    configured = True

    def __init__(self, lists=None, statements=None, errors=None):
        self.lists = lists or {}
        self.statements = statements or {}
        self.errors = errors or {}            # (kind, key) → list of TrueDataError to raise first
        self.calls = []

    def _answer(self, kind, key):
        self.calls.append((kind, key))
        errs = self.errors.get((kind, key)) or self.errors.get((kind, "*"))
        if errs:
            e = errs.pop(0) if len(errs) > 1 else errs[0]
            raise e
        if kind == "lists":
            return self.lists.get(key, [])
        if (kind, key) not in self.statements:
            raise td.TrueDataError(td.EMPTY_RESPONSE, "There is no row at position 0.")
        return self.statements[(kind, key)]

    def result_list(self, day):
        return self._answer("lists", day)

    def balance_sheet(self, i):
        return self._answer("al", i)

    def cash_flow(self, i, cumulative=True):
        return self._answer("cf", i)

    def pnl(self, i, cumulative=True):
        return self._answer("pl" if cumulative else "plq", i)


class FakeWarehouse:
    def __init__(self, known=("AAAA",), database="nidp_staging"):
        self.known = set(known)
        self.database = database                     # what current_database() would answer
        self.loads, self.rollbacks, self.ref_calls, self.gate_calls = [], [], 0, 0

    async def load_gate(self, env=None):             # the real shared rule, on this fake's database name
        self.gate_calls += 1
        return deploy_env.classify(self.database, env if env is not None else {})

    async def references(self, symbols=None):
        self.ref_calls += 1
        ours = T.OurFinancials([dict(symbol="AAAA", period_end=date(2026, 3, 31), consolidated=True,
                                     period_type="annual", revenue_from_ops_cr=2600.0, total_income_cr=None),
                                dict(symbol="AAAA", period_end=date(2026, 9, 30), consolidated=True,
                                     period_type="quarterly", revenue_from_ops_cr=650.0, total_income_cr=None)])
        return References(set(symbols) if symbols else self.known, {}, ours, {}, {"AAAA": 1000.0})

    async def load(self, offers, run_id, dry_run):
        self.loads.append((list(offers), run_id, dry_run))
        return {"dry_run": dry_run, "rows_written": 0 if dry_run else len(offers)}

    async def rollback(self, run_id):
        self.rollbacks.append(run_id)
        return {"provenance_rows": 3}


class FakeJob:
    instances = []

    def __init__(self):
        self.run_id = uuid.uuid4()
        self.metadata, self.final = {}, None
        self.rows_fetched = self.rows_inserted = self.rows_skipped = 0
        FakeJob.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        if exc[0] is not None and self.final is None:
            self.final = ("FAILED", str(exc[1]))

    async def finalize(self, status, error_message=None, error_class=None):
        self.final = (status, error_message)
        self.error_class = error_class


def lists_for(fy_id=100, h1_id=200):
    return {date(2026, 4, 20): [{"id": fy_id, "file_time": "2026-04-20T18:00:00", "scripcode": "1", "Symbol": "AAAA",
                                 "ReportingQuarter": "Yearly", "Nature": "Consolidated"}],
            date(2026, 10, 30): [{"id": h1_id, "file_time": "2026-10-30T18:00:00", "scripcode": "1",
                                  "Symbol": "AAAA", "ReportingQuarter": "Second quarter", "Nature": "Consolidated"}]}


def statements():
    return {("pl", 100): pl(revenue=2600.0), ("al", 100): al(), ("cf", 100): cf(),
            ("al", 200): al(fy_start="2026-04-01", fy_end="2027-03-31", quarter="Second quarter"),
            ("cf", 200): cf(start="2026-04-01", end="2026-09-30"),
            ("plq", 200): pl("2026-07-01", "2026-09-30", revenue=650.0, interest=3.0)}


def go(coro):
    return asyncio.run(coro)


STAGING_ENV = {"NIDP_HOME": "/opt/nidp-staging"}


def run_job(tmp_path, client=None, warehouse=None, resolution=SHADOW, clock=None, **kw):
    clock = clock or Clock()
    FakeJob.instances.clear()
    kw.setdefault("anchor_days", 220)
    kw.setdefault("environ", STAGING_ENV)
    return go(S.run(days=kw.pop("days", 10), today=TODAY, raw_root=tmp_path, client=client,
                    warehouse=warehouse or FakeWarehouse(), resolution=resolution, job_factory=FakeJob,
                    clock=clock.now, sleep=clock.sleep, **kw))


# ── TC-28 switch ─────────────────────────────────────────────────────────────────────────────────────────────

def test_tc28_current_calls_nothing_writes_only_skipped_job(tmp_path):
    client, wh = FakeClient(lists_for(), statements()), FakeWarehouse()
    rep = run_job(tmp_path, client, wh, resolution=CURRENT)
    assert rep["status"] == "SKIPPED" and rep["verdict"] == "SWITCHED_OFF"
    assert client.calls == [] and wh.ref_calls == 0 and wh.loads == []
    assert FakeJob.instances[0].final[0] == "SKIPPED"
    assert not any(tmp_path.iterdir())                         # nothing cached either


def test_tc28_current_dry_run_writes_no_job_row(tmp_path):
    rep = run_job(tmp_path, FakeClient(), resolution=CURRENT, dry_run=True)
    assert rep["status"] == "SKIPPED" and FakeJob.instances == []


def test_tc28_forced_current_by_env_is_off():
    r = mds.resolve({"source": "shadow"}, {**CREDS, "MARKET_DATA_SOURCE_FORCE_CURRENT": "1"})
    assert not mds.truedata_is_on(r)
    assert not mds.truedata_is_on(mds.resolve({"source": "shadow"}, {}))      # no credentials → current
    assert mds.truedata_is_on(SHADOW)                                          # staging's setting runs the job


def test_tc28_shadow_runs_and_loads(tmp_path):
    client, wh = FakeClient(lists_for(), statements()), FakeWarehouse()
    rep = run_job(tmp_path, client, wh)
    assert rep["status"] == "OK", rep
    offers, run_id, dry = wh.loads[0]
    assert run_id == str(FakeJob.instances[0].run_id) and dry is False
    assert sorted((o.kind, o.period_end.isoformat()) for o in offers) == [
        ("balance_sheet", "2026-09-30"), ("finance_costs", "2026-09-30")]   # window: only the H1 filing
    job = FakeJob.instances[0]
    assert job.final[0] == "OK" and job.rows_inserted == 2 and job.rows_fetched == rep["fetch"]["calls"]


def test_tc28_rollback_ignores_the_switch():
    wh = FakeWarehouse()
    rid = str(uuid.uuid4())
    rep = go(S.rollback(rid, warehouse=wh))
    assert wh.rollbacks == [rid] and rep["provenance_rows"] == 3


def test_tc28_dry_run_passes_dry_run_and_records_no_job(tmp_path):
    wh = FakeWarehouse()
    rep = run_job(tmp_path, FakeClient(lists_for(), statements()), wh, dry_run=True)
    assert rep["dry_run"] and wh.loads[0][1] is None and wh.loads[0][2] is True
    assert FakeJob.instances == []


# ── TC-29 cache and fetch policy ─────────────────────────────────────────────────────────────────────────────

def test_tc29_cached_statements_and_old_lists_are_not_refetched_recent_lists_are(tmp_path):
    cache = RawCache(tmp_path)
    for d, recs in lists_for().items():
        cache.write("lists", d, {"status": "Success", "Records": recs})
    cache.write("lists", TODAY, {"status": "Success", "Records": []})          # today: refetched anyway
    for (k, i), v in statements().items():
        cache.write(k, i, v)
    client = FakeClient(lists_for(), statements())
    rep = run_job(tmp_path, client)
    fetched_lists = {k for kind, k in client.calls if kind == "lists"}
    assert TODAY in fetched_lists and TODAY - timedelta(days=2) in fetched_lists
    assert date(2026, 10, 30) not in fetched_lists and date(2026, 4, 20) not in fetched_lists
    assert [c for c in client.calls if c[0] != "lists"] == []
    assert rep["status"] == "OK" and rep["fetch"]["statements_cached"] == 4


def test_tc29_empty_answers_are_cached_failures_are_not(tmp_path):
    st = statements()
    del st[("plq", 200)]                                                         # → EMPTY_RESPONSE (cached)
    client = FakeClient(lists_for(), st,
                        errors={("cf", 200): [td.TrueDataError(td.INVALID_PAYLOAD, "TrueData x: not JSON")]})
    rep = run_job(tmp_path, client)
    cache = RawCache(tmp_path)
    assert T.is_empty_answer(cache.read("plq", 200))
    assert not cache.has("cf", 200)                                              # a failure is not cached
    assert rep["status"] == "PARTIAL" and rep["fetch"]["error_INVALID_PAYLOAD"] == 1
    calls_before = len(client.calls)
    client.errors.clear()
    run_job(tmp_path, client)
    later = client.calls[calls_before:]
    assert ("cf", 200) in later and ("plq", 200) not in later                    # retried; empty not re-asked


def test_tc29_rate_limit_waits_then_stops_and_still_loads(tmp_path):
    clock = Clock()
    client = FakeClient(lists_for(), statements(),
                        errors={("al", "*"): [td.TrueDataError(td.RATE_LIMITED, "TrueData x: quota exceeded")]})
    wh = FakeWarehouse()
    rep = run_job(tmp_path, client, wh, clock=clock)
    assert clock.sleeps.count(S.RATE_LIMIT_PAUSE_S) == S.MAX_RATE_LIMIT_PAUSES
    assert rep["fetch"]["stopped"] == "RATE_LIMITED" and rep["status"] == "PARTIAL"
    assert len(wh.loads) == 1                                                   # what is cached is still loaded


def test_tc29_deadline_stops_fetching(tmp_path):
    clock = Clock(step=10.0)                                                   # every clock read = 10 s later
    wh = FakeWarehouse()
    rep = run_job(tmp_path, FakeClient(lists_for(), statements()), wh, clock=clock, max_minutes=1)
    assert rep["fetch"]["stopped"] == "DEADLINE" and rep["status"] == "PARTIAL" and len(wh.loads) == 1


def test_tc29_refused_login_fails_without_loading(tmp_path):
    wh = FakeWarehouse()
    client = FakeClient(errors={("lists", "*"): [td.TrueDataError(td.AUTH_EXPIRED, "TrueData login refused")]})
    rep = run_job(tmp_path, client, wh)
    assert rep["status"] == "FAILED" and wh.loads == [] and FakeJob.instances[0].final[0] == "FAILED"


def test_tc29_no_credentials_fails(tmp_path):
    client = FakeClient()
    client.configured = False
    rep = run_job(tmp_path, client)
    assert rep["status"] == "FAILED" and rep["error_class"] == "NOT_CONFIGURED" and client.calls == []


def test_tc29_offline_uses_cache_only(tmp_path):
    cache = RawCache(tmp_path)
    for d, recs in lists_for().items():
        cache.write("lists", d, {"status": "Success", "Records": recs})
    for (k, i), v in statements().items():
        cache.write(k, i, v)
    wh = FakeWarehouse()
    rep = run_job(tmp_path, None, wh, offline=True)
    assert rep["status"] == "OK" and rep["fetch"]["calls"] == 0 and len(wh.loads[0][0]) == 2


def test_tc29_cache_reads_legacy_failure_files_as_empty(tmp_path):
    cache = RawCache(tmp_path)
    cache.write("pl", 7, {"status": "Invalid Type", "Records": ""})              # as the 2 Nov fetch stored it
    assert T.is_empty_answer(cache.read("pl", 7))
    (tmp_path / "al").mkdir()
    (tmp_path / "al" / "8.json.gz").write_bytes(b"not gzip")
    assert cache.read("al", 8) is None and cache.read("cf", 9) is None


# ── TC-30 CLI ────────────────────────────────────────────────────────────────────────────────────────────────

def test_tc30_cli_parses_and_rejects_bad_usage():
    a = cli.parser().parse_args(["--days", "3", "--symbols", "tcs, infy", "--dry-run", "--offline",
                                 "--max-minutes", "5", "--no-finance-costs"])
    assert (a.days, a.symbols, a.dry_run, a.offline, a.max_minutes, a.no_finance_costs) == (3, "tcs, infy", True,
                                                                                           True, 5.0, True)
    for bad in (["--rollback", "not-a-uuid"], ["--days", "-1"], ["--bogus"]):
        with pytest.raises(SystemExit) as e:
            cli.parser().parse_args(bad)
        assert e.value.code == 2


@pytest.mark.parametrize("status,code", [("OK", 0), ("PARTIAL", 0), ("SKIPPED", 0), ("FAILED", 1)])
def test_tc30_exit_codes(monkeypatch, status, code):
    seen = {}

    async def fake_run(**kw):
        seen.update(kw)
        return {"status": status}

    async def fake_close():
        return None

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr("nidp.shared.storage.pg.close_pool", fake_close)
    assert cli.main(["--symbols", "tcs,INFY", "--days", "2"]) == code
    assert seen["symbols"] == ["TCS", "INFY"] and seen["days"] == 2


def test_tc30_rollback_cli(monkeypatch):
    rid = str(uuid.uuid4())
    seen = []

    async def fake_rollback(r):
        seen.append(r)
        return {"rollback_of": r}

    async def fake_close():
        return None

    monkeypatch.setattr(cli, "rollback", fake_rollback)
    monkeypatch.setattr("nidp.shared.storage.pg.close_pool", fake_close)
    assert cli.main(["--rollback", rid]) == 0 and seen == [rid]


# ── TC-39 the cron file is staging-only ──────────────────────────────────────────────────────────────────────

REPO = __import__("pathlib").Path(__file__).resolve().parents[4]


def test_tc39_production_cron_is_built_from_the_staging_feed_file_only():
    """deploy/cloudpe-prod/deploy-nidp.sh writes production's /etc/cron.d/nidp by rewriting
    deploy/cloudpe/nidp/nidp-staging.cron. This job is not in that file, so it can never be scheduled on production."""
    prod = (REPO / "deploy" / "cloudpe-prod" / "deploy-nidp.sh").read_text()
    sources = set(__import__("re").findall(r"deploy/cloudpe/nidp/[\w.-]+\.cron", prod))
    assert sources == {"deploy/cloudpe/nidp/nidp-staging.cron"}
    assert "truedata" not in prod.lower()
    assert "truedata_fundamentals" not in (REPO / "deploy" / "cloudpe" / "nidp" / "nidp-staging.cron").read_text()
    ours = (REPO / "deploy" / "cloudpe" / "nidp" / "nidp-staging-truedata-fundamentals.cron").read_text()
    lines = [x for x in ours.splitlines() if x.strip() and not x.lstrip().startswith("#") and "=" not in x.split()[0]]
    assert lines == ["15 21 * * 1-5  nidp-staging  NIDP_MAX_ATTEMPTS=1 /opt/nidp-staging/run_service.sh "
                     "truedata_fundamentals --days 10 --max-minutes 75"]
    assert "NIDP_HOME=/opt/nidp-staging" in ours


# ── TC-35..TC-38 staging only (owner, 3 Nov 2026) ────────────────────────────────────────────────────────────

def test_tc35_staging_database_runs(tmp_path):
    for env in (STAGING_ENV, {}):                                   # NIDP_HOME may be unset: the database decides
        wh = FakeWarehouse(database="nidp_staging")
        rep = run_job(tmp_path, FakeClient(lists_for(), statements()), wh, environ=env)
        assert rep["status"] == "OK" and rep["environment"] == "staging" and len(wh.loads) == 1


@pytest.mark.parametrize("database,env", [
    ("nidp", STAGING_ENV),                                          # rows would land in production's database
    ("nidp", {}),
    ("nidp_staging", {"NIDP_HOME": "/opt/nidp"}),                   # prod run_service.sh / prod cron
    ("nidp_staging", {**STAGING_ENV, "NIDP_ENV": "production"}),
    ("nidp_staging", {**STAGING_ENV, "APP_ENV": "prod"}),
])
def test_tc36_any_production_signal_refuses_calls_nothing_writes_no_data(tmp_path, database, env):
    client, wh = FakeClient(lists_for(), statements()), FakeWarehouse(database=database)
    rep = run_job(tmp_path, client, wh, environ=env)
    assert rep["status"] == "SKIPPED" and rep["verdict"] == "NOT_STAGING" and rep["environment"] == "production"
    assert client.calls == [] and wh.ref_calls == 0 and wh.loads == []          # no TrueData, no data read or write
    assert not any(tmp_path.iterdir())                                           # no raw cache either
    job = FakeJob.instances[0]
    assert job.final[0] == "SKIPPED" and job.error_class == "NOT_STAGING"


@pytest.mark.parametrize("database,env", [
    ("postgres", {}),                                               # some other database
    ("postgres", {"NIDP_ENV": "staging"}),                          # NIDP_ENV=staging alone is not trusted
    ("nidp_staging", {"NIDP_HOME": "/home/someone"}),               # conflicting: staging database, odd home
    ("", {}),                                                       # current_database() unreadable
])
def test_tc37_unknown_or_conflicting_refuses_fail_closed(tmp_path, database, env):
    client, wh = FakeClient(lists_for(), statements()), FakeWarehouse(database=database)
    rep = run_job(tmp_path, client, wh, environ=env)
    assert rep["verdict"] == "NOT_STAGING" and rep["environment"] == "unknown"
    assert client.calls == [] and wh.ref_calls == 0 and wh.loads == []
    assert FakeJob.instances[0].error_class == "NOT_STAGING"
    rep = run_job(tmp_path, client, wh, environ=env, dry_run=True)                # dry run: refused, no job row
    assert rep["verdict"] == "NOT_STAGING" and FakeJob.instances == [] and client.calls == []


def test_tc37_switch_off_is_still_checked_first(tmp_path):
    wh = FakeWarehouse(database="nidp")
    rep = run_job(tmp_path, FakeClient(), wh, resolution=CURRENT)
    assert rep["verdict"] == "SWITCHED_OFF" and wh.gate_calls == 0


@pytest.mark.parametrize("database", ["nidp_staging", "nidp", "postgres"])
def test_tc38_rollback_is_allowed_in_every_environment(database):
    wh = FakeWarehouse(database=database)
    rid = str(uuid.uuid4())
    rep = go(S.rollback(rid, warehouse=wh))
    assert wh.rollbacks == [rid] and rep["provenance_rows"] == 3 and wh.gate_calls == 0


def test_tc38_shared_gate_module_is_the_pr455_copy():
    """deploy_env.py is shared with PR #455 (truedata_history / truedata_macro) and must stay byte-identical."""
    import hashlib
    src = (REPO / "backend" / "nidp" / "shared" / "deploy_env.py").read_bytes()
    blob = hashlib.sha1(b"blob %d\0" % len(src) + src).hexdigest()
    assert blob == "83b493120f5b2f5d357613f59319106d59d6baa0"
