"""Opening Bell — fetch NSE's public pre-open market data (9:00-9:08 IST call auction) for the edition date.

NSE's page needs its own cookies first, then /api/market-data-pre-open?key=FO (F&O stocks) and key=ALL (every
stock, used only to price the AI list's names outside F&O). Polls until the data carries the edition date and an
update time at or after 09:08 IST (the order book closes between 9:07 and 9:08), up to --until.
No credentials; read-only.

usage: python3 preopen.py OUT.json --date YYYY-MM-DD [--until HH:MM] [--allow-stale]
  --allow-stale   TESTS ONLY: accept an earlier day's pre-open (marked "allow_stale" in the output; the cards keep
                  it visible as stale). Never used by the scheduled run.
exit 0 written / 2 not available in time
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
PAGE = "https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge-market"
API = "https://www.nseindia.com/api/market-data-pre-open?key={key}"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
FINAL_AT = "09:08:00"


def fetch() -> dict:
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", "Accept": "*/*"}
    op.open(urllib.request.Request(PAGE, headers=h), timeout=20).read()
    out = {}
    for key in ("FO", "ALL"):
        r = op.open(urllib.request.Request(API.format(key=key), headers={**h, "Referer": PAGE}), timeout=30)
        out[key] = json.loads(r.read())
    return out


def rows(body: dict) -> list:
    res = []
    for x in body.get("data") or []:
        m = x.get("metadata") or {}
        sym, iep, prev = m.get("symbol"), m.get("iep"), m.get("previousClose")
        if not sym or prev in (None, 0):
            continue
        iep = float(iep or 0)
        prev = float(prev)
        res.append({"sym": sym, "iep": iep, "prev": prev, "pct": round((iep / prev - 1) * 100, 4) if iep else 0.0,
                    "qty": m.get("finalQuantity")})
    return res


def parse_ts(ts: str):
    try:
        return datetime.strptime(ts, "%d-%b-%Y %H:%M:%S")
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--date", required=True)
    ap.add_argument("--until", default="09:12")
    ap.add_argument("--allow-stale", action="store_true")
    a = ap.parse_args()
    hh, mm = map(int, a.until.split(":"))
    deadline = datetime.now(IST).replace(hour=hh, minute=mm, second=0, microsecond=0)
    last = "no attempt"
    while True:
        try:
            b = fetch()
            ts = parse_ts((b["FO"] or {}).get("timestamp"))
            day = ts.date().isoformat() if ts else None
            if ts and (a.allow_stale or (day == a.date and ts.strftime("%H:%M:%S") >= FINAL_AT)):
                fo, al = rows(b["FO"]), rows(b["ALL"])
                out = {"source": "NSE pre-open (nseindia.com/api/market-data-pre-open)", "timestamp": b["FO"].get("timestamp"), "date": day,
                       "fetched_at": datetime.now(IST).isoformat(timespec="seconds"), "allow_stale": bool(a.allow_stale and day != a.date),
                       "fo_adv": b["FO"].get("advances"), "fo_dec": b["FO"].get("declines"), "fo_unch": b["FO"].get("unchanged"),
                       "fo": fo, "all": al}
                json.dump(out, open(a.out, "w"))
                print(json.dumps({"timestamp": out["timestamp"], "fo": len(fo), "all": len(al), "adv": out["fo_adv"], "dec": out["fo_dec"],
                                  "stale": out["allow_stale"]}))
                return 0
            last = f"NSE timestamp {b['FO'].get('timestamp')} (want {a.date} after {FINAL_AT})"
        except Exception as e:  # noqa: BLE001 — retried until the deadline, then reported
            last = f"{type(e).__name__}: {str(e)[:160]}"
        if datetime.now(IST) >= deadline:
            print(f"pre-open not available by {a.until} IST: {last}", file=sys.stderr)
            return 2
        time.sleep(20)


if __name__ == "__main__":
    sys.exit(main())
