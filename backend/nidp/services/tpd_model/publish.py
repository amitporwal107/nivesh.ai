"""Publish a frozen, counted snapshot to nidp_staging for the Research page's Move odds screen (migration 149).

    python -m nidp.services.tpd_model.publish run     --snapshot <root>/<D> --exports <dir> --events-db <sqlite> [--apply]
    python -m nidp.services.tpd_model.publish grades  --root <snapshots_v4> [--apply]
    python -m nidp.services.tpd_model.publish record  --model v4 --verdict <early_window_v4_verdict.json> --window "Jan–Aug 2025" [--apply]
    python -m nidp.services.tpd_model.publish refusal --model v4 --target YYYY-MM-DD --reason stale_data --detail '{...}' [--apply]

Every command emits one psql script: a single transaction, insert-only, idempotent (runs are keyed on the manifest's
hash; child rows on their primary keys). Without --apply the script is only printed or saved (--out), so a dry run
never touches a database. --apply pipes it to psql inside the staging Postgres container.

Only verified snapshots that count toward their forward test are publishable: a tampered, rehearsal or preview
snapshot is refused, so the page can only ever show numbers that were frozen before the open and graded honestly.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import math
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from .event_gate import IST
from .forward import verify

logger = logging.getLogger(__name__)
CONTAINER = "nidp-postgres-staging"
PSQL = ["psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", "nidp_staging", "-d", "nidp_staging"]
HEADS = ("p_up5_1d", "p_down5_1d", "p_up10_1d", "p_down10_1d")
INPUT_KEYS = ("close_change_pct", "day_range_pct", "volume_vs_20d_median", "delivery_pct", "change_5_sessions_pct", "atr14_pct")
EVENT_WINDOW_DAYS = 5
SOURCE_LABELS = {
    "nse_announcements_api": "NSE filing", "nse_announcements_rss": "NSE filing", "nse_board_meetings_rss": "NSE board meeting",
    "nse_corporate_actions_rss": "NSE corporate action", "bse_subcat_api": "BSE filing", "bse_announcements_rss": "BSE filing",
    "rbi_press": "RBI", "rbi_notifications": "RBI", "sebi_rss": "SEBI", "sebi_press": "SEBI", "cci_combination_press": "CCI", "cci_combination_orders": "CCI",
    "pib": "PIB", "nhai_press_release": "NHAI", "nhai_tenders": "NHAI tenders", "nhai_news": "NHAI press clippings", "cppp_tenders": "CPPP tenders",
    "cppp_corrigendums": "CPPP corrigenda", "mod": "Ministry of Defence", "mnre": "MNRE", "heavy_industries": "Ministry of Heavy Industries",
    "ibbi": "IBBI", "nclt": "NCLT", "cdsco_alerts": "CDSCO", "cdsco_notices": "CDSCO", "openfda_drug_enforcement": "US FDA", "openfda_device_enforcement": "US FDA",
    "fda_recalls_rss": "US FDA", "fda_press_rss": "US FDA", "fda_warning_letters": "US FDA", "sec_edgar_6k": "US SEC", "icra": "ICRA", "gleif_press": "GLEIF", "gleif_news": "GLEIF",
    "et_stocks": "Economic Times", "bs_companies": "Business Standard", "bs_markets": "Business Standard", "mint_companies": "Mint", "mint_markets": "Mint",
    "cnbc_market": "CNBC-TV18", "reuters": "Reuters", "moneycontrol": "Moneycontrol",
}
# Third-party journalism: its headline can carry advice language the page must not render (spec D2), so only the
# source, time and classified type are published. NHAI's "news" feed is newspaper clippings, so it counts as media.
MEDIA_SOURCES = frozenset({"et_stocks", "bs_companies", "bs_markets", "mint_companies", "mint_markets", "cnbc_market", "reuters", "moneycontrol", "nhai_news"})
NOT_LISTED_TYPES = frozenset({"UNCLASSIFIED", "ROUTINE"})


class PublishRefused(RuntimeError):
    pass


def manifest_sha(snap: Path) -> str:
    return (Path(snap) / "manifest.sha256").read_text().strip()


def load_publishable(snap: Path) -> tuple[dict, pd.DataFrame, set[str]]:
    """(manifest, predictions, symbols with a results filing in the print window). Raises TamperError or PublishRefused."""
    manifest = verify(snap)
    if manifest.get("rehearsal"):
        raise PublishRefused(f"{snap}: a rehearsal snapshot is never published")
    if manifest.get("preview"):
        raise PublishRefused(f"{snap}: a preview snapshot is never published")
    if not manifest.get("counts_toward_verdict"):
        raise PublishRefused(f"{snap}: the snapshot does not count toward its forward test")
    if "model" not in manifest:
        raise PublishRefused(f"{snap}: no model name in the manifest")
    preds = pd.read_csv(Path(snap) / "tpd3_predictions.csv")
    filed: set[str] = set()
    live = Path(snap) / "results_live.csv"
    if live.exists():
        lv = pd.read_csv(live)
        filed = set(lv["symbol"].dropna().astype(str)) if "symbol" in lv else set()
    return manifest, preds, filed


def _r(x: float, n: int = 2) -> Optional[float]:
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else round(float(x), n)


def inputs_on_record(panel: pd.DataFrame, symbols, T: date) -> dict:
    """The fixed six inputs, same order for every stock, each with the date of the data it rests on. A stock without a
    bar on T gets no entry (never zeros)."""
    t = pd.Timestamp(T)
    p = panel[panel["symbol"].isin(set(symbols)) & (panel["as_of_date"] <= t)].sort_values(["symbol", "as_of_date"])
    out = {}
    for sym, g in p.groupby("symbol", sort=False):
        g = g.tail(40).set_index("as_of_date")
        if t not in g.index:
            continue
        r = g.loc[t]; prev = g[g.index < t]
        tr = pd.concat([g["high"] - g["low"], (g["high"] - g["close"].shift()).abs(), (g["low"] - g["close"].shift()).abs()], axis=1).max(axis=1)
        med20 = float(prev["volume"].tail(20).median()) if len(prev) >= 10 else float("nan")
        dl = g["deliverable_pct"].dropna() if "deliverable_pct" in g else pd.Series(dtype=float)
        c5 = float(r["close"] / g["close"].iloc[-6] - 1) * 100 if len(g) >= 6 else float("nan")
        out[sym] = {
            "close_change_pct": {"v": _r((r["close"] / r["prev_close"] - 1) * 100), "date": str(T)},
            "day_range_pct": {"v": _r((r["high"] - r["low"]) / r["prev_close"] * 100), "date": str(T)},
            "volume_vs_20d_median": {"v": _r(r["volume"] / med20) if med20 and not math.isnan(med20) else None, "date": str(T)},
            "delivery_pct": {"v": _r(float(dl.iloc[-1])) if len(dl) else None, "date": str(dl.index[-1].date()) if len(dl) else None},
            "change_5_sessions_pct": {"v": _r(c5), "date": str(T)},
            "atr14_pct": {"v": _r(float(tr.tail(14).mean()) / r["close"] * 100) if len(g) >= 15 else None, "date": str(T)},
        }
    return out


def events_on_record(events_db: Path, symbols, T: date, frozen_at: datetime) -> dict:
    """Up to 3 classified events per stock from the catalyst store, between the start of T-4 (5 calendar days) and the
    freeze; one per subtype, highest catalyst score first; media titles withheld."""
    con = sqlite3.connect(f"file:{events_db}?mode=ro", uri=True, timeout=120)
    try:
        q = ("SELECT symbol, event_time, source, source_url, event_type, event_subtype, direction, catalyst_score, title, classification_method "
             f"FROM stock_events WHERE symbol IN ({','.join('?' * len(symbols))})")
        ev = pd.read_sql_query(q, con, params=list(symbols))
    finally:
        con.close()
    if ev.empty:
        return {}
    ev["t"] = pd.to_datetime(ev["event_time"], utc=True, format="mixed")
    start = pd.Timestamp(datetime.combine(T - timedelta(days=EVENT_WINDOW_DAYS - 1), datetime.min.time(), tzinfo=IST))
    ev = ev[(ev["t"] >= start) & (ev["t"] <= pd.Timestamp(frozen_at)) & ~ev["event_type"].isin(NOT_LISTED_TYPES)]
    out = {}
    for sym, g in ev.sort_values(["catalyst_score", "t"], ascending=[False, False]).groupby("symbol", sort=False):
        g = g.drop_duplicates("event_subtype").head(3)
        rows = []
        for k, e in enumerate(g.itertuples(), start=1):
            media = e.source in MEDIA_SOURCES
            rows.append({"ord": k, "event_time": e.t.tz_convert(IST).isoformat(), "source_label": SOURCE_LABELS.get(e.source, e.source), "is_media": media,
                         "event_type": e.event_type, "event_subtype": e.event_subtype, "direction": e.direction,
                         "title": None if media else (e.title or "")[:300], "url": e.source_url or None,
                         "method": "rules + model" if "LLM" in (e.classification_method or "") else "rules"})
        out[sym] = rows
    return out


def lit(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def _copy(table: str, frame: pd.DataFrame) -> str:
    buf = io.StringIO(); frame.to_csv(buf, index=False, lineterminator="\n")
    body = buf.getvalue()
    if "\n\\.\n" in "\n" + body:
        raise PublishRefused("a CSV row equals the COPY terminator")
    return f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true);\n{body}\\.\n"


def run_script(manifest: dict, msha: str, preds: pd.DataFrame, stocks: dict, events: dict, filed: set[str]) -> str:
    heads = [h for h in HEADS if h in set(preds["head"])]
    train = manifest.get("train", {})
    first = train.get(heads[0], {}) if heads else {}
    est = preds[preds["head"].isin(heads)].rename(columns={"p_tpd3": "p"})[["head", "symbol", "p", "p_base_rate"]].sort_values(["head", "symbol"])
    st = pd.DataFrame([{"symbol": s, "company_name": v.get("company_name") or None, "sector": v.get("sector") or None,
                        "inputs": json.dumps(v.get("inputs", {}), separators=(",", ":")), "results_filed": s in filed} for s, v in sorted(stocks.items())],
                      columns=["symbol", "company_name", "sector", "inputs", "results_filed"])
    evr = pd.DataFrame([{"symbol": s, **e} for s, es in sorted(events.items()) for e in es],
                       columns=["symbol", "ord", "event_time", "source_label", "is_media", "event_type", "event_subtype", "direction", "title", "url", "method"])
    skipped = "'{" + ",".join(manifest.get("skipped_holidays", [])) + "}'::date[]"
    join = f"JOIN nidp.tpd_runs r ON r.snapshot_sha256 = {lit(msha)}"
    return "\n".join([
        "\\set ON_ERROR_STOP on",
        "BEGIN;",
        "INSERT INTO nidp.tpd_runs (model, refit, status, data_as_of, target_session, frozen_at, snapshot_sha256, lock_sha256, git_sha, universe_size, scored, "
        "input_count, train_rows, train_end, skipped_holidays, counts_toward_verdict, results_filed_in_universe) VALUES ("
        + ", ".join([lit(manifest["model"]), lit(manifest.get("refit", "monthly")), lit("final"), lit(manifest["data_as_of"]), lit(manifest["target_session"]),
                     lit(manifest["generated_at"]), lit(msha), lit(manifest["lock_sha256"]), lit(manifest["git_sha"]), lit(int(manifest.get("universe_size", 0))),
                     lit(int(preds["symbol"].nunique())), lit(manifest.get("columns")), lit(first.get("train_rows")), lit(first.get("train_end_max_horizon")),
                     skipped, lit(bool(manifest.get("counts_toward_verdict"))), lit(manifest.get("filed_today_in_universe"))])
        + ") ON CONFLICT (snapshot_sha256) DO NOTHING;",
        "CREATE TEMP TABLE _est (head text, symbol text, p double precision, p_base_rate double precision) ON COMMIT DROP;",
        _copy("_est", est),
        f"INSERT INTO nidp.tpd_run_estimates (run_id, head, symbol, p, p_base_rate) SELECT r.run_id, e.head, e.symbol, e.p, e.p_base_rate FROM _est e {join} ON CONFLICT DO NOTHING;",
        "CREATE TEMP TABLE _stk (symbol text, company_name text, sector text, inputs jsonb, results_filed boolean) ON COMMIT DROP;",
        _copy("_stk", st),
        f"INSERT INTO nidp.tpd_run_stocks (run_id, symbol, company_name, sector, inputs, results_filed) SELECT r.run_id, s.symbol, s.company_name, s.sector, s.inputs, s.results_filed FROM _stk s {join} ON CONFLICT DO NOTHING;",
        "CREATE TEMP TABLE _evt (symbol text, ord smallint, event_time timestamptz, source_label text, is_media boolean, event_type text, event_subtype text, "
        "direction text, title text, url text, method text) ON COMMIT DROP;",
        _copy("_evt", evr),
        "INSERT INTO nidp.tpd_run_events (run_id, symbol, ord, event_time, source_label, is_media, event_type, event_subtype, direction, title, url, method) "
        f"SELECT r.run_id, v.symbol, v.ord, v.event_time, v.source_label, v.is_media, v.event_type, v.event_subtype, v.direction, v.title, v.url, v.method FROM _evt v {join} ON CONFLICT DO NOTHING;",
        "COMMIT;",
    ]) + "\n"


def _band_edges(key: str) -> tuple[float, float]:
    lo, hi = key.split("-")
    return float(lo), min(float(hi), 1.0)


def record_script(model: str, verdict_path: Path, window_label: str) -> str:
    v = json.loads(Path(verdict_path).read_text())
    lines = ["\\set ON_ERROR_STOP on", "BEGIN;"]
    for head in HEADS:
        h = v["heads"][head]
        lines.append("INSERT INTO nidp.tpd_model_record (model, head, source, window_label, sessions, base_rate, top10_hit_rate) VALUES ("
                     + ", ".join([lit(model), lit(head), lit("test_2025"), lit(window_label), lit(int(v["graded_sessions"])), lit(float(h["base_rate"])), lit(float(h["p10"]))])
                     + ") ON CONFLICT DO NOTHING;")
        for key, b in h["rows_by_p_band"].items():
            lo, hi = _band_edges(key)
            lines.append("INSERT INTO nidp.tpd_band_record (model, head, source, band_lo, band_hi, rows, realised) VALUES ("
                         + ", ".join([lit(model), lit(head), lit("test_2025"), lit(lo), lit(hi), lit(int(b["rows"])), lit(b["realised"])])
                         + ") ON CONFLICT DO NOTHING;")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def grades_script(root: Path, top_k: int = 10) -> str:
    """Per-head outcome summaries for every graded, counted snapshot under `root` (the live record on the page)."""
    lines = ["\\set ON_ERROR_STOP on", "BEGIN;"]
    for snap in sorted(p for p in Path(root).iterdir() if p.is_dir() and (p / "graded.csv").exists()):
        try:
            load_publishable(snap)
        except PublishRefused:
            continue
        g = pd.read_csv(snap / "graded.csv")
        g = g[g["y"].notna()]
        for head, gh in g.groupby("head"):
            top = gh.sort_values(["p_tpd3", "symbol"], ascending=[False, True]).head(top_k)
            lines.append("INSERT INTO nidp.tpd_run_grades (run_id, head, graded_rows, touched, top10_hits) SELECT r.run_id, "
                         + ", ".join([lit(head), lit(int(len(gh))), lit(int(gh["y"].sum())), lit(int(top["y"].sum()))])
                         + f" FROM nidp.tpd_runs r WHERE r.snapshot_sha256 = {lit(manifest_sha(snap))} ON CONFLICT DO NOTHING;")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def refusal_script(model: str, target: date, reason: str, detail: dict) -> str:
    return "\n".join(["\\set ON_ERROR_STOP on", "BEGIN;",
                      "INSERT INTO nidp.tpd_run_refusals (model, target_session, reason, detail) VALUES ("
                      + ", ".join([lit(model), lit(str(target)), lit(reason), lit(json.dumps(detail)) + "::jsonb"]) + ") ON CONFLICT DO NOTHING;",
                      "COMMIT;"]) + "\n"


def apply(sql: str, container: str = CONTAINER) -> None:
    res = subprocess.run(["docker", "exec", "-i", container, *PSQL], input=sql.encode(), capture_output=True, timeout=300)
    if res.returncode != 0:
        raise RuntimeError(f"psql failed ({res.returncode}): {res.stderr.decode(errors='replace')[:800]}")


def _emit(sql: str, a) -> int:
    if a.out:
        Path(a.out).write_text(sql); logger.info("wrote %s (%d bytes)", a.out, len(sql))
    if a.apply:
        apply(sql); logger.info("applied to %s", CONTAINER)
    if not a.out and not a.apply:
        sys.stdout.write(sql)
    return 0


def main(argv=None) -> int:
    from .forward import _load

    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "grades", "record", "refusal"):
        p = sub.add_parser(name); p.add_argument("--apply", action="store_true"); p.add_argument("--out", type=Path, default=None)
        if name == "run":
            p.add_argument("--snapshot", type=Path, required=True); p.add_argument("--exports", type=Path, required=True); p.add_argument("--events-db", type=Path, required=True)
        elif name == "grades":
            p.add_argument("--root", type=Path, required=True)
        elif name == "record":
            p.add_argument("--model", required=True); p.add_argument("--verdict", type=Path, required=True); p.add_argument("--window", required=True)
        else:
            p.add_argument("--model", required=True); p.add_argument("--target", required=True); p.add_argument("--reason", required=True); p.add_argument("--detail", default="{}")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.cmd == "run":
        manifest, preds, filed = load_publishable(a.snapshot)
        T = date.fromisoformat(manifest["data_as_of"]); symbols = sorted(preds["symbol"].unique())
        panel, _, _ = _load(a.exports)
        names = pd.read_csv(a.exports / "company_names.csv").drop_duplicates("symbol").set_index("symbol")
        inputs = inputs_on_record(panel, symbols, T)
        def text(col, s):
            v = names[col].get(s) if s in names.index else None
            return v if isinstance(v, str) and v.strip() else None       # NaN / blank → NULL, never the string "nan"
        stocks = {s: {"company_name": text("company_name", s), "sector": text("sector", s), "inputs": inputs.get(s, {})} for s in symbols}
        frozen = datetime.fromisoformat(manifest["generated_at"])
        events = events_on_record(a.events_db, symbols, T, frozen) if a.events_db.exists() else {}
        logger.info("run %s %s -> %s: %d estimates, %d stocks with inputs, %d with events", manifest["model"], T, manifest["target_session"],
                    len(preds), len(inputs), len(events))
        return _emit(run_script(manifest, manifest_sha(a.snapshot), preds, stocks, events, filed), a)
    if a.cmd == "grades":
        return _emit(grades_script(a.root), a)
    if a.cmd == "record":
        return _emit(record_script(a.model, a.verdict, a.window), a)
    return _emit(refusal_script(a.model, date.fromisoformat(a.target), a.reason, json.loads(a.detail)), a)


if __name__ == "__main__":
    raise SystemExit(main())
