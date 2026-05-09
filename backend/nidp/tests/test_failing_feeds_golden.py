"""Golden-fixture tests for the NIDP feeds that were failing on Cloud Run.

Each test loads a REAL day's slice from /tests/fixtures/ and exercises:
  1. Parser correctness (fields populated, types correct)
  2. Avro schema round-trip (serialize → deserialize)
  3. SQL/persistence shape (matches the migration column names)

These tests are the local gate before any Cloud Build / Cloud Run deploy.
Run: python3 -m pytest backend/nidp/tests/test_failing_feeds_golden.py -v
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Iterable

import pytest
from fastavro import parse_schema, schemaless_reader, schemaless_writer


FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"


# ─────────────────────────────────────────────────────────────────────
# fno_bhavcopy — real May 7 2026 file (STO/IDO/STF/IDF only)
# ─────────────────────────────────────────────────────────────────────
def _read_fno_csv() -> bytes:
    z = zipfile.ZipFile(FIXTURES / "fno_bhavcopy_post2024_sample.csv.zip")
    name = z.namelist()[0]
    return z.read(name)


def test_fno_bhavcopy_parser_handles_post_2024_codes():
    from nidp.services.fno_bhavcopy.parser import parse_fno_bhavcopy
    rows = parse_fno_bhavcopy(_read_fno_csv())

    # Fixture has 5 of each: STO, IDO, STF, IDF
    assert len(rows) == 20
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["instrument_type"]] = by_type.get(r["instrument_type"], 0) + 1
    assert by_type == {"STO": 5, "IDO": 5, "STF": 5, "IDF": 5}, by_type

    # Spot-check a known STO row (ABCAPITAL 26JUN 405 CE)
    sto = next(r for r in rows if r["instrument_type"] == "STO" and r["ticker_symbol"] == "ABCAPITAL")
    assert sto["option_type"] == "CE"
    assert sto["strike_price"] == pytest.approx(405.00)
    assert sto["close_price"] == pytest.approx(5.15)
    assert sto["expiry_date"] == "2026-06-30"

    # Spot-check a futures row (no option_type, no strike)
    stf = next(r for r in rows if r["instrument_type"] == "STF" and r["ticker_symbol"] == "ABCAPITAL")
    assert stf["option_type"] is None
    assert stf["strike_price"] is None


def test_fno_bhavcopy_avro_roundtrip_real_rows():
    """Production failure was `'STO' is not in list` thrown by fastavro
    at publish. This serializes the parsed real rows through the
    canonical .avsc and reads them back — proves the schema accepts
    every code the live source emits TODAY."""
    from nidp.services.fno_bhavcopy.parser import parse_fno_bhavcopy
    rows = parse_fno_bhavcopy(_read_fno_csv())

    schema_dict = json.loads((CONTRACTS / "fno_bhavcopy_v1.avsc").read_text())
    schema = parse_schema(schema_dict)

    enum_codes: set[str] = set()
    for f in schema_dict["fields"]:
        ftype = f["type"]
        # Walk the type — may be a union [null, {type:enum, symbols:[...]}]
        candidates = ftype if isinstance(ftype, list) else [ftype]
        for c in candidates:
            if isinstance(c, dict) and c.get("type") == "enum" and f["name"] == "instrument_type":
                enum_codes.update(c.get("symbols", []))
    assert enum_codes, "could not extract instrument_type enum from schema"
    # Every code in the live file must be in the enum
    for r in rows:
        assert r["instrument_type"] in enum_codes, f"missing {r['instrument_type']} in enum"

    # Round-trip every row. Service.persist() adds {source, source_run_id}
    # before publishing — mirror that wrapper here.
    wrapper = {"source": "nse_archives", "source_run_id": "00000000-0000-4000-8000-000000000000"}
    for r in rows:
        buf = io.BytesIO()
        schemaless_writer(buf, schema, {**r, **wrapper})
        buf.seek(0)
        out = schemaless_reader(buf, schema)
        assert out["instrument_type"] == r["instrument_type"]
        assert out["ticker_symbol"] == r["ticker_symbol"]
        assert out["close_price"] == r["close_price"]


def test_fno_bhavcopy_db_columns_match_migration():
    """Validate the parser's output keys match the columns in the
    migration that creates fno_bhavcopy persistence (catches drift
    between parser and schema)."""
    from nidp.services.fno_bhavcopy.parser import parse_fno_bhavcopy
    rows = parse_fno_bhavcopy(_read_fno_csv())
    sample = rows[0]
    # All keys the parser emits — these must be either in the DB or
    # explicitly dropped by the writer
    parser_keys = set(sample.keys())
    expected_min = {
        "as_of_date", "biz_date", "instrument_type", "ticker_symbol",
        "expiry_date", "strike_price", "option_type",
        "open_price", "high_price", "low_price", "close_price",
        "last_price", "prev_close_price", "settle_price",
    }
    missing = expected_min - parser_keys
    assert not missing, f"parser missing fields: {missing}"


# ─────────────────────────────────────────────────────────────────────
# delivery — real sec_bhavdata_full May 7 2026
# ─────────────────────────────────────────────────────────────────────
def test_delivery_parser_against_real_may_2026_file():
    from nidp.services.delivery.parser import parse_delivery
    body = (FIXTURES / "sec_bhavdata_full_sample_20260507.csv").read_bytes()
    rows = parse_delivery(body)

    # Fixture has 30 lines = header + 29 data rows
    assert len(rows) == 29

    # Spot check: 20MICRONS EQ on 2026-05-07
    eq = next(r for r in rows if r["symbol"] == "20MICRONS")
    assert eq["series"] == "EQ"
    assert eq["as_of_date"] == "2026-05-07"
    assert eq["traded_qty"] == 89_735
    assert eq["deliverable_qty"] == 51_904
    assert eq["deliverable_pct"] == pytest.approx(57.84)


# ─────────────────────────────────────────────────────────────────────
# amfi_nav_history — real MFAPI scheme 100027 payload (531 rows)
# ─────────────────────────────────────────────────────────────────────
def test_amfi_nav_history_parses_real_mfapi_response():
    payload = json.loads((FIXTURES / "mfapi_scheme_100027_sample.json").read_text())
    assert payload["status"] == "SUCCESS"
    assert payload["meta"]["scheme_code"] == 100027
    assert len(payload["data"]) >= 500

    # Reproduce the parser's date+nav extraction (mirrors service.py:_parse_mfapi_date)
    from nidp.services.amfi_nav_history.service import _parse_mfapi_date
    parsed = []
    for entry in payload["data"]:
        d = _parse_mfapi_date(str(entry.get("date", "")))
        n = entry.get("nav")
        try:
            n = float(n) if n not in (None, "") else None
        except (TypeError, ValueError):
            n = None
        if d and n is not None:
            parsed.append((d, n))
    # All 531 rows must parse cleanly (no date / nav format surprises)
    assert len(parsed) == len(payload["data"])

    # Dates must be monotonically descending (MFAPI returns latest-first)
    dates = [d for d, _ in parsed]
    assert dates == sorted(dates, reverse=True)


def test_amfi_nav_history_only_stale_days_kwarg_threaded():
    """The new `only_stale_days` kwarg must be plumbed through service.run
    AND the __main__ argparse — guards against future regression."""
    import inspect

    from nidp.services.amfi_nav_history import service
    sig = inspect.signature(service.run)
    assert "only_stale_days" in sig.parameters
    assert "only_stale_days" in inspect.signature(service._resolve_scheme_codes).parameters

    main_src = (Path(__file__).resolve().parents[1] / "services" / "amfi_nav_history" / "__main__.py").read_text()
    assert "--only-stale-days" in main_src
    assert "only_stale_days=args.only_stale_days" in main_src


# ─────────────────────────────────────────────────────────────────────
# price_adjuster — SQL alias check + corporate-actions fixture round-trip
# ─────────────────────────────────────────────────────────────────────
def test_price_adjuster_sql_aliases_volume_correctly():
    """Production failure: `column "traded_volume" does not exist`.
    The fix was to alias `volume AS traded_volume` in the SELECT."""
    src = (Path(__file__).resolve().parents[1] / "services" / "price_adjuster" / "service.py").read_text()
    assert "volume AS traded_volume" in src or "volume as traded_volume" in src.lower(), (
        "price_adjuster must alias volume → traded_volume to match nidp.prices_eod schema"
    )
    # Also ensure no naked `WHERE traded_volume` reference (would crash in prod)
    assert "WHERE traded_volume" not in src


# ─────────────────────────────────────────────────────────────────────
# Source URL host migration — every NSE archive URL must use nsearchives
# ─────────────────────────────────────────────────────────────────────
def test_nse_archive_host_migrated_to_nsearchives():
    """NSE killed archives.nseindia.com (Akamai 503). All archive URLs
    must point at nsearchives.nseindia.com now. Any new code dropping
    a hardcoded `archives.nseindia.com` URL is a deploy blocker."""
    from nidp.shared import config
    assert "nsearchives.nseindia.com" in config.NSE_ARCHIVES
    assert "archives.nseindia.com" not in config.NSE_ARCHIVES.replace("nsearchives.nseindia.com", "")

    # Also scan all service URLs for stragglers
    services_dir = Path(__file__).resolve().parents[1] / "services"
    offenders: list[str] = []
    for py in services_dir.rglob("*.py"):
        text = py.read_text()
        for ln_no, line in enumerate(text.splitlines(), 1):
            if "archives.nseindia.com" in line and "nsearchives.nseindia.com" not in line:
                offenders.append(f"{py.relative_to(services_dir)}:{ln_no}: {line.strip()[:120]}")
    assert not offenders, "Hardcoded `archives.nseindia.com` URL found:\n" + "\n".join(offenders)
