"""Track 1, days 6-7: post-close outcome job for one session (TRACK1_SCOPE_v2 rules; H-B = operational test, not validated).

  python outcomes.py --session 2026-09-21 [--bars kite|local|none] [--dry-run-label TEXT]
Inputs: reports/<session>/watchlist.csv (evening before) · nidp.prices_eod official open/close for the session ·
5-minute bars (Kite historical after the close, else the local research store, else none -> UNRESOLVED) ·
optional reports/<session>/manual_fills.csv (symbol, arm, side ENTRY|EXIT, time, price, qty).
Outputs (write-once): signals.csv, outcomes.csv, data_quality.json, outcome_manifest.json, daily_signal_report.html,
ledger.jsonl (hash-chained). Nothing here changes a rule; every exception is reported, never inferred.
"""
from __future__ import annotations
import argparse, datetime as dt, glob, hashlib, html, json, os, subprocess, sys, uuid
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from exits import stop_target_exit, hb_confirmation
from ledger import Ledger
from watchlist import q, REPORTS, SCOPE

SCOPE_V2 = "docs/ai_research/tpd3/track1/TRACK1_SCOPE_v3.md"   # the scope the job runs under (v3 since 2026-09-19)
CAP, BANDS = 5, (0.05, 0.10, 0.20)
OBS = ["09:15", "09:20", "09:25", "09:30", "09:35", "09:40"]
ETF_LIST = "/app/research/sealed/etf_symbols_name_contains_ETF.csv"

def signals_for(w: pd.DataFrame, px: pd.DataFrame) -> pd.DataFrame:
    """Join the watchlist with the session's official prices; compute gap, at-band, signal flags."""
    s = w.merge(px, on="symbol", how="left")
    s["has_price"] = s.open_price.notna() & s.close_price.notna()
    s["gap"] = s.open_price / s.p0_adj - 1
    s["gap_raw"] = s.open_price / s.p0_raw - 1
    s["at_band_v2"] = np.any([np.abs(s.gap_raw + b) <= 0.0025 for b in BANDS], axis=0) & s.has_price
    s["at_band"] = s.at_band_v2
    s["signal"] = s.has_price & (s.gap <= -0.03)
    return s

def apply_v3(s: pd.DataFrame, bands: pd.DataFrame | None, etf_names: set[str]) -> pd.DataFrame:
    """TRACK1_SCOPE_v3 exclusions known at the open. `bands` = the session's nidp.security_reference_daily rows
    (symbol, band_raw, price_band_pct, is_etf); None/empty -> historical fallback (ETF by Kite name; band rule deferred to
    the locked-first-bar check once 5-minute bars are loaded)."""
    s = s.copy()
    live = bands is not None and len(bands) > 0
    if live:
        b = bands.set_index("symbol")
        # psql CSV export writes booleans as 't'/'f' strings — never use bool() on them ("f" is truthy)
        s["is_etf"] = s.symbol.map(b.is_etf).map(lambda v: v in (True, 1, "t", "true", "True", "1"))
        s["band_raw"] = s.symbol.map(b.band_raw)
        s["band_pct"] = pd.to_numeric(s.symbol.map(b.price_band_pct), errors="coerce")
        s["band_status"] = np.where(s.band_raw.isna(), "UNKNOWN", np.where(s.band_raw == "No Band", "NO_BAND", "BANDED"))
        lower = s.p0_raw * (1 - s.band_pct / 100)
        s["at_own_band"] = (s.band_status == "BANDED") & ((s.open_price - lower).abs() <= np.maximum(0.05, 0.0005 * s.open_price))
    else:
        s["is_etf"] = s.symbol.isin(etf_names)
        s["band_raw"], s["band_pct"], s["band_status"] = None, np.nan, "HISTORICAL_FALLBACK"
        s["at_own_band"] = False                                   # decided later from the locked 09:15 bar (H-B only)
    s["v3_excluded"] = np.select([s.is_etf, s.band_status == "UNKNOWN", s.at_own_band], ["ETF", "BAND_UNKNOWN", "OPEN_AT_OWN_BAND"], "")
    return s

def first_bar_locked(bar_open: float, bar_low: float, gap_raw: float) -> bool:
    """v3 historical fallback: the 09:15 bar never traded below its open AND the open sits within 0.25pp of a standard band."""
    return abs(bar_low - bar_open) < 1e-9 and any(abs(gap_raw + b) <= 0.0025 for b in BANDS)

def select_capped(df: pd.DataFrame, cap: int = CAP) -> pd.DataFrame:
    """Deepest gap first, ties -> higher 20-day value."""
    return df.sort_values(["gap", "value20"], ascending=[True, False]).head(cap)

def load_bars(session: str, symbols: list[str], source: str) -> tuple[dict, str]:
    if source == "none" or not symbols:
        return {}, "none"
    if source == "kite":
        try:
            sys.path.insert(0, "/app/.claude/worktrees/paper-engine/backend")
            from nidp.services.kite_bars.client import kite
            from nidp.services.kite_bars.auth import read_token
            kc = kite(read_token())
            tok = {r["tradingsymbol"]: r["instrument_token"] for r in kc.instruments("NSE") if r.get("segment") == "NSE"}
            d = dt.date.fromisoformat(session); out = {}
            for sym in symbols:
                if sym in tok:
                    rows = kc.historical_data(tok[sym], d, d, "5minute")
                    out[sym] = pd.DataFrame([{"hm": r["date"].strftime("%H:%M"), "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"], "v": r.get("volume", 0)} for r in rows])
            return out, "kite"
        except Exception as e:  # noqa: BLE001 — fall back, and say so in data_quality
            print(f"kite bars unavailable ({type(e).__name__}: {e}); trying the local store", file=sys.stderr)
    out, skipped = {}, 0
    for f in sorted(glob.glob("/app/research/kite_history/five_min_2024/part-*.csv.gz")):
        try:
            for ch in pd.read_csv(f, usecols=["symbol", "ts", "open", "high", "low", "close", "volume"], chunksize=1_000_000):
                ch = ch[ch.symbol.isin(symbols) & ch.ts.str.startswith(session)]
                for sym, x in ch.groupby("symbol"):
                    out[sym] = pd.concat([out.get(sym, pd.DataFrame()), pd.DataFrame({"hm": x.ts.str.slice(11, 16), "o": x.open, "h": x.high, "l": x.low, "c": x.close, "v": x.volume})])
        except (EOFError, OSError, pd.errors.ParserError) as e:   # a part file still being written by the backfill
            skipped += 1; print(f"skipped unreadable part {os.path.basename(f)}: {type(e).__name__}", file=sys.stderr)
    return {k: v.drop_duplicates("hm").sort_values("hm") for k, v in out.items()}, f"local (skipped {skipped} unreadable part files)"

def run(session: str, bars_source: str, label: str | None, repo: str) -> dict:
    out = os.path.join(REPORTS, session)
    wl = os.path.join(out, "watchlist.csv")
    if not os.path.exists(wl):
        raise SystemExit(f"no watchlist for {session} ({wl})")
    for fn in ("signals.csv", "outcomes.csv", "outcome_data_quality.json", "outcome_manifest.json", "daily_signal_report.html"):
        if os.path.exists(os.path.join(out, fn)):
            raise SystemExit(f"REFUSED: {fn} exists for {session} (write-once)")
    w = pd.read_csv(wl)
    px = q(f"SELECT symbol, open_price, close_price FROM nidp.prices_eod WHERE series='EQ' AND as_of_date='{session}'")
    exc = {"session": session, "official_prices_rows": int(len(px))}
    if px.empty:
        raise SystemExit(f"official prices for {session} not ingested yet — rerun after the EOD feed")
    etfs = set(pd.read_csv(ETF_LIST, header=None)[0]) if os.path.exists(ETF_LIST) else set()
    bands = q(f"SELECT symbol, band_raw, price_band_pct, is_etf FROM nidp.security_reference_daily WHERE series='EQ' AND as_of_date='{session}'")
    s = apply_v3(signals_for(w, px), bands, etfs); s["etf"] = s.is_etf
    s["cost_rt"] = s.cost_round_trip_pct / 100
    s["at_band"] = s.v3_excluded != ""                  # v3 exclusion at the open; v2's rule is kept only as at_band_v2
    sig = s[s.signal & ~s.at_band]
    bars, used = load_bars(session, sig.symbol.tolist(), bars_source)
    exc.update(bars_source=used, watchlist_symbols=int(len(w)), missing_official_price=int((~s.has_price).sum()),
               signals=int(s.signal.sum()), excluded_at_band=int((s.signal & s.at_band).sum()), etf_signals=int((s.signal & s.etf).sum()),
               v3_exclusions=s.loc[s.signal & s.at_band, "v3_excluded"].value_counts().to_dict(), band_mode="LIVE" if len(bands) else "HISTORICAL_FALLBACK",
               v2_rule_would_exclude=int((s.signal & s.at_band_v2).sum()))
    L = Ledger(os.path.join(out, "ledger.jsonl"))
    rows, open_mismatch, unresolved = [], 0, 0
    ha_pick = set(select_capped(sig).symbol)
    hb_rows = []
    for r in s.itertuples():
        for arm in ("H-A", "H-B"):
            L.transition(r.symbol, arm, "WATCHLIST", "evening watchlist", {"trigger": r.trigger_open_at_or_below}, at=f"{r.prev_session}T20:00:00+05:30")
        if not r.has_price:
            for arm in ("H-A", "H-B"): L.transition(r.symbol, arm, "INVALIDATED", "NO_OFFICIAL_PRICE")
            continue
        if not r.signal:
            for arm in ("H-A", "H-B"): L.transition(r.symbol, arm, "EXPIRED", "NO_GAP")
            continue
        if r.at_band:
            for arm in ("H-A", "H-B"): L.transition(r.symbol, arm, "INVALIDATED", r.v3_excluded)
            continue
        b = bars.get(r.symbol)
        rec = {"symbol": r.symbol, "gap": r.gap, "value20": r.value20, "etf": r.etf, "open": r.open_price, "close": r.close_price,
               "cost_rt": r.cost_rt, "liquidity": r.liquidity}
        # H-A: enter at the official open; exit at the official close (v2). -2/+3 recorded as a description when bars exist.
        if r.symbol in ha_pick:
            L.transition(r.symbol, "H-A", "ENTRY_CONFIRMED", "open", {"entry": r.open_price}, at=f"{session}T09:15:00+05:30")
            ha_ret = r.close_price / r.open_price - 1
            desc = None
            if b is not None and len(b):
                desc = stop_target_exit(list(b[["o", "h", "l", "c"]].itertuples(index=False, name=None)), r.open_price, r.close_price)
            L.transition(r.symbol, "H-A", "CLOSED", "TIME", {"exit": r.close_price, "gross": ha_ret})
            rec.update(ha="ENTERED", ha_gross=ha_ret, ha_net=ha_ret - r.cost_rt, ha_desc_stop_target=desc[1] if desc else None)
        else:
            L.transition(r.symbol, "H-A", "EXPIRED", "CAP")
            rec.update(ha="CAPPED")
        # H-B: needs the session's 5-minute bars.
        L.transition(r.symbol, "H-B", "TRIGGER_APPROACHING", f"gap {100*r.gap:.2f}% at 09:15", at=f"{session}T09:15:00+05:30")
        if b is None or not set(OBS + ["09:45"]).issubset(set(b.hm)):
            L.transition(r.symbol, "H-B", "INVALIDATED", "UNRESOLVED_MISSING_BARS"); unresolved += 1
            rec.update(hb="UNRESOLVED"); rows.append(rec); continue
        o915 = b[b.hm == "09:15"].o.iloc[0]
        if r.band_status == "HISTORICAL_FALLBACK" and first_bar_locked(o915, b[b.hm == "09:15"].l.iloc[0], r.gap_raw):
            L.transition(r.symbol, "H-B", "INVALIDATED", "LOCKED_FIRST_BAR_AT_BAND"); rec.update(hb="EXCLUDED_LOCKED_BAR"); rows.append(rec); continue
        if abs(o915 / r.open_price - 1) > 1e-6:
            open_mismatch += 1; L.transition(r.symbol, "H-B", "INVALIDATED", "DATA_ERROR_OPEN_MISMATCH", {"bar_open": o915, "official_open": r.open_price})
            rec.update(hb="DATA_ERROR"); rows.append(rec); continue
        obs = b[b.hm.isin(OBS)].sort_values("hm")
        ok, p945, vwap, why = hb_confirmation(list(obs[["o", "h", "l", "c", "v"]].itertuples(index=False, name=None)), o915)
        rec.update(p945=p945, vwap945=vwap, mae_pre=obs.l.min() / o915 - 1, recovery=(p945 / obs.l.min() - 1) if p945 else None,
                   vwap_dist=(p945 / vwap - 1) if (p945 and vwap) else None)
        if not ok:
            L.transition(r.symbol, "H-B", "EXPIRED", why); rec.update(hb="NOT_CONFIRMED_" + why); rows.append(rec); continue
        rec.update(hb="CONFIRMED"); hb_rows.append((r, b)); rows.append(rec)
    R = pd.DataFrame(rows)
    conf = R[R.get("hb", pd.Series(dtype=str)) == "CONFIRMED"] if len(R) else R
    hb_pick = set(select_capped(conf).symbol) if len(conf) else set()
    for r, b in hb_rows:
        i = R.index[R.symbol == r.symbol][0]
        if r.symbol not in hb_pick:
            L.transition(r.symbol, "H-B", "EXPIRED", "CAP"); R.loc[i, "hb"] = "CAPPED"; continue
        post = b[b.hm >= "09:45"].sort_values("hm"); E = post.o.iloc[0]
        L.transition(r.symbol, "H-B", "ENTRY_CONFIRMED", "09:45 confirmed", {"entry": E}, at=f"{session}T09:45:00+05:30")
        px_exit, reason = stop_target_exit(list(post[["o", "h", "l", "c"]].itertuples(index=False, name=None)), E, r.close_price)
        L.transition(r.symbol, "H-B", "CLOSED", reason, {"exit": px_exit})
        R.loc[i, ["hb", "hb_entry", "hb_exit", "hb_reason", "hb_gross", "hb_net"]] = ["ENTERED", E, px_exit, reason, px_exit / E - 1, px_exit / E - 1 - r.cost_rt]
    # manual fills
    mf = os.path.join(out, "manual_fills.csv"); recon = []
    if os.path.exists(mf):
        for m in pd.read_csv(mf).itertuples():
            try:
                L.manual("MANUAL_ENTRY" if m.side == "ENTRY" else "MANUAL_EXIT", m.symbol, m.arm, m.price, m.qty, m.time)
                recon.append({"symbol": m.symbol, "arm": m.arm, "side": m.side, "manual_price": m.price})
            except Exception as e:  # noqa: BLE001
                recon.append({"symbol": m.symbol, "arm": m.arm, "side": m.side, "error": str(e)})
    exc.update(open_mismatch=open_mismatch, hb_unresolved=unresolved, manual_fills=len(recon),
               status="NO_SIGNALS" if len(sig) == 0 else "CERTIFIED" if used != "none" and open_mismatch == 0 and unresolved == 0 else "DEGRADED" if used != "none" else "UNRESOLVED")
    s.to_csv(os.path.join(out, "signals.csv"), index=False); R.to_csv(os.path.join(out, "outcomes.csv"), index=False)
    json.dump(exc, open(os.path.join(out, "outcome_data_quality.json"), "w"), indent=1, default=str)
    sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
    man = {"run_id": f"oc-{uuid.uuid4().hex[:10]}", "session": session, "label": label or "live",
           "git_sha": subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
           "scope": SCOPE_V2, "scope_sha256": sha(os.path.join(repo, SCOPE_V2)), "cost_model": "v1", "bars_source": used}
    json.dump(man, open(os.path.join(out, "outcome_manifest.json"), "w"), indent=1)
    write_html(out, session, exc, R, recon, man)
    return exc

def write_html(out, session, exc, R, recon, man):
    e = lambda x: html.escape(str(x))
    def table(df, cols):
        if df is None or not len(df): return "<p>None.</p>"
        cols = [c for c in cols if c in df.columns]
        head = "".join(f"<th>{e(c)}</th>" for c in cols)
        body = "".join("<tr>" + "".join(f"<td>{e(round(v, 4) if isinstance(v, float) else v)}</td>" for v in r) + "</tr>" for r in df[cols].itertuples(index=False))
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    ha = R[R.get("ha", pd.Series(dtype=str)) == "ENTERED"] if len(R) else R
    hb = R[R.get("hb", pd.Series(dtype=str)) == "ENTERED"] if len(R) else R
    def summ(df, col):
        return f"{len(df)} trades, mean net {100 * df[col].mean():+.2f}%" if len(df) and col in df else "no trades"
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gap-down signals {e(session)}</title><style>
:root{{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#ddd}} @media (prefers-color-scheme:dark){{:root{{--bg:#141414;--fg:#eee;--muted:#aaa;--line:#333}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:16px}}
table{{border-collapse:collapse;width:100%;font-size:13px;display:block;overflow-x:auto}} th,td{{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;white-space:nowrap}}
.muted{{color:var(--muted)}} .warn{{font-weight:600}}</style></head><body>
<h1>Gap-down signals — {e(session)}</h1>
<p class="muted">Run {e(man['run_id'])} · {e(man['label'])} · git {e(man['git_sha'][:8])} · scope v3 {e(man['scope_sha256'][:8])} · cost model v1 · bars: {e(man['bars_source'])}</p>
<p class="warn">H-B is a candidate confirmation rule — operational test, not a validated edge. H-A is CLOSED; its column is a reference for what confirmation skips, not a trade candidate.</p>
<h2>Data freshness and completeness</h2><pre>{e(json.dumps(exc, indent=1))}</pre>
<h2>Market-day summary</h2><p>{exc.get('signals',0)} gap-down signals · {exc.get('excluded_at_band',0)} excluded at a lower band · {exc.get('etf_signals',0)} ETF signals (flagged)</p>
<h2>H-A reference only (closed hypothesis; open → close, max {CAP})</h2><p>{summ(ha,'ha_net')}</p>{table(ha, ['symbol','gap','open','close','ha_gross','ha_net','ha_desc_stop_target','liquidity','etf'])}
<h2>H-B (09:45 confirmation, max {CAP})</h2><p>{summ(hb,'hb_net')}</p>{table(hb, ['symbol','gap','p945','vwap945','hb_entry','hb_exit','hb_reason','hb_gross','hb_net','mae_pre','recovery','vwap_dist','liquidity','etf'])}
<h2>All signals, side by side</h2>{table(R, ['symbol','gap','ha','hb','ha_net','hb_net','mae_pre','etf'])}
<h2>Unresolved intraday outcomes</h2><p>{exc.get('hb_unresolved',0)} H-B signals without usable 5-minute bars (never inferred).</p>
<h2>Manual execution notes</h2>{table(pd.DataFrame(recon), ['symbol','arm','side','manual_price','error'])}
<h2>Cost assumptions</h2><p>Cost model v1: charges 0.10% round trip (accepted as-is by the owner) plus slippage by 20-day value — 0.20% / 0.30% / 0.40% round trip for &gt; Rs 100 cr / Rs 25–100 cr / Rs 5–25 cr.</p>
</body></html>"""
    open(os.path.join(out, "daily_signal_report.html"), "w").write(doc)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--session", required=True); ap.add_argument("--bars", default="kite", choices=["kite", "local", "none"])
    ap.add_argument("--dry-run-label"); ap.add_argument("--repo", default=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    a = ap.parse_args(); print(json.dumps(run(a.session, a.bars, a.dry_run_label, a.repo), indent=1, default=str))
