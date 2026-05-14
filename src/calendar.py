"""Fetch and parse calendar events from iCal (.ics) feeds."""
import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from icalendar import Calendar

from src.config import DATA_DIR


def normalize_dt(dt) -> datetime:
    """Convert an icalendar date/datetime to a timezone-aware datetime."""
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    # If naive, assume UTC
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    # Convert to UTC
    return dt.astimezone(timezone.utc)


def is_today(dt: datetime, now: datetime) -> bool:
    """Check if a UTC datetime falls on the same local day as now."""
    # Compare using UTC date for simplicity
    return dt.date() == now.date()


def is_tomorrow(dt: datetime, now: datetime) -> bool:
    """Check if a UTC datetime falls on tomorrow (local day after now)."""
    return dt.date() == (now + timedelta(days=1)).date()


def extract_events(ical_text: str, target_date: date) -> list[dict]:
    """Extract events from ical text for a specific date."""
    cal = Calendar.from_ical(ical_text)
    events = []
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        
        dtstart = component.get("dtstart")
        dtend = component.get("dtend")
        summary = str(component.get("summary", ""))
        location = str(component.get("location", ""))
        description = str(component.get("description", ""))
        
        if not dtstart:
            continue
        
        start_dt = normalize_dt(dtstart.dt)
        end_dt = normalize_dt(dtend.dt) if dtend else None
        
        # Check if event is on target_date (using UTC date for simplicity)
        if start_dt.date() == target_date:
            events.append({
                "summary": summary,
                "start": start_dt,
                "end": end_dt,
                "location": location,
                "description": description,
            })
        # Also check recurring events that might span into today
        elif end_dt and start_dt.date() <= target_date <= end_dt.date():
            events.append({
                "summary": summary,
                "start": start_dt,
                "end": end_dt,
                "location": location,
                "description": description,
            })
    
    # Sort by start time
    events.sort(key=lambda e: e["start"])
    return events


async def fetch_calendar(url: str) -> str:
    """Fetch an .ics feed from a URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def load_calendar_urls() -> list[str]:
    """Load calendar URLs from .env file."""
    env_path = Path(__file__).parent.parent / ".env"
    urls = []
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or not line:
                    continue
                if "_CALENDAR_URL=" in line:
                    _, val = line.split("=", 1)
                    val = val.strip().strip('"\'')
                    if val and not val.startswith("TODO"):
                        urls.append(val)
    return urls


async def fetch_all_calendars() -> dict:
    """Fetch events from all configured calendars for today and tomorrow."""
    urls = load_calendar_urls()
    now = datetime.now(timezone.utc)
    today = now.date()
    tomorrow = (now + timedelta(days=1)).date()
    
    all_today = []
    all_tomorrow = []
    
    for url in urls:
        try:
            ical_text = await fetch_calendar(url)
            today_events = extract_events(ical_text, today)
            tomorrow_events = extract_events(ical_text, tomorrow)
            all_today.extend(today_events)
            all_tomorrow.extend(tomorrow_events)
        except Exception:
            # Skip failed calendars silently for now
            continue
    
    # Deduplicate and sort
    all_today.sort(key=lambda e: e["start"])
    all_tomorrow.sort(key=lambda e: e["start"])
    
    return {
        "today": all_today,
        "tomorrow": all_tomorrow,
        "fetched_at": now.isoformat(),
    }


async def refresh_calendar() -> dict:
    """Fetch fresh calendar data and save to disk."""
    data = await fetch_all_calendars()
    cal_file = DATA_DIR / "calendar.json"
    import json
    cal_file.write_text(json.dumps(data, indent=2, default=str))
    return data


def load_calendar() -> dict | None:
    """Load cached calendar data from disk."""
    import json
    cal_file = DATA_DIR / "calendar.json"
    if not cal_file.exists():
        return None
    try:
        return json.loads(cal_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None
