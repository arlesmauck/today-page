"""AI-powered news summarization with article fetching and caching."""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from src.config import AI_MODEL, AI_API_KEY, AI_API_BASE, AI_SUMMARY_ENABLED, CONTEXT_MODEL, CONTEXT_ENABLED, CONTEXT_MAX_PER_REFRESH, DATA_DIR
from src.news import NEWS_FILE


logger = logging.getLogger("ai_summarizer")

CACHE_FILE = DATA_DIR / "news_ai_cache.json"
CACHE_TTL_DAYS = 7
MAX_ARTICLE_CHARS = 8000
ARTICLE_FETCH_TIMEOUT = 15.0
MAX_CONCURRENT_LLM_CALLS = 5

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

CONTEXT_SYSTEM_PROMPT = (
    "You are a reference editor. Write one paragraph of essential background "
    "for a reader encountering this news story. Cover: who the key players are, "
    "relevant history, and why this topic matters. Use only well-established, "
    "verifiable facts. Be neutral and concise."
)

PROMPTS_FILE = DATA_DIR / "prompts.json"


def _load_prompts() -> dict[str, str]:
    """Return active prompts, falling back to hardcoded defaults if file missing or invalid."""
    from src.morning_briefer import DEFAULT_BRIEFING_PROMPT
    from src.news_curator import DEFAULT_CURATION_PROMPT
    defaults = {
        "summary_prompt": SYSTEM_PROMPT,
        "context_prompt": CONTEXT_SYSTEM_PROMPT,
        "briefing_prompt": DEFAULT_BRIEFING_PROMPT,
        "curation_prompt": DEFAULT_CURATION_PROMPT,
    }
    if PROMPTS_FILE.exists():
        try:
            data = json.loads(PROMPTS_FILE.read_text())
            return {key: data.get(key) or default for key, default in defaults.items()}
        except (json.JSONDecodeError, OSError):
            logger.warning("prompts.json unreadable — using defaults")
    return defaults


def _load_cache() -> dict:
    """Read cache, prune expired entries, and return dict keyed by URL."""
    if not CACHE_FILE.exists():
        return {}
    try:
        raw = json.loads(CACHE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Cache file unreadable — starting fresh")
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=CACHE_TTL_DAYS)
    pruned = {
        url: entry for url, entry in raw.items()
        if datetime.fromisoformat(entry["cached_at"]) > cutoff
    }
    expired = len(raw) - len(pruned)
    if expired:
        logger.debug("Pruned %d expired cache entries", expired)
    return pruned


def _save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


async def _fetch_article_text(
    client: httpx.AsyncClient, url: str
) -> tuple[str | None, bool]:
    """Fetch and extract main article text. Returns (text, accessible)."""
    import trafilatura

    logger.debug("Fetching article: %s", url)
    try:
        resp = await client.get(url, follow_redirects=True, timeout=ARTICLE_FETCH_TIMEOUT)
        resp.raise_for_status()
        text = trafilatura.extract(resp.text)
        if text:
            logger.debug("Article fetched: %d chars from %s", url, len(text))
            return text[:MAX_ARTICLE_CHARS], True
        logger.debug("No extractable content (likely paywalled): %s", url)
        return None, False
    except Exception as e:
        logger.debug("Article fetch failed for %s: %s", url, e)
        return None, False


def _parse_llm_response(text: str) -> tuple[str, str] | None:
    """Parse BRIEF/DETAIL from LLM output. Tolerates varied formatting."""
    import re
    # Normalize line endings and strip markdown bold around labels
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\*\*(BRIEF|DETAIL):\*\*", r"\1:", text)
    # Split on DETAIL: regardless of whether a newline precedes it
    parts = re.split(r"\n?DETAIL:", text, maxsplit=1)
    if len(parts) == 2:
        brief = re.sub(r"^BRIEF:\s*", "", parts[0], flags=re.IGNORECASE).strip()
        detail = parts[1].strip()
        if brief and detail:
            return brief, detail
    logger.warning("LLM response did not match expected format. Raw output: %r", text[:200])
    return None


async def _call_llm(headline: str, article_text: str) -> tuple[str, str] | None:
    """Call the configured LLM and parse the BRIEF/DETAIL response."""
    import litellm

    kwargs: dict = {
        "model": AI_MODEL,
        "max_tokens": 512,
        "messages": [
            {"role": "system", "content": _load_prompts()["summary_prompt"]},
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
        result = _parse_llm_response(text)
        if result:
            logger.debug("LLM summarized: %r", headline[:60])
        return result
    except Exception as e:
        logger.error("LLM call failed for %r: %s", headline[:60], e)
        return None


async def _call_context_llm(headline: str) -> str | None:
    """Call CONTEXT_MODEL (e.g. Perplexity sonar) for web-searched background on a headline."""
    import litellm

    kwargs: dict = {
        "model": CONTEXT_MODEL,
        "max_tokens": 256,
        "messages": [
            {"role": "system", "content": _load_prompts()["context_prompt"]},
            {"role": "user", "content": f"News headline: {headline}"},
        ],
    }
    if AI_API_KEY:
        kwargs["api_key"] = AI_API_KEY
    if AI_API_BASE:
        kwargs["api_base"] = AI_API_BASE

    try:
        response = await litellm.acompletion(**kwargs)
        text = response.choices[0].message.content.strip()
        logger.debug("Context LLM responded for %r", headline[:60])
        return text
    except Exception as e:
        logger.warning("Context LLM call failed for %r: %s", headline[:60], e)
        return None


async def _summarize_one(
    http_client: httpx.AsyncClient,
    story: dict,
    cache: dict,
    context_budget: list[int] | None = None,
) -> dict:
    """Enrich a single story with AI summaries. Reads/writes cache in-place."""
    url = story.get("url", "")
    headline = story.get("headline", "")

    # Cache hit — apply and return immediately
    if url and url in cache:
        logger.debug("Cache hit: %r", headline[:60])
        entry = cache[url]
        enriched = {
            **story,
            "summary_brief": entry["summary_brief"],
            "summary_detail": entry["summary_detail"],
            "accessible": entry["accessible"],
            "ai_source": entry["ai_source"],
        }
        if entry.get("summary_context"):
            enriched["summary_context"] = entry["summary_context"]
        return enriched

    logger.debug("Cache miss — fetching article: %r", headline[:60])

    # Fetch full article text
    article_text, accessible = await _fetch_article_text(http_client, url)
    ai_source = "full_article" if article_text else "rss_lede"
    input_text = article_text or story.get("lede", story.get("headline", ""))

    # Skip the LLM if we have nothing beyond the headline — but keep the story.
    has_content = input_text and len(input_text) > len(headline) + 50
    if not has_content:
        logger.debug("No article content — keeping story without AI summary: %r", headline[:60])
        return {**story, "accessible": accessible}

    if not article_text:
        logger.debug("Using RSS lede as LLM input for: %r", headline[:60])

    result = await _call_llm(headline, input_text)
    if not result:
        logger.warning("LLM failed — keeping story without AI summary: %r", headline[:60])
        return {**story, "accessible": accessible}

    brief, detail = result

    # Optional: call context model for background paragraph.
    # Skip for lede-only stories (article not accessible) — lower value, not worth the cost.
    # Skip if the per-refresh context budget is exhausted.
    context: str | None = None
    if CONTEXT_ENABLED and ai_source == "full_article":
        if context_budget is None or context_budget[0] > 0:
            if context_budget is not None:
                context_budget[0] -= 1
            context = await _call_context_llm(headline)
        else:
            logger.debug("Context budget exhausted — skipping for %r", headline[:60])

    # Update cache
    if url:
        cache[url] = {
            "summary_brief": brief,
            "summary_detail": detail,
            "accessible": accessible,
            "ai_source": ai_source,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        if context:
            cache[url]["summary_context"] = context

    enriched = {**story, "summary_brief": brief, "accessible": accessible, "ai_source": ai_source}
    if detail:
        enriched["summary_detail"] = detail
    if context:
        enriched["summary_context"] = context
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
    cache_hits = sum(1 for s in stories if s.get("url") in cache)
    new_count = len(stories) - cache_hits
    context_note = (
        f", up to {CONTEXT_MAX_PER_REFRESH} context calls (model: {CONTEXT_MODEL})"
        if CONTEXT_ENABLED and new_count > 0 and CONTEXT_MAX_PER_REFRESH > 0
        else f", context calls: unlimited (model: {CONTEXT_MODEL})"
        if CONTEXT_ENABLED and new_count > 0
        else ""
    )
    logger.info(
        "Enriching %d stories — %d cached, %d need LLM calls (model: %s%s)",
        len(stories), cache_hits, new_count, AI_MODEL, context_note,
    )

    # Shared context budget — limits expensive context LLM calls per refresh cycle.
    # None = no cap. CONTEXT_MAX_PER_REFRESH=0 means no cap (unlimited).
    context_budget: list[int] | None = (
        [CONTEXT_MAX_PER_REFRESH] if CONTEXT_ENABLED and CONTEXT_MAX_PER_REFRESH > 0 else None
    )

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)

    async def _with_limit(http_client, story, cache):
        async with semaphore:
            return await _summarize_one(http_client, story, cache, context_budget)

    async with httpx.AsyncClient(
        timeout=ARTICLE_FETCH_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        },
    ) as http_client:
        results = await asyncio.gather(
            *[_with_limit(http_client, story, cache) for story in stories],
            return_exceptions=True,
        )

    enriched_stories = []
    failed = 0
    for original, result in zip(stories, results):
        if isinstance(result, Exception):
            logger.error(
                "Summarization failed for %r: %s",
                original.get("headline", "?")[:60], result,
            )
            enriched_stories.append(original)
            failed += 1
        else:
            enriched_stories.append(result)

    with_ai = sum(1 for s in enriched_stories if s.get("summary_brief"))
    with_context = sum(1 for s in enriched_stories if s.get("summary_context"))
    context_calls_made = (
        (CONTEXT_MAX_PER_REFRESH - context_budget[0]) if context_budget is not None else
        with_context - sum(1 for s in stories if s.get("url") in cache and cache[s.get("url", "")].get("summary_context"))
    )
    context_log = f", {with_context} with background context ({context_calls_made} new calls)" if CONTEXT_ENABLED else ""
    logger.info(
        "Enrichment complete — %d stories (%d with AI summaries, %d without%s), %d errors",
        len(enriched_stories), with_ai, len(enriched_stories) - with_ai, context_log, failed,
    )

    _save_cache(cache)
    NEWS_FILE.write_text(json.dumps(enriched_stories, indent=2, ensure_ascii=False))
    return enriched_stories


async def summarize_on_demand(url: str, headline: str, lede: str) -> dict:
    """
    Fetch and summarize a single story on demand (called when user clicks a button).
    Cache-first: returns cached result immediately if available.
    Returns dict with keys: brief, detail, context (optional), accessible, ai_source.
    """
    if not AI_SUMMARY_ENABLED:
        return {}

    cache = _load_cache()

    # Cache hit — return immediately at no cost
    if url and url in cache:
        entry = cache[url]
        logger.debug("On-demand cache hit: %r", headline[:60])
        result = {
            "brief": entry["summary_brief"],
            "detail": entry["summary_detail"],
            "accessible": entry["accessible"],
            "ai_source": entry["ai_source"],
        }
        if entry.get("summary_context"):
            result["context"] = entry["summary_context"]
        return result

    logger.info("On-demand summarize: %r", headline[:60])

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    async with httpx.AsyncClient(timeout=ARTICLE_FETCH_TIMEOUT, headers=HEADERS) as client:
        article_text, accessible = await _fetch_article_text(client, url)

    ai_source = "full_article" if article_text else "rss_lede"
    input_text = article_text or lede or headline

    llm_result = await _call_llm(headline, input_text)
    if not llm_result:
        logger.warning("On-demand LLM failed for %r", headline[:60])
        return {"accessible": accessible, "ai_source": ai_source}

    brief, detail = llm_result

    context: str | None = None
    if CONTEXT_ENABLED and ai_source == "full_article":
        context = await _call_context_llm(headline)

    if url:
        cache[url] = {
            "summary_brief": brief,
            "summary_detail": detail,
            "accessible": accessible,
            "ai_source": ai_source,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        if context:
            cache[url]["summary_context"] = context
        _save_cache(cache)

    result = {
        "brief": brief,
        "detail": detail,
        "accessible": accessible,
        "ai_source": ai_source,
    }
    if context:
        result["context"] = context
    return result
