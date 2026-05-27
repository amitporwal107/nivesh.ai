# Portfolio — screen spec

## Objective
Show the user every holding in a single table; provide a glance-level allocation breakdown and SIP roster.

## UX behaviour
- Tabs: **Holdings · Allocation · SIPs**, deep-linkable via URL query (`?tab=allocation`) — TODO.
- Row click → `/funds/:id` (Fund details).
- Loading: list skeleton. Empty: CTA → `/onboarding`. Error: retry both queries.
- Mobile: table collapses to stacked list (handled inside `HoldingsTable`).

## Component tree
```
PortfolioPage → Portfolio
  ├─ MetricCard × 4         (value · invested · P&L · monthly SIP)
  └─ Tabs
     ├─ HoldingsTable
     ├─ AllocationDonut + legend list
     └─ SIP list
```

## API
- `GET /portfolio/summary` → PortfolioSummary
- `GET /portfolio/holdings` → Holding[]

## Notes
- All ₹ from paise. P&L derived client-side from `marketValue − costBasis`.
- Asset-class colors centralised in `AllocationDonut.tsx` (`ALLOCATION_COLORS`).
