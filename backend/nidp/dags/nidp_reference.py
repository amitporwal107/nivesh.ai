"""DAG: nidp_reference

Low-cadence reference data:
    - Index constituents — quarterly rebalance + on-event; we poll
      weekly to catch ad-hoc inclusions/exclusions.
    - NSE holidays — annual + on-event; we poll weekly.
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
        dag_id="nidp_reference",
        description="Index constituents + NSE holidays (low-cadence reference).",
        default_args=make_default_args(retries=2),
        start_date=datetime(2026, 1, 1),
        schedule="0 5 * * 1",                                       # Mon 05:00 UTC
        catchup=False,
        max_active_runs=1,
        tags=["nidp", "ingest", "reference"],
    ) as dag:

        constituents = PythonOperator(
            task_id="index_constituents",
            python_callable=python_ingest("index_constituents", with_date=False),
        )

        calendar = PythonOperator(
            task_id="nse_calendar",
            python_callable=python_ingest("nse_calendar", with_date=False),
        )
