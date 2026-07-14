#!/usr/bin/env python3
"""Create Design Tasks (standard Design-Task template) under the UI-bearing
stories/epics of the ADVW project. Idempotent (POST dedupes by sig).

Usage: NIVESH_ADMIN_TOKEN=... python3 add_design_tasks.py [--dry-run]
"""
import os, sys, json, urllib.request, urllib.error

BASE = os.environ.get("NIVESH_BASE", "https://staging.niveshcopilot.com")
TOKEN = os.environ.get("NIVESH_ADMIN_TOKEN", "")
DRY = "--dry-run" in sys.argv
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
H = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA,
     "Authorization": "Bearer " + TOKEN}

def _req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=H)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read().decode())

DS = "the V5 design system (frontend-v5 tokens + components/shared)"
STD_REQS = [f"Must follow {DS}", "Must support dark mode", "Accessibility: WCAG 2.1 AA minimum"]

# (sig, parent_sig, title, objective, persona, extra_reqs[], refs[], estimate, needed_by)
D = [
 ("advw:design:0.4","advw:P0-story:0.4","Design the V5 form component kit",
  "Design the reusable form field kit (input/select/checkbox/radio/slider/OTP) + multi-step stepper so every regulated form is consistent and accessible.",
  "Internal: developers building onboarding/order/comms forms — the pattern every investor/MFD form inherits.",
  ["OTP + scroll-gate + consent-confirm patterns included","Error-announce + focus order specified","Max friction: labels + inline validation"],
  ["Existing components/shared/{Stepper,ConfirmationDrawer}","Radix form primitives"],"5 days","Before Sprint 1 (Phase-1)"),
 ("advw:design:0.3","advw:P0-story:0.3","Design the disclosure acknowledgement flow (checkbox + OTP)",
  "Design SEBI disclosure presentation + checkbox+OTP acknowledgement + the MFD 'X pending' view.",
  "Investor acknowledging RDD/KIM/commission/COI; MFD tracking pending acks.",
  ["Scroll-to-end gate before ack enabled","Versioned re-ack prompt","Max 3 steps"],
  ["ConfirmationDrawer","DPDP consent-ledger UI"],"3 days","Before Sprint 2 (Phase-1)"),
 ("advw:design:0.5","advw:P0-story:0.5","Design the client email composer",
  "Design compose-to individual/segment/all with channel, personalisation-token preview, scheduling, and delivery status.",
  "MFD sending client communications at scale.",
  ["Token preview ({client_name}, {portfolio_value}…)","Segment picker from existing tags/filters","Delivery-status chips + opt-out visibility","Novel UI — prototype required"],
  ["No existing composer analog","AdvisorDashboard patterns"],"5 days","Before Sprint 2 (Phase-1)"),
 ("advw:design:0.6","advw:P0-story:0.6","Design the white-label branding config + live preview",
  "Design MFD branding setup (logo/colour/tagline) with a live preview of client-facing surfaces.",
  "MFD configuring their brand in Settings.",
  ["Live preview via CSS-variable theming","Logo upload + colour pickers","Extend the Settings layout"],
  ["tailwind.config CSS-vars","Settings page"],"3 days","Before Sprint 2 (Phase-1)"),
 ("advw:design:0.8","advw:P0-story:0.8","Design the goal template gallery + goal-plan PDF",
  "Design the 8-template goal gallery (picker → prefill creator) and the branded goal-plan PDF layout.",
  "Investor picking a goal; MFD presenting the plan.",
  ["Template gallery cards → prefill custom-goal creator","Branded PDF: projection chart, SIP schedule, basket, assumptions","Print + screen layouts"],
  ["pages/Goals","reportlab PDF path"],"4 days","Before Sprint 2 (Phase-1)"),
 ("advw:design:0.9","advw:P0-story:0.9","Design the ≤3-fund comparison screen",
  "Design a side-by-side comparison of up to 3 funds across returns/risk/TER/holdings/score, with share.",
  "Investor choosing a fund for a goal.",
  ["≤3-fund picker","Grid: rolling + SD/beta/Sharpe/Sortino/maxDD + Reg-vs-Direct TER + top-5 + score","Responsive table → cards; share PDF/link"],
  ["components/charts/RiskReturnBubble","FundDetails"],"4 days","Before Sprint 3 (Phase-1)"),
 ("advw:design:0.10","advw:P0-story:0.10","Design the branded portfolio statement template",
  "Design the branded actual-holdings/performance statement (logo/colour/tagline, allocation pie, holdings, SIP, performance chart).",
  "MFD dispatching periodic statements; client reading them.",
  ["MFD branding applied throughout","Print/PDF layout","Allocation pie + performance chart","Reconciled-figures note"],
  ["portfolio_builder_export reportlab","components/charts/AllocationDonut"],"3 days","Before Sprint 3 (Phase-1)"),
 ("advw:design:0.11","advw:P0-story:0.11","Design the rebalance accept/modify/reject flow",
  "Design the MFD flow to review a rebalancing rec and accept/modify/reject with a mandatory note, showing tax/exit-load impact.",
  "MFD actioning rebalancing recommendations.",
  ["Reuse ConfirmationDrawer","Tax + exit-load impact display","Mandatory note on modify/reject","Pre-fill order handoff state"],
  ["ConfirmationDrawer","TaxImpactPanel","RecommendationCard"],"3 days","Before Sprint 3 (Phase-1)"),
 ("advw:design:0.13","advw:P0-story:0.13","Design the alert / notification surface + MFD digest",
  "Design where drift/underperformer/SIP alerts appear for investor + MFD, the MFD daily digest, and the 'stale since last sync' state.",
  "MFD reviewing daily flags; investor receiving alerts.",
  ["Alert list + live-region (a11y)","Severity via glyph + label (not colour-only)","Digest layout","Stale-state indicator"],
  ["No existing alert-center — new shared surface"],"3 days","Before Sprint 3 (Phase-1)"),
 ("advw:design:2.1","advw:P2:2.1","Design the digital onboarding wizard (eKYC/eSign/eMandate)",
  "Design the end-to-end regulated onboarding wizard (Aadhaar eKYC → eSign bundle → eMandate → status) + the MFD pipeline tracker.",
  "New investor (retail/HNI) self-onboarding; MFD tracking the pipeline.",
  ["Multi-step stepper with resume","OTP/lockout, timeout & graceful fallback (UIDAI down → manual KYC)","eSign scroll-gate viewer","Vendor SDK handoff (redirects) — finalise once vendor is known"],
  ["Stepper","form kit (design 0.4)","vendor SDK docs (TBD)"],"1.5 weeks","1 sprint before Phase-2 build (post vendor 1.1)"),
 ("advw:design:2.2","advw:P2:2.2","Design the MF order console + SIP management",
  "Design the order ticket (all txn types), cut-off indicator, MPIN entry, failed-order retry, and the SIP lifecycle screen.",
  "Investor placing/managing orders; MFD bulk ordering.",
  ["Order ticket for lumpsum/SIP/redeem/switch/SWP/STP","Cut-off-time indicator","MPIN/biometric entry","Failed-order reason + retry","Bulk multi-select + preview + exclude"],
  ["ConfirmationDrawer","HoldingsTable (bulk select)","BSE STAR UAT (TBD)"],"2 weeks","1 sprint before Phase-2 build (post vendor 1.2)"),
 ("advw:design:3.1","advw:P3:3.1","Design the product-shelf browse/card/factsheet pattern",
  "Design a reusable shelf pattern (list → card → factsheet → EOI) for PMS/AIF/Bonds/Insurance/NPS/Gold with eligibility gates.",
  "Investor browsing non-MF products; MFD recommending.",
  ["Reusable card + factsheet drawer","Eligibility gate (e.g. AIF net-worth)","Request-Info/EOI forms","Suitability banner","Bonds ISIN table"],
  ["Card/MetricCard","HoldingsTable","partner data (TBD)"],"1.5 weeks","1 sprint before each shelf build (Phase-3)"),
 ("advw:design:3.2","advw:P3:3.2","Design the MFD marketing suite (composer, eCard, lead funnel, segments)",
  "Design the growth tooling: eVisiting card designer, social content pack, lead funnel board, HNI analytics, and the segment AND/OR rule builder.",
  "MFD growing their book.",
  ["Segment AND/OR rule builder","Lead funnel (Kanban, keyboard-accessible)","eCard template picker + QR","Content-pack gallery","Novel interactions — prototype + moodboard"],
  ["AdvisorDashboard","novel — needs moodboard"],"2 weeks","Phase-3"),
]

def design_md(objective, persona, reqs, refs, estimate, needed_by, parent_id):
    return (f"🎯 Objective:\n{objective}\n\n"
        f"👤 Target User / Persona:\n{persona}\n\n"
        f"📦 Deliverables:\n- [ ] User flow diagram\n- [ ] Wireframes (low-fi)\n- [ ] High-fidelity mockups (mobile + desktop)\n- [ ] Interactive prototype\n- [ ] Design specs / redlines for dev handoff\n\n"
        f"🧭 Requirements & Constraints:\n" + "\n".join(f"- {r}" for r in reqs) + "\n\n"
        f"🎨 References / Inspiration:\n" + "\n".join(f"- {r}" for r in refs) + "\n\n"
        f"✔️ Definition of Done:\n- [ ] Reviewed by PM & Eng Lead\n- [ ] Feasibility confirmed with engineering\n- [ ] Accessibility check passed\n- [ ] Approved in design review\n- [ ] Handed off in Figma with dev annotations\n\n"
        f"🔗 Links:\n- Figma file: (TBD)\n- Parent Story/Epic: {parent_id}\n- Related research: (TBD)\n\n"
        f"⏱️ Estimate: {estimate}\n📅 Needed by: {needed_by}")

def main():
    if not TOKEN and not DRY:
        print("ERROR: NIVESH_ADMIN_TOKEN not set"); sys.exit(1)
    issues = _req("GET", "/api/work/issues?project=ADVW&limit=500")["issues"] if not DRY else []
    by_sig = {i["sig"]: i for i in issues}
    print(f"Fetched {len(issues)} ADVW items. {len(D)} design tasks to create. DRY={DRY}")
    created = 0
    for sig, psig, title, obj, persona, xreqs, refs, est, need in D:
        parent = by_sig.get(psig)
        parent_id = parent["issue_id"] if parent else "?"
        wf = parent.get("workflow", []) if parent else []
        phase = parent.get("phase") if parent else None
        track = parent.get("track") if parent else None
        body = {
            "sig": sig, "title": f"Design – {title.replace('Design the ','').replace('Design ','')}"[:80],
            "issue_type": "task", "project": "ADVW", "parent": parent_id,
            "phase": phase, "track": track, "workflow": wf, "assignee": "design-engineer",
            "estimate": None, "priority": "P2", "severity": "WARNING", "source": "manual",
            "labels": ["advisory-workflows", "design", "type:design-task"] + wf,
            "requirements_md": design_md(obj, persona, STD_REQS + xreqs, refs, est, need, parent_id),
        }
        if DRY:
            if created < 1:
                print(f"\n===== {sig} (parent {psig}) =====\nTITLE: {body['title']}\n{body['requirements_md']}")
            created += 1; continue
        r = _req("POST", "/api/work/issues", body)
        print(f"  design {r['issue_id']} → {body['title'][:56]}  (parent {parent_id})")
        created += 1
    print(f"\n{'DRY — sample above' if DRY else f'DONE. {created} design tasks'}")

if __name__ == "__main__":
    main()
