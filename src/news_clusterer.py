"""Story clustering — detect duplicate-coverage events and synthesize a merged lede."""
import hashlib
import json
import logging
import re
from datetime import datetime, timezone

import litellm

from src.config import AI_MODEL, AI_API_KEY, AI_API_BASE, AI_SUMMARY_ENABLED, DATA_DIR
from src.news import NEWS_FILE, load_news

logger = logging.getLogger("news_clusterer")

CLUSTER_CACHE_FILE = DATA_DIR / "cluster_cache.json"
CLUSTER_THRESHOLD = 0.3  # Jaccard similarity threshold

SYNTHESIS_SYSTEM_PROMPT = (
    "Multiple news sources covered the same story. "
    "Write a single concise summary (2-3 sentences) combining the most important facts "
    "from all versions. Include specific details that appear in multiple sources. "
    "Factual, no editorializing. Output only the summary sentences, nothing else."
)

_STOP = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
    "is", "are", "was", "were", "has", "have", "it", "its", "that", "this",
    "with", "as", "by", "from", "new", "says", "say", "after", "over", "us",
    "its", "their", "will", "but", "not", "be", "been", "had", "he", "she",
    "they", "who", "what", "than", "up", "out", "into", "about", "would",
}

# Google News redirect domains — prefer other sources as cluster representative
_GNEWS_DOMAINS = {"news.google.com", "google.com"}


def _sig_words(headline: str) -> set[str]:
    words = re.findall(r"\b\w{3,}\b", headline.lower())
    return {w for w in words if w not in _STOP}


def _jaccard(h1: str, h2: str) -> float:
    w1, w2 = _sig_words(h1), _sig_words(h2)
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / len(w1 | w2)


def _is_gnews(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc in _GNEWS_DOMAINS
    except Exception:
        return False


def _cluster_hash(stories: list[dict]) -> str:
    urls = sorted(s.get("url", "") for s in stories)
    return hashlib.sha256(json.dumps(urls).encode()).hexdigest()[:16]


def _load_cache() -> dict:
    if not CLUSTER_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CLUSTER_CACHE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    CLUSTER_CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def _detect_clusters(stories: list[dict]) -> list[list[dict]]:
    """
    Group stories that cover the same event using Jaccard similarity on headlines.
    Returns a list of clusters; each cluster is a list of story dicts.
    Solo stories are clusters of length 1.
    """
    assigned = [False] * len(stories)
    clusters: list[list[dict]] = []

    for i, story in enumerate(stories):
        if assigned[i]:
            continue
        cluster = [story]
        assigned[i] = True
        for j in range(i + 1, len(stories)):
            if assigned[j]:
                continue
            if _jaccard(story["headline"], stories[j]["headline"]) >= CLUSTER_THRESHOLD:
                cluster.append(stories[j])
                assigned[j] = True
        clusters.append(cluster)

    return clusters


def _pick_representative(cluster: list[dict]) -> dict:
    """Choose the best story as the cluster representative (prefer non-Google-News sources)."""
    non_gnews = [s for s in cluster if not _is_gnews(s.get("url", ""))]
    return (non_gnews or cluster)[0]


async def _synthesize_cluster(cluster: list[dict], cache: dict) -> dict:
    """
    For a multi-story cluster, call LLM to synthesize a merged lede.
    Cache-first: same cluster URLs → return cached synthesis.
    On failure, return the representative story unchanged.
    """
    cluster_key = _cluster_hash(cluster)
    rep = _pick_representative(cluster)

    # Cache hit
    if cluster_key in cache:
        cached = cache[cluster_key]
        sources = " · ".join(s["source"] for s in cluster)
        return {
            **rep,
            "lede": cached["lede"],
            "source": sources,
            "synthesized": True,
        }

    # Build user message
    lines = []
    for s in cluster:
        lines.append(f"[{s['source']}] {s['headline']}")
        if s.get("lede"):
            lines.append(s["lede"])
        lines.append("")
    user_message = "\n".join(lines).strip()

    kwargs: dict = {
        "model": AI_MODEL,
        "max_tokens": 256,
        "messages": [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    }
    if AI_API_KEY:
        kwargs["api_key"] = AI_API_KEY
    if AI_API_BASE:
        kwargs["api_base"] = AI_API_BASE

    try:
        response = await litellm.acompletion(**kwargs)
        synthesized_lede = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("Synthesis LLM call failed for cluster %r: %s", rep.get("headline", "")[:60], e)
        return rep

    # Save to cache
    cache[cluster_key] = {
        "lede": synthesized_lede,
        "sources": [s["source"] for s in cluster],
        "synthesized_at": datetime.now(timezone.utc).isoformat(),
    }

    sources = " · ".join(s["source"] for s in cluster)
    return {
        **rep,
        "lede": synthesized_lede,
        "source": sources,
        "synthesized": True,
    }


async def cluster_news() -> int:
    """
    Read news.json, detect same-event clusters per category, synthesize merged stories.
    Writes result back to news.json.
    Returns number of stories merged (removed from display).
    No-op if AI_SUMMARY_ENABLED is False.
    """
    if not AI_SUMMARY_ENABLED:
        return 0

    stories = load_news()
    if not stories:
        return 0

    # Group by category
    by_category: dict[str, list[dict]] = {}
    for story in stories:
        cat = story.get("category", "")
        by_category.setdefault(cat, []).append(story)

    cache = _load_cache()
    final_stories: list[dict] = []
    total_merged = 0

    for cat, cat_stories in by_category.items():
        clusters = _detect_clusters(cat_stories)
        multi = [c for c in clusters if len(c) > 1]
        logger.debug("Category %r: %d stories → %d clusters (%d multi-source)", cat, len(cat_stories), len(clusters), len(multi))

        for cluster in clusters:
            if len(cluster) == 1:
                final_stories.append(cluster[0])
            else:
                merged = await _synthesize_cluster(cluster, cache)
                final_stories.append(merged)
                total_merged += len(cluster) - 1

    _save_cache(cache)
    NEWS_FILE.write_text(json.dumps(final_stories, indent=2, ensure_ascii=False))
    logger.info("Clustering: %d stories merged into clusters", total_merged)
    return total_merged
