"""SPT slice A, part 2: market-wide opportunities (PRD §6.4, §7; Workflow §5, §6, §21.1; DESIGN.md §4, §5).

    store.py        the `spt_opportunities` collection and the read/transition interface slice B uses
    consolidate.py  normalized signals → one opportunity per SYMBOL|direction|horizon|window, conflicts kept
    inputs.py       the market data a validation reads (NSE end-of-day bars, the desk regime), cached per process
    validate.py     Workflow §6 validation, the opportunity score, QUALIFIED / CONDITIONAL / WATCHLIST / REJECTED /
                    DATA_INSUFFICIENT, and expiry
    runner.py       the leader-locked loop: catch-up ingest → consolidate → validate → expire (→ outcomes, P1)
"""
