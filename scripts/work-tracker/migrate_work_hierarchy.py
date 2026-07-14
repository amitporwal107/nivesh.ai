#!/usr/bin/env python3
"""Migrate the flat advisory-workflows tickets into an Epic → Story → Task tree
with phase/track/workflow + requirements. Idempotent (POST dedupes by sig; PATCH
by issue_id). RUN ONLY AFTER the updated backend (work.py hierarchy fields) is
deployed to staging — the current staging backend ignores the new fields.

Usage: NIVESH_ADMIN_TOKEN=... python3 migrate_work_hierarchy.py [--dry-run]
"""
import os, sys, json, urllib.request, urllib.error

BASE = os.environ.get("NIVESH_BASE", "https://staging.niveshcopilot.com")
TOKEN = os.environ.get("NIVESH_ADMIN_TOKEN", "")
DRY = "--dry-run" in sys.argv
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
H = {"Content-Type": "application/json", "Accept": "application/json",
     "User-Agent": UA, "Authorization": "Bearer " + TOKEN}

def _req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=H)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read().decode())

def list_all():
    return _req("GET", "/api/work/issues?limit=500")["issues"]

def post(body):    return _req("POST", "/api/work/issues", body)
def patch(iid, b): return _req("PATCH", f"/api/work/issues/{iid}", b)

# ── Phase-0 epics (tracker phase-1, internal). (num, title, workflows, estimate) ──
P0_EPICS = [
    ("0.1",  "Scheduler / Alert Dispatcher foundation", ["WF-04","WF-02","WF-05","WF-06"], "M"),
    ("0.2",  "WORM audit promotion (fail-closed, full events)", ["WF-06"], "M"),
    ("0.3",  "Consent / disclosure layer extension", ["WF-06","WF-01","WF-03"], "M"),
    ("0.4",  "V5 form foundation (RHF + Radix primitives)", ["WF-01","WF-05","WF-06","WF-07"], "M"),
    ("0.5",  "Comms dispatcher (email-MVP)", ["WF-07","WF-04","WF-02"], "M"),
    ("0.6",  "Branding / white-label config store", ["WF-07","WF-05","WF-02"], "M"),
    ("0.7",  "WF-02 FE↔BE contract-drift fix", ["WF-02"], "S"),
    ("0.8",  "Goal library + goal-plan PDF", ["WF-02"], "M"),
    ("0.9",  "Fund Comparison Tool", ["WF-03"], "M"),
    ("0.10", "Branded holdings statement + review-pack worker", ["WF-05","WF-07"], "M"),
    ("0.11", "Rebalance accept/modify/reject route", ["WF-04"], "M"),
    ("0.12", "Scheme-wise realised capital-gains export", ["WF-04"], "S"),
    ("0.13", "Wire monitoring engines → scheduler + dispatcher", ["WF-04"], "M"),
]
P0_EPIC_REQ = "Phase-1 internal foundation/quick-win epic. See child stories/tasks for scope; " \
              "all buildable now with no external-vendor dependency."

# ── Existing epics WORK-00xx by sig → (phase, track, workflows) ──
EPIC_ENRICH = {
    "advw:P1:1.1": ("phase-1","vendor-gated",["WF-01","WF-06"]),
    "advw:P1:1.2": ("phase-1","vendor-gated",["WF-05"]),
    "advw:P1:1.3": ("phase-1","vendor-gated",["WF-06"]),
    "advw:P1:1.4": ("phase-1","vendor-gated",["WF-07","WF-04"]),
    "advw:P1:1.5": ("phase-1","vendor-gated",["WF-05"]),
    "advw:P1:1.6": ("phase-1","vendor-gated",["WF-04"]),
    "advw:P1:1.7": ("phase-1","vendor-gated",["WF-03"]),
    "advw:P2:2.1": ("phase-2","vendor-gated",["WF-01","WF-06"]),
    "advw:P2:2.2": ("phase-2","vendor-gated",["WF-05"]),
    "advw:P2:2.3": ("phase-2","vendor-gated",["WF-04"]),
    "advw:P2:2.4": ("phase-2","vendor-gated",["WF-06"]),
    "advw:P3:3.1": ("phase-3","vendor-gated",["WF-03"]),
    "advw:P3:3.2": ("phase-3","internal",["WF-07"]),
    "advw:P3:3.3": ("phase-3","vendor-gated",["WF-05","WF-07"]),
    "advw:P3:3.4": ("phase-3","vendor-gated",["WF-04"]),
    "advw:P3:3.5": ("phase-3","internal",["WF-05","WF-07"]),
}

def main():
    if not TOKEN and not DRY:
        print("ERROR: NIVESH_ADMIN_TOKEN not set"); sys.exit(1)
    issues = [] if DRY else list_all()
    by_sig = {i["sig"]: i for i in issues}
    print(f"Fetched {len(issues)} issues. DRY={DRY}")

    plan = {"create_epics": [], "create_stories": [], "patch_tasks": [], "patch_epics": []}

    # 1) Phase-0 epics + one story each
    epic_sig_by_num, story_sig_by_num = {}, {}
    for num, title, wfs, est in P0_EPICS:
        esig = f"advw:P0-epic:{num}"; ssig = f"advw:P0-story:{num}"
        epic_sig_by_num[num] = esig; story_sig_by_num[num] = ssig
        plan["create_epics"].append({
            "sig": esig, "title": f"[{num}] {title}", "issue_type": "epic",
            "phase": "phase-1", "track": "internal", "workflow": wfs, "estimate": est,
            "priority": "P1" if num in ("0.1","0.2","0.4","0.5","0.7") else "P2",
            "severity": "WARNING", "source": "manual",
            "labels": ["advisory-workflows","phase-0","type:epic","internal"] + wfs,
            "requirements_md": P0_EPIC_REQ,
        })
        plan["create_stories"].append({
            "sig": ssig, "title": f"[{num}] {title} — implementation", "issue_type": "story",
            "phase": "phase-1", "track": "internal", "workflow": wfs,
            "priority": "P2", "severity": "WARNING", "source": "manual",
            "labels": ["advisory-workflows","phase-0","type:story","internal"] + wfs,
            "requirements_md": f"Story grouping the concrete tasks for epic {num}.",
            "_parent_epic_sig": esig,
        })

    # 2) Re-parent the 42 Phase-0 tasks → their epic's story
    for i in issues:
        sig = i["sig"]
        if sig.startswith("advw:P0:"):           # e.g. advw:P0:0.1.1
            dotted = sig.split(":")[-1]           # 0.1.1
            num = ".".join(dotted.split(".")[:2]) # 0.1
            wfs = next((w for n,_,w,_ in P0_EPICS if n == num), [])
            plan["patch_tasks"].append({
                "issue_id": i["issue_id"], "sig": sig, "_epic_num": num,
                "body": {"issue_type": "task", "phase": "phase-1", "track": "internal",
                         "workflow": wfs},  # parent filled after stories exist
            })

    # 3) Enrich existing epics WORK-00xx
    for sig,(phase,track,wfs) in EPIC_ENRICH.items():
        i = by_sig.get(sig)
        if not i and not DRY:
            print(f"  WARN missing epic sig {sig}"); continue
        plan["patch_epics"].append({
            "issue_id": i["issue_id"] if i else "?", "sig": sig,
            "body": {"issue_type": "epic", "phase": phase, "track": track, "workflow": wfs},
        })

    print(f"Plan: +{len(plan['create_epics'])} epics  +{len(plan['create_stories'])} stories  "
          f"~{len(plan['patch_tasks'])} tasks re-parented  ~{len(plan['patch_epics'])} epics enriched")
    if DRY:
        for e in plan["create_epics"]:  print("  EPIC ", e["sig"], e["title"])
        for s in plan["create_stories"]:print("  STORY", s["sig"])
        print(f"  (tasks/epics patched at run time once ids resolve)")
        return

    # 0) Create the ADVW project (top of hierarchy) — the "Advisory Workflows" requirement
    proj = post({
        "sig": "proj:ADVW", "title": "Advisory Workflows", "issue_type": "project", "project": "ADVW",
        "requirements_md": "Create the advisory workflows (WF-01..07) integrated into the current system.",
        "assignee": "aporwal107@gmail.com", "status": "in_progress", "priority": "P1",
        "severity": "WARNING", "source": "manual", "labels": ["project", "key:ADVW", "advisory-workflows"],
    })
    advw_id = proj["issue_id"]; print(f"  project {advw_id} ADVW")

    # 1) Create epics (parented to the project, project=ADVW)
    esig_to_id = {}
    for e in plan["create_epics"]:
        body = {k: v for k, v in e.items() if not k.startswith("_")}
        body["project"] = "ADVW"; body["parent"] = advw_id
        r = post(body); esig_to_id[e["sig"]] = r["issue_id"]; print(f"  epic  {r['issue_id']} {e['sig']}")
    # 2) Create stories (parented to their epic, project=ADVW)
    ssig_to_id = {}
    for s in plan["create_stories"]:
        body = {k: v for k, v in s.items() if not k.startswith("_")}
        body["parent"] = esig_to_id.get(s["_parent_epic_sig"]); body["project"] = "ADVW"
        r = post(body); ssig_to_id[s["sig"]] = r["issue_id"]; print(f"  story {r['issue_id']} {s['sig']}")
    # 3) Re-parent the 42 tasks to their story, project=ADVW
    for t in plan["patch_tasks"]:
        story_id = ssig_to_id.get(f"advw:P0-story:{t['_epic_num']}")
        body = dict(t["body"]); body["parent"] = story_id; body["project"] = "ADVW"
        patch(t["issue_id"], body); print(f"  task  {t['issue_id']} → story {story_id}")
    # 4) Enrich the 16 existing epics (parent=project, project=ADVW)
    for e in plan["patch_epics"]:
        body = dict(e["body"]); body["parent"] = advw_id; body["project"] = "ADVW"
        patch(e["issue_id"], body); print(f"  epic+ {e['issue_id']} {e['sig']}")
    # 5) Stamp project=ADVW on any remaining advisory-workflows item (e.g. the tracking row)
    for i in issues:
        if i["sig"].startswith("advw:") and i.get("project") != "ADVW":
            patch(i["issue_id"], {"project": "ADVW"})
    print("\nDONE. Verify: GET /api/work/issues?issue_type=project  ·  ?project=ADVW  ·  ?issue_type=epic&project=ADVW")

if __name__ == "__main__":
    main()
