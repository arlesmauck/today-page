"""Fetch and cache news stories from RSS feeds."""
import json
import logging
import os
import re
from datetime import datetime, timezone

import asyncio

import feedparser
import httpx
from urllib.parse import quote

from src.config import DATA_DIR
from src.app_settings import get_feeds, get_location_name, get_stories_per_category

logger = logging.getLogger("news")


NEWS_FILE = DATA_DIR / "news.json"

# Google News topic feeds — aggregate from hundreds of publishers.
# These are the primary broad-coverage sources, no config required.
# Default feeds — direct publisher RSS that return real article URLs
# (needed for AI article fetching to work)
DEFAULT_FEEDS = [
    ("World",      "NEWS_FEED_WORLD_URL",  "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Technology", "NEWS_FEED_TECH_URL",   "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("Science",    "NEWS_FEED_SCI_URL",    "https://www.sciencedaily.com/rss/top/science.xml"),
    ("Health",     "NEWS_FEED_HEALTH_URL", "https://feeds.bbci.co.uk/news/health/rss.xml"),
    ("US",         "NEWS_FEED_US_URL",     "https://feeds.npr.org/1001/rss.xml"),
]

# Google News topic feeds — broader coverage alongside direct publisher RSS.
# Same category labels so stories merge into existing tabs.
# Disable individually: NEWS_GNEWS_WORLD=false, etc.
_GNEWS_BASE = "https://news.google.com/rss/topics"
SUPPLEMENTARY_FEEDS = [
    ("World",      "NEWS_GNEWS_WORLD",  f"{_GNEWS_BASE}/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB"),
    ("Technology", "NEWS_GNEWS_TECH",   f"{_GNEWS_BASE}/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTlhRU0FtVnVHZ0pWVXlnQVAB"),
    ("Science",    "NEWS_GNEWS_SCI",    f"{_GNEWS_BASE}/CAAqJggKIiBDQkFTRWdvSUwyMHZNR1ptZHpRU0FtVnVHZ0pWVXlnQVAB"),
    ("Health",     "NEWS_GNEWS_HEALTH", f"{_GNEWS_BASE}/CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ"),
]

# Maps env var category keys → category labels used in the app.
# Used to detect NEWS_FEED_{KEY}_{SUFFIX}_URL vars that should merge into
# an existing category tab rather than create a new one.
_CATEGORY_KEY_MAP = {
    "WORLD":  "World",
    "TECH":   "Technology",
    "SCI":    "Science",
    "HEALTH": "Health",
    "US":     "US",
    "LOCAL":  "Local",
}


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _auto_local_url(location: str) -> str:
    """Google News search feed for a location name — used for the Local tab."""
    encoded = quote(location)
    return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"


def _direct_feeds() -> list[tuple[str, str]]:
    """
    Direct publisher feeds as [(category, url), ...].

    settings.json feeds take precedence when configured. Otherwise fall back
    to the legacy env-var behaviour: app defaults, overridable per category,
    plus NEWS_FEED_* scans (NEWS_FEED_{KEY}_{SUFFIX}_URL merges into an
    existing category tab, NEWS_FEED_{ANYTHING}_URL creates a new tab).

    Excludes the supplementary Google News feeds and the auto-generated
    Local feed — those are added in _load_feeds and always derived from
    current config, so they never get baked into saved settings.
    """
    settings_feeds = get_feeds()
    if settings_feeds is not None:
        feeds: dict[str, str] = {}
        additional: list[tuple[str, str]] = []
        for f in settings_feeds:
            if f["category"] in feeds:
                additional.append((f["category"], f["url"]))
            else:
                feeds[f["category"]] = f["url"]
        result = list(feeds.items())
        result.extend(additional)
        return result

    # Legacy env-var behaviour
    known_env_vars = {env_var for _, env_var, _ in DEFAULT_FEEDS}
    feeds = {
        label: os.environ.get(env_var, default_url)
        for label, env_var, default_url in DEFAULT_FEEDS
    }
    additional: list[tuple[str, str]] = []
    for key, val in sorted(os.environ.items()):
        if not (key.startswith("NEWS_FEED_") and key.endswith("_URL") and val):
            continue
        if key in known_env_vars:
            continue
        body = key.removeprefix("NEWS_FEED_").removesuffix("_URL")  # e.g. WORLD_REUTERS
        parts = body.split("_", 1)
        if len(parts) == 2 and parts[0] in _CATEGORY_KEY_MAP:
            # Merges into existing category
            additional.append((_CATEGORY_KEY_MAP[parts[0]], val))
        else:
            # New tab
            label = body.replace("_", " ").title()
            feeds[label] = val

    result = list(feeds.items())
    result.extend(additional)
    return result


def editable_feeds() -> list[dict]:
    """Feeds shown in the settings UI: direct feeds only, as dicts."""
    return [
        {"category": category, "label": "", "url": url}
        for category, url in _direct_feeds()
    ]


def _load_feeds() -> list[tuple[str, str]]:
    """
    Return [(category, url), ...] for all feeds to fetch:
    direct feeds (settings or env), the auto-generated Local feed, and the
    supplementary Google News topic feeds.
    """
    feeds = _direct_feeds()

    # Auto-add Local tab from Google News search if not already configured
    location = get_location_name()
    if location and not any(cat == "Local" for cat, _ in feeds):
        feeds.append(("Local", _auto_local_url(location)))
        logger.debug("Auto-added Local feed for %r via Google News search", location)

    for label, env_var, url in SUPPLEMENTARY_FEEDS:
        if os.environ.get(env_var, "true").lower() not in ("false", "0", "no", "off"):
            feeds.append((label, url))
    return feeds


async def _fetch_feed(client: httpx.AsyncClient, category: str, url: str) -> list[dict]:
    """Fetch one RSS feed and return parsed stories."""
    try:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)
    except Exception as e:
        logger.warning("Feed fetch failed (%s): %s", url, e)
        return []

    per_category = get_stories_per_category() * 2
    feed_title = parsed.feed.get("title", url.split("/")[2])
    stories = []
    for entry in parsed.entries[:per_category]:
        # Google News embeds the publisher in entry.source; fall back to feed title
        source_name = (
            entry.get("source", {}).get("title")
            or feed_title
        )

        headline = _strip_html(entry.get("title", ""))
        # Google News appends " - Publisher Name" to titles — strip it
        if source_name and headline.endswith(f" - {source_name}"):
            headline = headline[: -len(f" - {source_name}")].strip()

        lede = _strip_html(entry.get("summary", entry.get("description", "")))
        if len(lede) > 200:
            lede = lede[:197].rsplit(" ", 1)[0] + "…"

        stories.append({
            "source": source_name,
            "headline": headline,
            "lede": lede,
            "url": entry.get("link", ""),
            "published_at": entry.get("published", ""),
            "category": category,
        })
    return stories


async def refresh_news() -> list[dict]:
    """Fetch all RSS feeds and save deduplicated stories to disk."""
    feeds = _load_feeds()
    category_stories: dict[str, list[dict]] = {}

    async with httpx.AsyncClient(timeout=20.0) as client:
        results = await asyncio.gather(
            *[_fetch_feed(client, cat, url) for cat, url in feeds],
            return_exceptions=True,
        )

    for (category, feed_url), result in zip(feeds, results):
        if isinstance(result, Exception):
            logger.warning("Feed fetch raised exception (%s): %s", feed_url, result)
        else:
            category_stories.setdefault(category, []).extend(result)

    # Deduplicate by URL within each category, cap at STORIES_PER_CATEGORY
    per_category = get_stories_per_category() * 2
    all_stories: list[dict] = []
    for category, stories in category_stories.items():
        seen_urls: set[str] = set()
        kept = []
        for story in stories:
            url = story["url"]
            if url and url not in seen_urls:
                seen_urls.add(url)
                kept.append(story)
            if len(kept) >= per_category:
                break
        all_stories.extend(kept)

    category_counts = {}
    for s in all_stories:
        category_counts[s["category"]] = category_counts.get(s["category"], 0) + 1
    logger.info(
        "News fetched — %d stories: %s",
        len(all_stories),
        ", ".join(f"{cat} ({n})" for cat, n in category_counts.items()),
    )
    NEWS_FILE.write_text(json.dumps(all_stories, indent=2, ensure_ascii=False))
    return all_stories


def load_news() -> list[dict]:
    """Load cached news from disk."""
    if not NEWS_FILE.exists():
        return []
    try:
        return json.loads(NEWS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def news_categories() -> list[str]:
    """Return ordered unique category labels from the current story cache."""
    seen: list[str] = []
    for story in load_news():
        cat = story.get("category", "")
        if cat and cat not in seen:
            seen.append(cat)
    return seen
