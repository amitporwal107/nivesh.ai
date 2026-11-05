"""SPT slice C: paper orders → execution simulation → fills → positions → monitoring/exits → modifications →
reconciliation (docs/scanner_paper_trading/DESIGN.md §3–§8, execution model `spt-exec-v1`).

    orders.py      create_entry_order (called by slice B, DESIGN §4), create_exit_order, cancel_paper_order, expiry, and
                   sync_order (the order's filled figures from its recorded fills: the fills are the truth)
    execution.py   the pure fill model (quote + order + now → fills or the reason there are none) and execute_order
    positions.py   fills → positions (weighted average, realised P&L net of costs, R, MFE/MAE), close and the ONE
                   release of the paper account's reservation, breakeven after T1, the trade outcome record
    monitor.py     the leader-locked loop: fills, stop/target exits, expiry, the evening trail/trend/time pass
    modify.py      position modifications (risk-increasing → slice B's check_modification; reducing → always allowed)
    reconcile.py   orders ↔ fills ↔ positions ↔ paper-account reservations; a read-only report
    controls.py    whether new entries are blocked (kill switch / halt / B's account state)
    store.py       the Mongo collections, indexes and conditional transitions
    config.py      the environment knobs (read at call time)

Nothing here talks to a broker: every order is a simulated paper order filled from the live quote cache.
"""
