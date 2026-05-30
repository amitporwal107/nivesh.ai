#!/usr/bin/env python3
"""
Nivesh.ai Work Monitor Board
Run: python3 /app/monitor.py
Board at http://localhost:7771  — auto-refreshes every 60s
"""

import json
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

WORKSPACE = Path("/app/.claude/workspace")
MEMORY = Path("/root/.claude/projects/-app/memory")


# ─────────────────────────────────────────────────────────────────────────────
# Parsers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_status_cell(cell: str) -> str:
    """Normalise a raw status string → BLOCKED|IN_PROGRESS|DONE|BACKLOG"""
    cell = cell.strip().upper()
    if "DONE" in cell:
        return "DONE"
    if "BLOCKED" in cell or "BLOCKED" in cell:
        return "BLOCKED"
    if "IN_PROGRESS" in cell or "IN PROGRESS" in cell or "STARTED" in cell:
        # NOT STARTED → BACKLOG
        if "NOT" in cell:
            return "BACKLOG"
        return "IN_PROGRESS"
    if "PENDING" in cell or "NOT STARTED" in cell:
        return "BACKLOG"
    return "BACKLOG"

def _priority_from_size(size: str) -> str:
    size = size.upper().strip()
    if "XL" in size:    return "P1"
    if size in ("L", "**L–XL**", "L–XL"): return "P1"
    if size == "M–L":   return "P2"
    if size == "M":     return "P2"
    if size == "S–M":   return "P2"
    if size == "S":     return "P3"
    return "P3"

def _clean(s: str) -> str:
    """Strip markdown bold/code/links."""
    s = re.sub(r'\*\*([^*]+)\*\*', r'\1', s)
    s = re.sub(r'`([^`]+)`', r'\1', s)
    s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', s)
    s = re.sub(r'~~([^~]+)~~', r'[DONE] \1', s)
    return s.strip().strip('|').strip()

def parse_workspace_project(proj_dir: Path) -> dict | None:
    """Parse a workspace project into an epic dict."""
    plan_file = proj_dir / "plan.md"
    status_file = proj_dir / "status.md"
    if not plan_file.exists():
        return None

    plan_text = plan_file.read_text(errors="replace")
    status_text = status_file.read_text(errors="replace") if status_file.exists() else ""

    # Extract project name from heading
    name_match = re.search(r'^#+ (.+)', plan_text, re.MULTILINE)
    name = _clean(name_match.group(1)) if name_match else proj_dir.name

    # Parse overall status from status.md
    overall = "IN_PROGRESS"
    if "DONE" in status_text.upper() and "IN PROGRESS" not in status_text.upper():
        overall = "DONE"

    # Colour based on name
    colors = {
        "recommendation": "#be185d",
        "portfolio": "#0891b2",
        "performance": "#0891b2",
        "v3": "#7c3aed",
        "nidp": "#d97706",
    }
    color = "#6366f1"
    for k, v in colors.items():
        if k in proj_dir.name.lower():
            color = v
            break

    # Parse table rows from plan.md
    cards = []
    # Find all markdown table rows: | # | Step description | Owner | ... | Status |
    # Headers vary; we look for rows where last cell is a status keyword
    table_rows = re.findall(r'^\|(.+)\|$', plan_text, re.MULTILINE)

    # Detect header row by finding a row with "Step" and "Status" columns
    header_idx = None
    col_indices = {}
    for i, row in enumerate(table_rows):
        cells = [c.strip() for c in row.split('|')]
        cells_upper = [c.upper() for c in cells]
        if 'STEP' in cells_upper and 'STATUS' in cells_upper:
            header_idx = i
            for j, c in enumerate(cells_upper):
                if c == '#' or c == 'NO' or c == 'STEP' or c == 'NUM':
                    col_indices['num'] = j
                if c == 'STEP':
                    col_indices['step'] = j
                if c == 'OWNER':
                    col_indices['owner'] = j
                if c == 'SIZE':
                    col_indices['size'] = j
                if c == 'STATUS':
                    col_indices['status'] = j
                if 'DEPEND' in c:
                    col_indices['deps'] = j
            break

    if header_idx is not None:
        num_col   = col_indices.get('num', 0)
        step_col  = col_indices.get('step', 1)
        owner_col = col_indices.get('owner', 2)
        size_col  = col_indices.get('size', 4)
        status_col = col_indices.get('status', -1)
        deps_col   = col_indices.get('deps', -1)

        # Current phase label (track ## Phase N headings)
        # We need to associate each table row with its preceding phase heading
        phase_labels = {}
        # Build line-by-line map of phases vs table rows
        lines = plan_text.split('\n')
        current_phase = "Steps"
        table_row_idx = 0
        parsed_rows = []
        for line in lines:
            ph = re.match(r'^##+ (.+)', line)
            if ph:
                current_phase = ph.group(1).strip()
            row_match = re.match(r'^\|(.+)\|$', line)
            if row_match:
                cells = [c.strip() for c in row_match.group(1).split('|')]
                if len(cells) > max(step_col, status_col if status_col >= 0 else 0):
                    parsed_rows.append((current_phase, cells))

        for phase_name, cells in parsed_rows:
            # Skip header/separator rows
            if all(re.match(r'^[-:]+$', c.strip()) or c.strip() in ('', '#', '—') for c in cells):
                continue
            step_text = cells[step_col] if step_col < len(cells) else ""
            if not step_text or step_text.upper() in ('#', 'STEP', '—', ''):
                continue
            step_text_clean = _clean(step_text)
            if not step_text_clean or step_text_clean == '—':
                continue

            raw_status = cells[status_col] if status_col >= 0 and status_col < len(cells) else "BACKLOG"
            status = _parse_status_cell(raw_status)

            step_num = cells[num_col].strip() if num_col < len(cells) else "?"
            owner = cells[owner_col].strip() if owner_col < len(cells) else ""
            size = cells[size_col].strip() if size_col >= 0 and size_col < len(cells) else "M"
            deps = cells[deps_col].strip() if deps_col >= 0 and deps_col < len(cells) else ""
            priority = _priority_from_size(size)

            # Build label list
            labels = [phase_name.replace("Phase ", "Ph")]
            if owner:
                labels.append(owner[:20])

            detail_parts = []
            if deps:
                detail_parts.append(f"Deps: {_clean(deps)}")
            if raw_status.strip() and raw_status.strip() != status:
                detail_parts.append(f"Note: {_clean(raw_status)}")

            cards.append({
                "id": f"{proj_dir.name.upper()[:12]}-{step_num}",
                "title": step_text_clean,
                "status": status,
                "priority": priority,
                "labels": labels[:3],
                "detail": " | ".join(detail_parts) if detail_parts else step_text_clean,
            })

    # Add an overview card from status.md
    needs_input = re.findall(r'NEEDS-INPUT[^:]*:\s*(.+)', status_text)
    if needs_input:
        cards.insert(0, {
            "id": f"{proj_dir.name.upper()[:12]}-OVW",
            "title": f"Open NEEDS-INPUT ({len(needs_input)} items)",
            "status": "BLOCKED",
            "priority": "P1",
            "labels": ["needs-input", "planning"],
            "detail": " | ".join([ni.strip()[:120] for ni in needs_input[:3]]),
        })

    return {
        "id": proj_dir.name.upper().replace("-", "_"),
        "name": name,
        "color": color,
        "source": "workspace",
        "cards": cards,
    }


def get_board() -> dict:
    epics = []

    # ── 1. Live workspace projects ──
    if WORKSPACE.exists():
        for proj_dir in sorted(WORKSPACE.iterdir()):
            if proj_dir.is_dir() and not proj_dir.name.startswith("_"):
                epic = parse_workspace_project(proj_dir)
                if epic and epic["cards"]:
                    epics.append(epic)

    # ── 2. Static memory-based epics ──
    epics += [
        {
            "id": "BUGS",
            "name": "Open Defects",
            "color": "#dc2626",
            "source": "memory",
            "cards": [
                {
                    "id": "BUG-011", "title": "Dashboard crash — Zod contract drift on getNavHistory",
                    "status": "BLOCKED", "priority": "P1",
                    "labels": ["V5", "frontend"],
                    "detail": "ErrorState on /v5/dashboard. NavPointC schema expects series[].date + series[].value_rs but API returns different shape. Fix: update NavPointC in portfolio.contract.ts.",
                    "file": "frontend-v5/src/services/contracts/portfolio.contract.ts",
                },
                {
                    "id": "BUG-012", "title": "Google Sign-In silently fails — fix committed but NOT deployed",
                    "status": "BLOCKED", "priority": "P1",
                    "labels": ["V5", "auth"],
                    "detail": "renderButton() fix in commit 7431d38 not deployed. Users can't sign in via Google in Chrome (3P cookies off), Firefox, Safari.",
                },
                {
                    "id": "BUG-013", "title": "/api/auth/me rate-limited (429) on page load",
                    "status": "BACKLOG", "priority": "P2",
                    "labels": ["V5", "auth"],
                    "detail": "Multiple useMe() hooks fire simultaneously → 429. Fix: staleTime in React Query or raise rate limit.",
                },
                {
                    "id": "BUG-014", "title": "Concentration treemap blank in some viewports",
                    "status": "BACKLOG", "priority": "P2",
                    "labels": ["V5", "viz"],
                    "detail": "SectorTreemap SVG empty. Likely zero-size container. Check with agent-browser --headed.",
                    "file": "frontend-v5/src/components/charts/SectorTreemap.tsx",
                },
                {
                    "id": "BUG-015", "title": "Sidebar missing on Portfolio + Concentration (headless)",
                    "status": "BACKLOG", "priority": "P2",
                    "labels": ["V5", "layout"],
                    "detail": "hasSidebar: false in Playwright snapshots. Verify AppLayout renders <aside> at lg: breakpoint unconditionally.",
                },
                {
                    "id": "BUG-005", "title": "Portfolio endpoints log WARNINGs — missing relation tables",
                    "status": "BACKLOG", "priority": "P2",
                    "labels": ["backend", "migrations"],
                    "detail": "Apply pending migration for relation tables.",
                },
                {
                    "id": "BUG-010", "title": "NIDP migrations not idempotent (5 offenders in 037/047/050/057/058)",
                    "status": "BACKLOG", "priority": "P3",
                    "labels": ["NIDP", "migrations"],
                    "detail": "Add IF NOT EXISTS / DROP IF EXISTS guards. Genuine failures buried in false-positive noise.",
                },
                {
                    "id": "BUG-007-009", "title": "Infra noise — archive_raw, Fluent Bit, EMERGENT_LLM_KEY",
                    "status": "BACKLOG", "priority": "P4",
                    "labels": ["ops", "NIDP"],
                    "detail": "BUG-007: archive_raw Cloud Run path. BUG-008: Fluent Bit missing log file. BUG-009: EMERGENT_LLM_KEY missing in Secret Manager.",
                },
            ],
        },
        {
            "id": "V5_PROD",
            "name": "V5 Frontend — Prod Blockers",
            "color": "#7c3aed",
            "source": "memory",
            "cards": [
                {
                    "id": "V5-PROD-1", "title": "CAS Connect widget not integrated (onboarding broken)",
                    "status": "BLOCKED", "priority": "P0",
                    "labels": ["V5", "onboarding", "prod"],
                    "detail": "Onboarding adapter calls wrong endpoint. CAS Connect SDK not wired. Blocks all new user onboarding.",
                    "file": "frontend-v5/src/services/adapters/",
                },
                {
                    "id": "V5-PROD-2", "title": "npm run build never verified — TS errors unknown",
                    "status": "BLOCKED", "priority": "P0",
                    "labels": ["V5", "build", "prod"],
                    "detail": "frontend-v5 has never been built. Must pass `npm run build` clean before any deploy.",
                    "file": "frontend-v5/",
                },
                {
                    "id": "V5-PROD-3", "title": "RequireAuth not wired into router",
                    "status": "BACKLOG", "priority": "P0",
                    "labels": ["V5", "auth", "prod"],
                    "detail": "Component exists but routes are unprotected. Wrap authenticated routes in RequireAuth.",
                },
                {
                    "id": "V5-PROD-4", "title": "CORS/cookie attrs for v5 origin not confirmed on staging",
                    "status": "BACKLOG", "priority": "P1",
                    "labels": ["V5", "infra", "prod"],
                    "detail": "SameSite + cookie config for /v5 origin unverified. May block auth on staging.",
                },
            ],
        },
        {
            "id": "V3_REDESIGN",
            "name": "V3 Mobile+Web Redesign",
            "color": "#0891b2",
            "source": "memory",
            "cards": [
                {
                    "id": "V3-000", "title": "apiClient.js — add apiPut/apiPatch/apiDelete wrappers",
                    "status": "BACKLOG", "priority": "P1",
                    "labels": ["V3", "iter-1", "preflight"],
                    "detail": "Needed by V3-005, 006, 011, 012, 014.",
                },
                {
                    "id": "V3-001", "title": "Settings — logout, admin/advisor sections, risk profile stub",
                    "status": "IN_PROGRESS", "priority": "P0",
                    "labels": ["V3", "iter-1"],
                    "detail": "Branch: feature/v3-mobile-web-redesign. AccountCard, localStorage toggles, RiskProfileSheet stub.",
                    "file": "frontend-v5/src/pages/Settings/",
                },
                {
                    "id": "V3-002", "title": "Concentration — 100% mock removal, SectorBarChart, DetailPanel",
                    "status": "BACKLOG", "priority": "P0",
                    "labels": ["V3", "iter-1"],
                    "detail": "concentration.js adapter, 6 CompactCards, real backend data.",
                    "file": "frontend-v5/src/pages/Concentration/",
                },
                {
                    "id": "V3-003-004", "title": "Performance + Risk Analysis screens",
                    "status": "BACKLOG", "priority": "P1",
                    "labels": ["V3", "iter-1"],
                    "detail": "Performance: period chips, 4 benchmark tiles, RiskReturnScatter. Risk: 3 dimensions, Top Drivers.",
                },
                {
                    "id": "V3-007-010", "title": "Iter 2 — Benchmark, Risk Profile wizard, Family, Trading",
                    "status": "BACKLOG", "priority": "P2",
                    "labels": ["V3", "iter-2"],
                    "detail": "4 screens ~11h total.",
                },
                {
                    "id": "V3-011-012", "title": "Iter 3 — Plan Board + Goals",
                    "status": "BACKLOG", "priority": "P3",
                    "labels": ["V3", "iter-3"],
                    "detail": "HealthDonut, GoalProgressBars, PATCH mutations. ~11h.",
                },
                {
                    "id": "V3-013-014", "title": "Iter 4 — Strategy Builder + Client Snapshot",
                    "status": "BACKLOG", "priority": "P3",
                    "labels": ["V3", "iter-4"],
                    "detail": "5-step wizard, EquityCurveChart, 14-section MFD client snapshot. ~16h.",
                },
            ],
        },
        {
            "id": "RISK_GOALS",
            "name": "Risk & Goal Profiling (RP backlog)",
            "color": "#059669",
            "source": "memory",
            "cards": [
                {
                    "id": "RP-001", "title": "Post-onboarding profile completion wizard (Risk → Goals → Snapshot)",
                    "status": "BACKLOG", "priority": "P1",
                    "labels": ["V5", "goals", "risk"],
                    "detail": "3-step wizard. Dashboard progress banner. Blocks all RP-002..RP-008.",
                    "file": "frontend-v5/src/pages/Dashboard/PersonaCard.tsx",
                },
                {
                    "id": "RP-002", "title": "Settings — Financial Profile section",
                    "status": "BACKLOG", "priority": "P1",
                    "labels": ["V5", "settings"],
                    "detail": "Risk profile card + goals CRUD + snapshot editor. V5 Settings is a UI shell today.",
                    "file": "frontend-v5/src/pages/Settings/",
                },
                {
                    "id": "RP-003", "title": "Overview — Risk + Goal alignment insights (5 new insight types)",
                    "status": "BACKLOG", "priority": "P2",
                    "labels": ["V5", "insights"],
                    "detail": "Allocation drift, goal-at-risk, horizon-volatility mismatch, regular→direct, over-equity for profile.",
                },
                {
                    "id": "RP-004-005", "title": "Gate Action Matrix + goal-based rebalancing reasons",
                    "status": "BACKLOG", "priority": "P2",
                    "labels": ["V5", "rec-engine"],
                    "detail": "RP-004: block plan generation until profile+goals set. RP-005: extend ActionPlanManager with goal context on each action.",
                },
                {
                    "id": "RP-006-008", "title": "What-if simulator, capacity vs tolerance, de-risk trigger",
                    "status": "BACKLOG", "priority": "P3",
                    "labels": ["V5", "goals", "backend"],
                    "detail": "RP-006: GoalCard sliders (backend exists). RP-007: capacity_score + tolerance_score. RP-008: TRIM on >90% funded.",
                },
            ],
        },
        {
            "id": "NIDP",
            "name": "NIDP Data Platform",
            "color": "#d97706",
            "source": "memory",
            "cards": [
                {
                    "id": "NIDP-AMC", "title": "AMC scrapers broken — 10 sites 404, 4 MF scoring primitives at 0%",
                    "status": "BLOCKED", "priority": "P1",
                    "labels": ["NIDP", "MF", "scrapers"],
                    "detail": "consistency_score, downside_capture, aum_trend, turnover_ratio all 0% covered. Blocks consolidation rec engine surfacing.",
                    "file": "backend/nidp/services/mf_holdings/",
                },
                {
                    "id": "NIDP-S4S5", "title": "S4/S5 pipeline embedder (Week 2)",
                    "status": "IN_PROGRESS", "priority": "P1",
                    "labels": ["NIDP", "AI", "S5"],
                    "detail": "NSE+BSE announcements → classifier → pgvector LIVE (2026-05-07). Embedder = S5 Week 2, pending.",
                },
                {
                    "id": "NIDP-056", "title": "Stock category scorecard — migration 056",
                    "status": "BACKLOG", "priority": "P2",
                    "labels": ["NIDP", "scoring", "migration"],
                    "detail": "v_stock_category_scorecard by sector. Persona-aware weights: Investor/Trader/Advisor.",
                },
                {
                    "id": "NIDP-GROWW", "title": "Replace Groww HTML scraper with NIDP nightly cron",
                    "status": "BACKLOG", "priority": "P2",
                    "labels": ["NIDP", "V3", "cron"],
                    "detail": "POST /admin/v3-stock-score-nidp exists. Wire cron post refresh_stock_features().",
                },
                {
                    "id": "NIDP-TI-CRON", "title": "TI engine entry missing from cron schedule",
                    "status": "BACKLOG", "priority": "P2",
                    "labels": ["NIDP", "cron", "ops"],
                    "detail": "Vol/beta coverage 99% since migration 060. But TI engine cron entry never added.",
                },
            ],
        },
        {
            "id": "COPILOT",
            "name": "Copilot Chat",
            "color": "#0284c7",
            "source": "memory",
            "cards": [
                {
                    "id": "TASK-083", "title": "Persona-aware Copilot pipeline — 99-entry catalog + 7 specialists",
                    "status": "DONE", "priority": "P1",
                    "labels": ["copilot", "persona"],
                    "detail": "feat/copilot-persona-prompts commit beaa236. 5-category chips, persona framing, copilot_persona_prompts_enabled flag. DONE 2026-05-19.",
                },
                {
                    "id": "COPILOT-REDESIGN", "title": "Chat redesign — SSE route event + follow-up chips + top_recommendations orchestrator",
                    "status": "IN_PROGRESS", "priority": "P1",
                    "labels": ["copilot", "frontend"],
                    "detail": "On feat/copilot-persona-prompts pending PR. SSE route event, follow-up chips, /api/intelligence/portfolio orchestrator.",
                },
                {
                    "id": "REC-CONSOLID", "title": "Consolidation/Exit rec surfacing — blocked on NIDP AMC data",
                    "status": "BLOCKED", "priority": "P2",
                    "labels": ["rec-engine", "NIDP"],
                    "detail": "Engines shipped (PR #39). winner_pick_pending=True. Unblocks when AMC scrapers fixed.",
                },
                {
                    "id": "REC-PERSONA", "title": "Persona rec engine — 17 engines, all signals wired",
                    "status": "DONE", "priority": "P1",
                    "labels": ["rec-engine", "persona"],
                    "detail": "CategorySuitabilityEngine + BehaviouralPersonaFilterEngine + updated RA/Underperformer. severity/execution_path/requires_confirmation on all signals. DONE 2026-05-29.",
                },
                {
                    "id": "TASK-077-086", "title": "Epic 11 remainder — TASK-077..086",
                    "status": "BACKLOG", "priority": "P2",
                    "labels": ["copilot", "epic-11"],
                    "detail": "TASK-077 to 082 + 084 to 086. Not started.",
                },
            ],
        },
        {
            "id": "SECURITY",
            "name": "Security / Epic 10",
            "color": "#991b1b",
            "source": "memory",
            "cards": [
                {
                    "id": "SEC-TOKENS", "title": "CRITICAL: Live tokens in git history + 4 .token files in tree",
                    "status": "BLOCKED", "priority": "P0",
                    "labels": ["security", "CRITICAL"],
                    "detail": "PAT rotated 2026-05-22 but residual in history. gitleaks not in CI. Must purge history + add gitleaks hook.",
                },
                {
                    "id": "TASK-064-068", "title": "Epic 10 — hardening, observability, WAF, VAPT, prod checklist",
                    "status": "BACKLOG", "priority": "P1",
                    "labels": ["security", "ops", "epic-10"],
                    "detail": "TASK-064 SEBI/DPDP hardening. TASK-065 Grafana alerts. TASK-066 WAF. TASK-067 VAPT. TASK-068 prod checklist. All not started.",
                },
            ],
        },
    ]

    return {"epics": epics, "updated": __import__("datetime").datetime.now().isoformat()}


# ─────────────────────────────────────────────────────────────────────────────
# HTML + JS board
# ─────────────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nivesh.ai Work Board</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f1117;--surface:#171b26;--surface2:#1e2235;--border:#2a2f45;
  --text:#dde3f0;--muted:#6b748a;--accent:#6366f1;
  --blocked:#ef4444;--inprog:#3b82f6;--backlog:#4b5563;--done:#22c55e;
}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;height:100vh;display:flex;flex-direction:column}

/* ── header ── */
header{background:var(--surface);border-bottom:1px solid var(--border);padding:10px 18px;display:flex;align-items:center;gap:12px;flex-shrink:0;z-index:100}
.logo{font-size:14px;font-weight:800;letter-spacing:-.4px;color:#fff}
.logo span{color:var(--accent)}
.pill{padding:2px 9px;border-radius:99px;font-size:11px;font-weight:700;letter-spacing:.2px}
.pill-blocked{background:rgba(239,68,68,.15);color:#fca5a5}
.pill-inprog{background:rgba(59,130,246,.15);color:#93c5fd}
.pill-backlog{background:rgba(75,85,99,.15);color:#9ca3af}
.pill-done{background:rgba(34,197,94,.15);color:#86efac}
.spacer{flex:1}
.ts{color:var(--muted);font-size:11px}
input.search{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:5px 10px;color:var(--text);font-size:12px;width:180px;outline:none}
input.search:focus{border-color:var(--accent)}
.refresh{background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:4px 11px;border-radius:6px;cursor:pointer;font-size:12px}
.refresh:hover{background:var(--border)}

/* ── columns ── */
.board{flex:1;display:flex;gap:0;overflow:hidden}
.col{flex:1;min-width:220px;display:flex;flex-direction:column;border-right:1px solid var(--border)}
.col:last-child{border-right:none}
.col-hd{padding:10px 12px 8px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:7px;flex-shrink:0}
.col-hd.blocked{border-top:2px solid var(--blocked)}
.col-hd.inprog{border-top:2px solid var(--inprog)}
.col-hd.backlog{border-top:2px solid var(--backlog)}
.col-hd.done{border-top:2px solid var(--done)}
.col-name{font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.6px}
.col-cnt{background:var(--surface2);border:1px solid var(--border);border-radius:99px;padding:1px 7px;font-size:10px;color:var(--muted)}
.cards-wrap{flex:1;overflow-y:auto;padding:8px 8px 24px;display:flex;flex-direction:column;gap:6px}
.cards-wrap::-webkit-scrollbar{width:3px}
.cards-wrap::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}

/* ── epic group ── */
.epic-grp{margin-top:4px}
.epic-grp:first-child{margin-top:0}
.epic-lbl{display:flex;align-items:center;gap:5px;padding:3px 3px 4px;cursor:default}
.epic-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.epic-nm{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--muted)}
.epic-src{font-size:9px;color:#374151;margin-left:2px}

/* ── card ── */
.card{background:var(--surface);border:1px solid var(--border);border-radius:7px;padding:9px 11px;cursor:pointer;transition:border-color .12s,box-shadow .12s}
.card:hover{border-color:#404660;box-shadow:0 2px 8px rgba(0,0,0,.35)}
.card.open{border-color:var(--accent)}
.card.hidden{display:none}
.cid{font-size:9.5px;color:var(--muted);font-family:'SF Mono',monospace;margin-bottom:3px}
.ctitle{font-size:12px;font-weight:500;line-height:1.45;color:var(--text)}
.cmeta{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}
.badge{font-size:10px;padding:2px 6px;border-radius:4px;font-weight:700}
.p0{background:rgba(239,68,68,.12);color:#fca5a5}
.p1{background:rgba(249,115,22,.12);color:#fdba74}
.p2{background:rgba(234,179,8,.12);color:#fde047}
.p3{background:rgba(34,197,94,.12);color:#86efac}
.p4{background:rgba(107,114,128,.12);color:#9ca3af}
.tag{background:var(--surface2);color:var(--muted);font-size:10px;padding:2px 6px;border-radius:4px}
.cfile{font-size:10px;color:#818cf8;font-family:'SF Mono',monospace;margin-top:4px;word-break:break-all}
.cdetail{margin-top:7px;padding-top:7px;border-top:1px solid var(--border);font-size:11px;color:#7e8fb5;line-height:1.65;display:none}
.card.open .cdetail{display:block}

/* ── filter row ── */
.filter-row{background:var(--surface);border-bottom:1px solid var(--border);padding:6px 18px;display:flex;gap:8px;flex-wrap:wrap;flex-shrink:0}
.ftag{padding:3px 10px;border-radius:99px;font-size:11px;cursor:pointer;border:1px solid var(--border);color:var(--muted);transition:all .12s}
.ftag:hover,.ftag.active{background:var(--accent);border-color:var(--accent);color:#fff}
</style>
</head>
<body>
<header>
  <div class="logo">Nivesh<span>.ai</span> Board</div>
  <span class="pill pill-blocked" id="cnt-b">0</span>
  <span class="pill pill-inprog" id="cnt-i">0</span>
  <span class="pill pill-backlog" id="cnt-k">0</span>
  <span class="pill pill-done" id="cnt-d">0</span>
  <div class="spacer"></div>
  <span class="ts" id="ts">—</span>
  <input class="search" type="text" placeholder="Search…" oninput="filterCards(this.value)" id="search">
  <button class="refresh" onclick="load()">↻</button>
</header>
<div class="filter-row" id="filter-row"></div>
<div class="board">
  <div class="col" id="col-BLOCKED"><div class="col-hd blocked"><span class="col-name" style="color:#fca5a5">🔴 Blocked</span><span class="col-cnt" id="hc-BLOCKED">0</span></div><div class="cards-wrap" id="cw-BLOCKED"></div></div>
  <div class="col" id="col-IN_PROGRESS"><div class="col-hd inprog"><span class="col-name" style="color:#93c5fd">● In Progress</span><span class="col-cnt" id="hc-IN_PROGRESS">0</span></div><div class="cards-wrap" id="cw-IN_PROGRESS"></div></div>
  <div class="col" id="col-BACKLOG"><div class="col-hd backlog"><span class="col-name" style="color:#9ca3af">◻ Backlog</span><span class="col-cnt" id="hc-BACKLOG">0</span></div><div class="cards-wrap" id="cw-BACKLOG"></div></div>
  <div class="col" id="col-DONE"><div class="col-hd done"><span class="col-name" style="color:#86efac">✓ Done</span><span class="col-cnt" id="hc-DONE">0</span></div><div class="cards-wrap" id="cw-DONE"></div></div>
</div>

<script>
let data = null, activeTag = null;

async function load() {
  const r = await fetch('/api/board');
  data = await r.json();
  render(data);
  document.getElementById('ts').textContent = 'Refreshed ' + new Date().toLocaleTimeString();
}

function render(d) {
  // Group cards by status → epic
  const cols = { BLOCKED:{}, IN_PROGRESS:{}, BACKLOG:{}, DONE:{} };
  const allTags = new Set();
  for (const epic of d.epics) {
    for (const card of epic.cards) {
      const st = card.status;
      if (!cols[st]) continue;
      if (!cols[st][epic.id]) cols[st][epic.id] = { epic, cards:[] };
      cols[st][epic.id].cards.push(card);
      (card.labels||[]).forEach(t => allTags.add(t));
    }
  }

  const counts = { BLOCKED:0, IN_PROGRESS:0, BACKLOG:0, DONE:0 };
  for (const [st, groups] of Object.entries(cols)) {
    const wrap = document.getElementById('cw-'+st);
    wrap.innerHTML = '';
    for (const { epic, cards } of Object.values(groups)) {
      const grp = document.createElement('div');
      grp.className = 'epic-grp';
      grp.innerHTML = `<div class="epic-lbl"><span class="epic-dot" style="background:${epic.color}"></span><span class="epic-nm">${epic.name}</span><span class="epic-src">${epic.source==='workspace'?'📋':''}</span></div>`;
      for (const card of cards) {
        grp.appendChild(makeCard(card));
        counts[st]++;
      }
      wrap.appendChild(grp);
    }
    document.getElementById('hc-'+st).textContent = counts[st];
  }
  document.getElementById('cnt-b').textContent = counts.BLOCKED + ' Blocked';
  document.getElementById('cnt-i').textContent = counts.IN_PROGRESS + ' Active';
  document.getElementById('cnt-k').textContent = counts.BACKLOG + ' Backlog';
  document.getElementById('cnt-d').textContent = counts.DONE + ' Done';

  // Build filter tags
  buildFilters([...allTags].sort());
  if (activeTag) applyTag(activeTag);
}

function makeCard(card) {
  const el = document.createElement('div');
  el.className = 'card';
  el.dataset.id = card.id;
  el.dataset.tags = (card.labels||[]).join(' ').toLowerCase();
  el.dataset.search = (card.id+' '+card.title+' '+(card.labels||[]).join(' ')+' '+(card.detail||'')).toLowerCase();
  const tags = (card.labels||[]).map(l=>`<span class="tag">${l}</span>`).join('');
  const file = card.file ? `<div class="cfile">📄 ${card.file}</div>` : '';
  el.innerHTML = `<div class="cid">${card.id}</div><div class="ctitle">${card.title}</div><div class="cmeta"><span class="badge ${card.priority.toLowerCase()}">${card.priority}</span>${tags}</div>${file}<div class="cdetail">${card.detail||''}</div>`;
  el.addEventListener('click', ()=>el.classList.toggle('open'));
  return el;
}

function buildFilters(tags) {
  const row = document.getElementById('filter-row');
  row.innerHTML = '<span class="ftag '+(activeTag===null?'active':'')+'" onclick="applyTag(null)">All</span>';
  for (const t of tags) {
    const span = document.createElement('span');
    span.className = 'ftag' + (activeTag===t?' active':'');
    span.textContent = t;
    span.onclick = () => applyTag(t);
    row.appendChild(span);
  }
}

function applyTag(tag) {
  activeTag = tag;
  document.querySelectorAll('.ftag').forEach(el => {
    el.classList.toggle('active', el.textContent === (tag||'All'));
  });
  const q = document.getElementById('search').value.toLowerCase().trim();
  document.querySelectorAll('.card').forEach(c => {
    const tagMatch = !tag || c.dataset.tags.includes(tag.toLowerCase());
    const qMatch = !q || c.dataset.search.includes(q);
    c.classList.toggle('hidden', !(tagMatch && qMatch));
  });
}

function filterCards(q) {
  q = q.toLowerCase().trim();
  document.querySelectorAll('.card').forEach(c => {
    const tagMatch = !activeTag || c.dataset.tags.includes(activeTag.toLowerCase());
    const qMatch = !q || c.dataset.search.includes(q);
    c.classList.toggle('hidden', !(tagMatch && qMatch));
  });
}

load();
setInterval(load, 60000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/api/board"):
            body = json.dumps(get_board(), default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


if __name__ == "__main__":
    port = 7771
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"✓ Work board → http://localhost:{port}")
    print("  Auto-parses /app/.claude/workspace/ + memory files. Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
