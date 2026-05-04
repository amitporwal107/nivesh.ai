"""DAG: nidp_delivery

NSE publishes sec_bhavdata_full on T+1 morning (~10:00 IST). Runs
separately from market_eod because it lands a different day.

Schedule:  Tue-Sat 04:30 UTC (≈ 10:00 IST). `data_interval_start` is
           the trading date being fetched; Airflow templating gives
           us {{ ds }} = previous trading day.
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
        dag_id="nidp_delivery",
        description="NSE sec_bhavdata_full delivery percentage (T+1).",
        default_args=make_default_args(retries=4),
        start_date=datetime(2026, 1, 1),
        schedule="30 4 * * 2-6",                                   # Tue-Sat 04:30 UTC
        catchup=False,
        max_active_runs=1,
        tags=["nidp", "ingest", "delivery"],
    ) as dag:

        delivery = PythonOperator(
            task_id="delivery",
            python_callable=python_ingest("delivery", with_date=True),
        )
