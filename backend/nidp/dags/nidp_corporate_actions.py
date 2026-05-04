"""DAG: nidp_corporate_actions

NSE corporate-actions feed is rolling. We poll hourly during market
hours so newly-announced events surface within an hour. Idempotent
upserts mean repeated runs are safe.

Schedule:  Mon-Fri every hour 03:00–14:00 UTC (≈ 08:30–19:30 IST).
"""
from __future__ import annotations

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator
    AIRFLOW_AVAILABLE = True
except ImportError:                                                # pragma: no cover
    AIRFLOW_AVAILABLE = False

from datetime import datetime

from nidp.dags._dag_helpers import make_default_args, python_ingest

if AIRFLOW_AVAILABLE:
    with DAG(
        dag_id="nidp_corporate_actions",
        description="NSE corporate-actions rolling feed.",
        default_args=make_default_args(retries=2),
        start_date=datetime(2026, 1, 1),
        schedule="0 3-14 * * 1-5",
        catchup=False,
        max_active_runs=1,
        tags=["nidp", "ingest", "events"],
    ) as dag:

        corp = PythonOperator(
            task_id="corporate_actions",
            python_callable=python_ingest("corporate_actions", with_date=False),
        )
