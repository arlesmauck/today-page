"""Background scheduler that refreshes data on an interval."""
import asyncio
import logging

from src.config import REFRESH_INTERVAL, NEWS_CURATION_ENABLED
from src.fetcher import refresh_weather
from src.calendar import refresh_calendar
from src.news import refresh_news
from src.builder import write_page

import os
_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# trafilatura logs expected failures at WARNING — suppress since we handle them ourselves
logging.getLogger("trafilatura").setLevel(logging.ERROR)
logging.getLogger("trafilatura.core").setLevel(logging.ERROR)
logger = logging.getLogger("scheduler")


async def run_scheduler():
    """Run the refresh loop forever."""
    logger.info("Starting scheduler with %d-second interval", REFRESH_INTERVAL)

    # Do an initial fetch immediately
    try:
        await refresh_weather()
        logger.info("Initial weather fetch complete")
    except Exception as e:
        logger.error("Initial weather fetch failed: %s", e)

    try:
        await refresh_calendar()
        logger.info("Initial calendar fetch complete")
    except Exception as e:
        logger.error("Initial calendar fetch failed: %s", e)

    try:
        await refresh_news()
        logger.info("Initial news fetch complete")
    except Exception as e:
        logger.error("Initial news fetch failed: %s", e)

    if NEWS_CURATION_ENABLED:
        try:
            from src.news_curator import curate_news
            unselected = await curate_news()
            logger.info("Initial news curation complete — %d stories set aside", unselected)
        except Exception as e:
            logger.error("Initial news curation failed — showing all stories: %s", e)

    try:
        write_page()
        logger.info("Page rebuilt")
    except Exception as e:
        logger.error("Page build failed: %s", e)

    while True:
        await asyncio.sleep(REFRESH_INTERVAL)
        try:
            await refresh_weather()
            logger.info("Weather refresh complete")
        except Exception as e:
            logger.error("Weather refresh failed: %s", e)

        try:
            await refresh_calendar()
            logger.info("Calendar refresh complete")
        except Exception as e:
            logger.error("Calendar refresh failed: %s", e)

        try:
            await refresh_news()
            logger.info("News refresh complete")
        except Exception as e:
            logger.error("News refresh failed: %s", e)

        if NEWS_CURATION_ENABLED:
            try:
                from src.news_curator import curate_news
                unselected = await curate_news()
                logger.info("News curation complete — %d stories set aside", unselected)
            except Exception as e:
                logger.error("News curation failed — showing all stories: %s", e)

        try:
            write_page()
            logger.info("Page rebuilt")
        except Exception as e:
            logger.error("Page build failed: %s", e)
