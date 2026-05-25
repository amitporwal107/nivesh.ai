import asyncio

from nidp.services.analytics_refresh.service import run
from nidp.shared.derived_run import run_with_job_log
from nidp.shared.storage.pg import close_pool


async def _main() -> None:
    try:
        await run_with_job_log(
            "analytics_refresh",
            run,
            rows_inserted_attr="rows_inserted",
        )
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
