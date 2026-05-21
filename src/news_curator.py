"""AI-powered news curation — selects the most newsworthy stories from the pool."""
import hashlib
import json
import logging
import re
from datetime import datetime, timezone

from src.config import (
    NEWS_CURATION_ENABLED, REFRESH_INTERVAL, DATA_DIR,
    STORIES_PER_CATEGORY, get_category_quality,
)
from src.news import NEWS_FILE, load_news

logger = logging.getLogger("news_curator")

CURATION_CACHE_FILE = DATA_DIR / "curation_cache.json"
UNSELECTED_STORIES_FILE = DATA_DIR / "unselected_stories.json"

DEFAULT_CURATION_PROMPT = """\
You are an editor for a personal morning briefing. Each category is tagged with \
a display mode in brackets — follow it exactly.

STRICT [STRICT]: Apply an absolute newsworthiness standard.
  - Include ONLY stories reporting significant events with clear real-world impact \
(major policy, science breakthroughs, diplomacy, economics, public safety).
  - Specific verifiable facts required — no vague claims.
  - If nothing clears the bar, return an empty list for that category. 0 is correct.

RELAXED [RELAXED]: Select 2-4 of the best available stories.
  - Prefer real-world impact but include anything genuinely interesting or informative.
  - Fewer is fine if the pool is weak. Always pick at least 1 if stories exist.

For ALL categories, skip:
  - Celebrity gossip or entertainment fluff
  - Clickbait or engagement bait
  - Listicles with no original reporting
  - Viral moments with no broader significance

Respond with valid JSON only, no markdown fences:
{
  "World": [
    {"id": 1, "reason": "brief reason why selected (max 10 words)"},
    {"id": 3, "reason": "..."}
  ],
  "Technology": [...]
}

Include only categories that have stories worth selecting."""


def _get_curation_prompt() -> str:
    """Return active curation prompt, falling back to hardcoded default."""
    try:
        from src.ai_summarizer import _load_prompts
        return _load_prompts().get("curation_prompt") or DEFAULT_CURATION_PROMPT
    except Exception:
        return DEFAULT_CURATION_PROMPT


def _input_hash(stories: list[dict]) -> str:
    """SHA256 of sorted story URLs — used as cache key."""
    urls = sorted(s.get("url", "") for s in stories)
    return hashlib.sha256(json.dumps(urls).encode()).hexdigest()[:16]


def _load_cache() -> dict:
    if not CURATION_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CURATION_CACHE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    CURATION_CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def _build_prompt_message(stories_by_category: dict[str, list[tuple[int, dict]]]) -> str:
    """Build the user message listing all stories with IDs and per-category mode tag."""
    lines = []
    for category, numbered_stories in stories_by_category.items():
        mode = get_category_quality(category).upper()
        lines.append(f"=== {category.upper()} [{mode}] ===")
        for story_id, story in numbered_stories:
            headline = story.get("headline", "")
            lede = story.get("lede", "")
            source = story.get("source", "")
            lines.append(f"ID:{story_id}  [{source}] {headline}")
            if lede:
                lines.append(f"      {lede}")
        lines.append("")
    return "\n".join(lines).strip()


def _parse_llm_response(text: str, id_to_story: dict[int, dict]) -> dict[str, str]:
    """
    Parse LLM JSON response into {url: reason} dict.
    Returns empty dict on any parse failure.
    """
    # Strip markdown fences if model wrapped in ```json ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text.strip(), flags=re.MULTILINE)

    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError as e:
        logger.warning("LLM response JSON parse failed: %s — raw: %.200s", e, text)
        return {}

    if not isinstance(data, dict):
        logger.warning("LLM response was not a JSON object — raw: %.200s", text)
        return {}

    selections: dict[str, str] = {}
    for category, items in data.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            story_id = item.get("id")
            reason = str(item.get("reason", "")).strip()
            if story_id is not None and story_id in id_to_story:
                url = id_to_story[story_id].get("url", "")
                if url:
                    selections[url] = reason
    return selections


async def _call_curation_llm(user_message: str) -> str | None:
    """Call AI_MODEL with the curation prompt. Returns raw text or None on failure."""
    from src.llm import call_llm
    try:
        return await call_llm(
            _get_curation_prompt(),
            user_message,
            max_tokens=1024,
        )
    except Exception as e:
        logger.error("Curation LLM call failed: %s", e)
        return None


async def curate_news() -> int:
    """
    Read news.json, have AI select the most newsworthy stories per category,
    write selected stories back to news.json (with selected_reason field),
    write unselected stories to unselected_stories.json.
    Returns count of unselected stories.
    No-op (returns 0) if NEWS_CURATION_ENABLED is False.
    """
    if not NEWS_CURATION_ENABLED:
        return 0

    stories = load_news()
    if not stories:
        UNSELECTED_STORIES_FILE.write_text("[]")
        return 0

    current_hash = _input_hash(stories)
    cache = _load_cache()

    # Cache hit: same story pool and cache is fresher than one refresh interval
    if cache.get("input_hash") == current_hash:
        try:
            cached_at = datetime.fromisoformat(cache["curated_at"])
            age_seconds = (datetime.now(timezone.utc) - cached_at).total_seconds()
            if age_seconds < REFRESH_INTERVAL:
                selections: dict[str, str] = cache.get("selections", {})
                logger.info("Curation cache hit — reusing selection for unchanged story pool")
                return _apply_selections(stories, selections)
        except (KeyError, ValueError):
            pass

    # Build category → [(id, story)] mapping with sequential IDs
    stories_by_category: dict[str, list[tuple[int, dict]]] = {}
    id_to_story: dict[int, dict] = {}
    story_id = 1
    for story in stories:
        cat = story.get("category", "Uncategorized")
        stories_by_category.setdefault(cat, []).append((story_id, story))
        id_to_story[story_id] = story
        story_id += 1

    user_message = _build_prompt_message(stories_by_category)
    logger.info(
        "Curating %d stories across %d categories (model: %s)",
        len(stories), len(stories_by_category), AI_MODEL,
    )

    raw = await _call_curation_llm(user_message)
    if raw is None:
        logger.error("Curation failed — showing all %d stories", len(stories))
        UNSELECTED_STORIES_FILE.write_text("[]")
        return 0

    selections = _parse_llm_response(raw, id_to_story)
    if not selections:
        logger.error("Curation response could not be parsed — showing all %d stories", len(stories))
        UNSELECTED_STORIES_FILE.write_text("[]")
        return 0

    # Save to cache
    cache = {
        "input_hash": current_hash,
        "selections": selections,
        "curated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_cache(cache)

    return _apply_selections(stories, selections)


def _apply_selections(stories: list[dict], selections: dict[str, str]) -> int:
    """
    Partition stories into selected/unselected using the selections dict {url: reason}.
    Writes news.json and unselected_stories.json. Returns unselected count.
    """
    selected: list[dict] = []
    unselected: list[dict] = []

    for story in stories:
        url = story.get("url", "")
        if url in selections:
            selected.append({**story, "selected_reason": selections[url]})
        else:
            unselected.append(story)

    # Re-enforce per-category cap on selected stories (preserving AI's order)
    by_category: dict[str, list[dict]] = {}
    for s in selected:
        by_category.setdefault(s.get("category", ""), []).append(s)

    final_selected: list[dict] = []
    for cat_stories in by_category.values():
        final_selected.extend(cat_stories[:STORIES_PER_CATEGORY])

    logger.info(
        "Curation: %d selected from %d stories across %d categories, %d set aside",
        len(final_selected), len(stories), len(by_category), len(unselected),
    )

    NEWS_FILE.write_text(json.dumps(final_selected, indent=2, ensure_ascii=False))
    UNSELECTED_STORIES_FILE.write_text(json.dumps(unselected, indent=2, ensure_ascii=False))

    return len(unselected)
