
# Integration docs — index

Per-screen API integration notes. Each follows the same shape:

- Endpoints consumed (hook → backend)
- Response → ViewModel mapping
- States (loading / empty / error / pending mutation)
- Open contract questions / TODOs

## Architecture & cross-cutting

- [`architecture.md`](./architecture.md) — the four-layer integration model (contracts → mappers → adapters → hooks)
- [`assumptions.md`](./assumptions.md) — running list of decisions made under uncertainty
- [`contract-audit-2026-05-28.md`](./contract-audit-2026-05-28.md) — drift audit (3 passes) against `backend/docs/openapi/*.yaml`
- [`cas-connect.md`](./cas-connect.md) — CAS Connect SDK wiring (mirrors v4 frontend pattern)

## Per-screen

| Screen | Route | Doc |
|---|---|---|
| Dashboard       | `/dashboard`       | [dashboard.integration.md](./dashboard.integration.md) |
| Portfolio       | `/portfolio`       | [portfolio.integration.md](./portfolio.integration.md) |
| Fund Details    | `/funds/:id`       | [fund-details.integration.md](./fund-details.integration.md) |
| Concentration   | `/concentration`   | [concentration.integration.md](./concentration.integration.md) |
| Diversification | `/diversification` | [diversification.integration.md](./diversification.integration.md) |
| Risk Analysis   | `/risk`            | [risk.integration.md](./risk.integration.md) |
| Recommendations | `/recommendations` | [recommendations.integration.md](./recommendations.integration.md) |
| Chat            | `/chat`            | [chat.integration.md](./chat.integration.md) |
| Login           | `/login`           | [login.integration.md](./login.integration.md) |
| Onboarding      | `/onboarding`      | [onboarding.integration.md](./onboarding.integration.md) |
| Settings        | `/settings`        | [settings.integration.md](./settings.integration.md) |
