"""Staging verification for the Charts API — test cases TC-2..TC-14 and TC-24.

    STAGING_COOKIE_HEADER=<file containing one line "Cookie: session_token=<uuid>"> \
        python3 -m research.charting.tools.verify_staging_api

App AND data: every served value is compared with an independent source — the committed snapshot in this checkout, the
frozen config's hash, a hand-written SMA, and the raw Kite gz parts read with csv (not via research.charting.bars).
Drawings are created on the caller's own account and deleted again before the script ends.

TC-1 (non-allowlisted account → 403) and TC-13 (a second user cannot read or change another user's drawing) need a
second account; they are reported as NOT TESTED here and remain covered by the local TestClient suite.
Exit code 0 only when every case run here passes.
"""
from __future__ import annotations

import csv
import gzip
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from research.charting.config import config_hash

BASE = os.environ.get("STAGING_API_BASE", "https://staging.niveshcopilot.com")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/125.0 Safari/537.36")
ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / "backend" / "services" / "research_chart_snapshot"
KITE_DIR = Path(os.environ.get("CHARTING_KITE_DAILY_DIR", "/app/research/kite_history/day_2021"))
DATA_SYMBOLS = ("RELIANCE", "TCS", "HDFCBANK")


def _cookie() -> str:
    path = os.environ.get("STAGING_COOKIE_HEADER")
    if not path:
        sys.exit("STAGING_COOKIE_HEADER is not set (file holding 'Cookie: session_token=...')")
    line = Path(path).read_text().strip()
    if not line.startswith("Cookie: "):
        sys.exit("STAGING_COOKIE_HEADER file must contain a 'Cookie: ...' header line")
    return line[len("Cookie: "):]


COOKIE = _cookie()


def call(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"User-Agent": UA, "Cookie": COOKIE, "Content-Type": "application/json",
                 "Origin": "https://staging.niveshcopilot.com:8443"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode(errors="replace")[:200]


results: list[tuple[str, bool, str]] = []


def check(tc: str, ok: bool, detail: str) -> None:
    results.append((tc, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {tc:<6} {detail}", flush=True)


def _detail(payload: object) -> str:
    """Every error string in the body, joined — FastAPI puts it in "detail"; the app's error envelope puts its own
    code in "code" (e.g. RES-001) and the route's detail in "message". Checks must look in all of them."""
    if isinstance(payload, dict):
        vals = [payload[k] for k in ("detail", "message", "code", "error") if isinstance(payload.get(k), str)]
        return " | ".join(vals) if vals else str(payload)[:80]
    return str(payload)[:80]


def _has(payload: object, code: str) -> bool:
    """True when any error field carries `code` as its code token — the text before an optional ": <detail>"
    (the chart routes append the offending value, e.g. "unknown_indicator: not_an_indicator")."""
    return any(v.split(":", 1)[0].strip() == code for v in _detail(payload).split(" | "))


def main() -> int:
    local = json.loads((SNAPSHOT / "manifest.json").read_text())
    local_syms = {s["symbol"]: s for s in local["symbols"]}

    st, run = call("GET", "/api/research/chart/run")
    check("TC-2", st == 200 and isinstance(run, dict) and run.get("config_hash") == config_hash()
          and run.get("config_hash") == local["config_hash"] and run.get("fixture") is False,
          f"HTTP {st}; served config_hash {str((run or {}).get('config_hash', ''))[:12] if isinstance(run, dict) else run} "
          f"vs local {config_hash()[:12]}; fixture={run.get('fixture') if isinstance(run, dict) else '?'}")

    st, syms = call("GET", "/api/research/chart/symbols")
    served = [s["symbol"] for s in (syms or {}).get("symbols", [])] if isinstance(syms, dict) else []
    check("TC-3", st == 200 and served == [s["symbol"] for s in local["symbols"]],
          f"HTTP {st}; {len(served)} symbols served vs {len(local_syms)} in the committed manifest")

    for sym in DATA_SYMBOLS:
        st, o = call("GET", f"/api/research/chart/{sym}/ohlcv")
        bars = (o or {}).get("bars", []) if isinstance(o, dict) else []
        dates = [b[0] for b in bars]
        mine = json.loads(gzip.open(SNAPSHOT / local_syms[sym]["file"]).read())["bars"]
        check("TC-4", st == 200 and dates == sorted(set(dates)) and bars == mine,
              f"{sym}: HTTP {st}; {len(bars)} bars, ascending+unique={dates == sorted(set(dates))}, "
              f"identical to committed snapshot={bars == mine}")

    st, e = call("GET", "/api/research/chart/ZZZNOTREAL/ohlcv")
    check("TC-5", st == 404 and _has(e, "unknown_symbol"), f"HTTP {st} {_detail(e)!r}")

    st1, _ = call("GET", "/api/research/chart/reliance/ohlcv")
    st2, _ = call("GET", "/api/research/chart/" + "A" * 40 + "/ohlcv")
    check("TC-6", st1 == 422 and st2 == 422, f"lowercase → {st1}; 40 chars → {st2}")

    st, ind = call("GET", "/api/research/chart/RELIANCE/indicators?ids=sma_20,rsi_14")
    keys = sorted((ind or {}).get("indicators", {})) if isinstance(ind, dict) else []
    st_bad, bad = call("GET", "/api/research/chart/RELIANCE/indicators?ids=not_an_indicator")
    check("TC-8", st == 200 and keys == ["rsi_14", "sma_20"] and st_bad == 400 and _has(bad, "unknown_indicator"),
          f"ids filter → {keys}; unknown id → HTTP {st_bad} {_detail(bad)!r}")

    st, o = call("GET", "/api/research/chart/RELIANCE/ohlcv")
    if not (isinstance(o, dict) and o.get("bars") and isinstance(ind, dict) and "sma_20" in ind.get("indicators", {})):
        check("TC-9..14,24", False, f"RELIANCE ohlcv/indicators unavailable (HTTP {st}) — dependent cases cannot run")
        return _finish()
    closes = [b[4] for b in o["bars"]]
    sma = ind["indicators"]["sma_20"]["values"]
    last_date, served_last = sma[-1][0], sma[-1][1]
    idx = [b[0] for b in o["bars"]].index(last_date)
    mine_last = sum(closes[idx - 19: idx + 1]) / 20
    check("TC-9", abs(served_last - mine_last) <= 1e-9 * max(1.0, abs(mine_last)),
          f"sma_20 @ {last_date}: served {served_last:.6f} vs independent {mine_last:.6f}")

    st, p = call("GET", "/api/research/chart/RELIANCE/patterns")
    n = len((p or {}).get("patterns", [])) if isinstance(p, dict) else -1
    check("TC-10", st == 200 and n == local_syms["RELIANCE"]["n_patterns"],
          f"HTTP {st}; {n} patterns served vs {local_syms['RELIANCE']['n_patterns']} in the committed manifest")

    # Drawings — created on the caller's own account, deleted before exit.
    new = {"symbol": "RELIANCE", "timeframe": "1D", "drawing_type": "HORIZONTAL_LINE",
           "anchor_points": [{"date": o["bars"][-1][0], "price": round(closes[-1], 2)}], "style": {}}
    st, d = call("POST", "/api/research/drawings", new)
    did = d.get("drawing_id") if isinstance(d, dict) else None
    check("TC-11", st == 201 and bool(did) and d.get("symbol") == "RELIANCE",
          f"HTTP {st}; drawing_id={'set' if did else 'missing'}")
    st, lst = call("GET", "/api/research/drawings?symbol=RELIANCE")
    ids = [x.get("drawing_id") for x in lst] if isinstance(lst, list) else [
        x.get("drawing_id") for x in (lst or {}).get("drawings", [])] if isinstance(lst, dict) else []
    check("TC-12", st == 200 and did in ids, f"HTTP {st}; new drawing listed={did in ids}; {len(ids)} listed")
    st_t, _ = call("POST", "/api/research/drawings", dict(new, drawing_type="CIRCLE"))
    st_a, _ = call("POST", "/api/research/drawings", dict(new, drawing_type="TRENDLINE"))
    check("TC-14", st_t == 422 and st_a == 422, f"bad type → {st_t}; TRENDLINE with 1 anchor → {st_a}")
    if did:
        st, _ = call("DELETE", f"/api/research/drawings/{did}")
        st_g, _ = call("GET", f"/api/research/drawings/{did}")
        check("TC-11/cleanup", st == 200 and st_g == 404, f"DELETE → {st}; GET after delete → {st_g}")

    # TC-24 — served bars vs the raw Kite gz parts, read independently with csv.
    raw: dict[str, list] = {s: [] for s in DATA_SYMBOLS}
    for part in sorted(KITE_DIR.glob("part-*.csv.gz")):
        with gzip.open(part, "rt", newline="") as fh:
            for row in csv.DictReader(fh):
                if row["symbol"] in raw:
                    raw[row["symbol"]].append(row)
    for sym in DATA_SYMBOLS:
        st, o = call("GET", f"/api/research/chart/{sym}/ohlcv")
        served_rows = {b[0]: b[1:] for b in (o or {}).get("bars", [])} if isinstance(o, dict) else {}
        mism = 0
        for r in raw[sym]:
            b = served_rows.get(r["date"][:10])
            want = [float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r["volume"])]
            if b is None or any(abs(float(x) - y) > 1e-6 for x, y in zip(b, want)):
                mism += 1
        check("TC-24", st == 200 and mism == 0 and len(raw[sym]) == len(served_rows),
              f"{sym}: {len(raw[sym])} raw rows vs {len(served_rows)} served, mismatches {mism}")

    return _finish()


def _finish() -> int:
    print("NOT TESTED  TC-1   needs a non-allowlisted account (covered by local TestClient suite)")
    print("NOT TESTED  TC-13  needs a second user (covered by local TestClient suite)")
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
