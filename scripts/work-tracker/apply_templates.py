#!/usr/bin/env python3
"""Reformat every ADVW epic/story/task into the standard Epic/Story/Task template
(title + requirements_md). Idempotent (PATCH by issue_id). Pulls each item's real
description from its existing sample_message/requirements_md.

Usage: NIVESH_ADMIN_TOKEN=... python3 apply_templates.py [--dry-run] [--only SIG]
"""
import os, sys, re, json, urllib.request, urllib.error

BASE = os.environ.get("NIVESH_BASE", "https://staging.niveshcopilot.com")
TOKEN = os.environ.get("NIVESH_ADMIN_TOKEN", "")
DRY = "--dry-run" in sys.argv
ONLY = None
if "--only" in sys.argv: ONLY = sys.argv[sys.argv.index("--only") + 1]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
H = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA,
     "Authorization": "Bearer " + TOKEN}

def _req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=H)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read().decode())

STAKE = "PM, Eng Lead, Design, QA"
TIMELINE = {"phase-1": "Q3 2026 (Sprint 1–3)", "phase-2": "Q4 2026 (vendor-gated)", "phase-3": "Q1 2027"}
EST = {"S": "0.5–1 day", "M": "2–4 days", "L": "1–2 weeks", "XL": "3+ weeks"}

# ── Epic content (area, outcome, goal, problem, metrics[], in[], out[], deps[]) ──
E = {}
def epic(sig, area, outcome, goal, problem, metrics, ins, outs, deps):
    E[sig] = dict(area=area, outcome=outcome, goal=goal, problem=problem, metrics=metrics, ins=ins, outs=outs, deps=deps)

# Phase-1 internal epics
epic("advw:P0-epic:0.1","Monitoring","Proactive alerts reach advisors & clients",
 "Deliver a scheduler + alert dispatcher so portfolio/goal signals actually notify advisors and investors.",
 "Analytics engines exist but nothing schedules them or delivers alerts — advisory is reactive.",
 ["Proactive-advisor-call rate >40%","Alert delivery <5 min from trigger"],
 ["Per-user daily job runner","Alert dispatcher + delivery status","Wire drift/underperformer/SIP alerts"],
 ["Real ECS-bounce feed (vendor)","SMS/WhatsApp channels (vendor)"],["Comms email-MVP (0.5)"])
epic("advw:P0-epic:0.2","Compliance","Tamper-proof, fail-closed audit trail",
 "Promote the platform audit log to WORM + fail-closed so every regulated action is provably recorded.",
 "Main-app audit is mutable Mongo that swallows write failures — not audit-grade.",
 ["0 missed audit writes","Write-failure holds the transaction (100%)"],
 ["WORM table + immutability trigger","Fail-closed writes","Query + CSV, 10yr retention"],
 ["Regulatory export files (P2)"],["portfolio_ingestion WORM pattern"])
epic("advw:P0-epic:0.3","Compliance","SEBI disclosure acknowledgements captured",
 "Capture RDD/KIM/commission/COI acknowledgements with OTP so investors are protected and audit-ready.",
 "Only a static disclosure page + DPDP consent ledger exist; no SEBI disclosure capture.",
 ["100% disclosures acked before first purchase","0 unacked transacting investors"],
 ["Disclosure model + versioning","Checkbox+OTP ack","Pending-ack dashboard"],
 ["KYC rail OTP (vendor)"],["WORM audit (0.2)","Form foundation (0.4)"])
epic("advw:P0-epic:0.4","Platform / UX","Reusable, accessible form stack in V5",
 "Give V5 a real form foundation (RHF + Radix primitives) so every regulated form is fast to build and accessible.",
 "V5 has no form library — every form is hand-rolled, taxing onboarding/order/comms work.",
 ["Form build time -50%","WCAG AA on new forms"],
 ["Add RHF + Radix form primitives","Reusable field kit + a11y","Multi-step form shell"],
 ["Design tokens overhaul"],["—"])
epic("advw:P0-epic:0.5","Engagement","Reliable client email delivery",
 "Stand up a comms dispatcher (email-first) so reports, reminders and alerts actually reach clients with delivery status.",
 "No email/SMS/WhatsApp sender exists — nudges only enqueue rows no worker sends.",
 ["Report email open rate >55%","Delivery success >98%"],
 ["Email adapter + templates","Compose to individual/segment/all","Delivery status + opt-out"],
 ["SMS/WhatsApp channels (vendor)"],["Scheduler (0.1)"])
epic("advw:P0-epic:0.6","Engagement","MFD white-label branding",
 "Let each MFD brand the client-facing surfaces (logo/colour/tagline) so clients see the MFD, not Nivesh.",
 "Only firm name + contact are stored; no branding config.",
 ["MFD branding adoption >70%","Branded report share >50%"],
 ["Branding config model + API","CSS-variable theme injection + preview","Expose to report/email templates"],
 ["Custom domain / CNAME (infra)"],["Form foundation (0.4)"])
epic("advw:P0-epic:0.7","Goals","Goal simulate/what-if works end-to-end",
 "Fix the FE↔BE contract drift so goal simulate/what-if returns parse and render for investors.",
 "Adapter safeParse throws contractDrift; goal simulate/what-if is broken in the UI.",
 ["Goal what-if error rate → 0","SIP-start post-goal >70%/7d"],
 ["Align field names FE↔BE","Shared contract regression test","Staging verify"],
 ["—"],["—"])
epic("advw:P0-epic:0.8","Goals","One-click goal plans & branded PDF",
 "Offer goal templates and a branded goal-plan PDF so advisors turn goals into fundable plans in one click.",
 "Goals are free-form; no library, no exportable plan.",
 ["Goal-plan PDF downloads >60%","Goals/investor >1.5"],
 ["Goal template library","Template gallery UI","Branded goal-plan PDF"],
 ["Order gateway for one-click SIP (vendor)"],["Branding (0.6)","Contract-drift fix (0.7)"])
epic("advw:P0-epic:0.9","Advisory","Side-by-side fund comparison",
 "Give investors a dedicated ≤3-fund comparison so they can choose funds with full metrics.",
 "Only a copilot-chat compare exists; no dedicated tool with rolling/risk/TER columns.",
 ["Compare-tool usage >30% of fund views","Research-score adoption >70%"],
 ["≤3-fund compare payload","Comparison grid UI","Share as PDF/link"],
 ["—"],["Form foundation (0.4)"])
epic("advw:P0-epic:0.10","Reporting","Branded portfolio statements",
 "Generate real branded holdings/performance statements and wire the review-pack worker so reports actually produce.",
 "Reporting is a prospect-proposal PDF + a review-pack stub that returns a mock URL.",
 ["Report delivery >98%","Statement generation <10s"],
 ["Review-pack worker","Branded statement PDF","Dispatch via comms + CAS reconcile"],
 ["Commission data (vendor)"],["Branding (0.6)","Comms (0.5)"])
epic("advw:P0-epic:0.11","Monitoring","Advisors action rebalance recommendations",
 "Let MFDs accept/modify/reject rebalancing recs and pre-fill orders so recommendations become actions.",
 "decisions.py accept/reject is a TODO stub; recs can't be actioned or tracked.",
 ["Rebalance execution >50%","Rec→action rate >45%"],
 ["Accept/modify/reject route","Order-prefill payload","Outcome-tracking hooks"],
 ["Order gateway for execution (vendor)"],["—"])
epic("advw:P0-epic:0.12","Tax","Scheme-wise realised capital-gains statement",
 "Export a scheme-wise realised STCG/LTCG statement so investors and advisors have tax-ready data.",
 "Export is holdings-only; no realised capital-gains statement despite a complete FIFO engine.",
 ["TLH advisory usage >25% pre-Mar31","CG statement downloads"],
 ["Realised CG endpoint (date range)","Excel + PDF export"],
 ["—"],["capital_gains_engine (exists)"])
epic("advw:P0-epic:0.13","Monitoring","Drift & underperformer alerts fire daily",
 "Run the existing drift/underperformer/SIP engines on a daily schedule and dispatch alerts to investor + MFD.",
 "Engines exist but never run on a schedule; no alerts are dispatched.",
 ["Reviews/client >4/yr","Newly-flagged fund digest daily"],
 ["Daily post-NAV job","Emit alerts + MFD digest","'Stale since last sync' state"],
 ["Real ECS-bounce (vendor)"],["Scheduler (0.1)","Comms (0.5)"])
# Phase-1 vendor-gated (procurement) epics
epic("advw:P1:1.1","Onboarding","Contract a KYC / eSign / eMandate provider",
 "Procure an ESP + NACH provider so digital regulated onboarding can be built.",
 "No UIDAI eKYC / DigiLocker eSign / NACH integration exists.",
 ["Vendor contracted + UAT credentials","Time-to-active <15 min (post-build)"],
 ["Select ESP (eKYC+eSign+KRA/CKYC)","Select NACH provider","Obtain UAT access"],
 ["Actual onboarding build (2.1)"],["Legal / compliance sign-off"])
epic("advw:P1:1.2","Transactions","Contract the MF order gateway (BSE STAR / MFU)",
 "Procure BSE STAR MF and/or MFU access — the keystone that unblocks all transactions.",
 "No MF order execution exists; buyable_universe.py confirms no transactable source.",
 ["Gateway UAT credentials in hand","Order-to-exchange <2s (post-build)"],
 ["Contract BSE STAR MF / MFU","Obtain UAT + MPIN flows","Scope order/status webhooks"],
 ["Order console build (2.2)"],["Regulatory posture (MFD)"])
epic("advw:P1:1.3","Compliance","Registry access for ARN & KYC status",
 "Procure AMFI ARN registry + KRA/CKYC status endpoints for compliance enforcement.",
 "ARN is unvalidated free text; no KRA/CKYC status queries.",
 ["Registry endpoints live","ARN lapse <0.5% (post-build)"],
 ["AMFI ARN registry access","KRA/CKYC status endpoints"],
 ["ARN/KYC enforcement (2.4)"],["—"])
epic("advw:P1:1.4","Engagement","Multi-channel comms gateways (SMS/WhatsApp)",
 "Procure DLT-registered SMS + WhatsApp BSP so alerts/comms reach clients beyond email.",
 "Only email is internally feasible; SMS/WhatsApp need gateways.",
 ["SMS/WhatsApp delivery >98%","Opt-out compliance 100%"],
 ["DLT SMS gateway","WhatsApp BSP"],
 ["Multi-channel alerts (2.3)","WF-07 comms"],["—"])
epic("advw:P1:1.5","Reporting","Commission data feeds (AMC)",
 "Procure AMC commission-advice feeds so brokerage reconciliation can be built.",
 "No commission ingest exists.",
 ["Feeds contracted (CAMS/Karvy/BSE)","Discrepancy <0.5% (post-build)"],
 ["SFTP/API commission feeds"],
 ["Commission subsystem (3.3)"],["Regulatory posture (MFD)"])
epic("advw:P1:1.6","Monitoring","Live registrar & ECS-bounce feeds",
 "Procure CAMS/KFin live pull + NACH bounce feed for real aggregation and SIP-bounce alerts.",
 "Holdings are CAS-upload-only; SIP-bounce fields are stubs.",
 ["Live sync daily","SIP recovery >80%/7d (post-build)"],
 ["CAMS/KFin live pull","NACH ECS-bounce feed"],
 ["Live feeds build (3.4)"],["—"])
epic("advw:P1:1.7","Advisory","Product-shelf partner integrations",
 "Procure PMS/AIF/bond/insurer/PFRDA-CRA/MMTC partners for non-MF product shelves.",
 "6 non-MF shelves are zero-code, each gated on its own partner.",
 ["Partners contracted (per shelf)","Products/client >2.0 (post-build)"],
 ["Per-partner API access"],
 ["Non-MF shelves (3.1)"],["—"])
# Phase-2 transactional epics
epic("advw:P2:2.1","Onboarding","Digital account opening (eKYC/eSign/eMandate)",
 "Build the regulated onboarding rail so an investor goes from lead to KYC-verified + mandate-active without paper.",
 "Onboarding is CAS-import only; no eKYC/eSign/eMandate/KRA.",
 ["Onboarding completion >85%","Mandate activation >90% T+1"],
 ["eKYC + eSign + eMandate","KRA/CKYC sync","Onboarding status tracker"],
 ["Nominee/FATCA edge flows (later)"],["KYC vendor (1.1)","Consent (0.3)","Forms (0.4)"])
epic("advw:P2:2.2","Transactions","Place & manage MF orders",
 "Build the BSE STAR/MFU order gateway + SIP lifecycle + order console — the transactional core.",
 "No MF order execution exists anywhere in the platform.",
 ["Order success >99%","Order-to-exchange <2s"],
 ["Order gateway (all txn types)","SIP create/modify/pause/cancel/step-up","Order console UI + MPIN"],
 ["Bulk orders (later)"],["Gateway vendor (1.2)","WORM audit (0.2)","Forms (0.4)"])
epic("advw:P2:2.3","Monitoring","Alerts across email/SMS/WhatsApp",
 "Wire monitoring alerts to multi-channel dispatch so drift/underperformer/SIP-bounce reach clients everywhere.",
 "Alerts can only go by email (internal); gated channels + ECS-bounce need vendors.",
 ["Multi-channel delivery >98%","Proactive-call rate >40%"],
 ["Wire alerts to SMS/WhatsApp","TRAI/DND suppression"],
 ["—"],["Monitoring wiring (0.13)","Gateways (1.4)","ECS feed (1.6)"])
epic("advw:P2:2.4","Compliance","Live ARN & KYC enforcement",
 "Enforce ARN validation (block orders on lapse) and KYC-status gating, with disclosure acks — license-to-operate.",
 "ARN is free text; no KYC gating; no disclosure enforcement.",
 ["KYC-expiry prevention >90%","ARN lapse <0.5%"],
 ["ARN validation + order-block + reminders","KYC status monitor + purchase-block","Disclosure-ack enforcement"],
 ["—"],["Registry access (1.3)","WORM audit (0.2)","Consent (0.3)"])
# Phase-3 breadth epics
epic("advw:P3:3.1","Advisory","Non-MF product shelves",
 "Build PMS/AIF/Bonds/Insurance/NPS/Digital-Gold shelves so advisors cross-sell beyond mutual funds.",
 "The platform is MF-only; 6 product classes are absent.",
 ["Products/client >2.0","MF→PMS upgrade >5%/yr"],
 ["Per-shelf catalogue + cards","Eligibility gates + EOI flows"],
 ["Deep transaction integration per shelf"],["Partners (1.7)","Forms (0.4)"])
epic("advw:P3:3.2","Engagement","MFD growth & marketing tooling",
 "Give MFDs white-label domains, eCards, content packs, lead funnel and HNI/engagement analytics to grow AUM.",
 "No marketing/lead/engagement tooling exists.",
 ["MFD AUM growth >25% YoY","Referral conversion >20%"],
 ["Custom domain + eCard + content pack","Lead funnel","HNI + engagement analytics"],
 ["—"],["Branding (0.6)","Comms (0.5)"])
epic("advw:P3:3.3","Reporting","Commission reconciliation & dashboard",
 "Reconcile AMC commission credits vs expected and give MFDs a commission dashboard.",
 "No commission subsystem exists.",
 ["Discrepancy <0.5%","Commission-dash WAU >65%"],
 ["AMC file ingest + matching","Commission dashboard + trail"],
 ["—"],["Order gateway (2.2)","Commission feeds (1.5)"])
epic("advw:P3:3.4","Monitoring","Live aggregation & real ECS-bounce",
 "Move from CAS-upload to live registrar aggregation with real SIP-bounce detection.",
 "Aggregation is CAS-upload-only; bounce data is stubbed.",
 ["Daily live sync","SIP recovery >80%/7d"],
 ["Daily PAN+consent pull","Real ECS-bounce alerts"],
 ["—"],["Registrar feeds (1.6)","Monitoring wiring (0.13)"])
epic("advw:P3:3.5","Reporting","Scheduled report delivery",
 "Let MFDs schedule branded reports to all clients on a cadence with delivery tracking.",
 "Reports are on-demand only; no scheduler.",
 ["Scheduled-report adoption >40%","Delivery >98%"],
 ["Frequency/channel config","Auto-generate + dispatch all clients","Delivery status + resend"],
 ["—"],["Scheduler (0.1)","Comms (0.5)","Statement worker (0.10)"])

# ── Story content: story sig → (title, user, action, benefit, [(given,when,then)...]) ──
S = {
 "advw:P0-story:0.1": ("Advisor receives a proactive portfolio alert","MFD","get notified when a client's portfolio breaches a threshold","I can act before performance deteriorates",
   [("a client holding breaches drift/underperformance","the daily job runs","an alert is dispatched to me and the client with status tracked"),
    ("the alert dispatcher is down","a job tries to send","the failure is recorded and retried, not silently dropped")]),
 "advw:P0-story:0.2": ("Every regulated action is written to a tamper-proof log","compliance officer","have an immutable, queryable audit trail","the firm is audit-ready with zero missed events",
   [("any platform event occurs","it is logged","the row cannot be updated or deleted (WORM)"),
    ("the audit store write fails","a transaction is in progress","the transaction is held, not completed")]),
 "advw:P0-story:0.3": ("Investor acknowledges required disclosures with OTP","investor","acknowledge RDD/KIM/commission/COI disclosures","I understand product risks before I transact",
   [("I purchase a new product category for the first time","I proceed","the required disclosures are shown and I ack via checkbox+OTP"),
    ("a disclosure version changes","I next log in","I am asked to re-acknowledge the new version")]),
 "advw:P0-story:0.4": ("Developer builds accessible forms from a shared kit","frontend developer","use a reusable form kit with validation and a11y","I ship regulated forms quickly and accessibly",
   [("I build a new form","I use the field kit","validation, error-announce and focus order work out of the box"),
    ("a form has multiple steps","I use the stepper shell","per-step validation and resume work")]),
 "advw:P0-story:0.5": ("Advisor emails a client and sees delivery status","MFD","send a client an email and see if it was delivered","I know my communications actually reached the client",
   [("I compose and send an email","the send succeeds","the delivery status shows sent/delivered"),
    ("a client has opted out","I send to a segment","that client is suppressed per TRAI/DND")]),
 "advw:P0-story:0.6": ("Advisor brands the client-facing experience","MFD","set my logo, colours and tagline","clients see my brand, not Nivesh",
   [("I save branding config","I open a client surface","it reflects my logo and colours"),
    ("I update my branding","24h passes","the change propagates to client surfaces")]),
 "advw:P0-story:0.7": ("Investor runs a goal what-if without errors","investor","adjust my SIP/return assumptions and see updated projections","I can plan my goal confidently",
   [("I open the Goals page","I run a what-if","the response parses and the verdict renders (no contractDrift)"),
    ("I change the surplus slider","the request succeeds","the projected corpus updates")]),
 "advw:P0-story:0.8": ("Investor generates a branded goal plan","investor","pick a goal template and export a branded plan","I have a clear, shareable plan for my goal",
   [("I select a goal template","I confirm","the creator is pre-filled with sensible defaults"),
    ("I request a goal plan","generation runs","a branded PDF is produced in <5s and saved to my vault")]),
 "advw:P0-story:0.9": ("Investor compares up to three funds side by side","investor","compare ≤3 funds on returns, risk, TER and score","I can choose the best fund for my goal",
   [("I select up to 3 funds","I open compare","trailing+rolling returns, SD/beta/Sharpe/Sortino/maxDD, Reg-vs-Direct TER, top-5 and score are shown"),
    ("I want to share a comparison","I click share","a PDF/link is produced")]),
 "advw:P0-story:0.10": ("Advisor sends a client a branded portfolio statement","MFD","generate and send a branded holdings/performance statement","clients get professional, on-brand reports",
   [("I request a client statement","the worker runs","a branded PDF is produced (result_url populated, not a mock)"),
    ("figures differ from CAS","generation is attempted","the discrepancy is flagged before send")]),
 "advw:P0-story:0.11": ("Advisor accepts or rejects a rebalancing recommendation","MFD","accept/modify/reject a rebalance rec with a note","recommendations turn into tracked actions",
   [("a rebalance rec is shown","I accept it","the decision persists and an order-prefill payload is produced"),
    ("I reject a rec","I add a note","the decision and note are recorded")]),
 "advw:P0-story:0.12": ("Investor exports a scheme-wise capital-gains statement","investor","export realised STCG/LTCG for a date range","I have tax-ready capital-gains data",
   [("I pick a date range","I export","a scheme-wise realised STCG/LTCG statement downloads (Excel/PDF)"),
    ("I hold equity <1 year","I export","it is classified STCG at the correct rate")]),
 "advw:P0-story:0.13": ("Advisor gets a daily digest of flagged funds","MFD","receive a daily digest of drift/underperformer/SIP flags","I can review and act on issues each morning",
   [("the daily post-NAV job runs","holdings breach thresholds","alerts are emitted to investor+MFD and a digest is sent"),
    ("data is stale","I open the dashboard","a 'stale since last sync' state is shown")]),
}

def epic_md(e, phase):
    return (f"📌 EPIC: {e['outcome']}\n\n"
        f"🎯 Goal / Objective:\n{e['goal']}\n\n"
        f"🧩 Problem Statement:\n{e['problem']}\n\n"
        f"📈 Success Metrics:\n" + "\n".join(f"- {m}" for m in e['metrics']) + "\n\n"
        f"🔍 Scope:\nIn scope:\n" + "\n".join(f"- {x}" for x in e['ins']) +
        f"\nOut of scope:\n" + "\n".join(f"- {x}" for x in e['outs']) + "\n\n"
        f"🔗 Dependencies:\n" + "\n".join(f"- {d}" for d in e['deps']) + "\n\n"
        f"⏳ Target Timeline: {TIMELINE.get(phase,'TBD')}\n\n"
        f"👥 Stakeholders: {STAKE}")

def story_md(title, user, action, benefit, acs, points, epic_id):
    ac = "\n".join(f"{i+1}. Given {g}, when {w}, then {t}." for i,(g,w,t) in enumerate(acs))
    return (f"📌 STORY: {title}\n\n"
        f"👤 User Story:\nAs a {user},\nI want to {action},\nSo that {benefit}.\n\n"
        f"✅ Acceptance Criteria (Given/When/Then):\n{ac}\n\n"
        f"🎨 Design: (link TBD)\n\n"
        f"📎 Notes / Edge Cases:\n- Handle empty/error/permission states\n- Admin-only surface\n\n"
        f"🔢 Story Points: {points}\n🔗 Epic Link: {epic_id}")

def task_md(desc, tech, estimate, parent_id):
    return (f"📝 Description:\n{desc}\n\n"
        f"✔️ Definition of Done:\n- [ ] Implemented with input validation\n- [ ] Verified on staging (real output shown)\n"
        f"- [ ] Tests added (unit/api/e2e as applicable)\n- [ ] Docs updated\n- [ ] Code reviewed and merged\n\n"
        f"🔧 Technical Notes:\n{tech}\n\n"
        f"⏱️ Estimate: {estimate}\n🔗 Parent Story: {parent_id}")

def clean_desc(msg):
    # strip the "Epic 0.X (Name). Owner ... size M. Deps: ... Internal. TASK_... " preamble
    if not msg: return ""
    m = re.sub(r"^Epic\s+[0-9]+(?:\.[0-9]+)?\s*(?:\([^)]*\))?\.\s*", "", msg, flags=re.I)
    m = re.sub(r"^(Owner[^.]*\.\s*|size\s+[SMLX/–-]+\.?\s*|Deps?:[^.]*\.\s*|Internal\.?\s*|TASK_[a-z_]+\.?\s*)+", "", m, flags=re.I)
    return m.strip() or msg.strip()

def files_in(msg):
    fs = re.findall(r"[A-Za-z0-9_./]+\.(?:py|ts|tsx|sql)(?::[0-9\-]+)?", msg or "")
    return "- Key files: " + ", ".join(dict.fromkeys(fs)) if fs else "- Follow existing patterns in the touched module."

def verb_title(t):
    t = re.sub(r"^\[[0-9.]+\]\s*", "", t)          # drop [0.1.1]
    t = re.sub(r"^[^—]*—\s*", "", t)               # drop "Scheduler/Dispatcher — "
    return t[:1].upper() + t[1:] if t else t

def main():
    if not TOKEN and not DRY:
        print("ERROR: NIVESH_ADMIN_TOKEN not set"); sys.exit(1)
    issues = _req("GET", "/api/work/issues?project=ADVW&limit=500")["issues"] if not DRY_FETCH_SKIP else []
    by_id = {i["issue_id"]: i for i in issues}
    patched = 0; samples = {"epic":0,"story":0,"task":0}
    for i in issues:
        sig = i.get("sig", ""); it = i.get("issue_type", ""); iid = i["issue_id"]
        if ONLY and sig != ONLY: continue
        body = None; new_title = None
        if it == "epic" and sig in E:
            e = E[sig]; new_title = f"[{e['area']}] – {e['outcome']}"
            body = {"title": new_title, "requirements_md": epic_md(e, i.get("phase") or "")}
        elif it == "story" and sig in S:
            title,user,action,benefit,acs = S[sig]
            new_title = title
            body = {"title": new_title, "requirements_md": story_md(title,user,action,benefit,acs,i.get("estimate") or 5, i.get("parent"))}
        elif it == "task":
            desc = clean_desc(i.get("sample_message"))  # sample_message is the untouched original (idempotent)
            new_title = verb_title(i.get("title") or "")
            body = {"title": new_title, "requirements_md": task_md(desc, files_in(i.get("sample_message")), EST.get(i.get("estimate") or "M","2–4 days"), i.get("parent"))}
        if not body: continue
        if DRY:
            if samples.get(it,9) < 1:
                samples[it] = samples.get(it,0)+1
                print(f"\n===== {it.upper()} {iid} ({sig}) =====\nTITLE: {body['title']}\n{body['requirements_md']}")
            continue
        _req("PATCH", f"/api/work/issues/{iid}", body); patched += 1
        print(f"  {it:5} {iid} → {body['title'][:60]}")
    print(f"\n{'DRY — samples above' if DRY else f'DONE. patched {patched}'}")

DRY_FETCH_SKIP = False
if __name__ == "__main__":
    if DRY and not TOKEN:
        print("(dry-run needs a token to fetch live items; pass NIVESH_ADMIN_TOKEN to preview real data)")
    main()
