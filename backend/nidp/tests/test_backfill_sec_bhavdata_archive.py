"""Row builder for the one-off sec_bhavdata_full archive backfill (Ten-Percent Days 3.0, W1).

The loader itself is SQL (`backfill_sec_bhavdata_archive.sql`); these tests pin what goes into its CSVs.
"""
import importlib.util
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "vm" / "backfill_sec_bhavdata_archive.py"

HEADER = ("SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, "
          "AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER")


def _mod():
    spec = importlib.util.spec_from_file_location("backfill_sec_bhavdata_archive", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _file(tmp_path, name, *rows):
    p = tmp_path / name
    p.write_text("\n".join([HEADER, *rows]) + "\n")
    return p


ACME_31MAY = "ACME, EQ, 31-May-2024, 100.00, 101.00, 105.50, 99.00, 104.00, 104.10, 102.37, 1000, 7.12, 50, 600, 60.00"
BOND_31MAY = "1018GS2026, GS, 31-May-2024, 114.98, 117.00, 117.00, 114.99, 115.00, 115.00, 115.06, 6185, 7.12, 6, -, -"
ACME_03JUN = "ACME, EQ, 03-Jun-2024, 104.10, 104.00, 106.00, 103.00, 105.00, 105.20, 104.90, 2000, 21.00, 70, 900, 45.00"


def test_session_date_comes_from_date1_not_the_filename(tmp_path):
    """NSE holiday URLs serve the previous session's file (02-Jun-2024 holds 31-May-2024)."""
    m = _mod()
    recs = m.read_archive([_file(tmp_path, "sec_bhavdata_full_02062024.csv", ACME_31MAY)])
    assert set(recs) == {(date(2024, 5, 31), "ACME", "EQ")}


def test_identical_duplicate_files_are_collapsed(tmp_path):
    m = _mod()
    a = _file(tmp_path, "sec_bhavdata_full_31052024.csv", ACME_31MAY)
    b = _file(tmp_path, "sec_bhavdata_full_02062024.csv", ACME_31MAY)
    assert len(m.read_archive([a, b])) == 1


def test_conflicting_duplicate_refuses(tmp_path):
    m = _mod()
    a = _file(tmp_path, "sec_bhavdata_full_31052024.csv", ACME_31MAY)
    b = _file(tmp_path, "sec_bhavdata_full_02062024.csv", ACME_31MAY.replace("104.10, 102.37", "104.20, 102.37"))
    with pytest.raises(ValueError, match="conflicting"):
        m.read_archive([a, b])


def test_price_row_mapping_is_exact(tmp_path):
    m = _mod()
    recs = m.read_archive([_file(tmp_path, "f.csv", ACME_31MAY)])
    (row,) = m.price_rows(recs, before=date(2025, 1, 1))
    assert row == {
        "as_of_date": "2024-05-31", "symbol": "ACME", "series": "EQ", "isin": None,
        "prev_close": Decimal("100.00"), "open_price": Decimal("101.00"), "high_price": Decimal("105.50"),
        "low_price": Decimal("99.00"), "close_price": Decimal("104.10"), "last_price": Decimal("104.00"),
        "avg_price": Decimal("102.37"), "volume": 1000, "turnover": Decimal("712000.00"), "trades": 50,
        "deliv_qty": 600, "deliv_pct": Decimal("60.00"), "source": "NSE_SEC_BHAVDATA",
    }


def test_missing_delivery_is_null_and_non_eq_series_are_kept(tmp_path):
    """prices_eod holds every series (the bhavcopy writer loads them all), so the backfill must too."""
    m = _mod()
    recs = m.read_archive([_file(tmp_path, "f.csv", BOND_31MAY)])
    (row,) = m.price_rows(recs, before=date(2025, 1, 1))
    assert row["series"] == "GS" and row["deliv_qty"] is None and row["deliv_pct"] is None


def test_price_rows_stop_before_the_existing_data(tmp_path):
    m = _mod()
    recs = m.read_archive([_file(tmp_path, "f.csv", ACME_31MAY, ACME_03JUN)])
    assert [r["as_of_date"] for r in m.price_rows(recs, before=date(2024, 6, 3))] == ["2024-05-31"]


def test_delivery_rows_can_target_a_window_for_gap_fills(tmp_path):
    m = _mod()
    f = _file(tmp_path, "f.csv", ACME_31MAY, ACME_03JUN)
    rows = m.delivery_rows([f], before=date(2025, 1, 1), since=date(2024, 6, 1))
    assert [r["as_of_date"] for r in rows] == ["2024-06-03"]


def test_delivery_rows_reuse_the_delivery_parser_and_cutoff(tmp_path):
    m = _mod()
    f = _file(tmp_path, "f.csv", ACME_31MAY, BOND_31MAY, ACME_03JUN)
    rows = m.delivery_rows([f, f], before=date(2024, 6, 3))
    assert rows == [
        {"as_of_date": "2024-05-31", "symbol": "1018GS2026", "series": "GS", "traded_qty": 6185,
         "deliverable_qty": None, "deliverable_pct": None, "source": "NSE_SEC_BHAVDATA"},
        {"as_of_date": "2024-05-31", "symbol": "ACME", "series": "EQ", "traded_qty": 1000,
         "deliverable_qty": 600, "deliverable_pct": 60.0, "source": "NSE_SEC_BHAVDATA"},
    ]
