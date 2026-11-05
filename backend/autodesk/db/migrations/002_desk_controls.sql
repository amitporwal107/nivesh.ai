-- Emergency controls (PRD §10.4), first one: STOP_NEW_ENTRIES. A small head row per tenant and control; every change is
-- also an append-only event (DESK_CONTROL_ACTIVATED / DESK_CONTROL_LIFTED), which is the audit record.
-- Scope: the desk's real-time accounts. Simulations of past sessions are not affected.

CREATE TABLE IF NOT EXISTS autodesk.desk_controls (
    tenant_id     text NOT NULL,
    control       text NOT NULL CHECK (control IN ('STOP_NEW_ENTRIES')),
    active        boolean NOT NULL,
    reason        text NOT NULL,
    changed_by    text NOT NULL,
    changed_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, control)
);
