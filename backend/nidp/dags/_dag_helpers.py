"""Shared DAG helpers — keeps the per-DAG files terse.

We import Airflow lazily so the dags/ package can be unit-tested or
linted without an Airflow install.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable


def make_default_args(*, owner: str = "nidp", retries: int = 3) -> dict[str, Any]:
    return {
        "owner": owner,
        "depends_on_past": False,
        "email_on_failure": True,
        "email_on_retry": False,
        "retries": retries,
        "retry_delay": timedelta(minutes=5),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=30),
        "execution_timeout": timedelta(minutes=30),
    }


def python_ingest(service: str, with_date: bool = True) -> Callable:
    """Returns a callable suitable for PythonOperator.

    `service` is the NIDP service name (e.g. 'bhavcopy'). When
    `with_date=True`, the callable expects an Airflow execution date
    in `kwargs['ds']` (yyyy-mm-dd) and runs the ingester for that
    date. When False, runs the rolling/non-dated ingester.
    """
    import importlib
    from datetime import datetime

    def _run(**kwargs: Any) -> None:
        # Lazy: don't pay import-cost at DAG-load time
        mod = importlib.import_module(f"nidp.services.{service}.service")
        run_fn = getattr(mod, "run")
        if with_date:
            ds = kwargs["ds"]
            target = datetime.strptime(ds, "%Y-%m-%d").date()
            import asyncio
            asyncio.run(run_fn(target))
        else:
            import asyncio
            asyncio.run(run_fn(None))

    _run.__name__ = f"run_{service}"
    return _run
