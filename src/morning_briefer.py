"""Generate a prose morning briefing paragraph from the day's top stories."""
import hashlib
import json
import logging
from datetime import datetime, timezone

import litellm

from src.config import AI_MODEL, AI_API_KEY, AI_API_BASE, AI_SUMMARY_ENABLED, DATA_DIR
from src.news import load_news

logger = logging.getLogger("morning_briefer")

BRIEFING_FILE = DATA_DIR / "morning_briefing.json"

DEFAULT_BRIEFING_PROMPT = """\
You are writing the opening paragraph of a personal morning news briefing.
Summarize the most significant stories in 3-4 flowing sentences. Write directly \
to one reader — clear, no filler.
Focus on what genuinely matters and how stories connect, if they do.
Do not start with "Today" or list stories one by one. Do not use bullet points.
Output only the paragraph, nothing else."""

# Top N stories per category to include in the briefing input
_STORIES_PER_CATEGORY = 2
_MAX_INPUT_STORIES = 12


def _get_briefing_prompt() -> str:
    """Return active briefing prompt, falling back to default."""
    try:
        from src.ai_summarizer import _load_prompts
        return _load_prompts().get("briefing_prompt") or DEFAULT_BRIEFING_PROMPT
    except Exception:
        return DEFAULT_BRIEFING_PROMPT


def _input_hash(stories: list[dict]) -> str:
    """SHA256 of sorted headline+category strings — cache key."""
    keys = sorted(f"{s.get('category','')}:{s.get('headline','')}" for s in stories)
    return hashlib.sha256(json.dumps(keys).encode()).hexdigest()[:16]


def _load_cache() -> dict:
    if not BRIEFING_FILE.exists():
        return {}
    try:
        return json.loads(BRIEFING_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _select_top_stories(stories: list[dict]) -> list[dict]:
    """Pick top N stories per category up to a total cap."""
    by_cat: dict[str, list[dict]] = {}
    for s in stories:
        by_cat.setdefault(s.get("category", ""), []).append(s)

    selected: list[dict] = []
    for cat_stories in by_cat.values():
        selected.extend(cat_stories[:_STORIES_PER_CATEGORY])
        if len(selected) >= _MAX_INPUT_STORIES:
            break
    return selected[:_MAX_INPUT_STORIES]


async def generate_briefing() -> str | None:
    """
    Read clustered news.json, call LLM, write briefing to morning_briefing.json.
    Cache-first: same story set → return cached briefing, no LLM call.
    Returns briefing text, or None on error / no stories.
    No-op if AI_SUMMARY_ENABLED is False.
    """
    if not AI_SUMMARY_ENABLED:
        return None

    all_stories = load_news()
    if not all_stories:
        return None

    top_stories = _select_top_stories(all_stories)
    current_hash = _input_hash(top_stories)

    cache = _load_cache()
    if cache.get("input_hash") == current_hash and cache.get("briefing"):
        logger.debug("Morning briefing cache hit — skipping LLM call")
        return cache["briefing"]

    # Build user message
    lines = []
    for s in top_stories:
        cat = s.get("category", "")
        headline = s.get("headline", "")
        lede = s.get("lede", "")
        line = f"{cat}: {headline}"
        if lede:
            line += f"\n  {lede}"
        lines.append(line)
    user_message = "\n\n".join(lines)

    kwargs: dict = {
        "model": AI_MODEL,
        "max_tokens": 300,
        "messages": [
            {"role": "system", "content": _get_briefing_prompt()},
            {"role": "user", "content": user_message},
        ],
    }
    if AI_API_KEY:
        kwargs["api_key"] = AI_API_KEY
    if AI_API_BASE:
        kwargs["api_base"] = AI_API_BASE

    try:
        response = await litellm.acompletion(**kwargs)
        briefing = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("Morning briefing LLM call failed: %s", e)
        return None

    BRIEFING_FILE.write_text(json.dumps({
        "input_hash": current_hash,
        "briefing": briefing,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2, ensure_ascii=False))

    logger.info("Morning briefing generated (%d chars)", len(briefing))
    return briefing
