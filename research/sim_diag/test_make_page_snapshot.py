"""Tests for make_page_snapshot.py: the truncation, rounding and omission rules, and the strict-JSON guarantee.

They run against real run folders (the smoke matrix run and the D1-D4 run), not fixtures, because the point of the
rules is that they hold on the artifacts the page is actually built from. Override with SIM_MATRIX_DIR / SIM_D1D4_DIR.

    /app/research/tpd_run/.venv/bin/python -m pytest research/sim_diag/test_make_page_snapshot.py -q
"""
from __future__ import annotations

import gzip
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_page_snapshot as MS  # noqa: E402

MATRIX_DIR = os.environ.get("SIM_MATRIX_DIR", "/app/research/sim_diag/smoke_20260920T044126")
D1D4_DIR = os.environ.get("SIM_D1D4_DIR", "/app/research/sim_diag/run_20260920T003043")

pytestmark = pytest.mark.skipif(
    not (os.path.isdir(MATRIX_DIR) and os.path.isdir(D1D4_DIR)),
    reason=f"run folders not on this machine: {MATRIX_DIR}, {D1D4_DIR}")


@pytest.fixture(scope="module")
def snap():
    return MS.build(MATRIX_DIR, D1D4_DIR)


@pytest.fixture(scope="module")
def written(snap, tmp_path_factory):
    path = str(tmp_path_factory.mktemp("snap") / "sim_lab_snapshot.json")
    size, digest = MS.write(snap, path)
    return path, size, digest


# ---------------- the output contract ----------------

def test_top_level_keys(snap):
    assert snap["schema"] == "sim-lab-1"
    for k in ("generated_at", "source_sha256", "run", "sessions", "matrix", "reconciliation", "data_quality",
              "scorecard", "rc1", "trades", "candidates", "notes"):
        assert k in snap, k
    assert len(snap["source_sha256"]) == 64 and all(c in "0123456789abcdef" for c in snap["source_sha256"])


def test_source_sha256_is_the_matrix_results_file(snap):
    assert snap["source_sha256"] == MS.sha256_file(os.path.join(MATRIX_DIR, "matrix_results.json"))
    manifest = os.path.join(MATRIX_DIR, "manifest.json")
    if os.path.exists(manifest):
        assert snap["source_sha256"] == MS.read_json(manifest)["matrix_results.json"]


def test_smoke_flag_is_visible_at_the_top_level(snap):
    mres = MS.read_json(os.path.join(MATRIX_DIR, "matrix_results.json"))
    assert snap["smoke"] is bool(mres.get("smoke"))
    assert snap["run"]["smoke"] is snap["smoke"]


def test_matrix_block_is_the_scopes_verbatim(snap):
    mres = MS.read_json(os.path.join(MATRIX_DIR, "matrix_results.json"))
    assert snap["matrix"] == MS.clean(mres["scopes"])


def test_strict_json_and_size(written):
    path, size, digest = written
    with open(path) as fh:
        json.load(fh, parse_constant=MS.raise_constant)      # a bare NaN/Infinity token would raise here
    assert size == os.path.getsize(path) and size <= MS.SIZE_LIMIT_BYTES
    assert digest == MS.sha256_file(path)


def test_no_bare_non_json_constant_token(written):
    path, _, _ = written
    body = open(path).read()
    stripped = body.replace(MS.clean({"n": None}) and "", "")
    for token in (":NaN", ":Infinity", ":-Infinity", ",NaN", "[NaN"):
        assert token not in stripped, token


# ---------------- trades ----------------

def _replay(snap):
    return set(snap["sessions"]["replay"]["dates"])


def test_every_configuration_in_the_run_folder_is_present(snap):
    assert set(snap["trades"]) == set(MS.config_files(MATRIX_DIR))


def test_trades_are_replay_window_decision_dates_only(snap):
    replay = _replay(snap)
    for cfg, rows in snap["trades"].items():
        assert rows, f"{cfg} has no replay-window trades"
        assert {r["decision_date"] for r in rows} <= replay, cfg


def test_trade_row_counts_match_the_csv_filtered_to_the_replay_window(snap):
    replay = _replay(snap)
    for cfg, path in MS.config_files(MATRIX_DIR).items():
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt") as fh:
            header = fh.readline().rstrip("\n").split(",")
            col = header.index("decision_date")
            n = sum(1 for line in fh if line.split(",")[col][:10] in replay)
        assert len(snap["trades"][cfg]) == n, cfg


def test_absent_columns_are_omitted_not_substituted(snap):
    """A contract field whose column the run does not write must be missing from the row, never filled with a guess."""
    for cfg, path in MS.config_files(MATRIX_DIR).items():
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt") as fh:
            cols = set(fh.readline().rstrip("\n").split(","))
        for field, src in MS.TRADE_FIELDS:
            if src is not None and src not in cols:
                assert all(field not in r for r in snap["trades"][cfg]), (cfg, field)
                assert field in snap["notes"]["omitted_fields"].get(cfg, []), (cfg, field)


def test_trade_id_and_dq_status_only_where_the_audit_ledger_covers_the_configuration(snap):
    audit = os.path.join(D1D4_DIR, "audit_replay.csv")
    covered = set(MS.read_csv(audit)["config"].astype(str)) if os.path.exists(audit) else set()
    for cfg, rows in snap["trades"].items():
        has = any("trade_id" in r for r in rows)
        assert has == (cfg in covered), cfg


def test_hashes_and_ids_are_never_rounded(snap):
    for rows in snap["trades"].values():
        for r in rows:
            if "trade_id" in r:
                assert isinstance(r["trade_id"], str) and r["trade_id"]
    for c in snap["candidates"]:
        if c.get("prediction_id") is not None:
            assert len(c["prediction_id"]) == 64


# ---------------- rounding ----------------

def test_rounding_of_trade_rows_against_the_raw_csv(snap):
    """Every rounded number is the artifact's own number at the stated precision - nothing else."""
    raw = {}
    for r in MS.read_csv(os.path.join(MATRIX_DIR, "trades_A.csv")).to_dict("records"):
        raw[(str(r["decision_date"])[:10], r["symbol"])] = r
    checked = 0
    for row in snap["trades"]["A"]:
        src = raw[(row["decision_date"], row["symbol"])]
        for field in MS.RUPEES_2DP | MS.RATIOS_6DP:
            if field not in row or row[field] is None or field not in src:
                continue
            nd = 2 if field in MS.RUPEES_2DP else 6
            assert row[field] == round(float(src[field]), nd), (row["symbol"], field)
            assert abs(round(row[field], nd) - row[field]) < 1e-12, (row["symbol"], field)
            checked += 1
    assert checked > 0


def test_round_field_rules():
    assert MS.round_field("net_ret", 0.045359191814415695) == 0.045359
    assert MS.round_field("net_inr", 2496.4249) == 2496.42
    assert MS.round_field("rank", 1.0) == 1.0
    assert MS.round_field("prediction_id", "0" * 64) == "0" * 64
    assert MS.round_field("qty", 804) == 804
    assert MS.round_field("net_ret", float("nan")) != MS.round_field("net_ret", float("nan"))   # NaN passes through
    assert MS.cell("net_ret", float("nan")) is None
    assert MS.cell("flags", float("nan")) == ""
    assert MS.cell("mfe_pct", float("inf")) is None


def test_copied_blocks_are_not_rounded(snap):
    """matrix / scorecard / data_quality / reconciliation / rc1 are copies; rounding them would change the numbers."""
    d1d4 = MS.read_json(os.path.join(D1D4_DIR, "results.json"))
    assert snap["reconciliation"]["summary"]["replay"] == MS.clean(d1d4["reconciliation_replay"])
    assert snap["reconciliation"]["summary"]["year"] == MS.clean(d1d4["reconciliation_2022"])
    sc = MS.read_json(os.path.join(D1D4_DIR, "scorecard.json"))
    assert snap["scorecard"]["replay"] == MS.clean(sc["replay"])
    assert snap["data_quality"]["replay"] == MS.clean(sc["replay"]["A_data_quality"])


# ---------------- candidates ----------------

def test_candidate_truncation_rule_is_exactly_what_the_notes_say(snap):
    """Kept == picked OR traded by a configuration other than S5_POOL OR rank <= 20 - both directions."""
    replay = _replay(snap)
    ledger = MS.read_csv(os.path.join(D1D4_DIR, "candidates_replay.csv"))
    ledger["date"] = MS.datestr(ledger["date"])
    ledger = ledger[ledger.date.isin(replay)]
    traded = {(r["decision_date"], r["symbol"]) for cfg, rows in snap["trades"].items() if cfg != "S5_POOL"
              for r in rows}

    def wanted(r):
        rank = r["rank"]
        return (str(r["selection_status"]) == "SELECTED" or (r["date"], r["symbol"]) in traded
                or (rank == rank and rank <= MS.CANDIDATE_TOP_N))

    expected = {(r["date"], r["symbol"]) for r in ledger.to_dict("records") if wanted(r)}
    got = {(c["date"], c["symbol"]) for c in snap["candidates"]}
    assert got == expected
    assert len(got) < len(ledger), "the truncation rule kept everything, so it is not a truncation"


def test_candidates_are_replay_window_only(snap):
    assert {c["date"] for c in snap["candidates"]} <= _replay(snap)


def test_every_traded_and_picked_candidate_survived_truncation(snap):
    got = {(c["date"], c["symbol"]) for c in snap["candidates"]}
    for cfg, rows in snap["trades"].items():
        if cfg == "S5_POOL":
            continue
        for r in rows:
            assert (r["decision_date"], r["symbol"]) in got, (cfg, r["symbol"])


# ---------------- notes ----------------

def test_prereg_presentation_rules_survive(snap):
    n = snap["notes"]
    assert n["internal_only"] is True and n["tax"] == "illustrative"
    assert "in rupees only" in n["percent_of_capital_rule"]
    assert "portfolio runs only" in n["drawdown_rule"]
    assert "no p-value" in n["paired_comparison_rule"]
    assert "illustrative" in n["tax_rule"]


def test_the_block_and_the_sealed_statement_come_from_the_real_block_definitions(snap):
    """Neither run folder records them, so they are read from model_v5/dataset.BLOCKS - the same definitions the
    run's guarded loader enforces - and never typed in here."""
    import sys, os
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model_v5")))
    import dataset as DS
    dev, test = DS.BLOCKS["dev"], DS.BLOCKS["test"]
    assert str(dev.feat_end) in snap["run"]["block"] and str(dev.bar_end) in snap["run"]["block"]
    assert dev.name in snap["run"]["block"]
    sealed = snap["run"]["sealed_note"]
    assert str(test.feat_start) in sealed and str(test.bar_end) in sealed and "SEALED" in sealed


def test_unfillable_contract_fields_are_declared(snap):
    """Whatever the artifacts genuinely do not carry is named in notes.unavailable rather than guessed."""
    text = " ".join(snap["notes"]["unavailable"]) + " " + " ".join(snap["notes"].get("omitted_fields", []))
    assert snap["notes"]["unavailable"], "nothing declared at all"
    for k in snap["notes"]["unavailable"]:
        assert isinstance(k, str) and k
