"""SPT slice A, part 1: scanner signals (list marks and strong signals of the Scan dashboard) → normalized, persisted,
immutable scanner events in `spt_signal_events` (PRD §6, Workflow §4–§5; docs/scanner_paper_trading/DESIGN.md §3).

    normalize.py   LIST_MAP and the rules that give a mark its category, family, timeframe, horizon and direction
    store.py       the `spt_signal_events` collection (insert-only)
    ingest.py      a mark / strong record → the PRD §6.2 event, the Workflow §4.4 checks, idempotent insert, events
    hook.py        the scan loop's non-blocking hand-off (services/scan_builder/signals.py) and the day catch-up
"""
