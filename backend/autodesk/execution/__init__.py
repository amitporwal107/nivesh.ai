"""Risk-to-paper execution (Phase 2, docs/autodesk/PHASE2_DESIGN.md): capital ledger, reservations, intents, orders, simulated fills, positions, journal.

Nothing in this package can reach a broker. The verbs are submit / amend / withdraw; the only adapters are paper and shadow."""
