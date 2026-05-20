"""Generate a prose morning briefing paragraph from the day's top stories."""
import hashlib
import json
import logging
import re
from datetime import datetime, timezone

import litellm

from src.config import AI_MODEL, AI_API_KEY, AI_API_BASE, AI_SUMMARY_ENABLED, DATA_DIR
from src.news import load_news

logger = logging.getLogger("morning_briefer")

BRIEFING_FILE = DATA_DIR / "morning_briefing.json"

# Step 1: select the most significant stories from the full pool
DEFAULT_SELECTION_PROMPT = """\
You are an editor choosing which stories deserve attention in a morning briefing.
From the numbered list below, select the 3-5 most genuinely significant stories of the day.
Judge by real-world impact, not novelty or shock value. Prefer stories with clear facts \
over vague claims.
Respond with a JSON array of the story numbers you selected. Example: [1, 4, 7]
Nothing else — just the JSON array."""

# Step 2: write the briefing from the selected stories only
DEFAULT_BRIEFING_PROMPT = """\
You are writing the opening of a personal morning news briefing.
For each story below, write one clear factual sentence covering what happened. \
Do not invent connections between unrelated stories. \
Do not use filler phrases ("In today's news…", "Meanwhile…"). \
Do not start with "Today". Do not use bullet points.
If two stories are genuinely connected, you may note that in a sentence. \
Otherwise treat each on its own terms.
Output only the sentences, nothing else."""

# How many candidate stories to pass to the selection step
_MAX_CANDIDATES = 15


def _get_selection_prompt() -> str:
    try:
        from src.ai_summarizer import _load_prompts
        return _load_prompts().get("selection_prompt") or DEFAULT_SELECTION_PROMPT
    except Exception:
        return DEFAULT_SELECTION_PROMPT


def _get_briefing_prompt() -> str:
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


def _build_candidate_message(stories: list[dict]) -> str:
    """Number all stories for the selection step."""
    lines = []
    for i, s in enumerate(stories, 1):
        headline = s.get("headline", "")
        lede = s.get("lede", "")
        source = s.get("source", "")
        cat = s.get("category", "")
        line = f"{i}. [{cat} / {source}] {headline}"
        if lede:
            line += f"\n   {lede[:150]}"
        lines.append(line)
    return "\n\n".join(lines)


async def _llm_call(system: str, user: str, max_tokens: int) -> str | None:
    """Single LLM call. Returns raw text or None on failure."""
    kwargs: dict = {
        "model": AI_MODEL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if AI_API_KEY:
        kwargs["api_key"] = AI_API_KEY
    if AI_API_BASE:
        kwargs["api_base"] = AI_API_BASE
    try:
        response = await litellm.acompletion(**kwargs)
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return None


async def _select_stories(candidates: list[dict]) -> list[dict]:
    """
    Ask LLM to pick the 3-5 most significant stories from the candidate pool.
    Returns the selected story dicts. Falls back to first 5 on any failure.
    """
    user_message = _build_candidate_message(candidates)
    raw = await _llm_call(_get_selection_prompt(), user_message, max_tokens=64)

    if not raw:
        logger.warning("Story selection LLM call failed — using first 5 candidates")
        return candidates[:5]

    # Strip markdown fences if present
    raw = re.sub(r"^```[^\n]*\n?", "", raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw.strip())

    try:
        indices = json.loads(raw.strip())
        if not isinstance(indices, list):
            raise ValueError("not a list")
        selected = []
        for idx in indices:
            if isinstance(idx, int) and 1 <= idx <= len(candidates):
                selected.append(candidates[idx - 1])
        if selected:
            logger.info("Story selection: chose %d from %d candidates: %s",
                        len(selected), len(candidates), indices)
            return selected
    except Exception as e:
        logger.warning("Story selection parse failed (%s) — raw: %.100s", e, raw)

    return candidates[:5]


async def generate_briefing() -> str | None:
    """
    Two-step process:
      1. LLM selects the most significant stories from the full pool.
      2. LLM writes a briefing sentence per selected story.
    Cache-first: same story pool → same result, no LLM calls.
    Returns briefing text, or None on error / no stories.
    No-op if AI_SUMMARY_ENABLED is False.
    """
    if not AI_SUMMARY_ENABLED:
        return None

    all_stories = load_news()
    if not all_stories:
        return None

    candidates = all_stories[:_MAX_CANDIDATES]
    current_hash = _input_hash(candidates)

    cache = _load_cache()
    if cache.get("input_hash") == current_hash and cache.get("briefing"):
        logger.debug("Morning briefing cache hit — skipping LLM calls")
        return cache["briefing"]

    # Step 1: select top stories
    selected = await _select_stories(candidates)
    if not selected:
        return None

    # Step 2: write briefing from selected stories only
    lines = []
    for s in selected:
        cat = s.get("category", "")
        headline = s.get("headline", "")
        lede = s.get("lede", "")
        line = f"{cat}: {headline}"
        if lede:
            line += f"\n  {lede}"
        lines.append(line)
    user_message = "\n\n".join(lines)

    briefing = await _llm_call(_get_briefing_prompt(), user_message, max_tokens=300)
    if not briefing:
        return None

    BRIEFING_FILE.write_text(json.dumps({
        "input_hash": current_hash,
        "briefing": briefing,
        "selected_headlines": [s.get("headline", "") for s in selected],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2, ensure_ascii=False))

    logger.info("Morning briefing generated (%d chars) from %d selected stories",
                len(briefing), len(selected))
    return briefing
