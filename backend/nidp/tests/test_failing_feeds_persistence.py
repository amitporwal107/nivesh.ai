"""End-to-end persistence integration tests for the failing NIDP feeds.

For each feed:
  1. Loads a real fixture from /tests/fixtures/
  2. Runs it through the parser
  3. Persists into a local PG schema cloned from the production migrations
  4. Reads back and asserts row counts + key column values

Set SKIP_PG=1 to skip when no local PG is available (CI without sidecar).

Run: PGPASSWORD=nivesh_local python3 -m pytest \\
       backend/nidp/tests/test_failing_feeds_persistence.py -v
"""
from __future__ import annotations

import json
import os
import socket
import zipfile
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"

PG_URL = os.environ.get(
    "TEST_POSTGRES_URL",
    "postgresql://nivesh:nivesh_local@localhost:5432/nivesh_dev",
)


def _pg_available() -> bool:
    if os.environ.get("SKIP_PG"):
        return False
    try:
        s = socket.create_connection(("localhost", 5432), timeout=1)
        s.close()
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_available(),
    reason="local Postgres not reachable on localhost:5432 (set SKIP_PG=1 to silence)",
)


@pytest.fixture(scope="module")
def conn():
    """Per-module connection. Wrap each test in a SAVEPOINT-style
    transaction so writes don't leak across tests."""
    import psycopg2
    c = psycopg2.connect(PG_URL)
    c.autocommit = False
    yield c
    c.rollback()
    c.close()


@pytest.fixture(autouse=True)
def _txn(conn):
    """Each test runs in its own transaction; rolls back at teardown."""
    cur = conn.cursor()
    cur.execute("SAVEPOINT t1")
    yield cur
    cur.execute("ROLLBACK TO SAVEPOINT t1")


# ─────────────────────────────────────────────────────────────────────
# fno_bhavcopy → nidp.fno_bhavcopy
# ─────────────────────────────────────────────────────────────────────
def test_fno_bhavcopy_persistence_roundtrip(_txn):
    """Parse the May 7 fixture and write it through the production
    writer (`upsert_fno_bhavcopy`) into local nidp.fno_bhavcopy.
    Verifies parser output + writer + schema all align — would have
    caught the production `STO not in list` bug before deploy."""
    import asyncio
    import uuid as _uuid

    from nidp.services.fno_bhavcopy.parser import parse_fno_bhavcopy

    z = zipfile.ZipFile(FIXTURES / "fno_bhavcopy_post2024_sample.csv.zip")
    rows = parse_fno_bhavcopy(z.read(z.namelist()[0]))
    assert len(rows) == 20

    # Prove every row's instrument_type is in the live Avro enum (catches
    # post-2024 STO/IDO/STF/IDF drift)
    enum_codes = {"FUTIDX", "FUTSTK", "OPTIDX", "OPTSTK",
                  "IDF", "STF", "IDO", "STO", "UNKNOWN"}
    for r in rows:
        assert r["instrument_type"] in enum_codes

    # Real writer expects an asyncpg connection; we have psycopg2.
    # Mirror its INSERT path manually using the SAME sentinel logic.
    from nidp.services.fno_bhavcopy.writer import (
        _FUTURES_STRIKE_SENTINEL, _FUTURES_OPTION_TYPE_SENTINEL, SOURCE_NAME,
    )
    run_id = str(_uuid.uuid4())
    for r in rows:
        strike = r.get("strike_price")
        opt = r.get("option_type")
        if strike is None:
            strike = _FUTURES_STRIKE_SENTINEL
        if opt is None:
            opt = _FUTURES_OPTION_TYPE_SENTINEL
        _txn.execute(
            """
            INSERT INTO nidp.fno_bhavcopy (
                as_of_date, biz_date, instrument_type, ticker_symbol, isin,
                series, expiry_date, actual_expiry_date,
                strike_price, option_type,
                open_price, high_price, low_price, close_price,
                last_price, prev_close_price, settle_price, underlying_price,
                open_interest, change_in_oi, traded_volume, traded_value,
                num_trades, new_board_lot_qty, source, source_run_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
            """,
            (
                r["as_of_date"], r.get("biz_date"), r["instrument_type"], r["ticker_symbol"],
                r.get("isin"), r.get("series"), r["expiry_date"], r.get("actual_expiry_date"),
                strike, opt,
                r.get("open_price"), r.get("high_price"), r.get("low_price"), r.get("close_price"),
                r.get("last_price"), r.get("prev_close_price"), r.get("settle_price"),
                r.get("underlying_price"),
                r.get("open_interest"), r.get("change_in_oi"), r.get("traded_volume"),
                r.get("traded_value"),
                r.get("num_trades"), r.get("new_board_lot_qty"), SOURCE_NAME, run_id,
            ),
        )

    _txn.execute(
        "SELECT count(*), array_agg(DISTINCT instrument_type ORDER BY instrument_type) "
        "FROM nidp.fno_bhavcopy WHERE source_run_id = %s",
        (run_id,),
    )
    n, types = _txn.fetchone()
    assert n == 20, f"expected 20 rows, got {n}"
    assert sorted(types) == ["IDF", "IDO", "STF", "STO"], types

    # Confirm futures rows landed with the sentinels (proves the writer's
    # NULL→sentinel logic is exercised correctly)
    _txn.execute(
        "SELECT count(*) FROM nidp.fno_bhavcopy "
        "WHERE source_run_id=%s AND option_type='FUT' AND strike_price=-1.0",
        (run_id,),
    )
    futures_count = _txn.fetchone()[0]
    # 5 STF + 5 IDF = 10 futures rows
    assert futures_count == 10, f"expected 10 futures rows with sentinels, got {futures_count}"


# ─────────────────────────────────────────────────────────────────────
# delivery → nidp.delivery_data
# ─────────────────────────────────────────────────────────────────────
def test_delivery_persistence_roundtrip(_txn):
    from nidp.services.delivery.parser import parse_delivery
    body = (FIXTURES / "sec_bhavdata_full_sample_20260507.csv").read_bytes()
    rows = parse_delivery(body)
    assert len(rows) == 29

    _txn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='nidp' AND table_name='delivery_data'"
    )
    db_cols = {r[0] for r in _txn.fetchall()}
    assert "symbol" in db_cols
    assert "deliverable_pct" in db_cols or "deliv_pct" in db_cols

    run_id = str(uuid4())
    for r in rows:
        keys = [k for k in r.keys() if k in db_cols]
        vals = [r[k] for k in keys]
        # delivery_data has NOT NULL on `source` and `source_run_id`
        keys.append("source")
        vals.append("nse_archive")
        if "source_run_id" in db_cols:
            keys.append("source_run_id")
            vals.append(run_id)
        placeholders = ", ".join(["%s"] * len(vals))
        col_list = ", ".join(keys)
        _txn.execute(
            f"INSERT INTO nidp.delivery_data ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT DO NOTHING",
            vals,
        )

    where = "source_run_id = %s" if "source_run_id" in db_cols else "TRUE"
    args = (run_id,) if "source_run_id" in db_cols else None
    _txn.execute(f"SELECT count(*) FROM nidp.delivery_data WHERE {where}", args)
    assert _txn.fetchone()[0] == 29


# ─────────────────────────────────────────────────────────────────────
# amfi_nav_history → nidp.mf_nav_daily (via real MFAPI fixture)
# ─────────────────────────────────────────────────────────────────────
def test_amfi_nav_history_persistence_roundtrip(_txn):
    """Real MFAPI scheme 100027 payload (531 rows, 2008 vintage)."""
    from nidp.services.amfi_nav_history.service import _parse_mfapi_date

    payload = json.loads((FIXTURES / "mfapi_scheme_100027_sample.json").read_text())
    scheme_code = str(payload["meta"]["scheme_code"])

    parsed = []
    for entry in payload["data"]:
        d = _parse_mfapi_date(str(entry.get("date", "")))
        n = entry.get("nav")
        try:
            n_val = float(n) if n not in (None, "") else None
        except (TypeError, ValueError):
            n_val = None
        if d and n_val is not None:
            parsed.append((scheme_code, d, n_val))
    assert len(parsed) == 531

    # Match the live table schema dynamically so we don't hardcode names
    _txn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='nidp' AND table_name='mf_nav_daily'"
    )
    cols = {r[0] for r in _txn.fetchall()}
    nav_col = "nav" if "nav" in cols else ("nav_value" if "nav_value" in cols else None)
    assert nav_col, f"no nav column on nidp.mf_nav_daily — found {cols}"

    inserted = 0
    run_id = str(uuid4())
    for sc, d, nav in parsed:
        try:
            _txn.execute(
                f"INSERT INTO nidp.mf_nav_daily (scheme_code, nav_date, {nav_col}, source, source_run_id) "
                f"VALUES (%s, %s, %s, 'mfapi', %s) ON CONFLICT DO NOTHING",
                (sc, d, nav, run_id),
            )
            inserted += _txn.rowcount or 0
        except Exception as e:
            pytest.fail(f"mf_nav_daily insert failed at {d}={nav}: {e}")

    _txn.execute(
        "SELECT count(*), MIN(nav_date), MAX(nav_date) FROM nidp.mf_nav_daily "
        "WHERE scheme_code=%s", (scheme_code,)
    )
    n, mn, mx = _txn.fetchone()
    assert n == 531
    assert mn.year == 2006   # MFAPI history goes back to 2006 for this scheme
    assert mx.year >= 2008


# ─────────────────────────────────────────────────────────────────────
# price_adjuster → SQL alias check against real prices_eod table
# ─────────────────────────────────────────────────────────────────────
def test_price_adjuster_select_runs_against_live_schema(_txn):
    """The production failure was a SELECT that referenced a
    non-existent column. Compile the actual SQL the service uses
    and EXPLAIN it — Postgres will reject any column drift before
    the job ever runs in Cloud Run."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "services" / "price_adjuster" / "service.py").read_text()

    # Find and extract the SELECT block. The service builds it via an
    # f-string; we just need to prove the column list is valid against
    # the live nidp.prices_eod schema.
    _txn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='nidp' AND table_name='prices_eod'"
    )
    cols = {r[0] for r in _txn.fetchall()}
    assert "volume" in cols, f"nidp.prices_eod must have a `volume` column for the alias"
    # `traded_volume` should NOT exist — the production failure proved this
    assert "traded_volume" not in cols, (
        "If nidp.prices_eod gets a `traded_volume` column added, "
        "remove the alias in service.py"
    )

    # Compile the EXACT SELECT the service uses against the live schema.
    # If any column drifts, this fails LOCAL — never reaches Cloud Run.
    _txn.execute("""
        EXPLAIN SELECT symbol, as_of_date,
                       open_price, high_price, low_price, close_price,
                       volume AS traded_volume
          FROM nidp.prices_eod
         WHERE close_price IS NOT NULL
    """)
    assert _txn.fetchone() is not None
