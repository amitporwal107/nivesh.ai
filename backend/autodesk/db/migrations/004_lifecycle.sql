-- Autonomous Trading Desk, Phase 3A: trade lifecycle from fill to reconciled closure (docs/autodesk/PHASE3_DESIGN.md).
-- Additive only. Closing orders reuse trade_orders / trade_fills; settlement of expiring F&O legs has its own record (a
-- worthless option settles at 0, and a fill's price is always above 0). Nothing here reaches a broker.

-- ── positions and legs ────────────────────────────────────────────────────────────────────────────────────────────
ALTER TABLE autodesk.trade_positions
    ADD COLUMN IF NOT EXISTS lifecycle_state    text NOT NULL DEFAULT 'ACTIVE_POSITION',
    ADD COLUMN IF NOT EXISTS realized_gross_rs  numeric(18,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS closing_charges_rs numeric(18,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS closed_at          timestamptz,
    ADD COLUMN IF NOT EXISTS close_reason       text,
    ADD COLUMN IF NOT EXISTS settled_at         timestamptz,
    ADD COLUMN IF NOT EXISTS flags              jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE autodesk.trade_positions DROP CONSTRAINT IF EXISTS trade_positions_lifecycle_state_check;
ALTER TABLE autodesk.trade_positions ADD CONSTRAINT trade_positions_lifecycle_state_check CHECK (lifecycle_state IN (
    'ACTIVE_POSITION','RISK_MANAGEMENT','EXIT_PENDING','PARTIAL_EXIT','CLOSED','SETTLED','RECONCILIATION_REQUIRED',
    'EXECUTION_ERROR'));

ALTER TABLE autodesk.trade_position_legs
    ADD COLUMN IF NOT EXISTS opened_qty         integer,
    ADD COLUMN IF NOT EXISTS closed_qty         integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS close_value_rs     numeric(18,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS closing_charges_rs numeric(18,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS realized_gross_rs  numeric(18,2) NOT NULL DEFAULT 0;

-- ── closing orders reuse the order table and its state machine ────────────────────────────────────────────────────
ALTER TABLE autodesk.trade_orders
    ADD COLUMN IF NOT EXISTS purpose       text NOT NULL DEFAULT 'OPEN',
    ADD COLUMN IF NOT EXISTS close_reason  text,
    ADD COLUMN IF NOT EXISTS trigger_price numeric(18,4);
ALTER TABLE autodesk.trade_orders DROP CONSTRAINT IF EXISTS trade_orders_purpose_check;
ALTER TABLE autodesk.trade_orders ADD CONSTRAINT trade_orders_purpose_check CHECK (purpose IN ('OPEN','CLOSE'));

-- ── journal: the chain continues past the position ────────────────────────────────────────────────────────────────
ALTER TABLE autodesk.trade_journal_entries DROP CONSTRAINT IF EXISTS trade_journal_entries_kind_check;
ALTER TABLE autodesk.trade_journal_entries ADD CONSTRAINT trade_journal_entries_kind_check CHECK (kind IN (
    'SIGNAL','PLAN_VERSION','RISK_ASSESSMENT','APPROVAL','EXECUTION_INTENT','RESERVATION','ORDER','FILL','POSITION','MARK',
    'LIFECYCLE','CLOSING_DECISION','CLOSING_FILL','CLOSURE','SETTLEMENT','LIMIT','CONTROL','RECONCILIATION'));

-- ── exit-rules-v1 state per trade (head row, rewritten each session it is stepped) ────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.trade_exit_state (
    trade_id           text PRIMARY KEY REFERENCES autodesk.trade_plans(trade_id),
    position_id        text NOT NULL REFERENCES autodesk.trade_positions(position_id),
    tenant_id          text NOT NULL,
    account_id         text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id      text REFERENCES autodesk.simulations(simulation_id),
    trigger_key        text,                      -- the row the levels are judged on (EQ:SYM / FUT:SYM:expiry); null = none
    trigger_basis      text NOT NULL,             -- OWN_ROW | FUTURE_ROW_TRANSLATED | UNDERLYING_ROW | NONE
    side               text NOT NULL CHECK (side IN ('long','short')),
    level_ratio        numeric(18,8) NOT NULL DEFAULT 1,
    rules              jsonb NOT NULL,            -- exit-rules-v1 Rules + versions
    state              jsonb NOT NULL,            -- exit-rules-v1 State
    objectives         jsonb NOT NULL DEFAULT '[]'::jsonb,
    next_objective     integer NOT NULL DEFAULT 0,
    pending            jsonb,                     -- a closing decided but not (fully) filled: reason, since
    first_step_session date NOT NULL,
    last_session       date,
    pre_expiry_session date,
    notes              jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at         timestamptz NOT NULL DEFAULT now()
);

-- ── lifecycle state moves (append-only) ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.trade_lifecycle_events (
    seq           bigserial PRIMARY KEY,
    tenant_id     text NOT NULL,
    account_id    text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id text REFERENCES autodesk.simulations(simulation_id),
    trade_id      text NOT NULL,
    position_id   text NOT NULL,
    from_state    text,
    to_state      text NOT NULL,
    reason        text NOT NULL,
    detail        jsonb NOT NULL DEFAULT '{}'::jsonb,
    session_date  date,
    sim_time      timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trade_lifecycle_events_trade_idx ON autodesk.trade_lifecycle_events (trade_id, seq);
CREATE INDEX IF NOT EXISTS trade_lifecycle_events_scope_idx ON autodesk.trade_lifecycle_events (tenant_id, simulation_id, seq);
DROP TRIGGER IF EXISTS trade_lifecycle_events_append_only ON autodesk.trade_lifecycle_events;
CREATE TRIGGER trade_lifecycle_events_append_only BEFORE UPDATE OR DELETE ON autodesk.trade_lifecycle_events
    FOR EACH ROW EXECUTE FUNCTION autodesk.refuse_change();

-- ── one row per closing or settlement (append-only; PRD §16.5 trade_exit_records) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.trade_exit_records (
    record_id         text PRIMARY KEY,
    tenant_id         text NOT NULL,
    account_id        text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id     text REFERENCES autodesk.simulations(simulation_id),
    trade_id          text NOT NULL,
    position_id       text NOT NULL,
    intent_id         text REFERENCES autodesk.execution_intents(intent_id),
    reason            text NOT NULL,
    how               text NOT NULL CHECK (how IN ('open','level','objective','close','quote','settlement')),
    session_date      date NOT NULL,
    trigger_price     numeric(18,4),
    level             numeric(18,4),
    gapped            boolean NOT NULL DEFAULT false,
    both_in_range     boolean NOT NULL DEFAULT false,
    fraction          numeric(10,6) NOT NULL,
    legs              jsonb NOT NULL,             -- [{leg_id, kind, side, quantity, price, value_rs, charges_rs, realized_gross_rs, source}]
    value_rs          numeric(18,2) NOT NULL,
    charges_rs        numeric(18,2) NOT NULL,
    realized_gross_rs numeric(18,2) NOT NULL,
    cash_rs           numeric(18,2) NOT NULL,     -- what the closing moved in cash (funds + futures realized − charges)
    sim_time          timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trade_exit_records_trade_idx ON autodesk.trade_exit_records (trade_id);
CREATE INDEX IF NOT EXISTS trade_exit_records_account_idx ON autodesk.trade_exit_records (account_id, session_date);
DROP TRIGGER IF EXISTS trade_exit_records_append_only ON autodesk.trade_exit_records;
CREATE TRIGGER trade_exit_records_append_only BEFORE UPDATE OR DELETE ON autodesk.trade_exit_records
    FOR EACH ROW EXECUTE FUNCTION autodesk.refuse_change();

-- ── emergency controls beyond STOP_NEW_ENTRIES (PRD §10.4); scope '*' = the tenant's desk accounts ────────────────
CREATE TABLE IF NOT EXISTS autodesk.lifecycle_controls (
    tenant_id   text NOT NULL,
    control     text NOT NULL CHECK (control IN ('SUSPEND_AUTOMATED_MODIFICATIONS','SUSPEND_ACCOUNT','SUSPEND_STRATEGY',
                                                 'REDUCE_ONLY')),
    scope       text NOT NULL,                    -- '*' | account id | strategy type
    active      boolean NOT NULL,
    reason      text NOT NULL,
    changed_by  text NOT NULL,
    changed_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, control, scope)
);

-- ── requests to close a whole position (a person, or a control) ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.close_requests (
    trade_id     text PRIMARY KEY,
    tenant_id    text NOT NULL,
    account_id   text NOT NULL REFERENCES autodesk.accounts(account_id),
    reason       text NOT NULL,                   -- manual | risk_control
    note         text NOT NULL,
    requested_by text NOT NULL,
    status       text NOT NULL CHECK (status IN ('PENDING','DONE')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    done_at      timestamptz
);

-- ── reconciliation runs (append-only) ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.reconciliation_runs (
    seq           bigserial PRIMARY KEY,
    tenant_id     text NOT NULL,
    account_id    text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id text REFERENCES autodesk.simulations(simulation_id),
    session_date  date,
    moment        text NOT NULL,
    ok            boolean NOT NULL,
    checks        jsonb NOT NULL,
    sim_time      timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reconciliation_runs_account_idx ON autodesk.reconciliation_runs (account_id, seq);
DROP TRIGGER IF EXISTS reconciliation_runs_append_only ON autodesk.reconciliation_runs;
CREATE TRIGGER reconciliation_runs_append_only BEFORE UPDATE OR DELETE ON autodesk.reconciliation_runs
    FOR EACH ROW EXECUTE FUNCTION autodesk.refuse_change();

-- ── the day's final mark: basis, and every correction kept ────────────────────────────────────────────────────────
ALTER TABLE autodesk.equity_snapshots ADD COLUMN IF NOT EXISTS mark_basis text NOT NULL DEFAULT 'SESSION_CLOSE';
CREATE TABLE IF NOT EXISTS autodesk.equity_snapshot_revisions (
    seq           bigserial PRIMARY KEY,
    account_id    text NOT NULL REFERENCES autodesk.accounts(account_id),
    session_date  date NOT NULL,
    tenant_id     text NOT NULL,
    simulation_id text REFERENCES autodesk.simulations(simulation_id),
    old_basis     text NOT NULL,
    new_basis     text NOT NULL,
    old_row       jsonb NOT NULL,
    new_row       jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS equity_snapshot_revisions_append_only ON autodesk.equity_snapshot_revisions;
CREATE TRIGGER equity_snapshot_revisions_append_only BEFORE UPDATE OR DELETE ON autodesk.equity_snapshot_revisions
    FOR EACH ROW EXECUTE FUNCTION autodesk.refuse_change();

-- legs that existed before this migration: what was opened is what they hold
UPDATE autodesk.trade_position_legs SET opened_qty = quantity WHERE opened_qty IS NULL;
