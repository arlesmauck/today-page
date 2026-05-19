"""Build the static index.html from template + live data."""
import json
from datetime import datetime, timezone
from itertools import groupby
from pathlib import Path

import jinja2

from src.config import BASE_DIR, DATA_DIR, LOCATION_NAME, TIMEZONE, REFRESH_INTERVAL, USER_NAME, PAGE_TITLE, AI_SUMMARY_ENABLED, CONTEXT_ENABLED, NEWS_CURATION_ENABLED
from src.fetcher import load_weather
from src.calendar import load_calendar
from src.news import load_news, news_categories


TEMPLATE_DIR = BASE_DIR / "src" / "templates"
OUTPUT_FILE = BASE_DIR / "src" / "static" / "index.html"


def format_time(dt_str: str) -> str:
    """Format an ISO datetime string as HH:MM AM/PM in the configured timezone."""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        local = dt.astimezone(TIMEZONE)
        return local.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return ""


def _time_of_day_greeting(now) -> str:
    hour = now.hour
    if hour < 12:
        return "Good Morning"
    elif hour < 17:
        return "Good Afternoon"
    else:
        return "Good Evening"


def build_page() -> str:
    """Fetch data and render the HTML page."""
    now = datetime.now(TIMEZONE)

    # Load weather
    weather = load_weather()
    current = weather.get("current", {}) if weather else {}
    daily = weather.get("daily", []) if weather else []
    temp_high = daily[0].get("temp_f") if daily else None

    # 5-day forecast: skip today (index 0), take next 5 days
    forecast = []
    for day in daily[1:6]:
        try:
            dt = datetime.fromisoformat(day["date"])
            day_name = dt.strftime("%a")
        except Exception:
            day_name = day.get("date", "")
        forecast.append({
            "day": day_name,
            "temp_f": round(day["temp_f"]) if day.get("temp_f") is not None else None,
            "desc": day.get("short_desc", ""),
        })

    # Load calendar
    cal = load_calendar()
    events_today = []
    events_tomorrow = []
    events_lookahead = []
    if cal:
        for ev in cal.get("today", []):
            events_today.append({
                "time": "All day" if ev.get("all_day") else format_time(ev["start"]),
                "summary": ev["summary"],
                "location": ev.get("location", ""),
            })

        for ev in cal.get("tomorrow", []):
            events_tomorrow.append({
                "time": "All day" if ev.get("all_day") else format_time(ev["start"]),
                "summary": ev["summary"],
                "location": ev.get("location", ""),
            })

        def _key(ev):
            return ev.get("_look_day", ""), ev.get("_look_day_name", "")

        grouped = []
        all_lookahead = cal.get("lookahead", [])
        sorted_events = sorted(all_lookahead, key=lambda e: (e.get("_look_day", ""), 0 if e.get("all_day") else 1, str(e.get("start", ""))))
        for (date_str, day_name), evs in groupby(sorted_events, key=_key):
            grouped.append({
                "day": day_name,
                "events": [
                    {
                        "time": "All day" if ev.get("all_day") else format_time(ev["start"]),
                        "summary": ev["summary"],
                        "location": ev.get("location", ""),
                    }
                    for ev in evs
                ]
            })

        # Limit to first 8 event instances for brevity
        total = sum(len(g["events"]) for g in grouped)
        if total > 8:
            trimmed = []
            count = 0
            for g in grouped:
                if count >= 8:
                    break
                remaining = 8 - count
                g["events"] = g["events"][:remaining]
                trimmed.append(g)
                count += len(g["events"])
            grouped = trimmed

        events_lookahead = grouped

    # Load news
    news = load_news()
    categories = news_categories()

    # Load unselected story count for curation badge
    unselected_count = 0
    if NEWS_CURATION_ENABLED:
        from src.news_curator import UNSELECTED_STORIES_FILE
        if UNSELECTED_STORIES_FILE.exists():
            try:
                unselected_count = len(json.loads(UNSELECTED_STORIES_FILE.read_text()))
            except (json.JSONDecodeError, OSError):
                pass

    # Render template
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("001.html")

    html = template.render(
        title=PAGE_TITLE,
        date_str=now.strftime("%A, %B %d, %Y"),
        greeting=f"{_time_of_day_greeting(now)}, {USER_NAME}",
        location=LOCATION_NAME,
        weather={
            "temp_f": current.get("temperature_f") or 62,
            "description": current.get("description") or "Mostly sunny",
            "temp_high": round(temp_high) if temp_high is not None else None,
            "wind_speed_mph": current.get("wind_speed_mph") or 8,
            "humidity": current.get("humidity") or 18,
        },
        forecast=forecast,
        events_today=events_today,
        events_tomorrow=events_tomorrow,
        events_lookahead=events_lookahead,
        news=news,
        news_categories=categories,
        updated_at=now.astimezone().strftime("%I:%M %p").lstrip("0"),
        refresh_interval_ms=REFRESH_INTERVAL * 1000,
        ai_summary_enabled=AI_SUMMARY_ENABLED,
        context_enabled=CONTEXT_ENABLED,
        curation_enabled=NEWS_CURATION_ENABLED,
        unselected_count=unselected_count,
    )

    return html


def write_page() -> None:
    """Build and write the page to disk."""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    html = build_page()
    OUTPUT_FILE.write_text(html)
    print(f"Page written to {OUTPUT_FILE}")


if __name__ == "__main__":
    write_page()
