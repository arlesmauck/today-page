"""FastAPI server for today-page dashboard."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import BASE_DIR, DATA_DIR
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
        return FileResponse(index_file)
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


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    weather = load_weather()
    return {
        "status": "ok",
        "weather_cached": weather is not None,
        "fetched_at": weather.get("fetched_at") if weather else None,
    }
