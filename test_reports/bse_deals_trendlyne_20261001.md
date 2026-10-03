# Functionality Verification Report — BSE bulk/block deals via Trendlyne

Date: 2026-10-01 · Branch: `feat/bse-deals-via-trendlyne` · Base: `origin/dev` @ 18f9b764

## Problem

The daily 5%-mover list showed MOLBIO +15.6% on 1 Oct, driven by a 23-lakh-share HDFC Mutual Fund
bulk purchase on 30 Sep. Our `nidp.bulk_deals` had no such row — and could not have, because the
deal executed on **BSE** and we ingest only NSE.

## The block, measured

```
$ curl https://api.bseindia.com/BseIndiaAPI/api/BulkDeals/w?...
HTTP 403 in 0.11s
<H1>Access Denied</H1>
You don't have permission to access ".../BseIndiaAPI/api/BulkDeals/w?" on this server
```

Edge/WAF denial keyed to our ASN (egress `34.93.60.254`, GCP asia-south1). Routes ruled out:

| route | result |
|---|---|
| `api.bseindia.com` HTTPS / HTTP | **403** both |
| `www.bseindia.com/BseIndiaAPI/api/BulkDeals/w` | 404 — API not served on www |
| `www.bseindia.com/download/*ulk*.csv` | soft 404 (SPA shell, 14,287 bytes) |
| `/downloads1/*`, `/BSEDATA/BulkDeals/*` | hard 404 |
| existing proxy | none — tinyproxy inactive, no `NSE_HTTPS_PROXY` set |

Controls proving it is the API host specifically: `www.bseindia.com/` → 200, the bhavcopy
download → 200 with 868 KB of real data, NSE's `bulk.csv` → 200 with 180 rows.

Also confirmed **not** a parser bug: MOLBIO appears **0 times** in NSE's own file.

## Fix

Trendlyne MCP's `get_ownership_deals_insider_sast(type='bulblockdeal')` carries the same records
**with an exchange tag**, so it stands in for the BSE half without a proxy.

`research/trendlyne/bin/ingest_bse_deals.py` queries it per symbol, keeps **BSE rows only**, and
emits idempotent SQL into the existing tables as `source = TRENDLYNE_BSE`.

**BSE-only is load-bearing.** The primary key is
`(as_of_date, symbol, client_name, deal_type, deal_seq, source)` — ingesting Trendlyne's NSE rows
too would store every NSE deal a second time under a different source. The exchange feed stays
authoritative for NSE.

## Real output

```
$ python research/trendlyne/bin/ingest_bse_deals.py MOLBIO
  MOLBIO         BSE rows: 4
total BSE rows: 4  |  symbols queried: 1

$ psql -f bse_deals.sql
INSERT 0 4

$ SELECT as_of_date, client_name, deal_type, quantity, avg_price, source
  FROM nidp.bulk_deals WHERE symbol='MOLBIO' AND as_of_date >= '2026-09-20';
2026-09-30 | HDFC MUTUAL FUND              | BUY  | 2300000 | 1315.0000 | TRENDLYNE_BSE
2026-09-30 | BUSINESS EXCELLENCE TRUST III | SELL | 2328996 | 1315.0100 | TRENDLYNE_BSE
2026-09-23 | KOTAK MAHINDRA MUTUAL FUND    | BUY  | 2750000 | 1315.0000 | TRENDLYNE_BSE
2026-09-23 | BUSINESS EXCELLENCE TRUST III | SELL | 2996798 | 1315.0000 | TRENDLYNE_BSE

$ SELECT source, count(*) FROM nidp.bulk_deals GROUP BY 1;
NSE_BULK       | 7652
TRENDLYNE_BSE  |    4
```

**The gap is closed on real staging data.** The sequence your analysis described is now queryable:
Kotak buys 2.39% on 23 Sep, HDFC buys 2.00% on 30 Sep — both absorbing **Business Excellence
Trust III** selling at a pegged ₹1,315. A trust distributing into mutual-fund demand, not
open-market accumulation.

```
$ PYTHONPATH=. pytest research/trendlyne/tests/ -q
20 passed in 0.11s
```

## Limits

- **Per-stock only.** This answers *"did THIS stock have a deal"*, never *"which stocks had deals
  today"*. It cannot replace a market-wide sweep.
- **Quota is the binding constraint:** ~400 calls/day but **2,000/month** → ~100 symbols/day
  sustained. Feed it a shortlist, never the universe.
- **It would not have caught MOLBIO on its own** — MOLBIO is absent from the 997-symbol model
  universe, so nothing would have prompted the query. The universe gap (775 liquid symbols
  missing) is upstream of this.
- Not yet scheduled. Run after ~19:30 IST (BSE disseminates same-session, post-close) and before
  the 20:50 prediction freeze, which keeps it point-in-time clean.

## Verdict: PASS
