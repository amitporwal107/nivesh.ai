"""Unit tests for the migration runner's discovery + bookkeeping logic.

These tests don't require a live Postgres — they exercise the bits that can
fail at code-review time (filename parsing, sha-256, ordering, drift check).
The DB-backed integration test lives in tests/integration/.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from portfolio_ingestion.db.migrations import runner


def test_discover_finds_001_and_orders_by_version(tmp_path: Path) -> None:
    # Drop in three valid files, out of name-order, plus a junk file.
    (tmp_path / "003_third.sql").write_text("SELECT 3;")
    (tmp_path / "001_first.sql").write_text("SELECT 1;")
    (tmp_path / "002_second.sql").write_text("SELECT 2;")
    (tmp_path / "README.md").write_text("# not a migration")
    (tmp_path / "no_prefix.sql").write_text("SELECT 'ignored';")

    migs = runner.discover_migrations(tmp_path)
    assert [m.filename for m in migs] == [
        "001_first.sql",
        "002_second.sql",
        "003_third.sql",
    ]
    assert [m.version for m in migs] == [1, 2, 3]


def test_discover_computes_sha256_of_file_bytes(tmp_path: Path) -> None:
    body = b"CREATE TABLE foo (id INT);\n"
    (tmp_path / "001_x.sql").write_bytes(body)
    [mig] = runner.discover_migrations(tmp_path)
    assert mig.sha256 == hashlib.sha256(body).hexdigest()


def test_filename_regex_rejects_uppercase_and_spaces(tmp_path: Path) -> None:
    (tmp_path / "001_OK.sql").write_text("-- has uppercase, ignored")
    (tmp_path / "001 with space.sql").write_text("-- has space, ignored")
    (tmp_path / "001_good_name.sql").write_text("-- ok")
    [mig] = runner.discover_migrations(tmp_path)
    assert mig.filename == "001_good_name.sql"


def test_packaged_001_init_schema_is_discoverable() -> None:
    migs = runner.discover_migrations()
    names = [m.filename for m in migs]
    assert "001_init_schema.sql" in names


def test_packaged_001_init_schema_has_invariant_index() -> None:
    """If the partial unique index disappears, we lose the core PRD invariant."""
    path = Path(runner.MIGRATIONS_DIR) / "001_init_schema.sql"
    body = path.read_text()
    assert "one_active_snapshot_per_pan" in body
    assert "WHERE is_active = true" in body


def test_packaged_001_init_schema_has_pan_checksum_unique() -> None:
    """Job idempotency relies on this unique constraint."""
    path = Path(runner.MIGRATIONS_DIR) / "001_init_schema.sql"
    body = path.read_text()
    assert "UNIQUE (pan_hash, checksum)" in body


def test_main_returns_2_when_postgres_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI exits non-zero with a clear log when config is missing."""
    monkeypatch.delenv("PI_POSTGRES_URL", raising=False)
    from portfolio_ingestion.config import reset_settings_for_test

    reset_settings_for_test()
    rc = runner.main(["up"])
    assert rc == 2
