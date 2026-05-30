# BUSINESS_SPECIFICATION.md — Nivesh.ai

> Honesty rule: the master architecture doc is technical, so much business detail below is
> NOT yet sourced. Anything not grounded is marked `NEEDS-INPUT` — do not let it read as fact.

## 1. Problem & opportunity
Indian retail investors lack an affordable, data-grounded copilot to understand and act on
their portfolios (MF + equity). Nivesh.ai provides AI guidance grounded in a proprietary
Indian market data platform (NIDP) and V3 scoring, rather than generic advice.

## 2. Target users
| Segment | Who | Need |
|---|---|---|
| Primary | Indian retail investors | Understand holdings, get actionable plans, goal planning |
| Secondary | MFDs (mutual fund distributors) | Advisor workspace, client list, reports (`/api/mfd`) |

## 3. Value proposition
AI copilot answers grounded in real, validated Indian market data (28 ingesters, V3
Quality/Health/Exit/Add scores, portfolio intelligence) — not ungrounded LLM output.

## 4. Business goals & success metrics
`NEEDS-INPUT` — not in the technical doc. Capture activation, retention, conversion,
corpus-under-management targets with real baselines (mark each baseline known vs ASSUMPTION).

## 5. Constraints
- **Compliance:** India DPDP — consent, data export, deletion (`/api/compliance`); compliance
  node in the LangGraph agent. PAN encryption at rest PLANNED (currently a gap).
- **Access:** whitelist-gated login (non-whitelisted email → 403).
- **Technical:** mobile via Capacitor (iOS/Android); V2 prod / V5 staging-only.
- **Cost:** infra ~$50–66/month (see DEVOPS).

## 6. Scope
- In: portfolio, plans, goals, copilot, intelligence, admin console, NIDP data + DaaS.
- Out / not-now: `NEEDS-INPUT` (define the explicit "no" list).

## 7. Stakeholders
GCP owner `aporwal107@gmail.com`; Platform Engineering. Decision rights: `NEEDS-INPUT`.

## 8. Open questions
Business metrics, pricing/plan economics (DaaS free/standard/pro/internal pricing),
go-to-market — all `NEEDS-INPUT`. Ask before filling.
