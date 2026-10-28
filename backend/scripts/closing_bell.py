"""Closing Bell — backend side of the nightly market-commentary video.

The video is built on the app VM by tools/closing_bell (see its README). This script is the
part that needs the backend's own access (Mongo, the NIDP warehouse bridge, Trendlyne), and runs
inside the backend container:

    docker exec nivesh-staging-app-backend python -m scripts.closing_bell <command> ...

Commands
  ensure-bot                      create the read-only bot account (role "user", onboarded); idempotent
  session --ttl-min 60            create a short-lived bot session; prints the token to stdout ONLY
                                  (the caller pipes it straight into a 0600 file, never a log)
  revoke --token-file PATH        delete that session (token read from the file)
  ready --date D                  is D a finished trading day? JSON on stdout, exit 0 ready / 3 not yet
  collect --date D --token-file P everything the bulletin says, as one JSON bundle on stdout
  notify                          JSON {date, status, reasons, url} on stdin -> Mongo `closing_bell_runs` + alert on
                                  hold/fail (operator channels, else the app mailer to CLOSING_BELL_ALERT_EMAIL_TO or
                                  KITE_TOKEN_ALERT_EMAIL_TO)

Read-only apart from the bot's own user/profile/session documents: collect only reads the
warehouse, the desk's own GET endpoints (as the bot) and the public Sensibull / Trendlyne feeds.
"""
from __future__ import annotations

import argparse
import asyncio
import calendar
import json
import secrets
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

IST = timezone(timedelta(hours=5, minutes=30))
BOT_USER_ID = "closing-bell-bot"
BOT_EMAIL = "closing-bell-bot@nivesh.invalid"
DESK_BASE = "http://localhost:8001"
INDICES = ["Nifty 50", "Nifty Bank", "Nifty Next 50", "Nifty 100", "Nifty 200", "Nifty 500",
           "Nifty Midcap 150", "Nifty Smallcap 250", "Nifty Microcap 250", "India VIX"]
HEATMAPS = ["NIFTY50", "NIFTY100", "NIFTY200", "NIFTY500"]
SENSIBULL = "https://oxide.sensibull.com"


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- bot account
async def ensure_bot() -> Dict[str, Any]:
    from deps import db
    now = datetime.now(timezone.utc).isoformat()
    await db.users.update_one(
        {"user_id": BOT_USER_ID},
        {"$set": {"email": BOT_EMAIL, "name": "Closing Bell (bot)", "role": "user", "is_admin": False,
                  "is_bot": True, "picture": ""},
         "$setOnInsert": {"user_id": BOT_USER_ID, "created_at": now}},
        upsert=True,
    )
    await db.user_profiles.update_one(
        {"user_id": BOT_USER_ID},
        {"$set": {"onboarding_completed": True, "updated_at": now},
         "$setOnInsert": {"user_id": BOT_USER_ID, "created_at": now}},
        upsert=True,
    )
    return {"user_id": BOT_USER_ID, "role": "user", "onboarding_completed": True}


async def create_session(ttl_min: int) -> str:
    from deps import db
    ttl_min = max(5, min(int(ttl_min), 180))
    token = "cb_" + secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    # Clear this bot's expired sessions so they never pile up.
    await db.user_sessions.delete_many({"user_id": BOT_USER_ID, "expires_at": {"$lt": now.isoformat()}})
    await db.user_sessions.insert_one({
        "user_id": BOT_USER_ID, "session_token": token,
        "expires_at": (now + timedelta(minutes=ttl_min)).isoformat(),
        "created_at": now.isoformat(), "purpose": "closing-bell-recorder",
    })
    return token


async def revoke_session(token: str) -> int:
    from deps import db
    r = await db.user_sessions.delete_one({"user_id": BOT_USER_ID, "session_token": token})
    return r.deleted_count


# ---------------------------------------------------------------- NIDP data API (DaaS)
async def daas(path: str, params: Optional[dict] = None) -> Any:
    """GET on the NIDP DaaS API with the backend's own key; returns the body, or {"_http": status}."""
    from services.copilot_tools.daas_client import get_raw
    status, body = await get_raw(path, params or {}, timeout=60.0)
    return body if status == 200 else {"_http": status}


async def readiness(d: str) -> Dict[str, Any]:
    """Ready = the EOD snapshot for D exists with D's prices and index closes, and D's Top 10 list is stored."""
    snap = await daas("/snapshots/market", {"on": d})
    s = (snap or {}).get("data") if isinstance(snap, dict) else None
    from services import ai_watchlist_store as store
    ideas = await store.has_day(d)
    snap_ok = bool(s and str(s.get("prices_as_of"))[:10] == d and str(s.get("index_as_of"))[:10] == d)
    day = date.fromisoformat(d)
    cal = await daas("/desk/macro-calendar", {"month": day.strftime("%Y-%m")})
    holiday = day.weekday() >= 5 or any(h.get("date") == d for h in ((cal or {}).get("holidays") or []) if isinstance(cal, dict))
    return {"date": d, "ready": bool(snap_ok and ideas), "snapshot_ready": snap_ok, "ideas_list": ideas,
            "snapshot_built_at": (s or {}).get("built_at"), "no_session": holiday}


async def warehouse(d: str) -> Dict[str, Any]:
    day = date.fromisoformat(d)
    lo = (day - timedelta(days=12)).isoformat()
    indices = []
    for name in INDICES:
        body = await daas(f"/indices/{name}/eod", {"start": lo, "end": d, "limit": 20})
        rows = sorted((body or {}).get("data") or [], key=lambda r: str(r["as_of_date"]))
        if rows and str(rows[-1]["as_of_date"])[:10] == d:
            r = rows[-1]
            prev = rows[-2]["close_price"] if len(rows) > 1 else None
            indices.append({"index_name": name, "open_price": r["open_price"], "high_price": r["high_price"],
                            "low_price": r["low_price"], "close_price": r["close_price"], "pct_change": r["pct_change"],
                            "prev_close": prev, "pts_change": round(r["close_price"] - prev, 2) if prev else None})
    snap = await daas("/snapshots/market", {"on": d})
    months = {day.strftime("%Y-%m"), (day + timedelta(days=7)).strftime("%Y-%m")}
    macro = {m: await daas("/desk/macro-calendar", {"month": m}) for m in sorted(months)}
    return {"indices": indices, "market_snapshot": (snap or {}).get("data"), "macro_calendar": macro}


# ---------------------------------------------------------------- desk + feeds
async def desk(client, path: str, params: Optional[dict] = None) -> Any:
    r = await client.get(DESK_BASE + path, params=params or {})
    if r.status_code != 200:
        return {"_http": r.status_code}
    return r.json()


async def sensibull(client, months: List[str]) -> Dict[str, Any]:
    """Market-wide FII/DII cash, daily, from Sensibull's anonymous cache (month NAME param)."""
    out: Dict[str, Any] = {}
    try:
        await client.get(f"{SENSIBULL}/v1/pluto/auth/web/session/a/platform/identify")
        for ym in months:
            r = await client.get(f"{SENSIBULL}/v1/compute/cache/fii_dii_daily", params={"year_month": ym},
                                 headers={"Origin": "https://web.sensibull.com"})
            if r.status_code == 200:
                out.update((r.json() or {}).get("data") or {})
            else:
                _err(f"sensibull {ym}: HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001 — a missing feed is reported by the checks, not fatal here
        _err(f"sensibull failed: {type(e).__name__}")
    return out


def trendlyne_profits(symbols: List[str]) -> Dict[str, Any]:
    """Latest-quarter and year-ago net profit (owners' share) for up to 10 symbols."""
    if not symbols:
        return {}
    from nidp.services.trendlyne_fundamentals.client import TrendlyneClient, mcp_url
    from nidp.services.trendlyne_fundamentals.parse import parse_parameter_values
    cl = TrendlyneClient(mcp_url(), budget_left=3)
    try:
        text = cl.call("get_stock_parameter_values", {"stock_codes": symbols[:10], "parameters": ["npq", "npqmy1"]})
    except Exception as e:  # noqa: BLE001
        _err(f"trendlyne failed: {type(e).__name__}: {cl.redact(str(e))[:200]}")
        return {"_error": cl.redact(str(e))[:200]}
    finally:
        cl.close()
    dates, values = parse_parameter_values(text)
    out = {}
    for sym, v in values.items():
        if sym.startswith("_"):
            continue
        npq, ago = v.get("npq"), v.get("npqmy1")
        out[sym] = {"npq": npq, "npqmy1": ago, "updated": str(dates.get(sym) or ""),
                    "yoy": round((npq / ago - 1) * 100, 1) if npq is not None and ago not in (None, 0) and ago > 0 else None}
    return out


def month_name(d: date) -> str:
    return f"{d.year}-{calendar.month_name[d.month]}"


async def collect(d: str, token: str) -> Dict[str, Any]:
    import httpx
    day = date.fromisoformat(d)
    hdr = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=120, headers=hdr) as c:
        rw = await desk(c, "/api/desk/results-week", {"date": d})
        if isinstance(rw, dict) and rw.get("_http"):
            rw = await desk(c, "/api/desk/results-week", {"date": (day + timedelta(days=1)).isoformat()})
        bundle: Dict[str, Any] = {
            "results_week": rw,
            "ai_watchlist": await desk(c, "/api/desk/ai-watchlist", {"date": d}),
            "sector_returns": await desk(c, "/api/markets/sector-returns"),
            "smart_money_flows": await desk(c, "/api/markets/smart-money/flows"),
            "market_dashboard": await desk(c, "/api/positional/market-dashboard"),
            "heatmaps": {i: await desk(c, "/api/markets/sector-heatmap", {"index": i}) for i in HEATMAPS},
        }
    months = []
    m = day.replace(day=1)
    for _ in range(4):
        months.append(month_name(m))
        m = (m - timedelta(days=1)).replace(day=1)
    async with httpx.AsyncClient(timeout=60, headers={"User-Agent": "Mozilla/5.0"}) as c:
        bundle["fii_dii_daily"] = await sensibull(c, months)
    bundle.update(await warehouse(d))
    rows = (rw.get("results") or []) if isinstance(rw, dict) else []
    # After-the-bell filers: declared on D after the close (they first react on the next session), F&O names.
    after = [r["symbol"] for r in rows if r.get("event_date") == d and r.get("fno") and r.get("status") == "declared"
             and ((r.get("reaction") or {}).get("filed_after_close") or (r.get("reaction") or {}).get("stock_return_pct") is None)]
    reacted = [r for r in rows if (r.get("reaction") or {}).get("first_session") == d
               and (r.get("reaction") or {}).get("stock_return_pct") is not None]
    reacted.sort(key=lambda r: abs(r["reaction"]["stock_return_pct"]), reverse=True)
    symbols = (after[:7] + [r["symbol"] for r in reacted[:3]])[:10]
    bundle["trendlyne_profit"] = trendlyne_profits(symbols)
    bundle["meta"] = {"date": d, "generated_at": datetime.now(IST).isoformat(timespec="seconds"),
                      "after_bell_symbols": after, "schema": "closing-bell-bundle-v1"}
    return bundle


# ---------------------------------------------------------------- run record + alert
async def notify(summary: Dict[str, Any]) -> Dict[str, Any]:
    import html
    import os
    from deps import db
    status = summary.get("status")
    doc = {**summary, "recorded_at": datetime.now(timezone.utc).isoformat()}
    await db.closing_bell_runs.update_one({"date": summary.get("date")}, {"$set": doc}, upsert=True)
    fired: List[str] = []
    if status in ("held", "failed", "missed"):
        subject = f"Closing Bell {summary.get('date')}: {status.upper()} — not published"
        body = "\n".join([f"Status: {status}", f"Date: {summary.get('date')}", "Reasons:"]
                         + [f"  - {r}" for r in summary.get("reasons") or []] + ["", f"Log: {summary.get('log', '')}"])
        from nidp.shared import notify as n
        if n.email_configured() and n.send_email(subject, body):
            fired.append("email")
        if n.send_telegram(f"{subject}\n\n{body}"):
            fired.append("telegram")
        if not fired:
            to = [a.strip() for a in (os.environ.get("CLOSING_BELL_ALERT_EMAIL_TO") or os.environ.get("KITE_TOKEN_ALERT_EMAIL_TO") or "").split(",") if a.strip()]
            try:
                from helpers import secrets as sec
                from services import email_service
                await sec.hydrate_from_db(db)
                if to and email_service.is_configured():
                    for addr in to:
                        await email_service.send_email(addr, subject, body, f"<pre>{html.escape(body)}</pre>")
                    fired.append("app_email")
            except Exception as e:  # noqa: BLE001 — the run record above still carries the status
                _err(f"app mailer failed: {type(e).__name__}")
        await db.closing_bell_runs.update_one({"date": summary.get("date")}, {"$set": {"alert_channels": fired}})
    return {"recorded": True, "alert_channels": fired}


# ---------------------------------------------------------------- cli
def main() -> int:
    ap = argparse.ArgumentParser(prog="closing_bell")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ensure-bot")
    s = sub.add_parser("session"); s.add_argument("--ttl-min", type=int, default=60)
    r = sub.add_parser("revoke"); r.add_argument("--token-file", required=True)
    rd = sub.add_parser("ready"); rd.add_argument("--date", required=True)
    co = sub.add_parser("collect"); co.add_argument("--date", required=True); co.add_argument("--token-file", required=True)
    sub.add_parser("notify")
    a = ap.parse_args()

    if a.cmd == "ensure-bot":
        print(json.dumps(asyncio.run(ensure_bot())))
    elif a.cmd == "session":
        print(asyncio.run(create_session(a.ttl_min)))
    elif a.cmd == "revoke":
        n = asyncio.run(revoke_session(Path(a.token_file).read_text().strip()))
        print(json.dumps({"revoked": n}))
    elif a.cmd == "ready":
        res = asyncio.run(readiness(a.date))
        print(json.dumps(res))
        return 0 if res["ready"] else 3
    elif a.cmd == "notify":
        print(json.dumps(asyncio.run(notify(json.loads(sys.stdin.read())))))
    elif a.cmd == "collect":
        tok = Path(a.token_file).read_text().strip()
        print(json.dumps(asyncio.run(collect(a.date, tok)), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
