# 02 · Agent command centre — UI test cases (AD-UI-30..39)

Written 5 Nov 2026 before the screen code. Design: `docs/autodesk/design/prototype/TDAgents.dc.html`. Screen:
`frontend-v5/src/autodesk/screens/Agents.tsx` (route `/autodesk/agents`). Spec: `frontend-v5/e2e/tests/autodesk-agents.spec.ts`
with fixtures in `autodesk-fixtures-agents.ts` (MOCK — shapes of the real API: `backend/autodesk/routers/api.py`, rows of
`autodesk.agent_registry`, `autodesk.agent_tasks`, `autodesk.agent_handoffs`, `autodesk.workflows`).

Layers: E = Playwright on the production build with route mocks; C = request contract (this screen sends no request
body: it is read-only).

Data: `GET /agents` (registry; the latest registered version per agent is the current one), `GET /agents/{key}/activity`
(desk tasks only: rows with a `simulation_id` are left out), `GET /desk/workflows/{id}` (full task rows + handoffs for the
decision trace), `GET /desk/workflows?account_id=…&kind=TRADE_PROPOSAL` per desk account (workflows in flight),
`GET /trade-plans` and `GET /signals/{id}` (names of the workflows).

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-UI-30 | E | Header, headline and status legend from `GET /agents` (5 agents, one older registry version) | eyebrow "02 · Agent command centre"; pills "Desk Orchestrator · deterministic" and "5 agents · 6 registered versions"; headline "All five agents are healthy." when every current agent is IDLE/BUSY, and "Four agents are healthy. *Tech Support* is degraded." when TECH_SUPPORT is DEGRADED; legend lists all seven statuses (IDLE, BUSY, SCALING, DEGRADED, MAINTENANCE, QUARANTINED, OFFLINE) with counts of the current versions |
| AD-UI-31 | E | Five agent cards from registry + activity | cards in the design order AI Trader, Trading Assistant, Risk & Operations, Middle Office, Tech Support; each: status pill, ♥ heartbeat age from `last_heartbeat`, role, current or last task, QUEUE "—" marked Phase 3, LAST SUCCESS = completion time · entity of the latest COMPLETED desk task, three recent decisions = `result_summary` as the agent wrote it, "N errors · N retries" from the desk tasks; a simulation task in the activity is not shown |
| AD-UI-32 | E | Decision trace: default = the most recent desk task; click another agent's decision line | eyebrow "Decision trace · {agent}" with the task's entity id; title = its `result_summary`; ten fields from the task row and the workflow's handoffs: requesting (upstream handoff agent or Desk Orchestrator), receiving (downstream handoff agent or Desk Orchestrator), input refs, structured output (schema + verdict/status fields), evidence refs, tool calls (count, tool names, ms), validation (schema ✓ · domain ✓), time · retries (latency_ms, attempt − 1), handoff, decision (state + summary); the "Hidden model reasoning is neither stored nor shown" note; clicking a decision line of another card shows that task's trace |
| AD-UI-33 | E | Permissions, model and config, human escalation of the selected agent | ✓ pills for the descriptor's task types and tools, × pills for `prohibited`; model line "{version} · deterministic · model — · prompt —"; escalation text for the agent and the count of escalated desk tasks |
| AD-UI-34 | E | Workflows in flight (13-step proposal workflow) | desk TRADE_PROPOSAL workflows of every desk account, newest first with in-flight (WAITING_HUMAN/RUNNING/CREATED) on top; WAITING_HUMAN → 4 steps done and step 5 amber "Step 5 · waiting on you"; APPROVED_NO_EXECUTION → 5 steps done; NO_TRADE at strategy → stopped at step 2; a revised plan (version 2) marks the revision step; steps 6–13 are never filled (Phase 2); names = instrument · strategy from the plan, or the signal's instrument when there is no plan; a simulation workflow is not listed |
| AD-UI-35 | E | Empty states | an agent with no desk tasks: "No desk tasks yet" and no decisions; no proposal workflows: a sentence saying they start when a session cycle runs; empty registry: "No agents are registered yet." |
| AD-UI-36 | E | API errors | `GET /agents` 500 → error box with the API's message in place of the cards; one agent's activity 500 → the error inside that card only, other cards render; workflow detail 404 → error box inside the decision trace |
| AD-UI-37 | E | No sample data from the prototype | none of the prototype's sample ids or figures (SIG-10267, PLN-2045, RSK-5530, APR-3107, INC-0311, "9 instances", "BSE feed", "187 of 212") appear; queue depth and scaling are labelled as later-phase states |
| AD-UI-38 | E | Phone 390×844 | single-column cards, trace and side panels stacked, workflow rows stacked; no horizontal overflow |
| AD-UI-39 | E+C | Read-only and clean | the screen sends no POST/PUT/DELETE; every request is under /autodesk/api/v1 (or the shell's /api/auth/me, /api/live/quotes); no console errors |
