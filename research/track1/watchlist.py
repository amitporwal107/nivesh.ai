"""Track 1, days 1-3: evening watchlist for liquid EQ gap-down signals (TRACK1_SCOPE_v1, sections 1-2, 6, 11).

Reads NIDP's own end-of-day table (nidp.prices_eod) — no Kite dependency. Writes, per next session:
  /app/research/reports/<next_session>/watchlist.csv, data_quality.json, run_manifest.json
Write-once: an existing day's watchlist is never overwritten; a rerun needs --version N and writes watchlist_vN.csv.
Stop and target are set from the ACTUAL entry price at trade time; the levels here are indicative only.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, io, json, os, subprocess, sys, uuid
import pandas as pd

SCOPE = "docs/ai_research/tpd3/track1/TRACK1_SCOPE_v1.md"
REPORTS = "/app/research/reports"
PSQL = ["docker", "exec", "-i", "nidp-postgres-staging", "psql", "-U", "nidp_staging", "-d", "nidp_staging", "-v", "ON_ERROR_STOP=1"]
LIQ_MIN = 5e7              # Rs 5 crore, 20-session average traded value
GAP_TRIGGER = 0.97         # signal if open <= previous close x 0.97
BANDS = (0.05, 0.10, 0.20)
COST_RT = [(1e9, 0.0020), (2.5e8, 0.0030), (5e7, 0.0040)]   # cost model v1 round trip by 20-day value

def q(sql: str) -> pd.DataFrame:
    r = subprocess.run(PSQL + ["-c", f"COPY ({sql}) TO STDOUT WITH CSV HEADER"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:400])
    return pd.read_csv(io.StringIO(r.stdout))

def next_session(after: dt.date, holidays: set[dt.date]) -> dt.date:
    d = after + dt.timedelta(days=1)
    while d.weekday() >= 5 or d in holidays:
        d += dt.timedelta(days=1)
    return d

def cost_rt(v: float) -> float:
    return next(c for lim, c in COST_RT if v >= lim)

def build(prev: dt.date | None = None) -> tuple[pd.DataFrame, dict]:
    hol = set(pd.to_datetime(q("SELECT DISTINCT holiday_date FROM nidp.nse_holidays").holiday_date).dt.date)
    dates = q("SELECT DISTINCT as_of_date FROM nidp.prices_eod WHERE series='EQ' ORDER BY as_of_date DESC LIMIT 40")
    dates = sorted(pd.to_datetime(dates.as_of_date).dt.date, reverse=True)
    prev = prev or dates[0]
    window = [d for d in dates if d <= prev][:20]
    px = q("SELECT as_of_date, symbol, close_price, turnover FROM nidp.prices_eod WHERE series='EQ' "
           f"AND as_of_date BETWEEN '{window[-1]}' AND '{prev}'")
    px["as_of_date"] = pd.to_datetime(px.as_of_date).dt.date
    nxt = next_session(prev, hol)
    g = px.groupby("symbol").agg(n_sessions=("as_of_date", "nunique"), value20=("turnover", "mean"))
    last = px[px.as_of_date == prev].set_index("symbol").close_price.rename("p0_raw")
    w = g.join(last, how="inner")
    missing_hist = w[w.n_sessions < 20]
    w = w[(w.n_sessions == 20) & (w.value20 >= LIQ_MIN)].copy()
    ca = q("SELECT symbol, action_type, ratio, face_value_pre, face_value_post, ex_date FROM nidp.corporate_actions "
           f"WHERE series='EQ' AND ex_date = '{nxt}'")
    w["ca_ex_next_session"] = w.index.isin(ca.symbol)
    w["p0_adj"] = w.p0_raw          # split/bonus factor applied at 09:15 from the published open; flagged here
    w["trigger_open_at_or_below"] = (w.p0_adj * GAP_TRIGGER).round(2)
    for b in BANDS:
        w[f"lower_band_{int(b*100)}pct"] = (w.p0_raw * (1 - b)).round(2)
    w["indicative_stop_at_trigger"] = (w.trigger_open_at_or_below * 0.98).round(2)
    w["indicative_target_at_trigger"] = (w.trigger_open_at_or_below * 1.03).round(2)
    w["liquidity"] = pd.cut(w.value20, [5e7, 2.5e8, 1e9, float("inf")], labels=["Rs5-25cr", "Rs25-100cr", ">Rs100cr"], right=False)
    w["cost_round_trip_pct"] = w.value20.map(cost_rt) * 100
    w = w.reset_index().sort_values("value20", ascending=False)
    w.insert(0, "next_session", nxt); w.insert(1, "prev_session", prev)
    now_ist = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30)))
    dq = {"prev_session": str(prev), "next_session": str(nxt), "generated_at_ist": now_ist.isoformat(timespec="seconds"),
          "eq_symbols_on_prev_session": int(last.shape[0]), "watchlist_symbols": int(len(w)),
          "excluded_missing_20_sessions": int(len(missing_hist)), "ca_ex_next_session": int(w.ca_ex_next_session.sum()),
          "stale": prev != max(dates), "status": "CERTIFIED" if len(w) and prev == max(dates) else "DEGRADED"}
    return w, dq

def write(w: pd.DataFrame, dq: dict, version: int | None, repo: str) -> str:
    out = os.path.join(REPORTS, dq["next_session"]); os.makedirs(out, exist_ok=True)
    name = "watchlist.csv" if version is None else f"watchlist_v{version}.csv"
    path = os.path.join(out, name)
    if os.path.exists(path):
        raise SystemExit(f"REFUSED: {path} exists (write-once). Rerun with --version N to create a new version.")
    w.to_csv(path, index=False)
    sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
    manifest = {"run_id": f"wl-{uuid.uuid4().hex[:10]}", "file": name, "file_sha256": sha(path),
                "scope": SCOPE, "scope_sha256": sha(os.path.join(repo, SCOPE)),
                "git_sha": subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
                "cost_model": "v1", "data_snapshot": {"table": "nidp.prices_eod", "prev_session": dq["prev_session"]}}
    for fn, obj in (("data_quality.json" if version is None else f"data_quality_v{version}.json", dq),
                    ("run_manifest.json" if version is None else f"run_manifest_v{version}.json", manifest)):
        p = os.path.join(out, fn)
        if os.path.exists(p):
            raise SystemExit(f"REFUSED: {p} exists (write-once).")
        json.dump(obj, open(p, "w"), indent=1, default=str)
    return path

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--prev", type=dt.date.fromisoformat); ap.add_argument("--version", type=int)
    ap.add_argument("--repo", default=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    a = ap.parse_args()
    w, dq = build(a.prev)
    p = write(w, dq, a.version, a.repo)
    print(json.dumps(dq)); print("wrote", p)
