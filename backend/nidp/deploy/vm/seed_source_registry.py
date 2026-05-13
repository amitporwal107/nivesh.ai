"""Seed nidp.source_registry with the 10 ingesters added during the
VM-cron migration. Idempotent (ON CONFLICT UPDATE).

Connection string resolution order:
  1. NIDP_POSTGRES_URL env (used by docker-compose local stack)
  2. POSTGRES_URL env
  3. localhost:5433 default (matches the VM-side TimescaleDB Docker)
"""
import asyncio
import os

import asyncpg


def _resolve_pg_url() -> str:
    return (
        os.environ.get("NIDP_POSTGRES_URL")
        or os.environ.get("POSTGRES_URL")
        or "postgresql://postgres:postgres@localhost:5433/nidp"
    )

SEEDS = [
    # source_name, ingester, url_pattern, source_class, confidence, expected_freq, schedule_cron
    ('AMFI India NAV',                'amfi_nav',                'https://portal.amfiindia.com/spages/NAVAll.txt',                                  'OFFICIAL', 1.00, 'daily',     '30 19 * * 1-5'),
    ('AMFI Circulars',                'amfi_circulars',          'https://www.amfiindia.com/research-information/amfi-circular',                    'OFFICIAL', 1.00, 'daily',     '0 20 * * *'),
    ('AMFI NAV History',              'amfi_nav_history',        'https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx',                   'OFFICIAL', 1.00, 'manual',     None),
    ('AMFI MF Holdings',              'mf_holdings',             'https://www.amfiindia.com/research-information/mf-holdings',                      'OFFICIAL', 1.00, 'monthly',   '0 8 5 * *'),
    ('AMFI MF Disclosure Snapshot',   'mf_disclosure_snapshot',  'https://www.amfiindia.com/research-information/mutual-fund-data',                 'OFFICIAL', 1.00, 'monthly',   '30 8 5 * *'),
    ('Corporate Event Calendar',      'event_calendar',          'derived://nidp/event_calendar',                                                   'DERIVED',  1.00, 'daily',     '0 21 * * 1-5'),
    ('Corporate Event Day Poller',    'event_day_poller',        'derived://nidp/event_day_poller',                                                 'DERIVED',  1.00, 'high-freq', '*/15 * * * 1-5'),
    ('D-1 Prep',                      'd1_prep',                 'derived://nidp/d1_prep',                                                          'DERIVED',  1.00, 'daily',     '15 22 * * 1-5'),
    ('Intelligence Aggregator',       'intelligence',            'derived://nidp/intelligence',                                                     'DERIVED',  1.00, 'daily',     '30 22 * * 1-5'),
    ('Quality Gate',                  'quality_gate',            'derived://nidp/quality_gate',                                                     'DERIVED',  1.00, 'daily',     '45 22 * * 1-5'),
    ('Announcement Classifier',       'announcement_classifier', 'derived://nidp/announcement_classifier',                                          'DERIVED',  1.00, 'high-freq', '*/10 * * * *'),
    ('Document Parser',               'document_parser',         'derived://nidp/document_parser',                                                  'DERIVED',  1.00, 'high-freq', '*/10 * * * *'),
    ('Price Adjuster',                'price_adjuster',          'derived://nidp/price_adjuster',                                                   'DERIVED',  1.00, 'daily',     '0 23 * * 1-5'),
    ('Intelligence Layer Materializer','intelligence_layer',     'derived://nidp/intelligence_layer',                                               'DERIVED',  1.00, 'daily',     '15 23 * * 1-5'),
    ('Portfolio Intelligence Sync',   'portfolio_intelligence_sync', 'derived://nidp/portfolio_intelligence_sync',                                  'DERIVED',  1.00, 'daily',     '30 23 * * 1-5'),
    ('Portfolio Holdings Sync',      'portfolio_holdings_sync',     'derived://nivesh_pg/portfolio_holdings',                                          'DERIVED',  1.00, 'daily',     '0 23 * * 1-5'),
]


async def main() -> None:
    c = await asyncpg.connect(_resolve_pg_url())
    for s in SEEDS:
        existing = await c.fetchval(
            "SELECT 1 FROM nidp.source_registry WHERE ingester = $1", s[1]
        )
        if existing:
            await c.execute(
                """
                UPDATE nidp.source_registry SET
                  source_name        = $1,
                  source_url_pattern = $3,
                  source_class       = $4,
                  confidence         = $5,
                  expected_freq      = $6,
                  schedule_cron      = $7,
                  updated_at         = now()
                WHERE ingester = $2
                """,
                *s,
            )
        else:
            await c.execute(
                """
                INSERT INTO nidp.source_registry
                  (source_name, ingester, source_url_pattern, source_class, confidence, expected_freq, schedule_cron, notes)
                VALUES ($1,$2,$3,$4,$5,$6,$7, 'Seeded by main agent during VM-cron migration')
                """,
                *s,
            )
    n_reg = await c.fetchval("SELECT count(*) FROM nidp.source_registry")
    n_fs  = await c.fetchval("SELECT count(*) FROM nidp.v_feed_status")
    print(f"source_registry rows: {n_reg}")
    print(f"v_feed_status rows : {n_fs}")
    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
