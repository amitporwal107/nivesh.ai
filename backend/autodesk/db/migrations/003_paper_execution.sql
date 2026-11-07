-- Autonomous Trading Desk, Phase 2: risk-to-paper execution (docs/autodesk/PHASE2_DESIGN.md).
-- Capital ledger, reservations, execution intents, orders, simulated fills, positions, journal, session snapshots.
-- Nothing here reaches a broker: `fill_kind` can only be SIMULATED and `adapter` only names a paper or shadow adapter.
--
-- Rules: money numeric(18,2), prices numeric(18,4); the ledger, order history, fills and journal are append-only;
-- balances are derived from the ledger, never updated in place; simulated rows carry simulation_id.

ALTER TABLE autodesk.trade_plans DROP CONSTRAINT IF EXISTS trade_plans_status_check;
ALTER TABLE autodesk.trade_plans ADD CONSTRAINT trade_plans_status_check CHECK (status IN (
    'DRAFT','RISK_REVIEW','NEEDS_REVISION','AWAITING_APPROVAL','APPROVED','REJECTED','RESEARCH_ONLY','EXPIRED',
    'EXECUTING','EXECUTED','EXECUTION_REFUSED'));

-- ── Capital ledger (ARCH §8.1): one row per movement; every measure of PRD §9.2 is a sum over these columns ───────
CREATE TABLE IF NOT EXISTS autodesk.capital_ledger_entries (
    seq                        bigserial PRIMARY KEY,
    entry_id                   text NOT NULL UNIQUE,
    tenant_id                  text NOT NULL,
    account_id                 text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id              text REFERENCES autodesk.simulations(simulation_id),
    entry_type                 text NOT NULL CHECK (entry_type IN (
        'CAPITAL_AVAILABLE','CAPITAL_RESERVED','CAPITAL_RESERVATION_CONSUMED','CAPITAL_RESERVATION_RELEASED',
        'POSITION_FUNDS','MARGIN_UTILIZED','MARGIN_RELEASED','REALIZED_PNL','FEES_BOOKED','MANUAL_ADJUSTMENT')),
    cash_delta_rs              numeric(18,2) NOT NULL DEFAULT 0,
    reserved_delta_rs          numeric(18,2) NOT NULL DEFAULT 0,
    margin_delta_rs            numeric(18,2) NOT NULL DEFAULT 0,
    notional_delta_rs          numeric(18,2) NOT NULL DEFAULT 0,
    open_risk_delta_rs         numeric(18,2) NOT NULL DEFAULT 0,
    pending_risk_delta_rs      numeric(18,2) NOT NULL DEFAULT 0,
    pending_commitment_delta_rs numeric(18,2) NOT NULL DEFAULT 0,
    realized_gross_delta_rs    numeric(18,2) NOT NULL DEFAULT 0,
    fees_delta_rs              numeric(18,2) NOT NULL DEFAULT 0,
    trade_id                   text,
    ref_type                   text NOT NULL,      -- ACCOUNT | RESERVATION | FILL | INTENT
    ref_id                     text NOT NULL,
    memo                       text NOT NULL DEFAULT '',
    sim_time                   timestamptz,
    created_at                 timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS capital_ledger_account_idx ON autodesk.capital_ledger_entries (account_id, seq);
CREATE INDEX IF NOT EXISTS capital_ledger_trade_idx ON autodesk.capital_ledger_entries (trade_id) WHERE trade_id IS NOT NULL;
DROP TRIGGER IF EXISTS capital_ledger_append_only ON autodesk.capital_ledger_entries;
CREATE TRIGGER capital_ledger_append_only BEFORE UPDATE OR DELETE ON autodesk.capital_ledger_entries
    FOR EACH ROW EXECUTE FUNCTION autodesk.refuse_change();

-- Accounts that already exist get their opening row; new accounts get it from store.create_account.
INSERT INTO autodesk.capital_ledger_entries (entry_id, tenant_id, account_id, simulation_id, entry_type, cash_delta_rs,
                                             ref_type, ref_id, memo)
SELECT 'CAP-open-' || a.account_id, a.tenant_id, a.account_id, a.simulation_id, 'CAPITAL_AVAILABLE', a.starting_capital_rs,
       'ACCOUNT', a.account_id, 'opening capital'
FROM autodesk.accounts a
ON CONFLICT (entry_id) DO NOTHING;

-- ── Reservations (PRD §9.4, ARCH §8.2) ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.capital_reservations (
    reservation_id     text PRIMARY KEY,
    tenant_id          text NOT NULL,
    account_id         text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id      text REFERENCES autodesk.simulations(simulation_id),
    trade_id           text NOT NULL,
    plan_version       integer NOT NULL,
    status             text NOT NULL CHECK (status IN ('ACTIVE','CONSUMED','RELEASED','EXPIRED')),
    amount_rs          numeric(18,2) NOT NULL CHECK (amount_rs >= 0),
    consumed_rs        numeric(18,2) NOT NULL DEFAULT 0,
    released_rs        numeric(18,2) NOT NULL DEFAULT 0,
    risk_rs            numeric(18,2) NOT NULL,
    risk_moved_rs      numeric(18,2) NOT NULL DEFAULT 0,
    commitment_rs      numeric(18,2) NOT NULL,
    commitment_done_rs numeric(18,2) NOT NULL DEFAULT 0,
    capital_rs         numeric(18,2) NOT NULL,      -- what the risk engine compares with its position / sector limits
    instrument         text NOT NULL,
    sector             text NOT NULL DEFAULT 'UNCLASSIFIED',
    fno                boolean NOT NULL DEFAULT false,
    idempotency_key    text NOT NULL,
    expires_at         timestamptz NOT NULL,
    close_reason       text,
    sim_time           timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    closed_at          timestamptz,
    UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT reservation_never_overdrawn CHECK (consumed_rs + released_rs <= amount_rs)
);
CREATE INDEX IF NOT EXISTS capital_reservations_active_idx ON autodesk.capital_reservations (account_id, expires_at)
    WHERE status = 'ACTIVE';
CREATE INDEX IF NOT EXISTS capital_reservations_trade_idx ON autodesk.capital_reservations (trade_id);

-- ── Execution intents (persisted BEFORE anything is submitted, ARCH §9.3) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.execution_intents (
    intent_id       text PRIMARY KEY,
    tenant_id       text NOT NULL,
    account_id      text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id   text REFERENCES autodesk.simulations(simulation_id),
    trade_id        text NOT NULL REFERENCES autodesk.trade_plans(trade_id),
    plan_version    integer NOT NULL,
    plan_hash       text,
    approval_id     text REFERENCES autodesk.approvals(approval_id),
    reservation_id  text REFERENCES autodesk.capital_reservations(reservation_id),
    execution_mode  text NOT NULL CHECK (execution_mode IN ('PAPER','SIMULATION','SHADOW')),
    adapter         text NOT NULL CHECK (adapter IN ('PAPER_LIVE','PAPER_SIM','SHADOW')),
    action          text NOT NULL DEFAULT 'ENTER',
    session_date    date NOT NULL,
    status          text NOT NULL CHECK (status IN ('CREATED','VALIDATED','REFUSED','SUBMITTED','COMPLETED')),
    result          text CHECK (result IN ('FILLED','PARTIALLY_FILLED','NOT_FILLED')),
    refusal_codes   jsonb NOT NULL DEFAULT '[]'::jsonb,
    controls        jsonb NOT NULL DEFAULT '[]'::jsonb,
    order_spec      jsonb,
    idempotency_key text NOT NULL,
    sim_time        timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS execution_intents_trade_idx ON autodesk.execution_intents (trade_id, plan_version);
CREATE INDEX IF NOT EXISTS execution_intents_account_idx ON autodesk.execution_intents (account_id, session_date, status);
CREATE INDEX IF NOT EXISTS execution_intents_sim_idx ON autodesk.execution_intents (simulation_id, created_at)
    WHERE simulation_id IS NOT NULL;

-- ── Orders (PRD §11.3): one per plan leg. No broker reference: nothing leaves this schema ────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.trade_orders (
    order_id            text PRIMARY KEY,
    intent_id           text NOT NULL REFERENCES autodesk.execution_intents(intent_id),
    tenant_id           text NOT NULL,
    account_id          text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id       text REFERENCES autodesk.simulations(simulation_id),
    trade_id            text NOT NULL REFERENCES autodesk.trade_plans(trade_id),
    plan_version        integer NOT NULL,
    leg_id              text NOT NULL,
    kind                text NOT NULL CHECK (kind IN ('EQ','FUT','CE','PE')),
    underlying          text NOT NULL,
    expiry              date,
    strike              numeric(18,4),
    side                text NOT NULL CHECK (side IN ('BUY','SELL')),
    lots                integer NOT NULL,
    lot_size            integer NOT NULL,
    quantity            integer NOT NULL CHECK (quantity > 0),
    order_type          text NOT NULL CHECK (order_type IN ('MARKET','LIMIT','BASKET_LEG')),
    limit_price         numeric(18,4),
    ref_price           numeric(18,4) NOT NULL,
    state               text NOT NULL CHECK (state IN ('CREATED','VALIDATED','SUBMITTED','ACKNOWLEDGED','OPEN',
                            'PARTIALLY_FILLED','FILLED','MODIFY_PENDING','CANCEL_PENDING','CANCELLED','REJECTED',
                            'EXPIRED','UNKNOWN')),
    filled_qty          integer NOT NULL DEFAULT 0,
    avg_fill_price      numeric(18,6),
    reject_code         text,
    reject_reason       text,
    attempts            integer NOT NULL DEFAULT 0,
    last_no_fill_reason text,
    last_quote_ref      text,                       -- the quote that last filled it: one quote fills an order once
    session_date        date NOT NULL,
    idempotency_key     text NOT NULL UNIQUE,
    sim_time            timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (intent_id, leg_id),
    CONSTRAINT trade_orders_limit CHECK ((order_type = 'LIMIT') = (limit_price IS NOT NULL)),
    CONSTRAINT trade_orders_filled CHECK (filled_qty >= 0 AND filled_qty <= quantity)
);
CREATE INDEX IF NOT EXISTS trade_orders_trade_idx ON autodesk.trade_orders (trade_id);
CREATE INDEX IF NOT EXISTS trade_orders_account_idx ON autodesk.trade_orders (account_id, session_date, state);
CREATE INDEX IF NOT EXISTS trade_orders_working_idx ON autodesk.trade_orders (state)
    WHERE state IN ('VALIDATED','SUBMITTED','ACKNOWLEDGED','OPEN','PARTIALLY_FILLED','CANCEL_PENDING','UNKNOWN');

CREATE TABLE IF NOT EXISTS autodesk.trade_order_events (
    seq           bigserial PRIMARY KEY,
    order_id      text NOT NULL REFERENCES autodesk.trade_orders(order_id),
    tenant_id     text NOT NULL,
    from_state    text,
    to_state      text NOT NULL,
    reason        text NOT NULL DEFAULT '',
    detail        jsonb NOT NULL DEFAULT '{}'::jsonb,
    sim_time      timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trade_order_events_order_idx ON autodesk.trade_order_events (order_id, seq);
DROP TRIGGER IF EXISTS trade_order_events_append_only ON autodesk.trade_order_events;
CREATE TRIGGER trade_order_events_append_only BEFORE UPDATE OR DELETE ON autodesk.trade_order_events
    FOR EACH ROW EXECUTE FUNCTION autodesk.refuse_change();

-- ── Fills: every one simulated, never broker-confirmed (PRD §11.5). Corrections would be adjustment rows ─────────
CREATE TABLE IF NOT EXISTS autodesk.trade_fills (
    fill_id        text PRIMARY KEY,
    order_id       text NOT NULL REFERENCES autodesk.trade_orders(order_id),
    intent_id      text NOT NULL REFERENCES autodesk.execution_intents(intent_id),
    tenant_id      text NOT NULL,
    account_id     text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id  text REFERENCES autodesk.simulations(simulation_id),
    trade_id       text NOT NULL REFERENCES autodesk.trade_plans(trade_id),
    leg_id         text NOT NULL,
    side           text NOT NULL CHECK (side IN ('BUY','SELL')),
    quantity       integer NOT NULL CHECK (quantity > 0),
    price          numeric(18,4) NOT NULL CHECK (price > 0),
    arrival_price  numeric(18,4) NOT NULL,          -- the session's open or the quote's mid, before spread and slippage
    value_rs       numeric(18,2) NOT NULL,
    spread_rs      numeric(18,2) NOT NULL DEFAULT 0,
    slippage_rs    numeric(18,2) NOT NULL DEFAULT 0,
    charges        jsonb NOT NULL,                  -- brokerage, stt, exchange, sebi, stamp, gst, total (desk-cost-v2)
    charges_rs     numeric(18,2) NOT NULL,
    cost_model     text NOT NULL,
    price_source   text NOT NULL,
    fill_model     text NOT NULL,
    latency_ms     integer NOT NULL DEFAULT 0,
    fill_kind      text NOT NULL DEFAULT 'SIMULATED' CHECK (fill_kind = 'SIMULATED'),
    fill_time      timestamptz NOT NULL,
    sim_time       timestamptz,
    session_date   date NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trade_fills_order_idx ON autodesk.trade_fills (order_id);
CREATE INDEX IF NOT EXISTS trade_fills_trade_idx ON autodesk.trade_fills (trade_id);
CREATE INDEX IF NOT EXISTS trade_fills_account_idx ON autodesk.trade_fills (account_id, fill_time);
DROP TRIGGER IF EXISTS trade_fills_append_only ON autodesk.trade_fills;
CREATE TRIGGER trade_fills_append_only BEFORE UPDATE OR DELETE ON autodesk.trade_fills
    FOR EACH ROW EXECUTE FUNCTION autodesk.refuse_change();

-- ── Positions: current state, materialised from fills in the fill's transaction (activated by a fill only) ───────
CREATE TABLE IF NOT EXISTS autodesk.trade_positions (
    position_id    text PRIMARY KEY,
    tenant_id      text NOT NULL,
    account_id     text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id  text REFERENCES autodesk.simulations(simulation_id),
    trade_id       text NOT NULL UNIQUE REFERENCES autodesk.trade_plans(trade_id),
    plan_version   integer NOT NULL,
    instrument     text NOT NULL,
    strategy_type  text NOT NULL,
    status         text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
    open_risk_rs   numeric(18,2) NOT NULL DEFAULT 0,
    capital_rs     numeric(18,2) NOT NULL DEFAULT 0,
    margin_rs      numeric(18,2) NOT NULL DEFAULT 0,
    sector         text NOT NULL DEFAULT 'UNCLASSIFIED',
    fno            boolean NOT NULL DEFAULT false,
    opened_at      timestamptz NOT NULL,
    sim_time       timestamptz,
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trade_positions_account_idx ON autodesk.trade_positions (account_id, status);

CREATE TABLE IF NOT EXISTS autodesk.trade_position_legs (
    position_id    text NOT NULL REFERENCES autodesk.trade_positions(position_id),
    leg_id         text NOT NULL,
    kind           text NOT NULL,
    underlying     text NOT NULL,
    expiry         date,
    strike         numeric(18,4),
    side           text NOT NULL CHECK (side IN ('LONG','SHORT')),
    lot_size       integer NOT NULL,
    quantity       integer NOT NULL CHECK (quantity >= 0),
    avg_price      numeric(18,6) NOT NULL,
    cost_value_rs  numeric(18,2) NOT NULL,          -- gross traded value of the fills, unsigned
    charges_rs     numeric(18,2) NOT NULL DEFAULT 0,
    mark_price     numeric(18,4),
    mark_source    text,
    marked_at      timestamptz,
    mark_stale     boolean NOT NULL DEFAULT false,  -- set when a session had no row for this contract
    unrealized_rs  numeric(18,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (position_id, leg_id)
);

-- ── One row per account per session: daily and cumulative P&L, maximum drawdown ──────────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.equity_snapshots (
    account_id          text NOT NULL REFERENCES autodesk.accounts(account_id),
    session_date        date NOT NULL,
    tenant_id           text NOT NULL,
    simulation_id       text REFERENCES autodesk.simulations(simulation_id),
    as_of               timestamptz NOT NULL,
    equity_rs           numeric(18,2) NOT NULL,
    cash_balance_rs     numeric(18,2) NOT NULL,
    used_margin_rs      numeric(18,2) NOT NULL,
    reserved_rs         numeric(18,2) NOT NULL,
    buying_power_rs     numeric(18,2) NOT NULL,
    notional_rs         numeric(18,2) NOT NULL,
    open_risk_rs        numeric(18,2) NOT NULL,
    realized_gross_rs   numeric(18,2) NOT NULL,
    fees_rs             numeric(18,2) NOT NULL,
    unrealized_gross_rs numeric(18,2) NOT NULL,
    net_pnl_rs          numeric(18,2) NOT NULL,
    stale_legs          integer NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, session_date)
);

-- ── Trade journal (PRD §12.1): the chain from signal to position, one row per link ───────────────────────────────
CREATE TABLE IF NOT EXISTS autodesk.trade_journal_entries (
    seq           bigserial PRIMARY KEY,
    tenant_id     text NOT NULL,
    account_id    text NOT NULL REFERENCES autodesk.accounts(account_id),
    simulation_id text REFERENCES autodesk.simulations(simulation_id),
    trade_id      text NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('SIGNAL','PLAN_VERSION','RISK_ASSESSMENT','APPROVAL','EXECUTION_INTENT',
                                                'RESERVATION','ORDER','FILL','POSITION','MARK')),
    ref_id        text NOT NULL,
    summary       text NOT NULL,
    data          jsonb NOT NULL DEFAULT '{}'::jsonb,
    sim_time      timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (trade_id, kind, ref_id)
);
CREATE INDEX IF NOT EXISTS trade_journal_scope_idx ON autodesk.trade_journal_entries (tenant_id, simulation_id, seq);
CREATE INDEX IF NOT EXISTS trade_journal_trade_idx ON autodesk.trade_journal_entries (trade_id, seq);
DROP TRIGGER IF EXISTS trade_journal_append_only ON autodesk.trade_journal_entries;
CREATE TRIGGER trade_journal_append_only BEFORE UPDATE OR DELETE ON autodesk.trade_journal_entries
    FOR EACH ROW EXECUTE FUNCTION autodesk.refuse_change();
