# Replay of 3 Nov 2026 — which scan-dashboard widgets flagged the day's movers early

Session fae0f691, 3 Nov 2026 evening. Owner's ask: "replay for the day… today's stocks that moved more than 5 % intraday… which
dashboard signals, across which widgets, flagged them early, so the same signals can surface the next ones while there's still
room". Owner's rule (3 Nov): a **mover** is a stock whose intraday range (high − low) reached **5 % of its open**.
One session only: an indication, not a tested signal. For a 30-session study (≥ 5 % rise from the open, up only, 247498 widgets
plus many other indicators) see session fffb64a1's `docs/scan_builder/early_signals/study_20261103.md` (branch
feat/scan-dashboard-early-signals).

## How it was replayed
- Both dashboards — Atlas fresh (Chartink 247498, 17 widgets) and Day trade (503347, 20 widgets) — rebuilt **every 5 minutes**
  from 09:20 to 15:30 by `market_dashboard.compute` itself (`replay_today.py`); only the data edges are replaced.
- Today's candle at each step from **Kite 1-minute candles** of every stock in the dashboard universe (`fetch_minutes.py`: 2,756
  stocks, 2,707 traded; read after the close through the app's shared Kite gate). The NIDP warehouse holds no intraday bars
  (`nidp.intraday_bars`, migration 152, was never created on staging); Mongo `kite_live_minute` holds indices, futures and options
  only, so the Kite read was needed.
- Daily history: the dashboard's adjusted NSE end-of-day panel to 2 Nov. Intraday widgets: candles built from the same 1-minute
  candles up to the step, over earlier sessions' Kite 5-minute candles (session fffb64a1's store, 1,593 liquid stocks).
- A flag is **early** when the step used only minutes before the stock's 5 % mark; **lead** = minutes from that step to the mark;
  **room left** = the move still ahead after the first early flag, in the move's direction (up = the day's low came first).
  **Hit rate** = of the stocks a widget listed while still under 5 %, the share that became movers; **lift** = hit rate ÷ the
  share of movers in the widget's universe (all stocks, or F&O). **Liquid** = 20-day average volume ≥ 50,000 and price ≥ ₹20.

## What it shows
1. **The rule is broad on a day like this:** 762 of 2,706 stocks that traded had a 5 % range (28 %); among liquid stocks 395 of
   1,592 (25 %), almost evenly up (205) and down (190). A widget needs a hit rate well above 25 % to help.
2. **Most movers were not flagged early.** Liquid up-movers with any widget before their 5 % mark: 61 of 205; without
   "Multiyear breakout" (which lists every stock with market cap > ₹10,000 cr or volume > 10 lakh by definition) 33 of 205.
   Down-movers: 41 (28) of 190. Many moves happened at once: 58 liquid movers reached 5 % by 09:30, 147 by 10:30.
3. **Widgets that stood out (liquid stocks, small counts):**
   - *Open interest* (Atlas, F&O): 5 of 7 stocks it listed while under 5 % became movers (base 5.2 % for F&O) — but it fires once
     the price is already ±5 % from yesterday's close, so the median lead was 16 min and the room left 1.6 %.
   - *Explosive movement* (Day trade): 6 of 7 (86 %, base 25 %), lead 36 min, room 4.1 % — but 4 up and 2 down: it flags
     volatility, not direction.
   - *10x volume first 5 min* (both tabs; the TrueData trade-side condition not replayed): 10 of 25 (40 %), lead 74 min,
     room 3.9 % — 3 up, 7 down.
   - *High growth stocks* (Day trade): 7 of 17 (41 %), but 5 of the 7 moved down.
   - F&O intraday widgets (*RSI VWAP intraday*, *15 minute stock breakouts*, *Long Build Up*, *Open interest 7*) list 129–168 of
     ~211 liquid F&O stocks at some point of the day, so their hit rates sit near the base (1.2–1.7×); every F&O mover they had
     early moved up, with 3.7–4.8 % room left (median).
4. **Several widgets at once did worse than chance** (0.4–0.55×, with or without Multiyear breakout): stocks listed by many
   widgets together are mostly large caps, which rarely move 5 % in a day.
5. Below the base rate: Multiyear breakout, Long tight consolidation, Low PE and High ROCE, RSI above 50 (D/W/M), Stocks below
   50 & 200 DMA; Supertrend RSI scan (0 of 7) and Delivery % + Volume (0 of 11) had no early movers.

This agrees with the 30-session study: no single widget is a strong early flag; what worked there was activity plus direction —
volume running 3–5× its usual for the time of day while the price is ≥ 2 % over the open.

## Caveats
- One session. Counts per widget are small (often under 20 stocks).
- **Kite's 1-minute candles for all 218 F&O stocks end at 15:14 today** (Kite's raw historical API, re-read and confirmed; other
  stocks run to 15:29). Against Kite's official day high/low this misses one F&O mover (BRITANNIA, 4.83 % on candles, 5.08 %
  officially) and understates late-day room for F&O stocks. The live dashboard's F&O 15-minute widgets see the same gap after 15:15.
- Fundamentals and company results are as loaded today: a look-ahead for results announced during the session (Good quarter
  results, High growth, Swing trade breakout, Stocks under 300, Stocks below 50 & 200 DMA).
- Not replayed: the TrueData trade-side condition of 10x volume (TrueData's login refused since ~17:40), index levels.
- A stock without stored 5-minute history cannot pass intraday conditions that need history. CONCORDBIO skipped (opened > 25 %
  from the adjusted previous close: a corporate action).

## Files
`fetch_minutes.py` (Kite 1-minute candles), `replay_today.py` (the replay), `analyse_today.py` (tables below),
`movers_liquid.csv` (each liquid mover: range, direction, 5 % mark, early widgets, lead, room). The raw candles (container
`/tmp/replay_20261103/minutes.jsonl`) and the 87,240 widget listings (`out/flags.csv`) are not in git.

---

**Movers (owner's rule: intraday range ≥ 5 % of the open):** 762 of 2706 stocks that traded (380 up, 382 down); liquid: 395 of 1592 (205 up).
Liquid movers reached the 5 % range at a median 11:45 IST; 57 of them inside the first 15 minutes (often a gap at the open).

## Liquid stocks (20-day average volume ≥ 50,000, price ≥ ₹20)

| Dashboard | Widget | Universe | Listed | Listed under 5 % | Early movers (up) | Hit rate | Base rate | Lift | Lead (median) | Room left after flag (median) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| atlas | Open interest | fno | 13 | 7 | 5 (5) | 71.4% | 5.2% | 13.83× | 16 min | 1.6% |
| daytrade | High volume and price breakout stocks | cash | 32 | 1 | 1 (1) | 100.0% | 24.8% | 4.03× | 60 min | 3.7% |
| atlas | Today's strong movers | cash | 3 | 1 | 1 (1) | 100.0% | 24.8% | 4.03× | 319 min | 3.2% |
| atlas | Nifty 50 Top Gainers | nifty50 | 14 | 14 | 1 (1) | 7.1% | 2.0% | 3.57× | 197 min | 4.5% |
| daytrade | Explosive movement | cash | 9 | 7 | 6 (4) | 85.7% | 24.8% | 3.45× | 36 min | 4.1% |
| daytrade | Short term breakouts | cash | 6 | 2 | 1 (0) | 50.0% | 24.8% | 2.02× | 146 min | 5.8% |
| daytrade | High growth stocks | cash | 22 | 17 | 7 (2) | 41.2% | 24.8% | 1.66× | 221 min | 3.5% |
| atlas | Open interest 7 | fno | 129 | 129 | 11 (11) | 8.5% | 5.2% | 1.65× | 86 min | 4.7% |
| atlas | 10x volume first 5 min | cash | 57 | 25 | 10 (3) | 40.0% | 24.8% | 1.61× | 74 min | 3.9% |
| daytrade | 10x volume first 5 min | cash | 57 | 25 | 10 (3) | 40.0% | 24.8% | 1.61× | 74 min | 3.9% |
| atlas | Triple bottom | fno | 13 | 13 | 1 (1) | 7.7% | 5.2% | 1.49× | 299 min | 2.4% |
| daytrade | RSI VWAP intraday | fno | 142 | 141 | 10 (10) | 7.1% | 5.2% | 1.37× | 100 min | 4.3% |
| daytrade | 15 minute stock breakouts | fno | 168 | 168 | 11 (11) | 6.5% | 5.2% | 1.27× | 81 min | 4.8% |
| atlas | Long Build Up (fresh) | fno | 133 | 130 | 8 (8) | 6.2% | 5.2% | 1.19× | 78 min | 3.7% |
| daytrade | Strong stocks | cash | 60 | 57 | 16 (7) | 28.1% | 24.8% | 1.13× | 242 min | 4.6% |
| daytrade | 52 week high stocks | cash | 19 | 16 | 4 (1) | 25.0% | 24.8% | 1.01× | 224 min | 4.5% |
| atlas | Cup & Handle Pattern | cash | 59 | 54 | 13 (6) | 24.1% | 24.8% | 0.97× | 243 min | 4.8% |
| daytrade | 52 week high breakout | cash | 20 | 17 | 4 (2) | 23.5% | 24.8% | 0.95× | 128 min | 4.2% |
| daytrade | Uptrend - 52 Week High | cash | 23 | 22 | 4 (3) | 18.2% | 24.8% | 0.73× | 111 min | 3.5% |
| atlas | Good quarter result stocks | cash | 15 | 12 | 2 (2) | 16.7% | 24.8% | 0.67× | 120 min | 4.1% |
| daytrade | Multiyear breakout | cash | 634 | 570 | 76 (51) | 13.3% | 24.8% | 0.54× | 170 min | 4.4% |
| atlas | RSI ABOVE 50 - DAILY, WEEKLY AND MONTHLY | cash | 21 | 18 | 2 (1) | 11.1% | 24.8% | 0.45× | 321 min | 3.0% |
| atlas | Long tight consolidation stocks | cash | 60 | 60 | 5 (5) | 8.3% | 24.8% | 0.34× | 159 min | 2.9% |
| atlas | Low PE and High ROCE | cash | 20 | 20 | 1 (0) | 5.0% | 24.8% | 0.20× | 314 min | 3.5% |
| daytrade | Stocks below 50 DMA & 200 DMA | cash | 30 | 30 | 1 (0) | 3.3% | 24.8% | 0.13× | 218 min | 2.4% |
| atlas | Supertrend RSI scan | cash | 9 | 7 | 0 (0) | 0.0% | 24.8% | 0.00× | – | – |
| daytrade | Delivery % + Volume | cash | 16 | 11 | 0 (0) | 0.0% | 24.8% | 0.00× | – | – |

| Several widgets at once | Listed under 5 % | Early movers | Hit rate | Base rate | Lift | Lead (median) | Room left (median) |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2 or more widgets (either dashboard) at the same step | 303 | 41 | 13.5% | 24.8% | 0.55× | 185 min | 4.0% |
| 3 or more widgets (either dashboard) at the same step | 207 | 22 | 10.6% | 24.8% | 0.43× | 76 min | 4.1% |
| 4 or more widgets (either dashboard) at the same step | 166 | 18 | 10.8% | 24.8% | 0.44× | 66 min | 4.5% |
| 2 or more widgets (either dashboard) at the same step — Multiyear breakout not counted | 221 | 27 | 12.2% | 24.8% | 0.49× | 130 min | 3.9% |
| 3 or more widgets (either dashboard) at the same step — Multiyear breakout not counted | 168 | 19 | 11.3% | 24.8% | 0.46× | 63 min | 4.5% |
| 4 or more widgets (either dashboard) at the same step — Multiyear breakout not counted | 118 | 12 | 10.2% | 24.8% | 0.41× | 80 min | 3.7% |

## All stocks

| Dashboard | Widget | Universe | Listed | Listed under 5 % | Early movers (up) | Hit rate | Base rate | Lift | Lead (median) | Room left after flag (median) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| atlas | Open interest | fno | 13 | 7 | 5 (5) | 71.4% | 5.0% | 14.16× | 16 min | 1.6% |
| atlas | Nifty 50 Top Gainers | nifty50 | 14 | 14 | 1 (1) | 7.1% | 2.0% | 3.57× | 197 min | 4.5% |
| atlas | Today's strong movers | cash | 3 | 1 | 1 (1) | 100.0% | 28.2% | 3.55× | 319 min | 3.2% |
| daytrade | Explosive movement | cash | 9 | 7 | 6 (4) | 85.7% | 28.2% | 3.04× | 36 min | 4.1% |
| atlas | Open interest 7 | fno | 130 | 130 | 11 (11) | 8.5% | 5.0% | 1.68× | 86 min | 4.7% |
| daytrade | High growth stocks | cash | 22 | 17 | 7 (2) | 41.2% | 28.2% | 1.46× | 221 min | 3.5% |
| atlas | 10x volume first 5 min | cash | 57 | 25 | 10 (3) | 40.0% | 28.2% | 1.42× | 74 min | 3.9% |
| daytrade | 10x volume first 5 min | cash | 57 | 25 | 10 (3) | 40.0% | 28.2% | 1.42× | 74 min | 3.9% |
| atlas | Triple bottom | fno | 14 | 14 | 1 (1) | 7.1% | 5.0% | 1.42× | 299 min | 2.4% |
| daytrade | RSI VWAP intraday | fno | 142 | 141 | 10 (10) | 7.1% | 5.0% | 1.41× | 100 min | 4.3% |
| daytrade | 15 minute stock breakouts | fno | 168 | 168 | 11 (11) | 6.5% | 5.0% | 1.30× | 81 min | 4.8% |
| atlas | Long Build Up (fresh) | fno | 133 | 130 | 8 (8) | 6.2% | 5.0% | 1.22× | 78 min | 3.7% |
| daytrade | Strong stocks | cash | 96 | 93 | 24 (10) | 25.8% | 28.2% | 0.92× | 116 min | 4.7% |
| atlas | Cup & Handle Pattern | cash | 61 | 56 | 14 (7) | 25.0% | 28.2% | 0.89× | 252 min | 4.6% |
| daytrade | Short term breakouts | cash | 8 | 4 | 1 (0) | 25.0% | 28.2% | 0.89× | 146 min | 5.8% |
| daytrade | 52 week high stocks | cash | 22 | 19 | 4 (1) | 21.1% | 28.2% | 0.75× | 224 min | 4.5% |
| daytrade | High volume and price breakout stocks | cash | 56 | 10 | 2 (2) | 20.0% | 28.2% | 0.71× | 31 min | 3.0% |
| daytrade | 52 week high breakout | cash | 24 | 21 | 4 (2) | 19.0% | 28.2% | 0.68× | 128 min | 4.2% |
| daytrade | Uptrend - 52 Week High | cash | 24 | 23 | 4 (3) | 17.4% | 28.2% | 0.62× | 111 min | 3.5% |
| atlas | Good quarter result stocks | cash | 15 | 12 | 2 (2) | 16.7% | 28.2% | 0.59× | 120 min | 4.1% |
| daytrade | Multiyear breakout | cash | 736 | 661 | 89 (56) | 13.5% | 28.2% | 0.48× | 191 min | 4.4% |
| atlas | Long tight consolidation stocks | cash | 67 | 67 | 8 (7) | 11.9% | 28.2% | 0.42× | 172 min | 3.8% |
| atlas | RSI ABOVE 50 - DAILY, WEEKLY AND MONTHLY | cash | 22 | 19 | 2 (1) | 10.5% | 28.2% | 0.37× | 321 min | 3.0% |
| atlas | Low PE and High ROCE | cash | 20 | 20 | 1 (0) | 5.0% | 28.2% | 0.18× | 314 min | 3.5% |
| daytrade | Stocks below 50 DMA & 200 DMA | cash | 30 | 30 | 1 (0) | 3.3% | 28.2% | 0.12× | 218 min | 2.4% |
| atlas | Supertrend RSI scan | cash | 9 | 7 | 0 (0) | 0.0% | 28.2% | 0.00× | – | – |
| daytrade | Delivery % + Volume | cash | 16 | 11 | 0 (0) | 0.0% | 28.2% | 0.00× | – | – |

| Several widgets at once | Listed under 5 % | Early movers | Hit rate | Base rate | Lift | Lead (median) | Room left (median) |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2 or more widgets (either dashboard) at the same step | 319 | 44 | 13.8% | 28.2% | 0.49× | 186 min | 4.4% |
| 3 or more widgets (either dashboard) at the same step | 210 | 22 | 10.5% | 28.2% | 0.37× | 76 min | 4.1% |
| 4 or more widgets (either dashboard) at the same step | 168 | 18 | 10.7% | 28.2% | 0.38× | 66 min | 4.5% |
| 2 or more widgets (either dashboard) at the same step — Multiyear breakout not counted | 227 | 27 | 11.9% | 28.2% | 0.42× | 130 min | 3.9% |
| 3 or more widgets (either dashboard) at the same step — Multiyear breakout not counted | 171 | 19 | 11.1% | 28.2% | 0.39× | 63 min | 4.5% |
| 4 or more widgets (either dashboard) at the same step — Multiyear breakout not counted | 120 | 12 | 10.0% | 28.2% | 0.36× | 80 min | 3.7% |

## Liquid movers: which widgets had them before the 5 % mark

| Stock | Range | Direction | 5 % mark | First early widget(s) | Lead | Price at flag | Room left | All early widgets |
|---|---:|---|---:|---|---:|---:|---:|---|
| IZMO | 20.0% | up | 10:22 | none | – | – | – | |
| TECHNOCRAF | 19.2% | up | 10:09 | none | – | – | – | |
| NELCAST | 18.0% | up | 09:17 | none | – | – | – | |
| GOCOLORS | 17.1% | up | 09:55 | none | – | – | – | |
| ECOSMOBLTY | 17.1% | up | 09:40 | none | – | – | – | |
| TAALTECH | 17.0% | up | 13:10 | none | – | – | – | |
| HCG | 16.5% | up | 15:28 | none | – | – | – | |
| TEMPSENS | 16.4% | up | 10:04 | none | – | – | – | |
| VGCL | 15.7% | up | 09:15 | none | – | – | – | |
| TRACXN | 15.7% | up | 10:20 | none | – | – | – | |
| AEGISLOG | 15.1% | up | 11:16 | Multiyear breakout | 116 min | 1,102.70 | 13.7% | Multiyear breakout (09:20) |
| DIGITIDE | 14.7% | down | 09:42 | none | – | – | – | |
| VPRPL | 14.6% | up | 10:09 | none | – | – | – | |
| DEEPINDS | 14.1% | down | 13:15 | none | – | – | – | |
| PRINCEPIPE | 14.1% | down | 13:12 | none | – | – | – | |
| LAXMIINDIA | 13.7% | up | 12:02 | none | – | – | – | |
| KOPRAN | 13.6% | down | 13:37 | none | – | – | – | |
| BHAGCHEM | 13.5% | down | 09:59 | none | – | – | – | |
| SHAREINDIA | 13.5% | up | 13:56 | none | – | – | – | |
| KANOHAR | 13.3% | down | 09:18 | none | – | – | – | |
| CONFIPET | 13.1% | down | 09:44 | none | – | – | – | |
| SUDARSHAN | 13.0% | down | 11:16 | none | – | – | – | |
| FUSION | 12.9% | up | 09:16 | none | – | – | – | |
| SHREEPUSHK | 12.5% | up | 09:17 | none | – | – | – | |
| AGIIL | 12.4% | down | 09:26 | none | – | – | – | |
| JYOTICNC | 12.4% | up | 12:03 | Multiyear breakout | 163 min | 943.95 | 7.5% | Multiyear breakout (09:20) |
| ZYDUSWELL | 12.4% | up | 12:32 | Multiyear breakout | 192 min | 492.75 | 6.9% | Multiyear breakout (09:20) |
| MONQ50 | 12.4% | up | 14:29 | none | – | – | – | |
| MERCANTILE | 12.4% | up | 13:30 | none | – | – | – | |
| MTNL | 12.3% | up | 12:01 | none | – | – | – | |
| 20MICRONS | 12.1% | up | 09:47 | none | – | – | – | |
| TNPETRO | 12.0% | down | 09:16 | none | – | – | – | |
| CARTRADE | 11.9% | up | 11:14 | Multiyear breakout | 114 min | 2,303.00 | 9.2% | Cup & Handle Pattern (09:50); Multiyear breakout (09:20) |
| KISSHT | 11.8% | up | 10:35 | none | – | – | – | |
| INFOBEAN | 11.6% | up | 10:02 | none | – | – | – | |
| DECNGOLD | 11.6% | up | 09:35 | none | – | – | – | |
| AARTECH | 11.5% | up | 11:28 | none | – | – | – | |
| VRLLOG | 11.3% | down | 09:15 | none | – | – | – | |
| PRABHA | 11.3% | up | 10:30 | none | – | – | – | |
| UNITEDPOLY | 11.2% | down | 11:11 | none | – | – | – | |
| TRIDENT | 11.2% | up | 09:19 | none | – | – | – | |
| PREMEXPLN | 11.1% | down | 13:12 | none | – | – | – | |
| KITEX | 11.0% | up | 09:15 | none | – | – | – | |
| LEMERITE | 11.0% | up | 09:25 | none | – | – | – | |
| GREENPANEL | 11.0% | up | 09:46 | none | – | – | – | |
| KRBL | 10.7% | up | 09:17 | none | – | – | – | |
| INDOBORAX | 10.7% | up | 13:13 | none | – | – | – | |
| DGCONTENT | 10.4% | up | 14:35 | none | – | – | – | |
| GANESHCP | 10.3% | down | 11:27 | none | – | – | – | |
| ANDREWYU | 10.2% | up | 13:04 | none | – | – | – | |
| LINC | 10.2% | down | 09:19 | none | – | – | – | |
| RSL | 10.2% | down | 09:56 | Strong stocks | 36 min | 183.35 | 9.4% | Strong stocks (09:20) |
| ITI | 10.1% | down | 09:21 | 10x volume first 5 min; Explosive movement; Multiyear breakout | 1 min | 271.21 | 7.1% | 10x volume first 5 min (09:20); Explosive movement (09:20); Multiyear breakout (09:20) |
| SIGNPOST | 10.1% | down | 09:21 | none | – | – | – | |
| DEVX | 10.1% | up | 10:00 | none | – | – | – | |
| LASERPOWER | 10.1% | up | 14:07 | none | – | – | – | |
| MINDACORP | 10.0% | up | 15:00 | Multiyear breakout | 315 min | 659.70 | 8.2% | Cup & Handle Pattern (10:40); Multiyear breakout (09:45) |
| BALAMINES | 10.0% | down | 09:17 | none | – | – | – | |
| EMCURE | 10.0% | up | 13:41 | Multiyear breakout | 261 min | 1,908.70 | 8.5% | Multiyear breakout (09:20) |
| GRAUWEIL | 10.0% | down | 13:59 | none | – | – | – | |
| BALRAMCHIN | 10.0% | up | 09:39 | Cup & Handle Pattern; Multiyear breakout | 19 min | 623.20 | 6.8% | Cup & Handle Pattern (09:20); Multiyear breakout (09:20) |
| MUFTI | 9.9% | up | 09:53 | none | – | – | – | |
| ALGOQUANT | 9.9% | down | 09:53 | none | – | – | – | |
| CARBORUNIV | 9.8% | up | 09:19 | none | – | – | – | |
| SURAJEST | 9.8% | up | 15:07 | none | – | – | – | |
| PSPPROJECT | 9.7% | down | 09:17 | none | – | – | – | |
| SAGARDEEP | 9.7% | up | 09:30 | none | – | – | – | |
| ORIENTTECH | 9.6% | down | 09:15 | none | – | – | – | |
| SEJALLTD | 9.6% | up | 09:59 | none | – | – | – | |
| ALKYLAMINE | 9.6% | down | 11:13 | none | – | – | – | |
| ESTER | 9.6% | down | 13:49 | none | – | – | – | |
| XTRANET | 9.5% | down | 10:20 | none | – | – | – | |
| YATHARTH | 9.4% | up | 14:08 | none | – | – | – | |
| AMANTA | 9.4% | up | 09:48 | none | – | – | – | |
| TCC | 9.4% | down | 09:25 | none | – | – | – | |
| RAIN | 9.3% | down | 11:40 | Cup & Handle Pattern | 135 min | 198.27 | 8.7% | Cup & Handle Pattern (09:25) |
| PFS | 9.2% | up | 13:15 | Multiyear breakout | 45 min | 24.09 | 7.1% | Multiyear breakout (12:30) |
| AKUMS | 9.2% | down | 09:17 | none | – | – | – | |
| IVALUE | 9.2% | down | 11:31 | none | – | – | – | |
| SOUTHWEST | 9.2% | up | 10:25 | none | – | – | – | |
| MARSONS | 9.1% | down | 11:36 | Multiyear breakout | 126 min | 158.23 | 3.9% | Multiyear breakout (09:30) |
| NRAIL | 9.0% | down | 09:46 | none | – | – | – | |
| MPIMANIPAL | 9.0% | up | 09:40 | none | – | – | – | |
| TIGERLOGS | 8.9% | down | 10:27 | Strong stocks | 67 min | 25.23 | 7.6% | Strong stocks (09:20) |
| GANECOS | 8.9% | down | 10:31 | none | – | – | – | |
| WHEELS | 8.8% | up | 14:32 | none | – | – | – | |
| VIVIANA | 8.8% | down | 09:44 | none | – | – | – | |
| GRSE | 8.8% | up | 09:43 | Multiyear breakout | 23 min | 2,069.50 | 8.0% | Multiyear breakout (09:20) |
| DCMSIL | 8.8% | down | 11:58 | none | – | – | – | |
| PURVA | 8.7% | down | 09:18 | none | – | – | – | |
| SHANTIGOLD | 8.6% | down | 10:43 | none | – | – | – | |
| MCX | 8.6% | up | 12:25 | 15 minute stock breakouts; Long Build Up (fresh); Multiyear breakout; RSI VWAP intraday | 185 min | 3,278.20 | 7.9% | 15 minute stock breakouts (09:20); Long Build Up (fresh) (09:20); Multiyear breakout (09:20); Open interest 7 (09:35); RSI VWAP intraday (09:20); Uptrend - 52 Week High (12:25) |
| HIKAL | 8.6% | down | 14:25 | Strong stocks | 265 min | 222.34 | 4.6% | Strong stocks (10:00) |
| SHIVALIK | 8.6% | up | 12:04 | none | – | – | – | |
| SHK | 8.5% | down | 10:18 | none | – | – | – | |
| DELTACORP | 8.5% | down | 13:01 | Multiyear breakout | 156 min | 76.04 | 5.8% | Multiyear breakout (10:25) |
| SINGERIND | 8.5% | down | 13:46 | none | – | – | – | |
| MOBIKWIK | 8.5% | down | 09:22 | none | – | – | – | |
| WELSPUNLIV | 8.5% | up | 09:50 | 10x volume first 5 min; 52 week high breakout; 52 week high stocks; Explosive movement; Multiyear breakout; Uptrend - 52 Week High | 30 min | 245.84 | 4.6% | 10x volume first 5 min (09:20); 52 week high breakout (09:20); 52 week high stocks (09:20); Explosive movement (09:20); Multiyear breakout (09:20); Uptrend - 52 Week High (09:20) |
| AONESTEELS | 8.5% | up | 15:24 | none | – | – | – | |
| JINDALPOLY | 8.4% | up | 09:29 | none | – | – | – | |
| BETA | 8.4% | down | 12:32 | none | – | – | – | |
| SUDARSCHEM | 8.4% | up | 13:20 | none | – | – | – | |
| ONEPOINT | 8.3% | up | 09:29 | none | – | – | – | |
| VASCONEQ | 8.3% | up | 15:01 | none | – | – | – | |
| AYMSYNTEX | 8.3% | up | 10:27 | Strong stocks | 67 min | 264.52 | 5.8% | Strong stocks (09:20) |
| MANGLMCEM | 8.3% | down | 15:18 | none | – | – | – | |
| ATLANTAELE | 8.3% | down | 10:03 | Explosive movement | 43 min | 1,419.70 | 6.4% | Explosive movement (09:20); Multiyear breakout (09:25) |
| ZIMLAB | 8.2% | up | 12:53 | none | – | – | – | |
| MOIL | 8.2% | down | 14:08 | none | – | – | – | |
| INDSWFTLAB | 8.1% | down | 13:08 | none | – | – | – | |
| EFCIL | 8.1% | down | 09:34 | none | – | – | – | |
| MAFANG | 8.1% | down | 10:05 | none | – | – | – | |
| JAYBARMARU | 8.1% | down | 09:15 | none | – | – | – | |
| PICCADIL | 8.1% | up | 13:26 | none | – | – | – | |
| ANGELONE | 8.1% | up | 10:30 | 15 minute stock breakouts; Multiyear breakout; Open interest 7; RSI VWAP intraday | 70 min | 294.35 | 7.3% | 15 minute stock breakouts (09:20); Long Build Up (fresh) (10:20); Multiyear breakout (09:20); Open interest (10:30); Open interest 7 (09:20); RSI VWAP intraday (09:20) |
| KRISHNADEF | 8.1% | up | 09:44 | none | – | – | – | |
| AWHCL | 8.0% | down | 10:02 | none | – | – | – | |
| NGIL | 8.0% | up | 12:13 | none | – | – | – | |
| DHOOTTRANS | 8.0% | down | 15:06 | none | – | – | – | |
| UNIPARTS | 8.0% | up | 09:52 | none | – | – | – | |
| GYFTR | 7.9% | up | 09:31 | none | – | – | – | |
| MOMSBELIEF | 7.9% | down | 12:26 | none | – | – | – | |
| ARFIN | 7.9% | up | 09:21 | none | – | – | – | |
| NITCO | 7.9% | down | 14:22 | none | – | – | – | |
| MONEYVIEW | 7.9% | up | 11:17 | Multiyear breakout | 117 min | 51.77 | 6.5% | Multiyear breakout (09:20) |
| RUSTOMJEE | 7.8% | up | 13:54 | none | – | – | – | |
| GRANULES | 7.7% | down | 09:16 | none | – | – | – | |
| KAMDHENU | 7.6% | up | 09:16 | none | – | – | – | |
| WALCHANNAG | 7.6% | down | 15:02 | none | – | – | – | |
| PVP | 7.6% | down | 11:31 | none | – | – | – | |
| GRMOVER | 7.6% | up | 14:31 | Multiyear breakout | 11 min | 91.12 | 5.4% | Multiyear breakout (14:20) |
| LATENTVIEW | 7.6% | down | 09:52 | none | – | – | – | |
| SSWL | 7.6% | up | 14:22 | High growth stocks | 252 min | 496.75 | 6.1% | High growth stocks (10:10) |
| MGL | 7.5% | up | 14:36 | Long tight consolidation stocks; Multiyear breakout | 316 min | 1,050.00 | 2.8% | Long tight consolidation stocks (09:20); Multiyear breakout (09:20) |
| RAMKY | 7.5% | up | 09:21 | none | – | – | – | |
| AJMERA | 7.5% | up | 12:16 | none | – | – | – | |
| RESPONIND | 7.5% | down | 10:49 | none | – | – | – | |
| STEAMHOUSE | 7.4% | down | 12:07 | none | – | – | – | |
| PRIMO | 7.4% | down | 09:19 | none | – | – | – | |
| SHANKARA | 7.4% | down | 14:26 | none | – | – | – | |
| JAINREC | 7.4% | down | 12:09 | none | – | – | – | |
| SOLARINDS | 7.4% | up | 14:05 | 15 minute stock breakouts; Long Build Up (fresh); Multiyear breakout; RSI VWAP intraday | 285 min | 19,581.00 | 6.6% | 15 minute stock breakouts (09:20); Long Build Up (fresh) (09:20); Multiyear breakout (09:20); Open interest 7 (12:35); RSI VWAP intraday (09:20) |
| KEC | 7.4% | down | 11:08 | 10x volume first 5 min | 103 min | 333.70 | 6.8% | 10x volume first 5 min (09:25) |
| GNFC | 7.4% | down | 10:17 | none | – | – | – | |
| INDOSTAR | 7.4% | up | 11:37 | none | – | – | – | |
| RPEL | 7.4% | up | 10:42 | none | – | – | – | |
| MASPTOP50 | 7.3% | down | 15:09 | none | – | – | – | |
| SPENCERS | 7.3% | up | 09:45 | none | – | – | – | |
| ASAHIINDIA | 7.3% | up | 14:45 | Multiyear breakout | 325 min | 951.80 | 6.6% | High volume and price breakout stocks (13:45); Multiyear breakout (09:20) |
| FAZE3Q | 7.3% | up | 14:51 | Strong stocks | 326 min | 440.00 | 4.3% | Strong stocks (09:25) |
| JISLJALEQS | 7.3% | up | 14:33 | Multiyear breakout | 313 min | 27.96 | 5.5% | Multiyear breakout (09:20) |
| HIMATSEIDE | 7.3% | down | 15:12 | none | – | – | – | |
| GARUDA | 7.3% | up | 14:07 | none | – | – | – | |
| ADFFOODS | 7.2% | up | 09:55 | none | – | – | – | |
| MOLDTKPAC | 7.2% | up | 09:19 | none | – | – | – | |
| THOMASCOOK | 7.2% | down | 09:55 | none | – | – | – | |
| ATLANTAA | 7.2% | down | 13:02 | none | – | – | – | |
| AAATECH | 7.2% | down | 14:05 | none | – | – | – | |
| CSM | 7.2% | down | 14:54 | none | – | – | – | |
| ADROITIND | 7.2% | up | 10:36 | none | – | – | – | |
| RTNINDIA | 7.1% | up | 09:15 | none | – | – | – | |
| DJML | 7.1% | down | 15:12 | none | – | – | – | |
| ARVINDFASN | 7.1% | down | 10:20 | none | – | – | – | |
| TBOTEK | 7.1% | up | 13:12 | none | – | – | – | |
| NACLIND | 7.1% | down | 09:20 | none | – | – | – | |
| DPWIRES | 7.0% | up | 14:38 | none | – | – | – | |
| SONA | 7.0% | up | 10:41 | none | – | – | – | |
| SMCGLOBAL | 7.0% | down | 14:32 | Multiyear breakout | 67 min | 92.80 | 4.1% | Multiyear breakout (13:25) |
| GODIGIT | 7.0% | down | 11:32 | none | – | – | – | |
| MOTILALOFS | 7.0% | up | 09:44 | 15 minute stock breakouts; Multiyear breakout; Open interest 7; RSI VWAP intraday | 24 min | 981.70 | 5.1% | 15 minute stock breakouts (09:20); Long Build Up (fresh) (09:25); Multiyear breakout (09:20); Open interest 7 (09:20); RSI VWAP intraday (09:20) |
| OSWALAGRO | 6.9% | up | 11:43 | none | – | – | – | |
| SIMPLEXINF | 6.9% | up | 10:38 | none | – | – | – | |
| JTLIND | 6.9% | down | 09:46 | Strong stocks | 26 min | 77.09 | 4.6% | Strong stocks (09:20) |
| WONDERLA | 6.9% | up | 09:55 | none | – | – | – | |
| PRIORITY | 6.9% | up | 09:47 | none | – | – | – | |
| BLS | 6.8% | up | 14:38 | none | – | – | – | |
| WSI | 6.8% | down | 12:17 | none | – | – | – | |
| LODHA | 6.8% | up | 10:28 | 15 minute stock breakouts; Cup & Handle Pattern; Multiyear breakout | 68 min | 1,012.60 | 5.6% | 15 minute stock breakouts (09:20); Cup & Handle Pattern (09:20); Multiyear breakout (09:20); Open interest 7 (09:25) |
| TRIVENI | 6.8% | down | 09:34 | 10x volume first 5 min; Multiyear breakout | 9 min | 250.94 | 4.3% | 10x volume first 5 min (09:25); Multiyear breakout (09:25) |
| AEROFLEX | 6.8% | up | 10:46 | Multiyear breakout | 36 min | 525.60 | 2.5% | Multiyear breakout (10:10) |
| HALDYNGL | 6.8% | up | 12:52 | none | – | – | – | |
| OAL | 6.7% | down | 09:54 | none | – | – | – | |
| INTELLECT | 6.7% | down | 12:51 | none | – | – | – | |
| HUBTOWN | 6.7% | down | 15:02 | none | – | – | – | |
| KOTIC | 6.7% | up | 09:41 | none | – | – | – | |
| JKIPL | 6.7% | down | 15:10 | none | – | – | – | |
| ZENTEC | 6.7% | up | 09:33 | Good quarter result stocks | 8 min | 1,670.00 | 4.2% | Good quarter result stocks (09:25) |
| MSTCLTD | 6.7% | up | 10:01 | none | – | – | – | |
| SAIPARENT | 6.7% | down | 15:05 | none | – | – | – | |
| GRWRHITECH | 6.6% | up | 13:02 | Multiyear breakout | 222 min | 7,016.00 | 5.8% | Long tight consolidation stocks (09:45); Multiyear breakout (09:20); Uptrend - 52 Week High (09:50) |
| DOLLEX | 6.6% | down | 14:28 | none | – | – | – | |
| DIVGIITTS | 6.6% | down | 09:23 | none | – | – | – | |
| BECTORFOOD | 6.6% | up | 09:29 | none | – | – | – | |
| MANINFRA | 6.6% | down | 14:29 | Multiyear breakout | 129 min | 109.95 | 5.0% | Multiyear breakout (12:20) |
| GSPCROP | 6.6% | down | 09:15 | none | – | – | – | |
| TIMEX | 6.6% | up | 09:35 | none | – | – | – | |
| COMSYN | 6.6% | up | 14:27 | none | – | – | – | |
| KLBRENG-B | 6.5% | down | 14:30 | none | – | – | – | |
| MAYURUNIQ | 6.5% | up | 10:08 | none | – | – | – | |
| BHAGERIA | 6.5% | down | 10:37 | none | – | – | – | |
| SFL | 6.5% | down | 11:03 | none | – | – | – | |
| LOKESHMACH | 6.5% | down | 10:47 | none | – | – | – | |
| KAPSTON | 6.5% | up | 09:58 | none | – | – | – | |
| OPTIEMUS | 6.5% | down | 09:26 | none | – | – | – | |
| HARIOMPIPE | 6.5% | up | 12:26 | none | – | – | – | |
| SHRINGARMS | 6.4% | down | 14:45 | Cup & Handle Pattern | 315 min | 287.80 | 4.8% | Cup & Handle Pattern (09:30) |
| EPACKPEB | 6.4% | down | 13:11 | none | – | – | – | |
| SOLARWORLD | 6.4% | down | 13:59 | none | – | – | – | |
| WINDMACHIN | 6.4% | up | 11:27 | none | – | – | – | |
| AVTNPL | 6.4% | up | 11:22 | none | – | – | – | |
| RAJOOENG | 6.4% | up | 11:46 | Strong stocks | 146 min | 53.31 | 6.0% | Strong stocks (09:20) |
| KAMATHOTEL | 6.4% | up | 15:03 | none | – | – | – | |
| AFFLE | 6.4% | up | 15:06 | Multiyear breakout | 346 min | 1,524.50 | 5.0% | Explosive movement (09:30); Multiyear breakout (09:20) |
| RELAXO | 6.4% | down | 09:15 | none | – | – | – | |
| EXCELSOFT | 6.4% | up | 15:26 | Multiyear breakout | 11 min | 78.81 | 3.8% | Multiyear breakout (15:15) |
| AWFIS | 6.4% | down | 15:04 | none | – | – | – | |
| BROOKS | 6.4% | up | 10:21 | none | – | – | – | |
| SKIPPER | 6.3% | up | 13:49 | none | – | – | – | |
| TANLA | 6.3% | up | 13:17 | Strong stocks | 237 min | 653.40 | 3.7% | 52 week high breakout (13:15); Good quarter result stocks (09:25); Strong stocks (09:20) |
| MENONBE | 6.3% | up | 09:39 | High growth stocks | 9 min | 309.90 | 3.9% | High growth stocks (09:30) |
| KOLTEPATIL | 6.3% | down | 11:52 | none | – | – | – | |
| NITINSPIN | 6.3% | down | 13:26 | 52 week high stocks; Multiyear breakout; Strong stocks | 246 min | 677.25 | 3.3% | 52 week high breakout (09:40); 52 week high stocks (09:20); High growth stocks (09:45); Multiyear breakout (09:20); Short term breakouts (11:00); Strong stocks (09:20) |
| IITL | 6.3% | down | 15:12 | none | – | – | – | |
| POONAWALLA | 6.3% | up | 14:50 | Cup & Handle Pattern; Explosive movement | 330 min | 473.40 | 3.5% | Cup & Handle Pattern (09:20); Explosive movement (09:20) |
| HEROMOTORS | 6.2% | up | 09:27 | Multiyear breakout | 2 min | 118.58 | 2.4% | Multiyear breakout (09:25) |
| LAGNAM | 6.2% | down | 10:12 | none | – | – | – | |
| OMINFRAL | 6.2% | down | 09:16 | none | – | – | – | |
| SUNFLAG | 6.2% | down | 15:08 | none | – | – | – | |
| GUJTHEM | 6.2% | up | 10:28 | none | – | – | – | |
| AYE | 6.2% | up | 11:43 | none | – | – | – | |
| GREAVESCOT | 6.2% | down | 14:53 | Cup & Handle Pattern | 328 min | 207.58 | 5.0% | Cup & Handle Pattern (09:25) |
| SENORES | 6.2% | up | 09:51 | none | – | – | – | |
| KOTYARK | 6.1% | up | 15:15 | none | – | – | – | |
| GODFRYPHLP | 6.1% | up | 09:56 | 15 minute stock breakouts; Multiyear breakout; Open interest 7; RSI VWAP intraday | 36 min | 1,731.70 | 4.8% | 15 minute stock breakouts (09:20); Long Build Up (fresh) (09:40); Multiyear breakout (09:20); Open interest (09:40); Open interest 7 (09:20); RSI VWAP intraday (09:20) |
| CAMLINFINE | 6.1% | up | 15:21 | none | – | – | – | |
| JTEKTINDIA | 6.1% | up | 10:49 | none | – | – | – | |
| SHARDACROP | 6.1% | down | 15:10 | none | – | – | – | |
| NAVNETEDUL | 6.1% | up | 10:16 | none | – | – | – | |
| SPANDANA | 6.1% | up | 10:42 | none | – | – | – | |
| JSFB | 6.1% | down | 14:18 | none | – | – | – | |
| FINPIPE | 6.1% | down | 13:06 | none | – | – | – | |
| MACPOWER | 6.1% | down | 09:20 | none | – | – | – | |
| 63MOONS | 6.0% | down | 15:06 | Strong stocks | 346 min | 964.00 | 5.5% | Strong stocks (09:20) |
| UTTAMSUGAR | 6.0% | down | 09:17 | none | – | – | – | |
| PRAJIND | 6.0% | down | 14:38 | 10x volume first 5 min | 193 min | 263.60 | 3.8% | 10x volume first 5 min (11:25) |
| IGCL | 6.0% | down | 10:47 | none | – | – | – | |
| SMARTLINK | 6.0% | down | 13:30 | none | – | – | – | |
| LTFOODS | 6.0% | up | 15:26 | Multiyear breakout | 366 min | 399.30 | 4.1% | Multiyear breakout (09:20) |
| WOCKPHARMA | 6.0% | up | 09:41 | none | – | – | – | |
| LCCPROJECT | 6.0% | up | 11:04 | Strong stocks | 99 min | 133.41 | 4.9% | Strong stocks (09:25) |
| MANIKA | 6.0% | down | 09:24 | none | – | – | – | |
| MTARTECH | 5.9% | down | 09:21 | none | – | – | – | |
| BLSE | 5.9% | down | 12:32 | none | – | – | – | |
| BSE | 5.9% | up | 12:52 | 15 minute stock breakouts; Multiyear breakout | 212 min | 3,508.20 | 4.8% | 15 minute stock breakouts (09:20); Multiyear breakout (09:20); Nifty 50 Top Gainers (09:35); Open interest 7 (09:50); RSI VWAP intraday (09:50) |
| WHIRLPOOL | 5.9% | down | 15:12 | Multiyear breakout | 352 min | 828.00 | 2.4% | Multiyear breakout (09:20) |
| IIFL | 5.9% | down | 14:11 | Cup & Handle Pattern; Multiyear breakout | 291 min | 560.45 | 3.9% | Cup & Handle Pattern (09:20); Multiyear breakout (09:20) |
| MMP | 5.9% | down | 14:36 | none | – | – | – | |
| FLUOROCHEM | 5.8% | up | 12:04 | Multiyear breakout | 164 min | 4,369.30 | 5.3% | Long tight consolidation stocks (09:25); Multiyear breakout (09:20) |
| PASUPTAC | 5.8% | up | 09:26 | none | – | – | – | |
| VMART | 5.8% | up | 15:25 | none | – | – | – | |
| JAIBALAJI | 5.8% | up | 09:23 | none | – | – | – | |
| STARHEALTH | 5.8% | up | 15:27 | Multiyear breakout | 367 min | 514.80 | 3.9% | Multiyear breakout (09:20) |
| BUILDPRO | 5.8% | up | 09:23 | none | – | – | – | |
| RAMCOCEM | 5.8% | up | 09:28 | Multiyear breakout | 8 min | 768.90 | 2.1% | Multiyear breakout (09:20) |
| MARATHON | 5.8% | up | 09:22 | Strong stocks | 2 min | 385.20 | 3.2% | Strong stocks (09:20) |
| FRACTAL | 5.8% | down | 15:29 | Multiyear breakout | 369 min | 744.25 | 5.6% | Multiyear breakout (09:20) |
| WELCORP | 5.7% | down | 15:27 | High growth stocks; Multiyear breakout | 367 min | 2,399.20 | 5.3% | High growth stocks (09:20); Multiyear breakout (09:20) |
| ELEVATE | 5.7% | down | 15:19 | none | – | – | – | |
| IDEAFORGE | 5.7% | down | 10:19 | Cup & Handle Pattern | 59 min | 663.15 | 2.4% | Cup & Handle Pattern (09:20) |
| FIVESTAR | 5.7% | down | 14:34 | Low PE and High ROCE; Multiyear breakout | 314 min | 409.40 | 3.5% | Low PE and High ROCE (09:20); Multiyear breakout (09:20) |
| RBA | 5.7% | up | 12:31 | Multiyear breakout | 176 min | 87.06 | 4.0% | Multiyear breakout (09:35) |
| CDSL | 5.7% | up | 10:46 | Multiyear breakout; Open interest 7 | 86 min | 1,271.50 | 4.8% | 15 minute stock breakouts (09:25); Long Build Up (fresh) (09:55); Multiyear breakout (09:20); Open interest (10:25); Open interest 7 (09:20); RSI VWAP intraday (10:10) |
| PRASOLCHEM | 5.7% | down | 09:40 | none | – | – | – | |
| GAUDIUMIVF | 5.7% | up | 12:27 | none | – | – | – | |
| TARSONS | 5.7% | up | 10:28 | none | – | – | – | |
| TRUALT | 5.7% | down | 14:56 | none | – | – | – | |
| SUBROS | 5.7% | down | 15:19 | none | – | – | – | |
| UDS | 5.7% | down | 13:35 | none | – | – | – | |
| SKMEGGPROD | 5.7% | down | 15:02 | none | – | – | – | |
| MERCURYEV | 5.7% | up | 14:16 | none | – | – | – | |
| SEIL | 5.7% | down | 13:12 | none | – | – | – | |
| GREENPLY | 5.7% | down | 14:41 | none | – | – | – | |
| JINDWORLD | 5.6% | down | 09:15 | none | – | – | – | |
| CHEMPLASTS | 5.6% | up | 10:32 | none | – | – | – | |
| HUHTAMAKI | 5.6% | down | 14:48 | none | – | – | – | |
| REMSONSIND | 5.6% | down | 14:25 | none | – | – | – | |
| PRADPME | 5.6% | up | 09:39 | none | – | – | – | |
| FERMENTA | 5.6% | up | 10:37 | none | – | – | – | |
| ORIENTCABL | 5.6% | down | 10:44 | none | – | – | – | |
| WELSPLSOL | 5.6% | down | 15:04 | none | – | – | – | |
| BATLIBOI | 5.6% | down | 15:12 | Strong stocks | 337 min | 90.56 | 4.8% | Strong stocks (09:35) |
| MARICO | 5.6% | up | 14:54 | 10x volume first 5 min; 15 minute stock breakouts; Long Build Up (fresh); Multiyear breakout; Open interest; Open interest 7; RSI VWAP intraday | 334 min | 842.65 | 3.5% | 10x volume first 5 min (09:20); 15 minute stock breakouts (09:20); Cup & Handle Pattern (09:40); Long Build Up (fresh) (09:20); Multiyear breakout (09:20); Open interest (09:20); Open interest 7 (09:20); RSI ABOVE 50 - DAILY, WEEKLY AND MONTHLY (09:55); RSI VWAP intraday (09:20); Today's strong move |
| KRSNAA | 5.6% | up | 15:15 | none | – | – | – | |
| AZAD | 5.6% | up | 10:33 | Multiyear breakout | 73 min | 2,529.70 | 4.9% | Multiyear breakout (09:20) |
| AARTIIND | 5.6% | up | 09:28 | Multiyear breakout | 8 min | 440.00 | 4.2% | Multiyear breakout (09:20) |
| DDEVPLSTIK | 5.6% | up | 13:55 | none | – | – | – | |
| ENGINERSIN | 5.5% | up | 09:26 | Explosive movement | 6 min | 287.50 | 2.9% | 10x volume first 5 min (09:25); Explosive movement (09:20); Multiyear breakout (09:25) |
| SPARC | 5.5% | up | 09:53 | none | – | – | – | |
| KIRLFER | 5.5% | down | 13:54 | none | – | – | – | |
| RISHABH | 5.5% | down | 10:41 | none | – | – | – | |
| YASHO | 5.5% | up | 14:20 | none | – | – | – | |
| THELEELA | 5.5% | down | 15:08 | Multiyear breakout; Uptrend - 52 Week High | 348 min | 668.40 | 3.1% | 52 week high stocks (11:45); Multiyear breakout (09:20); RSI ABOVE 50 - DAILY, WEEKLY AND MONTHLY (09:25); Uptrend - 52 Week High (09:20) |
| INDIASHLTR | 5.5% | up | 15:06 | none | – | – | – | |
| OLAELEC | 5.5% | up | 13:18 | Multiyear breakout | 228 min | 35.07 | 1.9% | Multiyear breakout (09:30) |
| MAZDOCK | 5.5% | up | 09:57 | Multiyear breakout | 37 min | 1,742.70 | 5.1% | 15 minute stock breakouts (09:30); Multiyear breakout (09:20); Open interest 7 (09:25); RSI VWAP intraday (09:30) |
| SAKSOFT | 5.5% | up | 10:19 | none | – | – | – | |
| AAREYDRUGS | 5.5% | down | 13:31 | none | – | – | – | |
| LAXMIDENTL | 5.5% | down | 14:49 | none | – | – | – | |
| SRIT | 5.5% | down | 13:55 | Strong stocks | 270 min | 120.00 | 4.2% | Strong stocks (09:25) |
| CRIZAC | 5.5% | up | 12:59 | none | – | – | – | |
| XPROINDIA | 5.5% | up | 13:04 | none | – | – | – | |
| CCAVENUE | 5.5% | up | 09:41 | none | – | – | – | |
| MMFL | 5.5% | down | 14:32 | none | – | – | – | |
| MCLEODRUSS | 5.5% | down | 14:38 | none | – | – | – | |
| EPIGRAL | 5.5% | down | 11:32 | none | – | – | – | |
| SHUKRAPHAR | 5.5% | down | 12:57 | Multiyear breakout | 207 min | 82.25 | 3.0% | Multiyear breakout (09:30) |
| ASTEC | 5.4% | up | 12:21 | none | – | – | – | |
| ONIDA | 5.4% | down | 14:15 | none | – | – | – | |
| SANGHVIMOV | 5.4% | down | 11:45 | 10x volume first 5 min; Multiyear breakout | 95 min | 326.80 | 3.3% | 10x volume first 5 min (10:10); Multiyear breakout (10:10) |
| KUANTUM | 5.4% | down | 14:46 | none | – | – | – | |
| SHADOWFAX | 5.4% | up | 14:22 | Multiyear breakout | 302 min | 274.35 | 3.8% | Multiyear breakout (09:20) |
| ADVENZYMES | 5.4% | down | 14:42 | none | – | – | – | |
| ARIHANTCAP | 5.4% | up | 09:25 | none | – | – | – | |
| KOHINOOR | 5.4% | down | 15:14 | none | – | – | – | |
| NUVAMA | 5.4% | up | 14:33 | Multiyear breakout | 313 min | 1,800.10 | 4.1% | Multiyear breakout (09:20) |
| REDINGTON | 5.4% | up | 15:25 | Multiyear breakout | 345 min | 330.25 | 2.4% | Multiyear breakout (09:40) |
| NITYAS | 5.4% | down | 14:56 | none | – | – | – | |
| DHARMAJ | 5.4% | down | 15:12 | none | – | – | – | |
| XCHANGING | 5.4% | up | 12:35 | none | – | – | – | |
| HEXAGON | 5.3% | down | 14:13 | none | – | – | – | |
| VINDHYATEL | 5.3% | down | 09:59 | none | – | – | – | |
| IOLCP | 5.3% | down | 15:25 | none | – | – | – | |
| SUVEN | 5.3% | down | 14:35 | none | – | – | – | |
| CHAMBLFERT | 5.3% | up | 13:03 | Multiyear breakout | 223 min | 372.00 | 4.4% | Multiyear breakout (09:20) |
| GROWW | 5.3% | up | 15:12 | Multiyear breakout; Strong stocks | 352 min | 198.13 | 4.4% | Multiyear breakout (09:20); Strong stocks (09:20) |
| ANTELOPUS | 5.3% | down | 15:05 | High growth stocks | 15 min | 981.50 | 1.1% | High growth stocks (14:50) |
| GNRL | 5.3% | down | 11:52 | none | – | – | – | |
| HTEL | 5.3% | up | 11:28 | none | – | – | – | |
| DREDGECORP | 5.3% | up | 10:17 | none | – | – | – | |
| GLASSWALL | 5.3% | up | 11:55 | none | – | – | – | |
| ABDL | 5.3% | down | 14:40 | Multiyear breakout | 320 min | 723.60 | 4.5% | Multiyear breakout (09:20) |
| PNGSREVA | 5.3% | up | 10:44 | none | – | – | – | |
| RRKABEL | 5.3% | up | 13:31 | Multiyear breakout | 251 min | 1,947.60 | 3.7% | Multiyear breakout (09:20) |
| GRINDWELL | 5.3% | down | 14:59 | Multiyear breakout | 339 min | 2,001.10 | 4.2% | Multiyear breakout (09:20) |
| MANAKCOAT | 5.3% | down | 13:57 | none | – | – | – | |
| ROUTE | 5.3% | up | 09:51 | none | – | – | – | |
| DMCC | 5.3% | down | 15:10 | none | – | – | – | |
| CAMS | 5.3% | up | 11:30 | 15 minute stock breakouts; Multiyear breakout; Open interest 7; RSI VWAP intraday | 130 min | 678.00 | 3.5% | 15 minute stock breakouts (09:20); Long Build Up (fresh) (09:45); Long tight consolidation stocks (09:25); Multiyear breakout (09:20); Open interest (11:30); Open interest 7 (09:20); RSI VWAP intraday (09:20) |
| SPMLINFRA | 5.2% | up | 14:14 | none | – | – | – | |
| EUREKAFORB | 5.2% | down | 10:36 | none | – | – | – | |
| GODREJIND | 5.2% | up | 10:53 | Multiyear breakout | 93 min | 939.15 | 4.4% | Multiyear breakout (09:20) |
| SHANKESH | 5.2% | up | 09:41 | none | – | – | – | |
| ORIENTCEM | 5.2% | up | 09:33 | none | – | – | – | |
| APARINDS | 5.2% | down | 15:11 | Multiyear breakout | 351 min | 15,950.00 | 3.8% | Multiyear breakout (09:20) |
| SUMICHEM | 5.2% | down | 15:08 | Multiyear breakout | 348 min | 324.95 | 3.8% | Multiyear breakout (09:20) |
| MAXIND | 5.2% | down | 10:23 | none | – | – | – | |
| SPORTKING | 5.2% | down | 13:28 | Cup & Handle Pattern; High growth stocks | 243 min | 194.01 | 3.5% | Cup & Handle Pattern (09:25); High growth stocks (09:25) |
| UNIMECH | 5.2% | up | 10:04 | none | – | – | – | |
| VSSL | 5.2% | up | 13:54 | none | – | – | – | |
| INTLCONV | 5.2% | down | 15:10 | none | – | – | – | |
| AFCONS | 5.2% | down | 15:18 | none | – | – | – | |
| VENUSPIPES | 5.2% | up | 11:50 | none | – | – | – | |
| KMSUGAR | 5.2% | up | 09:17 | none | – | – | – | |
| KRISHANA | 5.2% | down | 13:26 | 52 week high breakout; 52 week high stocks; Multiyear breakout; Strong stocks | 246 min | 238.70 | 4.5% | 52 week high breakout (09:20); 52 week high stocks (09:20); Cup & Handle Pattern (09:30); Multiyear breakout (09:20); Strong stocks (09:20) |
| KPEL | 5.1% | down | 15:07 | none | – | – | – | |
| TEGA | 5.1% | down | 10:19 | Multiyear breakout | 59 min | 1,712.10 | 1.1% | Multiyear breakout (09:20) |
| DALBHARAT | 5.1% | down | 13:48 | Multiyear breakout | 268 min | 1,398.60 | 2.4% | Multiyear breakout (09:20); Stocks below 50 DMA & 200 DMA (10:10) |
| JASH | 5.1% | down | 15:29 | none | – | – | – | |
| PROTEAN | 5.1% | down | 14:09 | none | – | – | – | |
| AEGISVOPAK | 5.1% | up | 12:53 | Multiyear breakout | 213 min | 231.41 | 3.5% | Multiyear breakout (09:20) |
| INDOAMIN | 5.1% | down | 14:51 | none | – | – | – | |
| EBGNG | 5.1% | up | 15:29 | none | – | – | – | |
| BAJAJCON | 5.1% | up | 09:42 | none | – | – | – | |
| TREL | 5.1% | up | 09:20 | none | – | – | – | |
| TI | 5.1% | down | 15:29 | Multiyear breakout | 369 min | 482.65 | 4.3% | Multiyear breakout (09:20) |
| ATL | 5.1% | down | 15:08 | none | – | – | – | |
| HATSUN | 5.1% | up | 11:07 | Multiyear breakout | 107 min | 1,016.90 | 3.0% | Multiyear breakout (09:20) |
| RATNAVEER | 5.1% | down | 10:18 | High growth stocks | 58 min | 381.30 | 3.4% | 10x volume first 5 min (09:25); High growth stocks (09:20); Multiyear breakout (09:25) |
| HNDFDS | 5.1% | up | 15:12 | none | – | – | – | |
| LLOYDSENGG | 5.1% | down | 15:29 | 10x volume first 5 min | 369 min | 82.54 | 4.0% | 10x volume first 5 min (09:20) |
| AMAGI | 5.1% | up | 11:48 | Multiyear breakout | 148 min | 543.60 | 4.9% | Long tight consolidation stocks (10:40); Multiyear breakout (09:20) |
| SERVOTECH | 5.1% | down | 14:21 | none | – | – | – | |
| MBEL | 5.1% | down | 15:29 | none | – | – | – | |
| BBL | 5.1% | up | 12:06 | none | – | – | – | |
| WCIL | 5.0% | down | 11:32 | none | – | – | – | |
| GOKEX | 5.0% | up | 12:32 | none | – | – | – | |
| EMBDL | 5.0% | up | 09:24 | none | – | – | – | |
| JWL | 5.0% | up | 10:20 | Multiyear breakout | 0 min | 197.78 | 0.5% | Multiyear breakout (10:20) |
| BHARATWIRE | 5.0% | up | 11:59 | none | – | – | – | |
| BLUSPRING | 5.0% | down | 15:21 | none | – | – | – | |
| AEROENTER | 5.0% | up | 11:01 | none | – | – | – | |
| ADVENTHTL | 5.0% | down | 09:47 | none | – | – | – | |
| AERONEU | 5.0% | up | 10:16 | none | – | – | – | |
| HLEGLAS | 5.0% | down | 09:44 | none | – | – | – | |

