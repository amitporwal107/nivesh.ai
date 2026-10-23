-- NIDP-SHP-FWD-001 panel builder.
--
-- One row per (formation quarter, symbol) carrying: the institutional-ownership change versus the
-- prior quarter, the LOOK-AHEAD-SAFE entry session, the adjusted opens needed for the 5/20/60
-- session forward returns, the strictly-pre-entry liquidity used by screen S3, and the counts
-- needed by screens S5 (corporate-action artefacts) and S6 (contested sources).
--
-- READ-ONLY. No DDL, no writes.
--
-- The availability rule is period_end + 25 calendar days, entry at the first trading session
-- STRICTLY AFTER that date. See preregistration.json -> availability_timestamp for why this and
-- not broadcast_at, ingested_at or period_end.
\pset pager off
\pset format csv

WITH cal AS (
    -- The trading calendar. series IN ('EQ','BE') is mandatory: 55 series values share symbol+date.
    SELECT as_of_date, row_number() OVER (ORDER BY as_of_date) AS sn
      FROM (SELECT DISTINCT as_of_date
              FROM nidp.prices_eod
             WHERE series IN ('EQ', 'BE')) s
),
shp AS (
    -- shareholding_pattern is NOT unique on (symbol, period_end): one row per source. Prefer a row
    -- that actually carries fii_pct, then the most recently ingested.
    SELECT DISTINCT ON (symbol, period_end)
           symbol, period_end, fii_pct, dii_pct, source
      FROM nidp.shareholding_pattern
     WHERE period_end BETWEEN DATE '2023-12-31' AND DATE '2026-06-30'
     ORDER BY symbol, period_end, (fii_pct IS NOT NULL) DESC, ingested_at DESC
),
contested AS (
    -- S6. Sources disagreeing by more than 2.00 pp on fii_pct are source disagreement, not an
    -- ownership change (reference case: ICICIBANK, 15.76 pp between NSE_SHP and screener_in).
    SELECT symbol, period_end
      FROM nidp.shareholding_pattern
     WHERE period_end BETWEEN DATE '2023-12-31' AND DATE '2026-06-30'
       AND fii_pct IS NOT NULL
     GROUP BY 1, 2
    HAVING max(fii_pct) - min(fii_pct) > 2.00
),
pairs AS (
    SELECT c.period_end,
           c.symbol,
           c.fii_pct AS cur_fii,
           p.fii_pct AS prv_fii,
           c.dii_pct AS cur_dii,
           p.dii_pct AS prv_dii,
           (ct.symbol IS NOT NULL) AS contested
      FROM shp c
      JOIN shp p
        ON p.symbol = c.symbol
       AND p.period_end = (date_trunc('quarter', c.period_end)::date - 1)
      LEFT JOIN contested ct
        ON ct.symbol = c.symbol AND ct.period_end = c.period_end
     WHERE c.period_end >= DATE '2024-03-31'
       AND c.fii_pct IS NOT NULL
       AND p.fii_pct IS NOT NULL
),
syms AS (SELECT DISTINCT symbol FROM pairs),
ent AS (
    SELECT q.period_end,
           (q.period_end + 25) AS avail_date,
           (SELECT min(c.sn) FROM cal c WHERE c.as_of_date > q.period_end + 25) AS entry_sn
      FROM (SELECT DISTINCT period_end FROM pairs) q
),
px AS (
    SELECT a.symbol,
           c.sn,
           a.adj_open,
           a.cumulative_adj_factor,
           lag(a.adj_open) OVER (PARTITION BY a.symbol ORDER BY c.sn) AS prev_open
      FROM nidp.prices_eod_adjusted a
      JOIN cal c  ON c.as_of_date = a.as_of_date
      JOIN syms s ON s.symbol = a.symbol
),
arte AS (
    -- S5. The unapplied-adjustment signature: a >=35% single-session fall with the cumulative
    -- adjustment factor still exactly 1.0.
    SELECT symbol, sn
      FROM px
     WHERE prev_open > 0
       AND adj_open / prev_open - 1 <= -0.35
       AND cumulative_adj_factor = 1.0
),
tv AS (
    SELECT p.symbol, c.sn, p.turnover
      FROM nidp.prices_eod p
      JOIN cal c  ON c.as_of_date = p.as_of_date
      JOIN syms s ON s.symbol = p.symbol
     WHERE p.series IN ('EQ', 'BE')
),
liq AS (
    -- S3. Median turnover over the 20 sessions ENDING THE SESSION BEFORE entry, so the screen
    -- itself cannot peek at the holding window.
    SELECT pr.period_end,
           pr.symbol,
           percentile_disc(0.5) WITHIN GROUP (ORDER BY t.turnover) AS med_turnover_pre,
           count(*) AS liq_sessions
      FROM pairs pr
      JOIN ent e ON e.period_end = pr.period_end
      JOIN tv  t ON t.symbol = pr.symbol
                AND t.sn BETWEEN e.entry_sn - 20 AND e.entry_sn - 1
     GROUP BY 1, 2
)
SELECT pr.period_end,
       pr.symbol,
       pr.contested,
       pr.cur_fii,
       pr.prv_fii,
       pr.cur_dii,
       pr.prv_dii,
       e.avail_date,
       (SELECT as_of_date FROM cal WHERE sn = e.entry_sn)      AS entry_date,
       p0.adj_open                                             AS open_entry,
       p5.adj_open                                             AS open_h5,
       p20.adj_open                                            AS open_h20,
       p60.adj_open                                            AS open_h60,
       l.med_turnover_pre,
       l.liq_sessions,
       (SELECT count(*)
          FROM arte a
         WHERE a.symbol = pr.symbol
           AND a.sn BETWEEN e.entry_sn AND e.entry_sn + 60)     AS artefact_days
  FROM pairs pr
  JOIN ent e        ON e.period_end = pr.period_end
  LEFT JOIN liq l   ON l.period_end = pr.period_end AND l.symbol = pr.symbol
  LEFT JOIN px p0   ON p0.symbol  = pr.symbol AND p0.sn  = e.entry_sn
  LEFT JOIN px p5   ON p5.symbol  = pr.symbol AND p5.sn  = e.entry_sn + 5
  LEFT JOIN px p20  ON p20.symbol = pr.symbol AND p20.sn = e.entry_sn + 20
  LEFT JOIN px p60  ON p60.symbol = pr.symbol AND p60.sn = e.entry_sn + 60
 ORDER BY pr.period_end, pr.symbol;
