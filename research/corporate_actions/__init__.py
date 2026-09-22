"""Corporate-action regime breaks for the Kite daily-bars research universe.

PRD: docs/charting.md §37.5 ("Corporate actions and universe" -- demergers only; the ETF
part of §37.5 is deferred by the owner and is NOT built here). See also §9 (data quality /
corporate-action discontinuities) and §32 (provider responsibility -- Kite is the OHLCV
source, NSE/BSE are exchange-grounded validation).

Finding this package starts from (data-availability.md, decisions-log.md #33, and
independently re-confirmed here): Kite's daily bars are back-adjusted for some corporate
actions (a tested split showed no discontinuity) but NOT reliably for demergers -- SIEMENS
(2025-04-07) and ABFRL (2025-05-22) show large raw open-vs-prior-close gaps in the Kite
series with no adjustment applied. A demerger also changes what a symbol's price history
economically represents (a different, smaller business), independent of whether Kite
happened to adjust the price -- so pre- and post-demerger bars must never be treated as one
continuous series regardless of gap size. This package provides:

  - `events`     the confirmed demerger event list (data/demergers.csv) and loaders
  - `regime`     regime_break_mask() / regime_segments() -- the helpers other packages
                 (research.charting, research.costs, ...) call to keep a rolling window,
                 pattern, or validation run from spanning a demerger
  - `gap_detector` a large-gap safety net over raw Kite bars, independent of any sourced
                 event list, used to cross-check the confirmed events and surface other
                 unexplained candidates for owner review
  - `config`     the frozen ±N-session window and gap threshold, hashed and versioned

This package does not touch research/charting, research/costs, research/index_history,
backend or frontend -- it is a new, independent package other agents import from.
"""
