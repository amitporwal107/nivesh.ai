# Dashboard — screen spec

## 1. Screen objective

Give a salaried Indian retail investor a 5-second answer to: **"How is my money doing, and what's the one thing to fix first?"**

Three things must be on screen above the fold:

1. Portfolio value with a calm, signed yearly change
2. A unified health score (0–100) — single trust number
3. Risk level — a five-step meter against the user's stated risk profile

Below the fold: top three plain-English insights, then a single dark CTA slab that promises a concrete delta ("74 → 88 in 3 moves").

## 2. UX behaviour

- **Loading** — full-page skeleton matching the final layout (hero card with three columns, three insight rows). No layout shift when data arrives.
- **Error** — centered `<ErrorState>` with retry that refetches both `summary` and `navHistory` together.
- **Empty** — when `totalValue === 0` (user hasn't connected anything yet) we show `<EmptyState>` pointing to the upload flow.
- **Navigation**
  - Insight CTA → `/recommendations?focus=<recId>` (focus highlights that card)
  - "Improve portfolio" → `/recommendations`
- **Responsive**
  - ≥ md: three-column hero, three-column insight rail width
  - < md: hero stacks vertically; insights stack; CTA stacks (button drops below copy)
- **Accessibility**
  - Page has one `<h1>`; insights are `<h3>` inside `<Card>`s
  - Score ring has `aria-label="Health score N out of 100"`
  - Risk meter has `aria-label` describing the bucket
  - CTA is a real `<button>`; tabbable, focus-visible ring

## 3. Component tree

```
DashboardPage (index.tsx)
└── usePortfolioSummary() ─┐
└── usePortfolioNavHistory() ─┴── Dashboard (Dashboard.tsx)
                                  ├── PortfolioValueCard
                                  │   └── SparkArea (recharts)
                                  ├── HealthScoreCard
                                  │   └── ScoreRing (svg)
                                  ├── RiskMeterCard
                                  │   └── RiskMeter
                                  ├── TopInsightsList
                                  │   └── InsightCard × 3
                                  └── ImproveCTA
```

Loading/empty/error states live in `index.tsx` so the data view (`Dashboard.tsx`) can be authored as if data is guaranteed.

## 4. Mock data schema

Stored in `src/mock-data/portfolio.ts`. Authoritative types in `src/types/portfolio.ts`.

```ts
PortfolioSummary {
  asOf: ISOTimestamp
  totalValue: Paise            // ₹ × 100, integer
  dayChange:  { abs: Paise, pct: number }
  weekChange: { abs: Paise, pct: number }
  yearChange: { abs: Paise, pct: number }
  healthScore: number          // 0..100
  riskBucket: "very-low" | "low" | "moderate" | "high" | "very-high"
  riskBucketIndex: 1..5
  allocation: AllocationSlice[]
  topInsights: PortfolioInsight[]
}

PortfolioInsight {
  id: string
  severity: "info" | "watch" | "fix" | "good"
  category: "overlap" | "concentration" | "balance" | "cost" | "tax" | "goal"
  title: string                // headline
  detail: string               // 1-2 sentence explanation
  evidence?: Array<{ label: string; value: string }>
  cta?: { label: string; recommendationId: string }
}

NavPoint { date: ISODate; value: Paise }
```

All money is stored as **paise** (integer × 100). Formatters in `lib/formatters.ts` convert to display (`₹24,82,400`, `₹24.8 L`).

## 5. API contract

The mock service (`services/portfolio.service.ts`) stubs three endpoints. When the real backend lands, swap the function bodies — the type contract and React Query keys stay unchanged.

```http
GET /api/v1/portfolio/summary              → PortfolioSummary
GET /api/v1/portfolio/nav-history?range=1y → NavPoint[]
GET /api/v1/portfolio/holdings             → Holding[]
```

| Concern        | Spec                                                     |
| -------------- | -------------------------------------------------------- |
| Auth           | Bearer JWT on `Authorization` header                     |
| Caching        | `staleTime: 60_000` (configured in `main.tsx`)           |
| Retry          | `retry: 1` for transient 5xx                             |
| 401 handling   | Redirect to `/login` (TODO)                              |
| Error envelope | `{ code: string; message: string; correlationId: string }` |

## 6. Styling notes

- All colors use semantic tokens (`bg-surface-1`, `text-ink-2`, `text-accent`). Never hex.
- Numerals use `font-variant-numeric: tabular-nums` (apply via the `num` class) so the score "74" and value "₹24,82,400" don't shift width across renders.
- The hero card uses `divide-x` between columns and falls back to vertical stack < md.
- The CTA slab inverts to `bg-ink` for visual stop; button stays accent so it pops.
- No animations beyond Skeleton shimmer; the spec calls for "very limited animations".

## 7. Full code

| File                                              | Purpose                                       |
| ------------------------------------------------- | --------------------------------------------- |
| `pages/Dashboard/index.tsx`                       | Route entry; data hooks; loading/empty/error  |
| `pages/Dashboard/Dashboard.tsx`                   | Main view (data-resolved)                     |
| `pages/Dashboard/PortfolioValueCard.tsx`          | Value + signed yearly change + sparkline      |
| `pages/Dashboard/HealthScoreCard.tsx`             | Score ring + verdict copy                     |
| `pages/Dashboard/RiskMeterCard.tsx`               | 5-step meter + label                          |
| `pages/Dashboard/TopInsightsList.tsx`             | Maps `topInsights` to `<InsightCard>`s        |
| `pages/Dashboard/ImproveCTA.tsx`                  | Final dark slab CTA                           |

Reused: `components/ui/card`, `components/ui/button`, `components/ui/badge`, `components/charts/{ScoreRing,SparkArea,RiskMeter}`, `components/shared/{InsightCard,LoadingSkeleton,EmptyState,ErrorState}`.

## 8. Open questions

- Should the hero card's right column show **"Risk vs target"** when the user is materially drifted (e.g. moderate target but current bucket is high)? Likely yes — adds in v0.2.
- The CTA copy is hard-coded ("74 → 88 in 3 moves"). When the recommendation engine lands, derive both numbers from `recommendations.sum(estHealthDelta)`.
- We currently show top **3** insights. Backend may return more; cap is in `topInsights` query at service layer (TBD).
