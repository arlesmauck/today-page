"""Background scheduler that refreshes data on an interval."""
import asyncio
import logging

from src.config import REFRESH_INTERVAL, NEWS_CURATION_ENABLED, AI_SUMMARY_ENABLED
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
# LiteLLM logs cost-tracking failures at DEBUG for models not in its pricing database
# These are harmless (cost defaults to None) but very chatty at DEBUG log level
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)
logger = logging.getLogger("scheduler")


async def _run_once(label: str = "") -> None:
    """Execute one full refresh cycle."""
    prefix = f"{label} " if label else ""

    try:
        await refresh_weather()
        logger.info("%sweather fetch complete", prefix)
    except Exception as e:
        logger.error("%sweather fetch failed: %s", prefix, e)

    try:
        await refresh_calendar()
        logger.info("%scalendar fetch complete", prefix)
    except Exception as e:
        logger.error("%scalendar fetch failed: %s", prefix, e)

    try:
        await refresh_news()
        logger.info("%snews fetch complete", prefix)
    except Exception as e:
        logger.error("%snews fetch failed: %s", prefix, e)

    if NEWS_CURATION_ENABLED:
        try:
            from src.news_curator import curate_news
            unselected = await curate_news()
            logger.info("%snews curation complete — %d stories set aside", prefix, unselected)
        except Exception as e:
            logger.error("%snews curation failed — showing all stories: %s", prefix, e)

    if AI_SUMMARY_ENABLED:
        try:
            from src.news_clusterer import cluster_news
            merged = await cluster_news()
            logger.info("%sclustering complete — %d stories merged", prefix, merged)
        except Exception as e:
            logger.error("%sclustering failed: %s", prefix, e)

    if AI_SUMMARY_ENABLED:
        try:
            from src.morning_briefer import generate_briefing
            briefing = await generate_briefing()
            if briefing:
                logger.info("%smorning briefing generated (%d chars)", prefix, len(briefing))
        except Exception as e:
            logger.error("%smorning briefing failed: %s", prefix, e)

    try:
        write_page()
        logger.info("%spage rebuilt", prefix)
    except Exception as e:
        logger.error("%spage build failed: %s", prefix, e)


async def run_scheduler():
    """Run the refresh loop forever."""
    logger.info("Starting scheduler with %d-second interval", REFRESH_INTERVAL)
    await _run_once(label="Initial")
    while True:
        await asyncio.sleep(REFRESH_INTERVAL)
        await _run_once()
