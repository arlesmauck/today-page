"""FastAPI server for today-page dashboard."""
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.requests import Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import BASE_DIR, DATA_DIR, AI_SUMMARY_ENABLED, CONTEXT_ENABLED, NEWS_CURATION_ENABLED
from src.fetcher import load_weather, refresh_weather
from src.calendar import load_calendar
from src.news import load_news

app = FastAPI(title="Today Page", version="1.0.0")

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
        "curation_enabled": NEWS_CURATION_ENABLED,
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
    return {
        "status": "ok",
        "weather_cached": weather is not None,
        "fetched_at": weather.get("fetched_at") if weather else None,
    }
