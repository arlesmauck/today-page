"""Fetch and cache news stories from RSS feeds."""
import json
import os
import re
from datetime import datetime, timezone

import feedparser
import httpx

from src.config import DATA_DIR


NEWS_FILE = DATA_DIR / "news.json"

# Default feeds shipped with the image — users can override via env vars.
# Each entry: (category_label, env_var_name, default_url)
DEFAULT_FEEDS = [
    ("World", "NEWS_FEED_WORLD_URL", "https://feeds.reuters.com/reuters/topNews"),
    ("Science & Tech", "NEWS_FEED_TECH_URL", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
]

STORIES_PER_FEED = 5


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _load_feeds() -> list[tuple[str, str]]:
    """Return [(category, url), ...] from env vars + defaults."""
    feeds = []
    for label, env_var, default_url in DEFAULT_FEEDS:
        url = os.environ.get(env_var, default_url)
        if url:
            feeds.append((label, url))

    # Allow arbitrary extra feeds: NEWS_FEED_LOCAL_URL, NEWS_FEED_SPORTS_URL, etc.
    for key, val in os.environ.items():
        if key.startswith("NEWS_FEED_") and key.endswith("_URL"):
            known = {e for _, e, _ in DEFAULT_FEEDS}
            if key not in known and val:
                label = key.removeprefix("NEWS_FEED_").removesuffix("_URL").replace("_", " ").title()
                feeds.append((label, val))

    return feeds


async def _fetch_feed(client: httpx.AsyncClient, category: str, url: str) -> list[dict]:
    """Fetch one RSS feed and return parsed stories."""
    try:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)
    except Exception as e:
        print(f"News feed error ({url}): {e}")
        return []

    source_name = parsed.feed.get("title", url.split("/")[2])
    stories = []
    for entry in parsed.entries[:STORIES_PER_FEED]:
        headline = _strip_html(entry.get("title", ""))
        lede = _strip_html(entry.get("summary", entry.get("description", "")))
        # Truncate lede to ~200 chars
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
    """Fetch all configured RSS feeds and save to disk."""
    feeds = _load_feeds()
    all_stories = []

    async with httpx.AsyncClient(timeout=20.0) as client:
        for category, url in feeds:
            stories = await _fetch_feed(client, category, url)
            all_stories.extend(stories)

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
    """Return the ordered list of category labels from configured feeds."""
    seen = []
    for label, _, _ in DEFAULT_FEEDS:
        env_var = f"NEWS_FEED_{label.replace(' & ', '_').replace(' ', '_').upper()}_URL"
        seen.append(label)
    for key in os.environ:
        if key.startswith("NEWS_FEED_") and key.endswith("_URL"):
            known_vars = {e for _, e, _ in DEFAULT_FEEDS}
            if key not in known_vars:
                label = key.removeprefix("NEWS_FEED_").removesuffix("_URL").replace("_", " ").title()
                seen.append(label)
    return seen
