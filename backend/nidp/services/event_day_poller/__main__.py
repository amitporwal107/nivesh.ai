import asyncio
from nidp.services.event_day_poller.service import run

if __name__ == "__main__":
    asyncio.run(run())
