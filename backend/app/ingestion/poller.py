import asyncio
import logging

import httpx

from app.config import settings
from app.ingestion import live_source
from app.ingestion.pipeline import ingest_reading

logger = logging.getLogger("sei")


async def run_live_poller() -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            failed = False
            for fetch in (live_source.fetch_wind_reading, live_source.fetch_hydro_reading):
                try:
                    reading = await fetch(client)
                    await ingest_reading(reading)
                except Exception as exc:
                    failed = True
                    logger.warning("Live poll failed (%s): %s", fetch.__name__, exc)
            # A failed poll (e.g. no network at startup) leaves the node empty, so retry soon instead of after a full interval.
            await asyncio.sleep(min(10.0, settings.live_poll_interval_seconds) if failed else settings.live_poll_interval_seconds)
