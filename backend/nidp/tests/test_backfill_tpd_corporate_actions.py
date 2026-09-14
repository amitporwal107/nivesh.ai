"""Builder for the model-only corporate-actions history (Ten-Percent Days 3.0, W1b).

Rows go to nidp.tpd_corporate_actions_history, never nidp.corporate_actions: price_adjuster rewrites the full
adjusted history of any symbol with a newly ingested action, which would change prod 1y metrics.
"""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "vm" / "backfill_tpd_corporate_actions.py"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "148_tpd_corporate_actions_history.sql"


def _mod():
    spec = importlib.util.spec_from_file_location("backfill_tpd_corporate_actions", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _entry(symbol, subject, ex, series="EQ"):
    return {"symbol": symbol, "series": series, "subject": subject, "exDate": ex, "recDate": ex,
            "bcStartDate": "-", "bcEndDate": "-", "ndStartDate": "-", "ndEndDate": "-", "faceVal": "10",
            "caBroadcastDate": None, "comp": symbol + " LTD", "isin": "INE000000000", "ind": "-"}


def _month(tmp_path, name, *entries):
    p = tmp_path / name
    p.write_text(json.dumps(list(entries)))
    return p


def test_archive_json_goes_through_the_production_classifier(tmp_path):
    m = _mod()
    f = _month(tmp_path, "ca_202406.json",
               _entry("ACME", "Bonus 1:1", "10-Jun-2024"),
               _entry("BETA", "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share",
                      "12-Jun-2024"),
               _entry("GAMA", "Interim Dividend - Rs 5 Per Share", "14-Jun-2024"))
    rows = {r["symbol"]: r for r in m.build_rows([f])}
    assert rows["ACME"]["action_type"] == "BONUS" and rows["ACME"]["ratio"] == "1:1"
    assert rows["BETA"]["action_type"] == "SPLIT"
    assert rows["GAMA"]["action_type"] == "DIVIDEND" and float(rows["GAMA"]["dividend_amount"]) == 5.0
    assert {r["source"] for r in rows.values()} == {"NSE_CA_ARCHIVE"}
    assert rows["ACME"]["ex_date"] == "2024-06-10"  # the production parser emits ISO strings


def test_primary_key_duplicates_across_files_keep_one_row(tmp_path):
    m = _mod()
    a = _month(tmp_path, "ca_202406.json", _entry("ACME", "Bonus 1:1", "10-Jun-2024"))
    b = _month(tmp_path, "ca_202407.json", _entry("ACME", "Bonus 1:1", "10-Jun-2024"))
    assert len(m.build_rows([a, b])) == 1


def test_two_dividends_on_one_ex_date_are_summed_not_dropped(tmp_path):
    """NESTLEIND 2024-07-16 paid Rs 8.50 + Rs 2.75 interim; the shared table's key keeps only one."""
    m = _mod()
    f = _month(tmp_path, "ca_202407.json",
               _entry("NESTLEIND", "Dividend - Rs 8.50 Per Share", "16-Jul-2024"),
               _entry("NESTLEIND", "Interim Dividend - Rs 2.75 Per Share", "16-Jul-2024"))
    (row,) = m.build_rows([f])
    assert float(row["dividend_amount"]) == pytest.approx(11.25)
    assert row["purpose"] == "Dividend - Rs 8.50 Per Share + Interim Dividend - Rs 2.75 Per Share"
    assert row["action_subtype"] is None


def test_other_same_day_actions_keep_both_purposes_and_null_disagreeing_fields(tmp_path):
    m = _mod()
    f = _month(tmp_path, "ca_202608.json",
               _entry("SIYSIL", "Scheme Of Arrangement - Bonus Ncrps 4:1", "21-Aug-2026"),
               _entry("SIYSIL", "Scheme Of Arrangement - Bonus Ncrps 3:1", "21-Aug-2026"))
    (row,) = m.build_rows([f])
    assert "4:1" in row["purpose"] and "3:1" in row["purpose"]


def test_conflicting_split_or_bonus_refuses(tmp_path):
    """These drive price adjustment; never guess between two ratios."""
    m = _mod()
    a = _month(tmp_path, "ca_202406.json", _entry("ACME", "Bonus 1:1", "10-Jun-2024"))
    b = _month(tmp_path, "ca_202407.json", _entry("ACME", "Bonus 2:1", "10-Jun-2024"))
    with pytest.raises(ValueError, match="conflicting"):
        m.build_rows([a, b])


def test_migration_creates_only_the_model_table():
    sql = MIGRATION.read_text()
    assert "CREATE TABLE IF NOT EXISTS nidp.tpd_corporate_actions_history" in sql
    assert "nidp.corporate_actions " not in sql.replace("nidp.corporate_actions_", "")
    assert "PRIMARY KEY (symbol, action_type, ex_date, source)" in sql
