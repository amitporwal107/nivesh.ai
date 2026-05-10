import asyncio

from nidp.services.d1_prep.service import run
from nidp.shared.derived_run import run_with_job_log
from nidp.shared.storage.pg import close_pool


async def _main() -> None:
    try:
        await run_with_job_log("d1_prep", run)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
