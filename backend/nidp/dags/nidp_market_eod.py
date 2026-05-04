"""DAG: nidp_market_eod

Runs after NSE close (~18:30 IST). Pulls EOD market data and the
end-of-day deals files. Bhavcopy is the gating task — index_close,
bulk, block all run after it succeeds (so a missed bhavcopy fails the
whole snapshot fast, rather than half-populating the day).

Schedule:  Mon-Fri 13:15 UTC (≈ 18:45 IST), with a 60-min retry window
           covering NSE's typical late-publish slip.
"""
from __future__ import annotations

# Lazy Airflow import — file imports cleanly without Airflow installed.
try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator
    AIRFLOW_AVAILABLE = True
except ImportError:                                                # pragma: no cover
    AIRFLOW_AVAILABLE = False
    DAG = None
    PythonOperator = None

from datetime import datetime, timedelta

from nidp.dags._dag_helpers import make_default_args, python_ingest

if AIRFLOW_AVAILABLE:
    with DAG(
        dag_id="nidp_market_eod",
        description="NSE EOD market data + bulk/block + index close",
        default_args=make_default_args(retries=4),
        start_date=datetime(2026, 1, 1),
        schedule="15 13 * * 1-5",                                  # Mon-Fri 13:15 UTC
        catchup=False,
        max_active_runs=1,
        tags=["nidp", "ingest", "eod"],
    ) as dag:

        bhavcopy = PythonOperator(
            task_id="bhavcopy",
            python_callable=python_ingest("bhavcopy", with_date=True),
        )

        index_close = PythonOperator(
            task_id="index_close",
            python_callable=python_ingest("index_close", with_date=True),
        )

        bulk_deals = PythonOperator(
            task_id="bulk_deals",
            python_callable=python_ingest("bulk_deals", with_date=False),
        )

        block_deals = PythonOperator(
            task_id="block_deals",
            python_callable=python_ingest("block_deals", with_date=False),
        )

        bhavcopy >> [index_close, bulk_deals, block_deals]
