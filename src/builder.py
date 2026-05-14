"""Build the static index.html from template + live data."""
import json
from datetime import datetime, timezone
from pathlib import Path

import jinja2

from src.config import BASE_DIR, DATA_DIR, LOCATION_NAME
from src.fetcher import load_weather
from src.calendar import load_calendar


TEMPLATE_DIR = BASE_DIR / "src" / "templates"
OUTPUT_FILE = BASE_DIR / "index.html"


def format_time(dt_str: str) -> str:
    """Format an ISO datetime string as HH:MM AM/PM."""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return ""


def build_page() -> str:
    """Fetch data and render the HTML page."""
    now = datetime.now(timezone.utc)
    
    # Load weather
    weather = load_weather()
    current = weather.get("current", {}) if weather else {}
    
    cal = load_calendar()
    events_today = []
    events_lookahead = []
    if cal:
        for ev in cal.get("today", []):
            events_today.append({
                "time": "All day" if ev.get("all_day") else format_time(ev["start"]),
                "summary": ev["summary"],
                "location": ev.get("location", ""),
            })
        for ev in cal.get("lookahead", [])[:8]:
            events_lookahead.append({
                "day": ev.get("_look_day_name", ""),
                "time": "All day" if ev.get("all_day") else format_time(ev["start"]),
                "summary": ev["summary"],
                "location": ev.get("location", ""),
            })
    
    # Static news for now (placeholder)
    news = [
        {
            "source": "Reuters",
            "when": "2 hours ago",
            "headline": "House Passes Revised Aerospace Funding Bill",
            "lede": "Bipartisan support for a $28 billion package focused on small satellite launch infrastructure.",
        },
        {
            "source": "AP News",
            "when": "4 hours ago",
            "headline": "NOAA Forecasts Quieter-Than-Average Hurricane Season",
            "lede": "Forecasters predict 11 named storms, below the 14-storm average.",
        },
    ]
    
    # Render template
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("001.html")
    
    html = template.render(
        title="Your Morning Paper",
        date_str=now.strftime("%A, %B %d, %Y"),
        greeting="Good Morning, Arles",
        location=LOCATION_NAME,
        weather={
            "temp_f": current.get("temperature_f") or 62,
            "description": current.get("description") or "Mostly sunny",
            "temp_high": 78,
            "wind_speed_mph": current.get("wind_speed_mph") or 8,
            "humidity": current.get("humidity") or 18,
        },
        events_today=events_today,
        events_lookahead=events_lookahead,
        news=news,
        updated_at=now.astimezone().strftime("%I:%M %p").lstrip("0"),
    )
    
    return html


def write_page() -> None:
    """Build and write the page to disk."""
    html = build_page()
    OUTPUT_FILE.write_text(html)
    print(f"Page written to {OUTPUT_FILE}")


if __name__ == "__main__":
    write_page()
