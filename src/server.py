"""FastAPI server for today-page dashboard."""
import asyncio
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import (
    BASE_DIR, AI_SUMMARY_ENABLED, CONTEXT_ENABLED,
    LATITUDE, LONGITUDE, LOCATION_NAME, TIMEZONE_NAME, USER_NAME, PAGE_TITLE,
    NEWS_CURATION_ENABLED, CONTEXT_MAX_PER_REFRESH, STORIES_PER_CATEGORY, CLUSTER_THRESHOLD,
)
from src import app_settings
from src.app_settings import (
    SETTINGS_VERSION, get_news_curation_enabled, mask_secret_url,
    resolve_submitted_calendar_url,
)
from src.fetcher import load_weather, refresh_weather
from src.calendar import effective_calendars, load_calendar
from src.news import editable_feeds, load_news, news_categories
from src.builder import write_page
from src.scheduler import refresh_now

logger = logging.getLogger("server")

app = FastAPI(title="Today Page", version="1.0.0")

# Keep references to fire-and-forget refresh tasks so they aren't garbage-collected
_background_tasks: set[asyncio.Task] = set()

# Serve static files (HTML, JS, CSS)
static_dir = BASE_DIR / "src" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    """Serve the main dashboard page."""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file, headers={"Cache-Control": "no-store"})
    return {"message": "Today Page is running. Data is being fetched on first start.", "status": "starting"}


@app.get("/api/weather")
async def get_weather():
    """Return cached weather data."""
    data = load_weather()
    if data is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Weather data not available yet. Refresh in progress."}
        )
    return data


@app.post("/api/weather/refresh")
async def trigger_weather_refresh():
    """Manually trigger a weather refresh."""
    try:
        data = await refresh_weather()
        return {"status": "ok", "fetched_at": data.get("fetched_at")}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/api/calendar")
async def get_calendar():
    """Return cached calendar data."""
    data = load_calendar()
    if data is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Calendar data not available yet. Refresh in progress."}
        )
    return data


@app.get("/api/news")
async def get_news():
    """Return cached news stories."""
    return load_news()


@app.get("/api/config/prompts")
async def get_prompts():
    """Return active prompts and hardcoded defaults."""
    from src.ai_summarizer import SYSTEM_PROMPT, CONTEXT_SYSTEM_PROMPT, _load_prompts
    from src.news_curator import DEFAULT_CURATION_PROMPT
    from src.morning_briefer import DEFAULT_BRIEFING_PROMPT
    active = _load_prompts()
    return {
        "summary_prompt": active["summary_prompt"],
        "context_prompt": active["context_prompt"],
        "curation_prompt": active.get("curation_prompt") or DEFAULT_CURATION_PROMPT,
        "briefing_prompt": active.get("briefing_prompt") or DEFAULT_BRIEFING_PROMPT,
        "context_enabled": CONTEXT_ENABLED,
        "curation_enabled": get_news_curation_enabled(),
        "defaults": {
            "summary_prompt": SYSTEM_PROMPT,
            "context_prompt": CONTEXT_SYSTEM_PROMPT,
            "curation_prompt": DEFAULT_CURATION_PROMPT,
            "briefing_prompt": DEFAULT_BRIEFING_PROMPT,
        },
    }


@app.post("/api/config/prompts")
async def save_prompts(request: Request):
    """Persist custom prompts to data/prompts.json."""
    import json as _json
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})

    summary_prompt = body.get("summary_prompt", "").strip()
    context_prompt = body.get("context_prompt", "").strip()
    curation_prompt = body.get("curation_prompt", "").strip()
    briefing_prompt = body.get("briefing_prompt", "").strip()

    if not summary_prompt:
        return JSONResponse(status_code=422, content={"error": "summary_prompt must not be empty"})

    from src.ai_summarizer import PROMPTS_FILE
    data: dict = {"summary_prompt": summary_prompt}
    if context_prompt:
        data["context_prompt"] = context_prompt
    if curation_prompt:
        data["curation_prompt"] = curation_prompt
    if briefing_prompt:
        data["briefing_prompt"] = briefing_prompt
    PROMPTS_FILE.write_text(_json.dumps(data, indent=2, ensure_ascii=False))
    return {"status": "saved"}


@app.delete("/api/config/prompts")
async def reset_prompts():
    """Delete custom prompts file, reverting to hardcoded defaults."""
    from src.ai_summarizer import PROMPTS_FILE
    if PROMPTS_FILE.exists():
        PROMPTS_FILE.unlink()
    return {"status": "reset"}


# ── General app settings (data/settings.json) ────────────────────────────────

_KNOWN_CATEGORIES = ["World", "Technology", "Science", "Health", "US", "Local"]


@app.get("/api/config/settings")
async def get_app_settings():
    """Return effective app settings plus env-only defaults for the UI reset button.

    Calendar URLs are returned masked (write-only) — the client sends the
    mask back unchanged, or a new full URL to replace it.
    """
    feeds = editable_feeds()
    # Ordered unique categories: current feeds first, then known defaults
    feed_categories: list[str] = []
    for cat in [f["category"] for f in feeds] + _KNOWN_CATEGORIES:
        if cat not in feed_categories:
            feed_categories.append(cat)

    return {
        "is_custom": app_settings.settings_exist(),
        "user_name": app_settings.get_user_name(),
        "page_title": app_settings.get_page_title(),
        "location_name": app_settings.get_location_name(),
        "latitude": app_settings.get_latitude(),
        "longitude": app_settings.get_longitude(),
        "timezone": app_settings.get_timezone_name(),
        "calendars": [
            {"label": c["label"], "url": mask_secret_url(c["url"])}
            for c in effective_calendars()
        ],
        "feeds": feeds,
        "feed_categories": feed_categories,
        "news_curation_enabled": app_settings.get_news_curation_enabled(),
        "quality_gates": {
            cat: app_settings.get_quality_gate(cat) for cat in feed_categories
        },
        "context_max_per_refresh": app_settings.get_context_max_per_refresh(),
        "stories_per_category": app_settings.get_stories_per_category(),
        "cluster_threshold": app_settings.get_cluster_threshold(),
        "context_enabled": CONTEXT_ENABLED,
        "ai_summary_enabled": AI_SUMMARY_ENABLED,
        "env_defaults": {
            "user_name": USER_NAME,
            "page_title": PAGE_TITLE,
            "location_name": LOCATION_NAME,
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "timezone": TIMEZONE_NAME,
            "news_curation_enabled": NEWS_CURATION_ENABLED,
            "context_max_per_refresh": CONTEXT_MAX_PER_REFRESH,
            "stories_per_category": STORIES_PER_CATEGORY,
            "cluster_threshold": CLUSTER_THRESHOLD,
        },
    }


def _validate_settings(body: dict) -> tuple[dict | None, str]:
    """Validate a settings payload. Returns (cleaned, error) — error empty on success."""
    errors: list[str] = []

    def _text(key: str, label: str) -> str:
        val = str(body.get(key, "") or "").strip()
        if not val:
            errors.append(f"{label} is required")
        return val

    def _float(key: str, label: str, lo: float, hi: float) -> float | None:
        try:
            val = float(body.get(key))
        except (TypeError, ValueError):
            errors.append(f"{label} must be a number")
            return None
        if not (lo <= val <= hi):
            errors.append(f"{label} must be between {lo} and {hi}")
            return None
        return val

    def _int(key: str, label: str, lo: int, hi: int) -> int | None:
        try:
            val = int(float(body.get(key)))
        except (TypeError, ValueError):
            errors.append(f"{label} must be a whole number")
            return None
        if not (lo <= val <= hi):
            errors.append(f"{label} must be between {lo} and {hi}")
            return None
        return val

    user_name = _text("user_name", "Your name")
    page_title = _text("page_title", "Page title")
    location_name = _text("location_name", "Location name")
    latitude = _float("latitude", "Latitude", -90, 90)
    longitude = _float("longitude", "Longitude", -180, 180)

    timezone_name = _text("timezone", "Timezone")
    if timezone_name:
        try:
            ZoneInfo(timezone_name)
        except Exception:
            errors.append(f"Timezone {timezone_name!r} is not a valid IANA timezone")

    # Feeds: drop empty rows, require category + http(s) URL
    cleaned_feeds: list[dict] = []
    feeds_raw = body.get("feeds")
    if feeds_raw is None:
        feeds_raw = []
    if not isinstance(feeds_raw, list):
        errors.append("Feeds must be a list")
    else:
        for i, feed in enumerate(feeds_raw, 1):
            if not isinstance(feed, dict):
                continue
            category = str(feed.get("category", "") or "").strip()
            url = str(feed.get("url", "") or "").strip()
            label = str(feed.get("label", "") or "").strip()
            if not category and not url:
                continue  # empty row
            if not category:
                errors.append(f"Feed {i}: category is required")
                continue
            if len(category) > 40:
                errors.append(f"Feed {i}: category name too long (max 40 characters)")
                continue
            if not url.startswith(("http://", "https://")):
                errors.append(f"Feed {i} ({category}): URL must start with http:// or https://")
                continue
            cleaned_feeds.append({"category": category, "label": label, "url": url})

    # Calendars: masks mean "unchanged", anything else must be a full http(s) URL
    cleaned_calendars: list[dict] = []
    calendars_raw = body.get("calendars")
    if calendars_raw is None:
        calendars_raw = []
    if not isinstance(calendars_raw, list):
        errors.append("Calendars must be a list")
    else:
        existing = effective_calendars()
        for i, cal in enumerate(calendars_raw, 1):
            if not isinstance(cal, dict):
                continue
            label = str(cal.get("label", "") or "").strip() or "Calendar"
            submitted = str(cal.get("url", "") or "").strip()
            if not submitted:
                continue  # empty row
            resolved = resolve_submitted_calendar_url(submitted, existing)
            if resolved is None:
                errors.append(
                    f"Calendar {i} ({label}): saved URL no longer matches — re-enter the full URL"
                )
                continue
            if not resolved.startswith(("http://", "https://")):
                errors.append(f"Calendar {i} ({label}): URL must start with http:// or https://")
                continue
            cleaned_calendars.append({"label": label, "url": resolved})

    curation_enabled = bool(body.get("news_curation_enabled"))

    cleaned_gates: dict[str, str] = {}
    gates_raw = body.get("quality_gates")
    if gates_raw is None:
        gates_raw = {}
    if not isinstance(gates_raw, dict):
        errors.append("Quality gates must be an object")
    else:
        for cat, val in gates_raw.items():
            v = str(val).lower().strip()
            if v in ("strict", "relaxed"):
                cleaned_gates[str(cat)] = v
            else:
                errors.append(f"Quality gate for {cat} must be 'strict' or 'relaxed'")

    # Numeric fields fall back to their effective value when omitted — the UI
    # leaves out context_max_per_refresh entirely when context is disabled.
    def _int_or_default(key: str, label: str, lo: int, hi: int, default: int) -> int:
        raw = body.get(key)
        if raw is None or str(raw).strip() == "":
            return default
        val = _int(key, label, lo, hi)
        return val if val is not None else default

    context_max = _int_or_default(
        "context_max_per_refresh", "Context call cap", 0, 100,
        app_settings.get_context_max_per_refresh(),
    )
    stories_per = _int_or_default(
        "stories_per_category", "Stories per category", 1, 20,
        app_settings.get_stories_per_category(),
    )

    cluster_raw = body.get("cluster_threshold")
    if cluster_raw is None or str(cluster_raw).strip() == "":
        cluster_threshold = app_settings.get_cluster_threshold()
    else:
        try:
            cluster_threshold = float(cluster_raw)
            if not (0 <= cluster_threshold <= 1):
                raise ValueError
        except (TypeError, ValueError):
            errors.append("Cluster threshold must be a number between 0 and 1")
            cluster_threshold = app_settings.get_cluster_threshold()

    if errors:
        return None, "; ".join(errors)

    return {
        "version": SETTINGS_VERSION,
        "user_name": user_name,
        "page_title": page_title,
        "location_name": location_name,
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone_name,
        "calendars": cleaned_calendars,
        "feeds": cleaned_feeds,
        "news_curation_enabled": curation_enabled,
        "quality_gates": cleaned_gates,
        "context_max_per_refresh": context_max,
        "stories_per_category": stories_per,
        "cluster_threshold": cluster_threshold,
    }, ""


def _pool_signature(s: dict) -> tuple:
    """The parts of a settings dict that determine what data gets fetched.
    Feed labels are display-only and deliberately excluded."""
    feeds = s.get("feeds") or []
    return (
        s.get("location_name"),
        s.get("latitude"),
        s.get("longitude"),
        s.get("timezone"),
        s.get("stories_per_category"),
        sorted((f.get("category"), f.get("url")) for f in feeds if isinstance(f, dict)),
    )


@app.post("/api/config/settings")
async def save_app_settings(request: Request):
    """Validate and persist app settings to data/settings.json."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={"error": "Settings must be a JSON object"})

    cleaned, error = _validate_settings(body)
    if error:
        return JSONResponse(status_code=422, content={"error": error})

    # Re-fetch the world only when something that changes the data pool changed
    previous = app_settings.load_settings()
    pool_changed = _pool_signature(previous) != _pool_signature(cleaned)

    app_settings.save_settings(cleaned)
    logger.info("App settings saved via settings UI (refresh_triggered=%s)", pool_changed)

    # Personalization changes show up immediately; data follows via the background refresh
    try:
        write_page()
    except Exception as e:
        logger.error("Page rebuild after settings save failed: %s", e)

    if pool_changed:
        task = asyncio.create_task(refresh_now("Settings"))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    return {"status": "saved", "refresh_triggered": pool_changed}


@app.delete("/api/config/settings")
async def reset_app_settings():
    """Delete settings.json, reverting every setting to its env default."""
    deleted = app_settings.delete_settings()
    logger.info("App settings reverted to env defaults (file existed: %s)", deleted)
    try:
        write_page()
    except Exception as e:
        logger.error("Page rebuild after settings reset failed: %s", e)
    return {"status": "reset", "deleted": deleted}


@app.get("/api/story/summarize")
async def summarize_story(
    url: str = Query(..., description="Article URL"),
    headline: str = Query(..., description="Story headline"),
    lede: str = Query("", description="RSS lede as fallback input"),
):
    """Summarize a story on demand. Cache-first; calls LLM only on cache miss."""
    if not AI_SUMMARY_ENABLED:
        return JSONResponse(status_code=503, content={"error": "AI summarization not configured"})
    from src.ai_summarizer import summarize_on_demand
    try:
        result = await summarize_on_demand(url, headline, lede)
        if not result.get("brief"):
            return JSONResponse(status_code=422, content={"error": "Could not summarize this story"})
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    weather = load_weather()
    calendar = load_calendar()
    news = load_news()
    return {
        "status": "ok",
        "weather_cached": weather is not None,
        "calendar_cached": calendar is not None,
        "news_cached": len(news) > 0,
        "news_count": len(news),
        "fetched_at": weather.get("fetched_at") if weather else None,
    }
