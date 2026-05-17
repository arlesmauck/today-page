"""AI-powered news summarization with article fetching and caching."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx

from src.config import AI_MODEL, AI_API_KEY, AI_API_BASE, AI_SUMMARY_ENABLED, DATA_DIR
from src.news import NEWS_FILE


CACHE_FILE = DATA_DIR / "news_ai_cache.json"
CACHE_TTL_DAYS = 7
MAX_ARTICLE_CHARS = 8000
ARTICLE_FETCH_TIMEOUT = 15.0

SYSTEM_PROMPT = """You are a calm, neutral news editor writing for a personal daily briefing. \
Summarize news articles at two levels of detail for a reader who wants facts and context \
without emotional manipulation.

Rules for all summaries:
- Use only facts present in the article. Do not speculate.
- Avoid sensational, emotional, or urgency-framing language \
("shocking", "alarming", "breaking", "you won't believe").
- Do not editorialize. Do not evaluate whether news is good or bad.
- Write in plain declarative sentences at an 8th-grade reading level.
- If the article is primarily opinion or analysis, note that in one phrase \
("In an opinion piece, ...").

Output format — respond with exactly this structure, nothing else:
BRIEF: [1-2 sentences: the core fact of what happened]
DETAIL: [5-8 sentences: what happened, who is involved, relevant background context, \
and any significant differing perspectives or implications]"""


def _load_cache() -> dict:
    """Read cache, prune expired entries, and return dict keyed by URL."""
    if not CACHE_FILE.exists():
        return {}
    try:
        raw = json.loads(CACHE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=CACHE_TTL_DAYS)
    return {
        url: entry for url, entry in raw.items()
        if datetime.fromisoformat(entry["cached_at"]) > cutoff
    }


def _save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


async def _fetch_article_text(
    client: httpx.AsyncClient, url: str
) -> tuple[str | None, bool]:
    """Fetch and extract main article text. Returns (text, accessible)."""
    try:
        import trafilatura
        resp = await client.get(url, follow_redirects=True, timeout=ARTICLE_FETCH_TIMEOUT)
        resp.raise_for_status()
        text = trafilatura.extract(resp.text)
        if text:
            return text[:MAX_ARTICLE_CHARS], True
        return None, False
    except Exception:
        return None, False


async def _call_llm(headline: str, article_text: str) -> tuple[str, str] | None:
    """Call the configured LLM and parse the BRIEF/DETAIL response."""
    import litellm

    kwargs: dict = {
        "model": AI_MODEL,
        "max_tokens": 512,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Headline: {headline}\n\nArticle:\n{article_text}"},
        ],
    }
    if AI_API_KEY:
        kwargs["api_key"] = AI_API_KEY
    if AI_API_BASE:
        kwargs["api_base"] = AI_API_BASE

    try:
        response = await litellm.acompletion(**kwargs)
        text = response.choices[0].message.content.strip()
        if "\nDETAIL:" in text:
            brief_part, detail_part = text.split("\nDETAIL:", 1)
            brief = brief_part.removeprefix("BRIEF:").strip()
            detail = detail_part.strip()
            if brief and detail:
                return brief, detail
        return None
    except Exception as e:
        print(f"LLM error ({AI_MODEL}): {e}")
        return None


async def _summarize_one(
    http_client: httpx.AsyncClient,
    story: dict,
    cache: dict,
) -> dict:
    """Enrich a single story with AI summaries. Reads/writes cache in-place."""
    url = story.get("url", "")

    # Cache hit — apply and return immediately
    if url and url in cache:
        entry = cache[url]
        return {
            **story,
            "summary_brief": entry["summary_brief"],
            "summary_detail": entry["summary_detail"],
            "accessible": entry["accessible"],
            "ai_source": entry["ai_source"],
        }

    # Fetch full article text
    article_text, accessible = await _fetch_article_text(http_client, url)
    ai_source = "full_article" if article_text else "rss_lede"
    input_text = article_text or story.get("lede", story.get("headline", ""))

    # Call LLM
    result = await _call_llm(story.get("headline", ""), input_text)

    if result:
        brief, detail = result
    else:
        brief = story.get("lede", "")
        detail = ""

    # Update cache
    if url:
        cache[url] = {
            "summary_brief": brief,
            "summary_detail": detail,
            "accessible": accessible,
            "ai_source": ai_source,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

    enriched = {**story, "summary_brief": brief, "accessible": accessible, "ai_source": ai_source}
    if detail:
        enriched["summary_detail"] = detail
    return enriched


async def enrich_stories_with_ai(stories: list[dict]) -> list[dict]:
    """
    Add AI summaries to stories, using cache to avoid redundant API calls.
    Rewrites news.json with enriched stories. Returns enriched list.
    No-op if AI_SUMMARY_ENABLED is False.
    """
    if not AI_SUMMARY_ENABLED or not stories:
        return stories

    cache = _load_cache()

    async with httpx.AsyncClient(
        timeout=ARTICLE_FETCH_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; today-page/1.0)"},
    ) as http_client:
        enriched_stories = await asyncio.gather(
            *[_summarize_one(http_client, story, cache) for story in stories]
        )

    _save_cache(cache)
    NEWS_FILE.write_text(json.dumps(list(enriched_stories), indent=2, ensure_ascii=False))
    return list(enriched_stories)
