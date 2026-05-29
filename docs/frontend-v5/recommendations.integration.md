# Recommendations — API integration

## Endpoints

| Hook | Endpoint | Notes |
|---|---|---|
| `useRecommendations(filter?)` | `GET /api/plans/active` | returns full Plan with actions[] |
| `useApplyRecommendation(planId)` | `PATCH /api/plans/{plan_id}/actions/{action_id}` body `{ status: "done" }` | optimistic; invalidates plans + recommendations |

## Two-step fetch — no longer needed

Earlier draft did `/active` → `planId` → `/plans/{id}`. Action-board canonical spec (`action-board.yaml`) declares `GET /active` returns the **full plan** including actions array + counters in a single response. Adapter simplified accordingly.

## action_type → RecAction bucketing

| Backend `action_type` | UI tone |
|---|---|
| `sell`, `switch`, `sip_decrease` | **REDUCE** |
| `buy`, `sip_increase` | **ADD** |
| `hold` | **KEEP** |

Card copy is composed from `holding_name`, `rationale`, `estimated_impact.{health_score_delta, annual_savings_rs}`, and `suggested_alternative` per the action's bucket.

## States

- Empty: backend returns `{ has_plan: false, plan: null }` → `EmptyState` "Your portfolio looks healthy."
- Loading: list skeleton (5 rows).
- Mutation pending: card-level `isApplying` flag disables Apply button.
- 401 / 5xx on PATCH → toast surfaces `ApiError`.

## Open

- `feedback` (PATCH `/actions/{id}/feedback`) is wired in adapter, not yet in UI. Add a thumbs-up/down strip under each card.
- Plan refresh (`POST /api/plans/refresh`) for "Re-run engine" CTA is wired; surface in header.
