"""DAG: nidp_macro

RBI G-Sec / T-Bill yields. RBI publishes daily reference rates in
the evening; runs after market_eod with a buffer so RBI page is
already updated.
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
        dag_id="nidp_macro",
        description="RBI G-Sec / T-Bill yields.",
        default_args=make_default_args(retries=3),
        start_date=datetime(2026, 1, 1),
        schedule="0 14 * * 1-5",                                    # Mon-Fri 14:00 UTC
        catchup=False,
        max_active_runs=1,
        tags=["nidp", "ingest", "macro"],
    ) as dag:

        rbi = PythonOperator(
            task_id="rbi_yields",
            python_callable=python_ingest("rbi_yields", with_date=False),
        )
