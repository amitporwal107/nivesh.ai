#!/usr/bin/env python3
"""Create Advisory-Workflows roadmap tickets in the staging Work dashboard.
Idempotent: deduped by `sig` server-side. Token via env NIVESH_ADMIN_TOKEN.
Usage: NIVESH_ADMIN_TOKEN=... python3 post_work_items.py [--dry-run]"""
import os, json, sys, urllib.request, urllib.error

BASE = os.environ.get("NIVESH_BASE", "https://staging.niveshcopilot.com")
TOKEN = os.environ.get("NIVESH_ADMIN_TOKEN", "")
DRY = "--dry-run" in sys.argv
TICKETS = []

def T(sig, title, priority, labels, body):
    TICKETS.append({
        "sig": "advw:" + sig, "title": title, "priority": priority,
        "severity": "WARNING", "source": "manual",
        "labels": ["advisory-workflows"] + labels, "sample_message": body,
    })

AW = "advisory-workflows"

# ── Tracking ──────────────────────────────────────────────────────────────
T("track", "[TRACK] Advisory Workflows PRD — 7-workflow roadmap", "P1", ["tracking"],
  "Master tracking item for the Nivesh Advisory Workflows PRD (7 workflows, 61 FRs). "
  "Code audit: 1 fully / 23 partial / 4 stub / 33 not-built. Platform today = research+analytics+advisor-monitoring; "
  "PRD wants transactional MFD. Artifacts: .claude/workspace/advisory-workflows/ (PRD, implementation-validation, spec, feasibility, plan, test-plan, phase0-tasks). "
  "Phase 0 = internal-buildable (this backlog). Phases 1-3 gated on vendors. "
  "Open NEEDS-INPUT: (1) which external partners are contracted (UIDAI/DigiLocker/NPCI/KRA-CKYC/BSE STAR MF/MFU/AMC feeds/comms gateways); "
  "(2) regulatory posture MFD vs RIA; (3) reshape MF research to PRD 7-factor score or keep existing engines; (4) V5 prod-eligibility.")

# ── Phase 0 tasks (internal, no vendor gate) ──────────────────────────────
P0 = "phase-0"
def P0T(sig, title, priority, epic, wf, body, foundation=False):
    labels = [P0, "type:task", "internal", "epic-"+epic] + wf
    if foundation: labels.append("foundation")
    T(sig, "[0."+sig.split(":")[-1] if False else title, priority, labels, body)

# 0.1 Scheduler / Alert Dispatcher (M, FULL_STACK_DEV) — foundation
f = ["WF-04","WF-02","WF-05","WF-06"]
T("P0:0.1.1","[0.1.1] Scheduler/Dispatcher — design job & dispatcher interface","P1",[P0,"type:task","internal","epic-0.1","foundation"]+f,
  "Epic 0.1 (Scheduler/Alert Dispatcher). Owner FULL_STACK_DEV · size M. Deps: none. Internal. "
  "Design per-user job/schedule model + dispatcher interface (channel abstraction: in-app/email first). Choose mechanism (existing cron infra vs worker/APScheduler). Decision note. Verify: design reviewed.")
T("P0:0.1.2","[0.1.2] Scheduler — per-user daily job registry/runner + notifications collection","P1",[P0,"type:task","internal","epic-0.1","foundation"]+f,
  "Epic 0.1. Owner FULL_STACK_DEV. Deps: 0.1.1. Implement job registry/runner + `notifications` collection (queued→dispatched→delivered). Verify: staging job run creates rows.")
T("P0:0.1.3","[0.1.3] Alert Dispatcher service (enqueue → channel adapter → delivery status)","P1",[P0,"type:task","internal","epic-0.1","foundation"]+f,
  "Epic 0.1. Owner FULL_STACK_DEV. Deps: 0.1.2. Dispatcher routes queued alerts to channel adapters and records delivery status. Verify: dispatched row transitions.")
T("P0:0.1.4","[0.1.4] Scheduler — e2e demo alert + observability + tests","P2",[P0,"type:task","internal","epic-0.1","foundation"]+f,
  "Epic 0.1. Owner FULL_STACK_DEV. Deps: 0.1.3, 0.5.1. End-to-end demo alert; job-run logs + dispatch metrics; tests. Verify: real alert dispatched on staging.")

# 0.2 WORM audit promotion (M) — foundation
f = ["WF-06"]
T("P0:0.2.1","[0.2.1] WORM audit — event schema + taxonomy + store choice","P1",[P0,"type:task","internal","epic-0.2","foundation"]+f,
  "Epic 0.2 (WORM audit). Owner FULL_STACK_DEV · M. Deps: none. Design platform audit event schema + taxonomy (login/OTP/order/eSign/field-change/report...). Pick store (Postgres WORM per portfolio_ingestion vs append-only). Verify: schema reviewed.")
T("P0:0.2.2","[0.2.2] WORM audit — migration: table + immutability trigger","P1",[P0,"type:task","internal","epic-0.2","foundation"]+f,
  "Epic 0.2. TASK_db_migration. Deps: 0.2.1. Create WORM audit table + trigger blocking UPDATE/DELETE, generalising backend/portfolio_ingestion/db/migrations/004_audit_log.sql. Verify: immutability test passes on staging.")
T("P0:0.2.3","[0.2.3] WORM audit — services/audit.py synchronous + fail-closed","P1",[P0,"type:task","internal","epic-0.2","foundation"]+f,
  "Epic 0.2. Deps: 0.2.2. Refactor services/audit.py to write synchronously + fail-closed (hold txn on write-fail; remove swallow at audit.py:87-88). Verify: forced write-fail holds txn (negative test).")
T("P0:0.2.4","[0.2.4] WORM audit — admin query interface + CSV + retention","P2",[P0,"type:task","internal","epic-0.2","foundation"]+f,
  "Epic 0.2. Deps: 0.2.2. Admin query (by investor/MFD/date/action) + CSV export + 10yr retention config. Verify: query returns real rows + CSV.")
T("P0:0.2.5","[0.2.5] WORM audit — negative + immutability tests","P2",[P0,"type:task","internal","epic-0.2","foundation"]+f,
  "Epic 0.2. Deps: 0.2.3. Tests: write-fail holds txn; UPDATE/DELETE rejected. Verify: test suite green.")

# 0.3 Consent/disclosure extension (S-M)
f = ["WF-06","WF-01","WF-03"]
T("P0:0.3.1","[0.3.1] Disclosure model (RDD/KIM/commission/COI) + versioning","P2",[P0,"type:task","internal","epic-0.3"]+f,
  "Epic 0.3. Owner FULL_STACK_DEV · S-M. Deps: 0.2. Model SEBI disclosure types + versioning on DPDP consents.py pattern. Verify: versioned rows.")
T("P0:0.3.2","[0.3.2] Disclosure ack API (checkbox+OTP) + trigger hooks","P2",[P0,"type:task","internal","epic-0.3"]+f,
  "Epic 0.3. Deps: 0.3.1, 0.4. Ack API (checkbox+OTP) + hooks (onboarding / first-new-category). Verify: ack stored w/ OTP.")
T("P0:0.3.3","[0.3.3] Disclosure — 'X pending acknowledgements' MFD query","P3",[P0,"type:task","internal","epic-0.3"]+f,
  "Epic 0.3. Deps: 0.3.2. Pending-ack count for MFD dashboard. Verify: count matches data.")

# 0.4 V5 form foundation (M, DESIGN_ENG) — foundation
f = ["WF-01","WF-05","WF-06","WF-07"]
T("P0:0.4.1","[0.4.1] V5 forms — add react-hook-form + Radix form primitives","P1",[P0,"type:task","internal","epic-0.4","foundation","ui"]+f,
  "Epic 0.4 (V5 form foundation). Owner DESIGN_ENG · M · TASK_ui_component. Deps: none. Add react-hook-form + resolvers + Radix form primitives (dialog/select/checkbox/radio/slider/label) to frontend-v5, themed to tokens. Verify: yarn build + Playwright.")
T("P0:0.4.2","[0.4.2] V5 forms — reusable field kit (Input/Select/Checkbox/Radio/Slider/OTP) + a11y","P1",[P0,"type:task","internal","epic-0.4","foundation","ui"]+f,
  "Epic 0.4. Deps: 0.4.1. Reusable field kit w/ zod resolver + a11y (labels/error-announce/focus). Verify: Playwright a11y.")
T("P0:0.4.3","[0.4.3] V5 forms — multi-step form shell on Stepper (per-step validation + resume)","P2",[P0,"type:task","internal","epic-0.4","foundation","ui"]+f,
  "Epic 0.4. Deps: 0.4.2. Formalize multi-step form shell on components/shared/Stepper.tsx. Verify: stepper demo.")
T("P0:0.4.4","[0.4.4] V5 forms — migrate one existing form as reference + Playwright","P2",[P0,"type:task","internal","epic-0.4","foundation","ui"]+f,
  "Epic 0.4. Deps: 0.4.2. Migrate one hand-rolled form (e.g., Settings/Goals create) as reference. Verify: Playwright on migrated screen.")

# 0.5 Comms dispatcher email-MVP (M) — foundation
f = ["WF-07","WF-04","WF-02"]
T("P0:0.5.1","[0.5.1] Comms — email channel adapter (SMTP) + templated HTML + delivery status","P1",[P0,"type:task","internal","epic-0.5","foundation"]+f,
  "Epic 0.5 (Comms dispatcher email-MVP). Owner FULL_STACK_DEV · M. Deps: 0.1. Email adapter (SMTP/provider) + templated HTML w/ personalisation tokens + delivery-status webhook/poll. Verify: e2e send to sink inbox.")
T("P0:0.5.2","[0.5.2] Comms — compose API (individual/segment/all)","P2",[P0,"type:task","internal","epic-0.5","foundation"]+f,
  "Epic 0.5. Deps: 0.5.1. Compose-to individual/segment/all (segment reuses existing tags/filters). Verify: send to a segment.")
T("P0:0.5.3","[0.5.3] Comms — delivery-status store + TRAI/DND opt-out suppression","P2",[P0,"type:task","internal","epic-0.5","foundation"]+f,
  "Epic 0.5. Deps: 0.5.1. Delivery-status store + opt-out suppression. Verify: opted-out recipient suppressed.")
T("P0:0.5.4","[0.5.4] Comms — register email as Alert-Dispatcher channel + e2e test","P2",[P0,"type:task","internal","epic-0.5","foundation"]+f,
  "Epic 0.5. Deps: 0.5.1, 0.1.3. Wire email as a dispatcher channel. Verify: alert delivered via email.")

# 0.6 Branding config (S-M, DESIGN_ENG) — foundation
f = ["WF-07","WF-05","WF-02"]
T("P0:0.6.1","[0.6.1] Branding — MFD config model + API (logo/colour/tagline)","P2",[P0,"type:task","internal","epic-0.6","foundation","ui"]+f,
  "Epic 0.6 (Branding config store). Owner DESIGN_ENG · S-M. Deps: 0.4. MFD branding config model + API (logo upload, colours, tagline). Verify: config persisted.")
T("P0:0.6.2","[0.6.2] Branding — inject into CSS-variable theme + live preview","P2",[P0,"type:task","internal","epic-0.6","foundation","ui"]+f,
  "Epic 0.6. Deps: 0.6.1. Inject branding into tailwind CSS-variable theme + live preview in Settings. Verify: Playwright theme change.")
T("P0:0.6.3","[0.6.3] Branding — expose to report/email templating","P3",[P0,"type:task","internal","epic-0.6","foundation"]+f,
  "Epic 0.6. Deps: 0.6.1. Expose branding to report/email templating (foundation for 0.10 / WF-07-03). Verify: template renders branding.")

# 0.7 WF-02 contract-drift fix (S) — real bug
f = ["WF-02"]
T("P0:0.7.1","[0.7.1] WF-02 fix — reconcile simulate/what-if field names (FE↔BE)","P1",[P0,"type:task","internal","epic-0.7","bug"]+f,
  "Epic 0.7 (WF-02 contract-drift fix). Owner FULL_STACK_DEV · S · TASK_bug_fix. Deps: none. Align backend goals.py:452/478 ↔ FE goal.contract.ts (prob_success_pct/p5-p50-p95/on_track_pct/preview vs success_probability_pct/corpus_projections.p10-p50-p90/what_if_on_track_pct/persisted). Verify: adapter safeParse no longer throws contractDrift.")
T("P0:0.7.2","[0.7.2] WF-02 fix — shared contract regression test","P1",[P0,"type:task","internal","epic-0.7","bug"]+f,
  "Epic 0.7. Deps: 0.7.1. Shared contract test so simulate/what-if can't silently drift again. Verify: test fails on drift.")
T("P0:0.7.3","[0.7.3] WF-02 fix — staging verify (curl + Playwright on Goals)","P2",[P0,"type:task","internal","epic-0.7","bug"]+f,
  "Epic 0.7. Deps: 0.7.1. Verify on staging: curl /api/goals/what-if + Playwright on Goals what-if. Verify: verdict renders.")

# 0.8 WF-02 goal library + PDF (S-M)
f = ["WF-02"]
T("P0:0.8.1","[0.8.1] Goal library — template table + seed 8 PRD templates + API","P2",[P0,"type:task","internal","epic-0.8"]+f,
  "Epic 0.8. Owner FULL_STACK_DEV · S-M. Deps: 0.7. Goal template table + seed 8 PRD templates (default inflation/allocation/min-SIP per type) + API. Verify: templates returned.")
T("P0:0.8.2","[0.8.2] Goal library — template gallery UI → prefill creator","P2",[P0,"type:task","internal","epic-0.8","ui"]+f,
  "Epic 0.8. Deps: 0.8.1, 0.4. Template gallery picker prefills custom-goal creator. Verify: Playwright.")
T("P0:0.8.3","[0.8.3] Goal-plan PDF (reportlab) + vault save + optional email","P2",[P0,"type:task","internal","epic-0.8"]+f,
  "Epic 0.8. Deps: 0.6, 0.5. Goal-plan PDF (projection/SIP schedule/basket/assumptions/MFD branding); save to vault + optional email. Verify: PDF <5s.")

# 0.9 Fund Comparison Tool (M)
f = ["WF-03"]
T("P0:0.9.1","[0.9.1] Fund Compare — backend ≤3-fund payload (all PRD columns)","P2",[P0,"type:task","internal","epic-0.9"]+f,
  "Epic 0.9. Owner FULL_STACK_DEV · M. Deps: none. ≤3-fund compare payload (trailing + rolling avg/min/max + SD/beta/Sharpe/Sortino/maxDD + Reg-vs-Direct TER + mgr/tenure/AUM + top-5 + research score) built on copilot_tools/mf.py:300. Verify: payload complete.")
T("P0:0.9.2","[0.9.2] Fund Compare — FE comparison grid + ≤3 picker","P2",[P0,"type:task","internal","epic-0.9","ui"]+f,
  "Epic 0.9. Deps: 0.9.1, 0.4. Comparison grid screen + fund picker (≤3), reuse Card/RiskReturnBubble. Verify: Playwright.")
T("P0:0.9.3","[0.9.3] Fund Compare — share as PDF/link (7-day expiry)","P3",[P0,"type:task","internal","epic-0.9"]+f,
  "Epic 0.9. Deps: 0.9.2. Share PDF/link w/ 7-day expiry. Verify: link opens.")

# 0.10 Branded holdings statement + review-pack worker (M)
f = ["WF-05","WF-07"]
T("P0:0.10.1","[0.10.1] Review-pack worker (consume review_pack_tasks, populate result_url)","P2",[P0,"type:task","internal","epic-0.10"]+f,
  "Epic 0.10. Owner FULL_STACK_DEV · M. Deps: 0.5. Implement review-pack worker — kills the /mock/review-pack.pdf stub; sets result_url. Verify: real PDF url produced.")
T("P0:0.10.2","[0.10.2] Branded actual-holdings/performance statement PDF","P2",[P0,"type:task","internal","epic-0.10"]+f,
  "Epic 0.10. Deps: 0.6. Branded statement (logo/colour/tagline, allocation pie, holdings, SIP, perf chart) — distinct from prospect proposal. Verify: PDF renders w/ branding.")
T("P0:0.10.3","[0.10.3] Statement dispatch via comms + CAS reconciliation gate","P2",[P0,"type:task","internal","epic-0.10"]+f,
  "Epic 0.10. Deps: 0.5, 0.10.2. Dispatch via comms; reconcile figures vs CAS before generation. Verify: dispatched + reconciled.")

# 0.11 Rebalance accept/reject route (S-M)
f = ["WF-04"]
T("P0:0.11.1","[0.11.1] Rebalance — accept/modify/reject route (replace decisions.py TODO)","P2",[P0,"type:task","internal","epic-0.11"]+f,
  "Epic 0.11. Owner FULL_STACK_DEV · S-M. Deps: none. Implement decisions.py accept/modify/reject (replace TODO stub :22-28); persist decision + mandatory note. Verify: decision persisted.")
T("P0:0.11.2","[0.11.2] Rebalance — accepted-rec order-prefill + outcome-tracking hooks","P2",[P0,"type:task","internal","epic-0.11"]+f,
  "Epic 0.11. Deps: 0.11.1. On accept → order-prefill payload (consumed by 2.2 later) + 3M/6M/1Y outcome-tracking hooks scaffolded. Verify: prefill payload shape.")

# 0.12 Scheme-wise CG export (S)
f = ["WF-04"]
T("P0:0.12.1","[0.12.1] CG export — scheme-wise realised STCG/LTCG endpoint (date range)","P2",[P0,"type:task","internal","epic-0.12"]+f,
  "Epic 0.12. Owner FULL_STACK_DEV · S. Deps: none (engine complete: tax_engine_fifo). Realised CG statement endpoint (date range) scheme-wise, not holdings-only. Verify: statement matches known dataset.")
T("P0:0.12.2","[0.12.2] CG export — Excel + PDF + Tax-page export button","P2",[P0,"type:task","internal","epic-0.12","ui"]+f,
  "Epic 0.12. Deps: 0.12.1. Excel + PDF export wired to Tax page. Verify: files download.")

# 0.13 Wire monitoring engines to scheduler+dispatcher (M)
f = ["WF-04"]
T("P0:0.13.1","[0.13.1] Monitoring — daily post-NAV job (drift/underperformer/SIP engines)","P2",[P0,"type:task","internal","epic-0.13"]+f,
  "Epic 0.13. Owner FULL_STACK_DEV · M. Deps: 0.1. Daily post-NAV job runs existing drift + underperformer + SIP-status engines per user. Verify: job produces flags.")
T("P0:0.13.2","[0.13.2] Monitoring — emit alerts to investor+MFD + MFD daily digest","P2",[P0,"type:task","internal","epic-0.13"]+f,
  "Epic 0.13. Deps: 0.13.1, 0.5. Emit drift/underperformer/SIP alerts via dispatcher + MFD daily digest. Verify: alert dispatched.")
T("P0:0.13.3","[0.13.3] Monitoring — 'stale since last sync' dashboard state","P3",[P0,"type:task","internal","epic-0.13"]+f,
  "Epic 0.13. Deps: 0.13.1. Surface 'stale since last sync' state (real ECS-bounce alert deferred to 1.6/3.4). Verify: state shows.")

# ── Phase 1 epics — vendor procurement (parallel, Day 0) ──────────────────
P1 = "phase-1"
T("P1:1.1","[1.1] Procure KYC-rail vendor (ESP: eKYC+eSign+KRA/CKYC) + NACH provider","P1",[P1,"type:epic","vendor-gated","WF-01","WF-06"],
  "Phase 1 procurement. Gates 2.1 (WF-01) + 2.4 (KYC monitor). Owner PM→FULL_STACK_DEV. Not estimable without vendor scope. Depends: NEEDS-INPUT #1. Verify: contract + UAT credentials in hand.")
T("P1:1.2","[1.2] Procure BSE STAR MF / MFU order-gateway contract + UAT","P1",[P1,"type:epic","vendor-gated","WF-05"],
  "Phase 1 procurement — BIGGEST BLOCKER. Gates 2.2 + WF-02/03 Start-SIP + 3.3 commission. Owner PM→FULL_STACK_DEV. Not estimable. Depends: NEEDS-INPUT #1,#2. Verify: gateway UAT credentials.")
T("P1:1.3","[1.3] Procure AMFI ARN registry + KRA/CKYC status endpoints","P2",[P1,"type:epic","vendor-gated","WF-06"],
  "Phase 1 procurement. Gates 2.4. Owner PM→FULL_STACK_DEV. Not estimable. Depends: NEEDS-INPUT #1.")
T("P1:1.4","[1.4] Procure SMS (DLT) + WhatsApp (BSP) gateways","P2",[P1,"type:epic","vendor-gated","WF-07","WF-04"],
  "Phase 1 procurement. Gates 2.3 multi-channel + WF-07 comms. Owner PM→FULL_STACK_DEV. Not estimable. Depends: NEEDS-INPUT #1.")
T("P1:1.5","[1.5] Procure AMC commission feeds (SFTP/API)","P2",[P1,"type:epic","vendor-gated","WF-05"],
  "Phase 1 procurement. Gates 3.3 commission subsystem. Owner PM→FULL_STACK_DEV. Not estimable. Depends: NEEDS-INPUT #1,#2 (MFD model).")
T("P1:1.6","[1.6] Procure live registrar feeds (CAMS/KFin) + real ECS-bounce (NACH)","P2",[P1,"type:epic","vendor-gated","WF-04"],
  "Phase 1 procurement. Gates 3.4 live feeds. Owner PM→FULL_STACK_DEV. Not estimable. Depends: NEEDS-INPUT #1.")
T("P1:1.7","[1.7] Procure non-MF shelf partners (PMS/AIF/bond/insurer/PFRDA-CRA/MMTC) — per partner","P3",[P1,"type:epic","vendor-gated","WF-03"],
  "Phase 1 procurement. Gates 3.1 shelves. Owner PM→FULL_STACK_DEV. Not estimable, per partner. Depends: NEEDS-INPUT #1.")

# ── Phase 2 epics — transactional core ────────────────────────────────────
P2 = "phase-2"
T("P2:2.1","[2.1] KYC/onboarding rail (eKYC+eSign+eMandate+KRA/CKYC) + status tracker","P1",[P2,"type:epic","vendor-gated","WF-01","WF-06"],
  "Phase 2. Deps: 0.3,0.4,0.5 + 1.1. Not estimable without vendor scope. WF-01 01/02/03/09/10. Verify (vendor UAT): PAN+Aadhaar+OTP→KYC-Verified, mandate Active via real NPCI callback, Aadhaar not persisted.")
T("P2:2.2","[2.2] MF order gateway (BSE STAR/MFU) + SIP execution + order console","P1",[P2,"type:epic","vendor-gated","WF-05"],
  "Phase 2 — transactional keystone. Deps: 0.2,0.4 + 1.2; gates WF-02/03 Start-SIP + 0.11 prefill. Not estimable. WF-05 01/02. Verify (BSE UAT): order routed, cut-off honored, real status+retry, db.sips app-written.")
T("P2:2.3","[2.3] Wire monitoring alerts → multi-channel dispatch","P2",[P2,"type:epic","vendor-gated","WF-04"],
  "Phase 2. Deps: 0.13,0.5 + 1.4 (SMS/WhatsApp); ECS-bounce also 1.6. Mixed internal+vendor; gated channels not estimable. WF-04 04/06. Verify: alert delivered on gated channels + TRAI/DND suppressed.")
T("P2:2.4","[2.4] ARN/KYC compliance (ARN validation+order-block+reminders; KYC monitor; disclosure-ack)","P1",[P2,"type:epic","vendor-gated","WF-06"],
  "Phase 2. Deps: 0.2,0.3,0.1 + 1.3 (registry); shares KRA w/ 2.1. Not estimable. WF-06 01/02/04. Verify: expired ARN blocks orders (view-only)+reminders; KYC OnHold blocks purchases; disclosure-ack versioned (checkbox+OTP).")

# ── Phase 3 epics — breadth ───────────────────────────────────────────────
P3 = "phase-3"
T("P3:3.1","[3.1] Non-MF product shelves (PMS/AIF/Bonds/Insurance/NPS/Gold) — 1 mini-project/shelf","P2",[P3,"type:epic","vendor-gated","WF-03"],
  "Phase 3. Deps: 0.4 + 1.7/partner. Not estimable per partner; ~6-7 net-new screens. WF-03 04..09. Verify: per-partner EOI/Request-Info flow vs sandbox.")
T("P3:3.2","[3.2] White-label + marketing (custom domain, eCard, content pack, lead funnel, HNI/engagement)","P2",[P3,"type:epic","internal","WF-07"],
  "Phase 3. Deps: 0.6, 0.5; custom domain=infra. Mostly internal · size L. WF-07 01/04/05/06/08/10. Verify: Playwright per surface + delivery status.")
T("P3:3.3","[3.3] Commission subsystem (AMC reconciliation + dashboard + trail)","P2",[P3,"type:epic","vendor-gated","WF-05","WF-07"],
  "Phase 3. Deps: 2.2 + 1.5. Not estimable; in-scope only under MFD model (NEEDS-INPUT #2). WF-05 04/05, WF-07-07. Verify: reconciliation 0-discrepancy on known AMC file.")
T("P3:3.4","[3.4] Live registrar feeds + real ECS-bounce","P2",[P3,"type:epic","vendor-gated","WF-04"],
  "Phase 3. Deps: 0.13 + 1.6. Not estimable. WF-04 02/06. Verify: real ECS bounce surfaces reason (not cas_transactions.py:66-72 stub).")
T("P3:3.5","[3.5] Report Scheduler (frequency/channel config, dispatch-all, delivery status)","P3",[P3,"type:epic","internal","WF-05","WF-07"],
  "Phase 3. Deps: 0.1,0.5,0.10. Internal · size M. WF-05-07, WF-07-02. Verify: scheduled dispatch to all clients + delivery status.")

# ── Execute ───────────────────────────────────────────────────────────────
def post(t):
    payload = {k: t[k] for k in ("sig","title","severity","priority","source","labels","sample_message")}
    req = urllib.request.Request(BASE + "/api/work/issues", data=json.dumps(payload).encode(),
        method="POST", headers={"Content-Type":"application/json","Authorization":"Bearer "+TOKEN,
        "Accept":"application/json",
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status, json.loads(r.read().decode())

def main():
    n = len(TICKETS)
    sigs = [t["sig"] for t in TICKETS]
    dupes = [s for s in set(sigs) if sigs.count(s) > 1]
    print(f"{n} tickets to create. Duplicate sigs (must be empty): {dupes}")
    by_pri = {}
    for t in TICKETS: by_pri[t["priority"]] = by_pri.get(t["priority"],0)+1
    print("by priority:", by_pri)
    if DRY:
        for t in TICKETS: print(f"  {t['priority']:3} {t['sig']:14} {t['title']}")
        return
    if not TOKEN:
        print("ERROR: NIVESH_ADMIN_TOKEN not set"); sys.exit(1)
    created, failed = [], []
    for t in TICKETS:
        try:
            st, resp = post(t)
            iid = resp.get("issue_id","?")
            print(f"  {st} {iid:9} {t['sig']:14} | {t['title'][:60]}")
            created.append(iid)
        except urllib.error.HTTPError as e:
            print(f"  ERR {e.code} {t['sig']:14} | {e.read().decode()[:160]}"); failed.append(t["sig"])
        except Exception as e:
            print(f"  ERR ??? {t['sig']:14} | {e}"); failed.append(t["sig"])
    print(f"\nDONE. created/updated={len(created)} failed={len(failed)}")
    if failed: print("failed sigs:", failed)

if __name__ == "__main__":
    main()
