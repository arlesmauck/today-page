"""Fetch and cache news stories from RSS feeds."""
import json
import os
import re
from datetime import datetime, timezone

import feedparser
import httpx

from src.config import DATA_DIR


NEWS_FILE = DATA_DIR / "news.json"

# Google News topic feeds — aggregate from hundreds of publishers.
# These are the primary broad-coverage sources, no config required.
GOOGLE_NEWS_FEEDS = [
    ("World",      "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en"),
    ("Technology", "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTlhRU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en"),
    ("Science",    "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNR1ptZHpRU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en"),
    ("Health",     "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ?hl=en-US&gl=US&ceid=US:en"),
]

# Max stories kept per category after deduplication
STORIES_PER_CATEGORY = 6


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _load_user_feeds() -> list[tuple[str, str]]:
    """Return [(category, url), ...] from user-configured env vars."""
    feeds = []
    for key, val in os.environ.items():
        if key.startswith("NEWS_FEED_") and key.endswith("_URL") and val:
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

    feed_title = parsed.feed.get("title", url.split("/")[2])
    stories = []
    for entry in parsed.entries[:STORIES_PER_CATEGORY]:
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
    user_feeds = _load_user_feeds()

    # Build per-category story lists: user feeds first (preferred), then Google News
    category_stories: dict[str, list[dict]] = {}

    async with httpx.AsyncClient(timeout=20.0) as client:
        # User-configured feeds first so they take priority in dedup
        for category, url in user_feeds:
            stories = await _fetch_feed(client, category, url)
            category_stories.setdefault(category, []).extend(stories)

        # Google News broad coverage
        for category, url in GOOGLE_NEWS_FEEDS:
            stories = await _fetch_feed(client, category, url)
            category_stories.setdefault(category, []).extend(stories)

    # Deduplicate by URL within each category, cap at STORIES_PER_CATEGORY
    all_stories: list[dict] = []
    for category, stories in category_stories.items():
        seen_urls: set[str] = set()
        kept = []
        for story in stories:
            url = story["url"]
            if url and url not in seen_urls:
                seen_urls.add(url)
                kept.append(story)
            if len(kept) >= STORIES_PER_CATEGORY:
                break
        all_stories.extend(kept)

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
