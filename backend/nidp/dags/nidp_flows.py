"""DAG: nidp_flows

NSE FII/DII daily XLS — published post-market (~18:30 IST). Runs
slightly after market_eod so it doesn't compete with bhavcopy
(both target the same NSE archive host).
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
        dag_id="nidp_flows",
        description="NSE FII/DII daily flows.",
        default_args=make_default_args(retries=4),
        start_date=datetime(2026, 1, 1),
        schedule="45 13 * * 1-5",                                  # Mon-Fri 13:45 UTC
        catchup=False,
        max_active_runs=1,
        tags=["nidp", "ingest", "flows"],
    ) as dag:

        fii_dii = PythonOperator(
            task_id="fii_dii",
            python_callable=python_ingest("fii_dii", with_date=True),
        )
