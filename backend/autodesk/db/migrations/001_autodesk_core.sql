-- Autonomous Trading Desk — core schema (Phase 1). Applied by autodesk.db.migrate on service start, inside one
-- transaction, recorded in autodesk.schema_migrations. Idempotent (IF NOT EXISTS) so a re-run is harmless.
--
-- Rules carried into the schema (PRD §16.7, architecture §13.3):
--   * every row carries tenant_id; account-level rows carry account_id; simulated rows carry simulation_id
--   * money / prices / quantities are NUMERIC; timestamps are timestamptz (UTC)
--   * plan versions, policy versions, approvals, risk assessments and events are append-only (triggers refuse
--     UPDATE/DELETE); current state lives in small "head" rows (trade_plans.current_version, workflows.state …)
--   * there is no LIVE account kind: this app never routes to a broker

CREATE SCHEMA IF NOT EXISTS autodesk;

CREATE OR REPLACE FUNCTION autodesk.refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'autodesk.%: rows are append-only (% refused)', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END $$;

-- ── Simulations (created before accounts: a SIMULATION account points at its simulation) ───────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.simulations (
    simulation_id     text PRIMARY KEY,
    tenant_id         text NOT NULL,
    name              text NOT NULL,
    mode              text NOT NULL CHECK (mode IN ('HISTORICAL_REPLAY','ACCELERATED_REPLAY','SCENARIO','LIVE_SHADOW')),
    status            text NOT NULL CHECK (status IN ('CREATED','RUNNING','PAUSED','STOPPED','COMPLETED','FAILED')),
    config            jsonb NOT NULL,
    account_id        text,
    clock_sim_time    timestamptz,                -- the simulation clock (UTC)
    clock_session     date,                       -- session date the clock is in
    clock_phase       text,                       -- ClockPhase reached last
    step_seq          integer NOT NULL DEFAULT 0, -- number of clock steps taken
    versions          jsonb NOT NULL DEFAULT '{}'::jsonb,   -- agent / rule / policy / engine versions pinned at create
    results           jsonb,
    error             text,
    created_by        text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    started_at        timestamptz,
    ended_at          timestamptz,
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS simulations_tenant_idx ON autodesk.simulations (tenant_id, created_at DESC);

-- ── Accounts ─────────────────────────────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.accounts (
    account_id          text PRIMARY KEY,
    tenant_id           text NOT NULL,
    name                text NOT NULL,
    kind                text NOT NULL CHECK (kind IN ('PAPER','SIMULATION','SHADOW')),
    operating_mode      text NOT NULL CHECK (operating_mode IN ('RESEARCH','ASSISTED','AUTONOMOUS_PAPER')),
    starting_capital_rs numeric(18,2) NOT NULL CHECK (starting_capital_rs > 0),
    currency            text NOT NULL DEFAULT 'INR',
    simulation_id       text REFERENCES autodesk.simulations(simulation_id),
    policy_id           text NOT NULL,
    status              text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUSPENDED','CLOSED')),
    created_by          text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT accounts_sim_binding CHECK ((kind = 'SIMULATION') = (simulation_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS accounts_tenant_idx ON autodesk.accounts (tenant_id);

-- ── Policies (versioned, immutable versions) ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.policies (
    policy_id       text PRIMARY KEY,
    tenant_id       text NOT NULL,
    name            text NOT NULL,
    scope_type      text NOT NULL CHECK (scope_type IN ('TENANT','ACCOUNT','STRATEGY','SEGMENT')),
    scope_ref       text,
    current_version integer NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS autodesk.policy_versions (
    policy_id   text NOT NULL REFERENCES autodesk.policies(policy_id),
    version     integer NOT NULL CHECK (version >= 1),
    body        jsonb NOT NULL,
    body_sha256 text NOT NULL,
    created_by  text NOT NULL,
    reason      text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (policy_id, version)
);
DROP TRIGGER IF EXISTS policy_versions_append_only ON autodesk.policy_versions;
CREATE TRIGGER policy_versions_append_only BEFORE UPDATE OR DELETE ON autodesk.policy_versions
    FOR EACH ROW EXECUTE FUNCTION autodesk.refuse_change();

-- ── Agent registry ───────────────────────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.agent_registry (
    agent_key      text NOT NULL CHECK (agent_key IN ('AI_TRADER','TRADING_ASSISTANT','RISK_OPS','MIDDLE_OFFICE','TECH_SUPPORT')),
    version        text NOT NULL,
    kind           text NOT NULL CHECK (kind IN ('DETERMINISTIC','LLM_ASSISTED')),
    model          text,
    prompt_version text,
    descriptor     jsonb NOT NULL,             -- AgentDescriptor: task types, tools, prohibited authority
    status         text NOT NULL DEFAULT 'IDLE'
                   CHECK (status IN ('IDLE','BUSY','SCALING','DEGRADED','MAINTENANCE','QUARANTINED','OFFLINE')),
    last_heartbeat timestamptz,
    registered_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_key, version)
);

-- ── Workflows and agent tasks ────────────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.workflows (
    workflow_id        text PRIMARY KEY,
    tenant_id          text NOT NULL,
    account_id         text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id      text REFERENCES autodesk.simulations(simulation_id),
    kind               text NOT NULL CHECK (kind IN ('SESSION_CYCLE','PREMARKET_CHECK','MARKET_SCAN','TRADE_PROPOSAL')),
    state              text NOT NULL CHECK (state IN ('CREATED','RUNNING','WAITING_HUMAN','COMPLETED','BLOCKED','FAILED','CANCELLED')),
    parent_workflow_id text REFERENCES autodesk.workflows(workflow_id),
    correlation_id     text NOT NULL,
    session_date       date,
    sim_time           timestamptz,
    input              jsonb NOT NULL DEFAULT '{}'::jsonb,
    outcome            jsonb,
    error              text,
    idempotency_key    text UNIQUE,              -- prevents duplicate workflow execution
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    completed_at       timestamptz
);
CREATE INDEX IF NOT EXISTS workflows_account_idx ON autodesk.workflows (account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS workflows_sim_idx ON autodesk.workflows (simulation_id, created_at);
CREATE INDEX IF NOT EXISTS workflows_open_idx ON autodesk.workflows (state) WHERE state IN ('CREATED','RUNNING','WAITING_HUMAN');

CREATE TABLE IF NOT EXISTS autodesk.agent_tasks (
    task_id                text PRIMARY KEY,
    workflow_id            text NOT NULL REFERENCES autodesk.workflows(workflow_id),
    simulation_id          text REFERENCES autodesk.simulations(simulation_id),
    tenant_id              text NOT NULL,
    account_id             text,
    from_agent             text NOT NULL,
    to_agent               text NOT NULL,
    task_type              text NOT NULL,
    step                   text,                  -- workflow step name, e.g. "plan", "risk", "approval"
    entity_id              text,
    input_refs             jsonb NOT NULL DEFAULT '[]'::jsonb,
    constraints            jsonb NOT NULL DEFAULT '{}'::jsonb,
    required_output_schema text NOT NULL,
    state                  text NOT NULL,
    attempt                integer NOT NULL DEFAULT 0,
    max_attempts           integer NOT NULL DEFAULT 2,
    deadline_s             numeric(10,3) NOT NULL,
    sim_time               timestamptz,
    result                 jsonb,                 -- AgentResult.output
    result_summary         text,
    result_ref             text,                  -- e.g. plan://TRD-…@2
    evidence_refs          jsonb NOT NULL DEFAULT '[]'::jsonb,
    tool_calls             jsonb NOT NULL DEFAULT '[]'::jsonb,
    validation             jsonb,                 -- {schema_ok, domain_ok, errors[]}
    error                  text,
    agent_version          text,
    model                  text,
    prompt_version         text,
    idempotency_key        text UNIQUE,
    created_at             timestamptz NOT NULL DEFAULT now(),
    assigned_at            timestamptz,
    accepted_at            timestamptz,
    started_at             timestamptz,
    completed_at           timestamptz,
    latency_ms             integer,
    updated_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_tasks_wf_idx ON autodesk.agent_tasks (workflow_id, created_at);
CREATE INDEX IF NOT EXISTS agent_tasks_agent_idx ON autodesk.agent_tasks (to_agent, created_at DESC);
CREATE INDEX IF NOT EXISTS agent_tasks_open_idx ON autodesk.agent_tasks (state)
    WHERE state IN ('CREATED','ASSIGNED','ACCEPTED','RUNNING','RESULT_READY','VALIDATED','RETRY_PENDING','TIMED_OUT','BLOCKED');

-- Handoffs: one row per accepted downstream handoff (PRD §29.3, §33 simulation_agent_handoffs)
CREATE TABLE IF NOT EXISTS autodesk.agent_handoffs (
    handoff_id     text PRIMARY KEY,
    workflow_id    text NOT NULL REFERENCES autodesk.workflows(workflow_id),
    simulation_id  text REFERENCES autodesk.simulations(simulation_id),
    tenant_id      text NOT NULL,
    from_task_id   text NOT NULL REFERENCES autodesk.agent_tasks(task_id),
    to_task_id     text NOT NULL REFERENCES autodesk.agent_tasks(task_id),
    from_agent     text NOT NULL,
    to_agent       text NOT NULL,
    entity_id      text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_handoffs_wf_idx ON autodesk.agent_handoffs (workflow_id, created_at);

-- ── Signals ──────────────────────────────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.signals (
    signal_id              text PRIMARY KEY,
    tenant_id              text NOT NULL,
    account_id             text REFERENCES autodesk.accounts(account_id),
    simulation_id          text REFERENCES autodesk.simulations(simulation_id),
    workflow_id            text REFERENCES autodesk.workflows(workflow_id),
    task_id                text REFERENCES autodesk.agent_tasks(task_id),
    instrument             text NOT NULL,
    exchange               text NOT NULL DEFAULT 'NSE',
    segment                text NOT NULL CHECK (segment IN ('CASH','FUTURES','OPTIONS','INDEX')),
    direction              text NOT NULL CHECK (direction IN ('BULLISH','BEARISH','NEUTRAL')),
    timeframe              text NOT NULL CHECK (timeframe IN ('INTRADAY','POSITIONAL')),
    category               text NOT NULL,
    signal_score           numeric(6,2) NOT NULL CHECK (signal_score BETWEEN 0 AND 100),
    calibrated_probability numeric(6,4),
    body                   jsonb NOT NULL,          -- the full Signal model
    session_date           date NOT NULL,
    data_as_of             timestamptz NOT NULL,
    rule_version           text NOT NULL,
    model_version          text NOT NULL,
    expires_at             timestamptz NOT NULL,
    status                 text NOT NULL CHECK (status IN ('DETECTED','CONSUMED','SUPPRESSED','EXPIRED')),
    dedupe_key             text NOT NULL UNIQUE,   -- duplicate suppression (AT-013)
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS signals_scope_idx ON autodesk.signals (tenant_id, session_date DESC, signal_score DESC);
CREATE INDEX IF NOT EXISTS signals_sim_idx ON autodesk.signals (simulation_id, session_date);

-- ── Trade plans (head row + immutable versions) ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.trade_plans (
    trade_id        text PRIMARY KEY,
    tenant_id       text NOT NULL,
    account_id      text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id   text REFERENCES autodesk.simulations(simulation_id),
    workflow_id     text REFERENCES autodesk.workflows(workflow_id),
    signal_id       text REFERENCES autodesk.signals(signal_id),
    instrument      text NOT NULL,
    strategy_type   text NOT NULL,
    current_version integer NOT NULL DEFAULT 1,
    status          text NOT NULL CHECK (status IN ('DRAFT','RISK_REVIEW','NEEDS_REVISION','AWAITING_APPROVAL','APPROVED',
                                                    'REJECTED','RESEARCH_ONLY','EXPIRED')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trade_plans_account_idx ON autodesk.trade_plans (account_id, created_at DESC);

CREATE TABLE IF NOT EXISTS autodesk.trade_plan_versions (
    trade_id           text NOT NULL REFERENCES autodesk.trade_plans(trade_id),
    version            integer NOT NULL CHECK (version >= 1),
    body               jsonb NOT NULL,           -- TradePlanBody
    body_sha256        text NOT NULL,
    strategy_type      text NOT NULL,
    max_loss_rs        numeric(18,2) NOT NULL,
    max_profit_rs      numeric(18,2),
    capital_required_rs numeric(18,2) NOT NULL,
    created_by         text NOT NULL,
    change_reason      text,
    supersedes_version integer,
    created_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_id, version)
);
DROP TRIGGER IF EXISTS trade_plan_versions_append_only ON autodesk.trade_plan_versions;
CREATE TRIGGER trade_plan_versions_append_only BEFORE UPDATE OR DELETE ON autodesk.trade_plan_versions
    FOR EACH ROW EXECUTE FUNCTION autodesk.refuse_change();

-- ── Risk assessments (immutable) ─────────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.risk_assessments (
    assessment_id  text PRIMARY KEY,
    tenant_id      text NOT NULL,
    trade_id       text NOT NULL,
    plan_version   integer NOT NULL,
    account_id     text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id  text REFERENCES autodesk.simulations(simulation_id),
    verdict        text NOT NULL CHECK (verdict IN ('PASS','REDUCE','FAIL')),
    body           jsonb NOT NULL,               -- RiskAssessment
    policy_id      text NOT NULL,
    policy_version integer NOT NULL,
    engine_version text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (trade_id, plan_version) REFERENCES autodesk.trade_plan_versions(trade_id, version)
);
CREATE INDEX IF NOT EXISTS risk_assessments_trade_idx ON autodesk.risk_assessments (trade_id, plan_version);
DROP TRIGGER IF EXISTS risk_assessments_append_only ON autodesk.risk_assessments;
CREATE TRIGGER risk_assessments_append_only BEFORE UPDATE OR DELETE ON autodesk.risk_assessments
    FOR EACH ROW EXECUTE FUNCTION autodesk.refuse_change();

-- ── Approvals (immutable decisions; a human decision is a new row) ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.approvals (
    approval_id        text PRIMARY KEY,
    tenant_id          text NOT NULL,
    trade_id           text NOT NULL,
    plan_version       integer NOT NULL,
    account_id         text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id      text REFERENCES autodesk.simulations(simulation_id),
    status             text NOT NULL CHECK (status IN ('APPROVED','REJECTED','NEEDS_HUMAN_APPROVAL','NEEDS_REVISION','SUSPENDED')),
    decided_by         text NOT NULL,
    body               jsonb NOT NULL,           -- ApprovalDecision (incl. scope)
    risk_assessment_id text REFERENCES autodesk.risk_assessments(assessment_id),
    supersedes_id      text REFERENCES autodesk.approvals(approval_id),
    expires_at         timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (trade_id, plan_version) REFERENCES autodesk.trade_plan_versions(trade_id, version)
);
CREATE INDEX IF NOT EXISTS approvals_trade_idx ON autodesk.approvals (trade_id, plan_version, created_at);
CREATE INDEX IF NOT EXISTS approvals_pending_idx ON autodesk.approvals (tenant_id, created_at DESC) WHERE status = 'NEEDS_HUMAN_APPROVAL';
-- A pending request can be answered once: only one row may supersede it.
CREATE UNIQUE INDEX IF NOT EXISTS approvals_one_answer ON autodesk.approvals (supersedes_id) WHERE supersedes_id IS NOT NULL;
DROP TRIGGER IF EXISTS approvals_append_only ON autodesk.approvals;
CREATE TRIGGER approvals_append_only BEFORE UPDATE OR DELETE ON autodesk.approvals
    FOR EACH ROW EXECUTE FUNCTION autodesk.refuse_change();

-- ── Event log = audit trail + transactional outbox (append-only) ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.events (
    seq            bigserial PRIMARY KEY,
    event_id       text NOT NULL UNIQUE,
    event_type     text NOT NULL,
    event_version  integer NOT NULL DEFAULT 1,
    occurred_at    timestamptz NOT NULL,
    recorded_at    timestamptz NOT NULL DEFAULT now(),
    sim_time       timestamptz,
    tenant_id      text NOT NULL,
    account_id     text,
    simulation_id  text,
    workflow_id    text,
    correlation_id text,
    causation_id   text,
    producer       text NOT NULL,
    payload        jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS events_tenant_idx ON autodesk.events (tenant_id, seq);
CREATE INDEX IF NOT EXISTS events_sim_idx ON autodesk.events (simulation_id, seq) WHERE simulation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS events_wf_idx ON autodesk.events (workflow_id, seq) WHERE workflow_id IS NOT NULL;
DROP TRIGGER IF EXISTS events_append_only ON autodesk.events;
CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON autodesk.events
    FOR EACH ROW EXECUTE FUNCTION autodesk.refuse_change();

-- Outbox cursor: consumers (SSE fan-out, later the TLM) record the last seq they processed (inbox/dedup).
CREATE TABLE IF NOT EXISTS autodesk.event_cursors (
    consumer   text PRIMARY KEY,
    last_seq   bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- ── Simulation clock trail ───────────────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.simulation_clock_events (
    simulation_id text NOT NULL REFERENCES autodesk.simulations(simulation_id),
    seq           integer NOT NULL,
    session_date  date NOT NULL,
    phase         text NOT NULL,
    sim_time      timestamptz NOT NULL,
    wall_time     timestamptz NOT NULL DEFAULT now(),
    workflows     jsonb NOT NULL DEFAULT '[]'::jsonb,   -- workflow ids run at this step
    PRIMARY KEY (simulation_id, seq)
);
