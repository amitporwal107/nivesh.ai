# TECHNICAL_ARCHITECTURE.md

> **This file is the home for the validated master architecture document.**
>
> Action required: paste the full "Nivesh.ai + NIDP — Technical Architecture Document"
> (v1.0, validated against code and deployed infrastructure, 2026-05-29) below this
> header — replacing this placeholder body. It is your authoritative source; it should
> live here as-is rather than being hand-summarized, so there is exactly one canonical
> copy and no drift.
>
> **Honesty rule:** keep this in sync with the running system. The master doc's own
> closing note holds: nothing is assumed or inferred; if code/migrations disagree with
> this doc, the code wins and this doc gets fixed.

The other `docs/` files reference this one by section number. For convenience, the
master doc's section map (so cross-references resolve even before you paste it):

| § | Section |
|---|---|
| 1 | System Overview |
| 2 | Tech Stack |
| 3 | Infrastructure — GCP & VMs |
| 4 | Nivesh Application Architecture (6 layers; backend service modules; APScheduler jobs; 7-phase post-deploy migration) |
| 5 | NIDP Data Platform Architecture (BaseIngester contract; 28 ingesters; derived analytics) |
| 6 | Database Schemas (NIDP TimescaleDB, Nivesh PostgreSQL, Nivesh MongoDB) |
| 7 | Data Lake & Storage (5-layer immutable archive; replay engine) |
| 8 | Data Feeds & Cron Schedule |
| 9 | NIDP DaaS OpenAPI Reference |
| 10 | Nivesh App OpenAPI Reference |
| 11 | Observability Stack (Prometheus / Grafana / Loki / Sentry) |
| 12 | CI/CD Pipeline (Cloud Build) |
| 13 | Security & IAM |
| 14 | DevOps Guidelines |
| 15 | Operations Cheat Sheet |
| 16 | NIDP Data Quality Gates (7-gate architecture) |
| 17 | Jenkins CI/CD Pipeline |
| 18 | Admin Console & NIDP Console (FR-ADM-001..019) |
| 19 | URL Directory, Kafka Topics, Sentry & Credentials |

<!-- PASTE THE MASTER ARCHITECTURE DOCUMENT BELOW THIS LINE -->
