"""Background scheduler that refreshes data on an interval."""
import asyncio
import logging

from src.config import REFRESH_INTERVAL
from src.fetcher import refresh_weather
from src.calendar import refresh_calendar
from src.builder import write_page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
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
    
    # Build the page
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
            write_page()
            logger.info("Page rebuilt")
        except Exception as e:
            logger.error("Page build failed: %s", e)
