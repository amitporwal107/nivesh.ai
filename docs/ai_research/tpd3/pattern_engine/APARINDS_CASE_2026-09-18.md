# APARINDS, 18 Sep 2026 (+5.94%) — what happened, and what our pipeline missed

One winner, looked at with hindsight: a case study, not evidence. Every number below is from NIDP staging tables, Kite
5-minute bars, or the owner's Trendlyne report (18 Sep 15:31). Nothing here is a trade recommendation.

## What happened
| date | event (source) | price reaction |
|---|---|---|
| 24 Jul 12:41 | Q1 FY27 results: PAT ₹467 cr, +78% YoY, +84% QoQ; revenue ₹6,591 cr, +29% YoY (announcement + `nse_financials_quarterly`) | +3.5% close on 3.6× volume (high +9.4%) |
| 31 Jul – 12 Aug | no company news; post-results drift into the QIP | **+31% in 9 sessions**, 13,745 → 18,000 |
| 10–13 Aug | QIP: 16,88,618 shares to institutions at **₹14,805**, ₹2,500 cr (parsed PDF); promoter 57.8% → 55.4% | −8.2% over 13–17 Aug |
| 18 Aug – 11 Sep | range 16,500–17,900 | — |
| 10 Sep 11:05 | **CARE upgrades long-term rating AA− → AA (Stable)**, short-term A1+ reaffirmed (parsed PDF) | −0.6%; no reaction |
| 14 Sep | dividend record date (holiday) | 15 Sep −5.4% on 0.76× volume |
| 16 Sep | reversal: low 16,015 (09:40) → close 17,075 | +3.2% |
| 17 Sep | — | +4.3% on 1.6× volume |
| 18 Sep | flat open (−0.01%); +2.3% in the first 5-minute bar (12× volume); +3.06% at 09:45; flat to 14:00; +1% at 14:05 (6× volume, no news, peers flat); late sector/midcap push | **+5.94%, all-time high 19,080** on 2.25× volume, delivery 43.9% |
| 21 Sep | AGM (announcement 25 Aug) | — |

Same day: the electrical-equipment / cables / power group rose together (Siemens +4.0, Havells +3.7, Waaree +3.6,
R R Kabel +2.5, Polycab +2.3, KEI +2.0); Nifty 50 +0.33%, Midcap 100 +1.23%, Smallcap 100 +1.82% (most of it after 14:15).

## What our models saw on the evening of 17 Sep
- **v4 paper engine, P5-NEXT:** probability 10.9% (median 4.2%), **rank 104 of 997**; 5 were selected. Not selected.
- **v4's only inputs:** ATR, day range, 1-day change, 5-session change, volume ÷ 20-day median, delivery % —
  and delivery was **one day stale** (16 Sep 29.2% used; 17 Sep was 43.9%).
- **Family #20 (early strength ≥ +3% at 09:45):** APARINDS qualified at 09:45 and gained a further +2.8% to the close,
  but that family loses −0.47%/session over 528 sessions. APARINDS is a winner inside a losing group.

## What we are missing
| # | Gap | Evidence |
|---|---|---|
| 1 | **Results arrive ~5 weeks late** | Jun-26 quarter: 2,032 symbols; median broadcast → ingest lag **36 days**; only **3.7%** within 1 day. APARINDS: filed 24 Jul, ingested 14 Sep. The announcement row itself arrived on time |
| 2 | **Events have a category but no direction or numbers** | Rating upgrade classified `rating / neutral`; QIP classified `qip / negative`; both PDFs were parsed and state "Upgraded … AA" and "issue price ₹14,805" |
| 3 | **No trend or position features** | v4 has no 52-week/all-time-high distance, no 20/50/200-DMA, nothing beyond 5 sessions |
| 4 | **No sector or market context** | `sector_master` = "Capital Goods" only; no peer-relative strength or breadth input on a sector day |
| 5 | **Ownership is stale or empty** | Latest shareholding row = 30 Jun (ingested 18 Sep), so the post-QIP pattern is absent; `mf_pct` NULL |
| 6 | **No event calendar** | AGM, record dates, results dates, days-since-results are not features |

## One-day profile check (hindsight, one session — NOT evidence)
17 Sep evening, 1,502 stocks, base rate of a +5% day on 18 Sep = 5.3%:
| filter | n | +5% next day |
|---|---|---|
| above 20/50/200-DMA | 272 | 10.7% |
| + within 5% of the 52-week high | 81 | 13.6% |
| + up ≥ 3% on 17 Sep | 36 | 19.4% |
| + volume ≥ 1.5× | 16 | 37.5% (includes MONQ50, an ETF) |
One strong mid/small-cap session. It suggests hypotheses; it tests nothing.

## Candidate families (registered as candidates only; not tested)
- **#21 52-week-high breakout with volume in an uptrend** — evening signal, enter next open; net of costs.
- **#22 Post-results drift** — needs point-in-time results (gap 1) before it can even be tested.
Both would be developed on the discovery period (2024-08 → 2026-09) only. 2021–22 is used; 2023-01 → 2024-07 is the
single remaining sealed slice.

## Where APARINDS stands (context, not advice)
All-time high 19,080; close 18,858 is 8% above the 20-DMA (17,415) and 18% above the 50-DMA (16,019); daily ATR ≈ ₹812
(4.3%). Trendlyne: P/E 66.8 with 99.9% of its history below it; 7-analyst average target ₹15,161 (−19.6%). QIP buyers at
₹14,805 are +27%. Reference levels: old high 18,465 (12 Aug), 17 Sep close 17,801, 16 Sep low 16,015.
