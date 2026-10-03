-- 158: labelled preview lists beside the official Move-odds run.
--
-- A preview is a snapshot scored with newer model code than the frozen nightly (forward_v4 score --preview). It never
-- counts toward the verdict and tpd_model.publish refuses to publish one, by design. These tables hold one so the
-- Movers page can show it NEXT TO the official run, clearly labelled, and so it can never be mistaken for it:
-- nothing here is read by /move-odds/*, the grader or the verdict, and tpd_runs is untouched.
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS nidp.tpd_preview_runs (
    preview_id      BIGSERIAL PRIMARY KEY,
    label           TEXT        NOT NULL,
    target_session  DATE        NOT NULL,
    data_as_of      DATE        NOT NULL,
    snapshot_sha256 TEXT        NOT NULL UNIQUE,
    git_sha         TEXT        NOT NULL,
    universe_size   INT         NOT NULL,
    scored          INT         NOT NULL,
    note            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tpd_preview_runs_target ON nidp.tpd_preview_runs (target_session DESC, preview_id DESC);

CREATE TABLE IF NOT EXISTS nidp.tpd_preview_estimates (
    preview_id BIGINT NOT NULL REFERENCES nidp.tpd_preview_runs (preview_id),
    head       TEXT   NOT NULL,
    symbol     TEXT   NOT NULL,
    p          DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (preview_id, head, symbol)
);
