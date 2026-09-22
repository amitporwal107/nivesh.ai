"""Synthetic-only: the sealed ETF list (no header row) is loaded correctly and
load_universe_bars drops every ETF symbol before breadth ever sees it."""
import gzip

import pandas as pd

from research.index_history.breadth import load_etf_symbols, load_universe_bars

RAW_HEADER = "symbol,instrument_token,date,open,high,low,close,volume,source_version\n"


def _write_gz(path, rows):
    with gzip.open(path, "wt") as fh:
        fh.write(RAW_HEADER)
        fh.writelines(rows)


def test_load_etf_symbols_has_no_header_row(tmp_path):
    p = tmp_path / "etfs.csv"
    p.write_text("ABGSEC\nABSLBANETF\nNIFTYBEES\n")
    symbols = load_etf_symbols(p)
    assert symbols == {"ABGSEC", "ABSLBANETF", "NIFTYBEES"}
    # every line, including the first, is a real symbol (no header consumed)
    assert len(symbols) == 3


def test_load_universe_bars_drops_etf_symbols(tmp_path):
    part = tmp_path / "part-1.csv.gz"
    _write_gz(part, [
        "ACME,111,2024-08-01,10,11,9,10.5,1000,kite-connect-v3\n",
        "NIFTYBEES,222,2024-08-01,100,101,99,100.5,500,kite-connect-v3\n",
        "BETAINC,333,2024-08-01,20,21,19,20.5,2000,kite-connect-v3\n",
    ])
    etf_symbols = {"NIFTYBEES"}

    bars = load_universe_bars(str(tmp_path / "part-*.csv.gz"), etf_symbols)

    assert set(bars["symbol"]) == {"ACME", "BETAINC"}
    assert "NIFTYBEES" not in set(bars["symbol"])


def test_load_universe_bars_handles_header_only_parts(tmp_path):
    good = tmp_path / "part-1.csv.gz"
    _write_gz(good, ["ACME,111,2024-08-01,10,11,9,10.5,1000,kite-connect-v3\n"])
    empty = tmp_path / "part-2.csv.gz"
    _write_gz(empty, [])  # header-only, like some real parts in day_2021/

    bars = load_universe_bars(str(tmp_path / "part-*.csv.gz"), set())

    assert len(bars) == 1
    assert bars.iloc[0]["symbol"] == "ACME"


def test_load_universe_bars_dedupes_symbol_date_across_parts(tmp_path):
    p1 = tmp_path / "part-1.csv.gz"
    _write_gz(p1, ["ACME,111,2024-08-01,10,11,9,10.5,1000,kite-connect-v3\n"])
    p2 = tmp_path / "part-2.csv.gz"
    _write_gz(p2, ["ACME,111,2024-08-01,10,11,9,999,1000,kite-connect-v3\n"])  # duplicate date

    bars = load_universe_bars(str(tmp_path / "part-*.csv.gz"), set())

    assert len(bars) == 1  # kept the first occurrence, not both
