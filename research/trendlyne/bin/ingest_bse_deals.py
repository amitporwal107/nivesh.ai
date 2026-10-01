"""Bulk/block deals for the BSE side, via Trendlyne — because api.bseindia.com refuses us.

WHY THIS EXISTS. The genuine source is the exchange, and we ingest NSE's rolling bulk.csv
directly. BSE's equivalent lives only behind api.bseindia.com, which returns a WAF
"Access Denied" 403 to our ASN (verified 2026-10-01 from 34.93.60.254; www.bseindia.com and its
/download/ file server are fine, the API host is not). Trendlyne's MCP carries the same records
WITH an exchange tag, so it stands in for the BSE half until the block is lifted.

ONLY BSE ROWS ARE WRITTEN. Trendlyne returns both exchanges; `source` is part of the primary key,
so ingesting its NSE rows too would store every NSE deal twice under two sources. The NSE feed
stays authoritative for NSE.

QUOTA IS THE BINDING CONSTRAINT: ~400 calls/day but 2,000/month, so ~100 symbols/day sustained.
This is a per-STOCK lookup — it answers "did THIS stock have a deal", never "which stocks had
deals today". Feed it a shortlist (volume/price anomalies, or the candidate universe), never the
whole market.

PIT: BSE disseminates bulk/block deals after market hours the same session, and the paper
prediction freezes at 20:50 IST, so a same-day deal is legitimately available pre-prediction.
Run this after ~19:30 IST and before the freeze.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import date, datetime

sys.path.insert(0, "/app/research/trendlyne")
from tl_mcp import TL  # noqa: E402

SOURCE = "TRENDLYNE_BSE"
ACTION = {"purchase": "BUY", "buy": "BUY", "sell": "SELL", "sale": "SELL"}


def _rows_from_text(text: str) -> list:
    """Pull the tableData tuples out of the MCP text payload.

    The server returns a YAML-ish block with a `tableData:` line holding JSON arrays. Parsing the
    arrays directly is deliberate: the surrounding format is not a documented contract, so the
    narrowest thing that can break is preferred over a whole-document parser.
    """
    i = text.find("tableData:")
    if i < 0:
        return []
    return re.findall(r"\[[^\[\]]*\]", text[i:])


def parse(symbol: str, text: str) -> list:
    """-> [(as_of_date, symbol, client, deal_type, qty, price, seq, remarks, kind)] for BSE only."""
    out, seq = [], {}
    for raw in _rows_from_text(text):
        try:
            f = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if len(f) < 8:
            continue
        client, kind, action, d, price, qty, pct, exch = f[:8]
        if str(exch).strip().upper() != "BSE":
            continue                                   # NSE half comes from the exchange directly
        dt = str(d)[:10]
        try:
            datetime.strptime(dt, "%Y-%m-%d")
        except ValueError:
            continue
        side = ACTION.get(str(action).strip().lower())
        if side is None:
            continue
        key = (dt, symbol, str(client).strip(), side)
        seq[key] = seq.get(key, 0) + 1                 # same client, same side, same day -> 1,2,3…
        out.append((dt, symbol, str(client).strip(), side, int(qty), float(price), seq[key],
                    f"pct_stake={pct};exchange=BSE;via=trendlyne",
                    "block" if str(kind).strip().lower() == "block" else "bulk"))
    return out


def sql_for(rows: list, run_id: str) -> str:
    """INSERT … ON CONFLICT DO NOTHING, split across the bulk and block tables.

    `source_run_id` is NOT NULL and one uuid identifies the whole batch, so every row written by a
    single run is traceable back to it — and a bad run can be deleted by that id alone.
    """
    def lit(s):
        return "'" + str(s).replace("'", "''") + "'"
    stmts = []
    for table, kind in (("nidp.bulk_deals", "bulk"), ("nidp.block_deals", "block")):
        part = [r for r in rows if r[8] == kind]
        if not part:
            continue
        vals = ",\n".join(
            f"({lit(d)}::date,{lit(sym)},{lit(c)},{lit(side)},{q},{p},{sq},{lit(rem)},"
            f"{lit(SOURCE)},{lit(run_id)}::uuid,now())"
            for d, sym, c, side, q, p, sq, rem, _ in part)
        stmts.append(
            f"INSERT INTO {table} (as_of_date,symbol,client_name,deal_type,quantity,avg_price,"
            f"deal_seq,remarks,source,source_run_id,ingested_at) VALUES\n{vals}\n"
            f"ON CONFLICT DO NOTHING;")
    return "\n".join(stmts)


def main(symbols: list) -> int:
    tl = TL()
    tl.init()
    all_rows, misses = [], []
    for sym in symbols:
        try:
            res = tl.call("get_ownership_deals_insider_sast",
                          {"stock_code": sym, "type": "bulblockdeal"}, f"deals_{sym}")
        except Exception as e:                          # one bad symbol must not lose the batch
            misses.append(f"{sym}: {e}")
            continue
        text = res.get("text") if isinstance(res, dict) else None
        if not text:
            misses.append(f"{sym}: no text payload")
            continue
        got = parse(sym, text)
        all_rows.extend(got)
        print(f"  {sym:<14} BSE rows: {len(got)}", file=sys.stderr)
    for m in misses:
        print(f"  MISS {m}", file=sys.stderr)
    print(f"total BSE rows: {len(all_rows)}  |  symbols queried: {len(symbols)}", file=sys.stderr)
    if all_rows:
        run_id = str(uuid.uuid4())
        print(f'-- run_id {run_id}', file=sys.stderr)
        print(sql_for(all_rows, run_id))
    return 0 if all_rows or not symbols else 1


if __name__ == "__main__":
    syms = [s.strip().upper() for s in sys.argv[1:] if s.strip()]
    if not syms:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(syms))
