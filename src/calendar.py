"""Fetch and parse calendar events from iCal (.ics) feeds."""
import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from icalendar import Calendar
from dateutil.rrule import rrule, WEEKLY, DAILY, MONTHLY, YEARLY

from src.config import DATA_DIR, TIMEZONE


def normalize_dt(dt) -> datetime:
    """Convert an icalendar date/datetime to a timezone-aware datetime in local time."""
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return datetime(dt.year, dt.month, dt.day, tzinfo=TIMEZONE)
    if dt is None:
        return datetime.min.replace(tzinfo=TIMEZONE)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TIMEZONE)
    # Convert to local timezone
    return dt.astimezone(TIMEZONE)


def _parse_exdates(component) -> set:
    """Extract exception dates from EXDATE properties."""
    exdates = set()
    raw = component.get("exdate")
    if raw is None:
        return exdates
    # EXDATE can be a single value or a list
    items = raw if isinstance(raw, list) else [raw]
    for item in items:
        # Each item is a vDDDLists containing one or more vDDDTypes
        for dt_obj in item.dts if hasattr(item, "dts") else [item]:
            val = dt_obj.dt
            if isinstance(val, datetime):
                exdates.add(val.date())
            elif isinstance(val, date):
                exdates.add(val)
    return exdates


def _expand_rrule(component, start: datetime, end: datetime | None) -> list[tuple[datetime, datetime | None]]:
    """Expand a recurring VEVENT into (start, end) instances within the requested range.

    Returns occurrences from start-7 days to end+7 days to catch events that
    span into the viewing window.
    """
    dtstart = component.get("dtstart")
    if not dtstart:
        return []

    dtstart_val = dtstart.dt
    rrule_prop = component.get("rrule")
    if not rrule_prop:
        # Non-recurring — handled separately
        return []

    # Parse dtstart timezone-aware
    if isinstance(dtstart_val, date) and not isinstance(dtstart_val, datetime):
        dtstart_naive = datetime(dtstart_val.year, dtstart_val.month, dtstart_val.day)
    else:
        dtstart_naive = dtstart_val

    # Ensure it's timezone-aware
    if isinstance(dtstart_naive, datetime):
        if dtstart_naive.tzinfo is None:
            dtstart_aware = dtstart_naive.replace(tzinfo=TIMEZONE)
        else:
            dtstart_aware = dtstart_naive.astimezone(TIMEZONE)
    else:
        dtstart_aware = datetime(
            dtstart_naive.year, dtstart_naive.month, dtstart_naive.day, tzinfo=TIMEZONE
        )

    # Map FREQ strings to dateutil constants
    freq_map = {
        "DAILY": DAILY,
        "WEEKLY": WEEKLY,
        "MONTHLY": MONTHLY,
        "YEARLY": YEARLY,
    }
    freq = freq_map.get(str(rrule_prop.get("FREQ", ["DAILY"])[0]).upper(), WEEKLY)

    # Parse UNTIL if present
    until = None
    until_vals = rrule_prop.get("UNTIL")
    if until_vals:
        until = until_vals[0]
        if isinstance(until, datetime):
            if until.tzinfo is None:
                until = until.replace(tzinfo=TIMEZONE)
            else:
                until = until.astimezone(TIMEZONE)
        elif isinstance(until, date):
            until = datetime(until.year, until.month, until.day, tzinfo=TIMEZONE)

    # Parse BYDAY / BYWEEKDAY
    byweekday = None
    byday = rrule_prop.get("BYDAY")
    if byday:
        # Convert BYDAY like SA, MO+1 to dateutil weekday constants
        from dateutil.rrule import MO, TU, WE, TH, FR, SA, SU

        weekday_map = {"MO": MO, "TU": TU, "WE": WE, "TH": TH, "FR": FR, "SA": SA, "SU": SU}
        days = []
        for d in byday:
            day_str = str(d)
            # Strip optional +/-n suffix like 1SU or MO
            base = ""
            for c in day_str:
                if c.isalpha():
                    base += c
            if base in weekday_map:
                days.append(weekday_map[base])
        if days:
            byweekday = days

    interval = rrule_prop.get("INTERVAL", [1])[0]
    count = rrule_prop.get("COUNT", [None])[0]

    # Build dateutil rrule — search window is expanded to catch multi-day events
    window_start = (start - timedelta(days=7)).replace(tzinfo=TIMEZONE)
    window_end = (end + timedelta(days=7)).replace(tzinfo=TIMEZONE) if end else None
    if window_end is None:
        window_end = (start + timedelta(days=30)).replace(tzinfo=TIMEZONE)

    # Apply UNTIL bound
    if until and (window_end is None or until < window_end):
        window_end = until

    kwargs = {
        "freq": freq,
        "dtstart": dtstart_aware,
        "interval": interval,
    }
    if byweekday:
        kwargs["byweekday"] = byweekday
    if count:
        kwargs["count"] = count
    if window_end:
        kwargs["until"] = window_end

    try:
        rule = rrule(**kwargs)
    except Exception:
        # If rrule construction fails, fall back to just dtstart
        return [(dtstart_aware, None)]

    # Get EXDATEs
    exdates = _parse_exdates(component)

    # Calculate duration from original dtstart/dtend
    duration = None
    dtend = component.get("dtend")
    if dtend:
        dtend_val = dtend.dt
        if isinstance(dtend_val, date) and not isinstance(dtend_val, datetime):
            dtend_aware = datetime(dtend_val.year, dtend_val.month, dtend_val.day, tzinfo=TIMEZONE)
        elif isinstance(dtend_val, datetime):
            if dtend_val.tzinfo is None:
                dtend_aware = dtend_val.replace(tzinfo=TIMEZONE)
            else:
                dtend_aware = dtend_val.astimezone(TIMEZONE)
        else:
            dtend_aware = None
        if dtend_aware:
            duration = dtend_aware - dtstart_aware
    else:
        duration = None

    # Generate occurrences within window
    occurrences = []
    for occ_start in rule.between(window_start, window_end, inc=True):
        # Skip exception dates
        if occ_start.date() in exdates:
            continue
        occ_end = (occ_start + duration) if duration else None
        occurrences.append((occ_start, occ_end))

    return occurrences


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

        start_value = dtstart.dt
        end_value = dtend.dt if dtend else None
        rrule_prop = component.get("rrule")

        # Detect all-day events: DTSTART is a date, not a datetime
        is_all_day = isinstance(start_value, date) and not isinstance(start_value, datetime)

        # Handle recurring events
        if rrule_prop and not is_all_day:
            # Build a datetime range for the target day
            day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=TIMEZONE)
            day_end = day_start + timedelta(days=1)

            for occ_start, occ_end in _expand_rrule(component, day_start, day_end):
                # Check if this occurrence falls on target_date (start or spans)
                if occ_start.date() == target_date:
                    events.append({
                        "summary": summary,
                        "start": occ_start,
                        "end": occ_end,
                        "location": location,
                        "description": description,
                        "all_day": False,
                        "all_day_date": None,
                    })
                elif occ_end and occ_start.date() <= target_date <= occ_end.date():
                    events.append({
                        "summary": summary,
                        "start": occ_start,
                        "end": occ_end,
                        "location": location,
                        "description": description,
                        "all_day": False,
                        "all_day_date": None,
                    })

            # Also handle all-day recurring events
            continue
        elif rrule_prop and is_all_day:
            # All-day recurring events
            day_start = datetime(
                target_date.year, target_date.month, target_date.day, tzinfo=TIMEZONE
            )
            day_end = day_start + timedelta(days=1)

            for occ_start, occ_end in _expand_rrule(component, day_start, day_end):
                # For all-day, compare dates
                occ_date = occ_start.date()
                occ_end_date = occ_end.date() if occ_end else occ_date

                if occ_date == target_date:
                    events.append({
                        "summary": summary,
                        "start": None,
                        "end": None,
                        "location": location,
                        "description": description,
                        "all_day": True,
                        "all_day_date": str(occ_date),
                    })
                elif occ_end_date and occ_date <= target_date < occ_end_date:
                    events.append({
                        "summary": summary,
                        "start": None,
                        "end": None,
                        "location": location,
                        "description": description,
                        "all_day": True,
                        "all_day_date": str(occ_date),
                    })
            continue

        # Non-recurring events below
        if is_all_day:
            # All-day events: compare raw dates, no timezone conversion
            if start_value == target_date:
                events.append({
                    "summary": summary,
                    "start": None,
                    "end": None,
                    "location": location,
                    "description": description,
                    "all_day": True,
                    "all_day_date": str(start_value),
                })
            # Multi-day all-day events spanning target date
            elif end_value and isinstance(end_value, date):
                if start_value <= target_date < end_value:
                    events.append({
                        "summary": summary,
                        "start": None,
                        "end": None,
                        "location": location,
                        "description": description,
                        "all_day": True,
                        "all_day_date": str(start_value),
                    })
        else:
            # Timed events: convert to timezone-aware datetime
            start_dt = normalize_dt(start_value)
            end_dt = normalize_dt(end_value) if end_value else None

            if start_dt.date() == target_date:
                events.append({
                    "summary": summary,
                    "start": start_dt,
                    "end": end_dt,
                    "location": location,
                    "description": description,
                    "all_day": False,
                    "all_day_date": None,
                })
            # Timed events that span across target date
            elif end_dt and start_dt.date() <= target_date <= end_dt.date():
                events.append({
                    "summary": summary,
                    "start": start_dt,
                    "end": end_dt,
                    "location": location,
                    "description": description,
                    "all_day": False,
                    "all_day_date": None,
                })

    # Sort: all-day events first, then timed events by start time
    events.sort(key=lambda e: (0 if e["all_day"] else 1, e["start"] or datetime.min.replace(tzinfo=TIMEZONE)))
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
    """Fetch events from all configured calendars for today and upcoming days."""
    urls = load_calendar_urls()
    now = datetime.now(TIMEZONE)
    today = now.date()
    tomorrow = (now + timedelta(days=1)).date()

    all_today = []
    all_tomorrow = []
    all_lookahead = []  # next 7 days after tomorrow

    for url in urls:
        try:
            ical_text = await fetch_calendar(url)
            today_events = extract_events(ical_text, today)
            tomorrow_events = extract_events(ical_text, tomorrow)
            all_today.extend(today_events)
            all_tomorrow.extend(tomorrow_events)

            # Look ahead: days 2-7 after today
            for offset in range(2, 8):
                look_date = (now + timedelta(days=offset)).date()
                look_events = extract_events(ical_text, look_date)
                for ev in look_events:
                    ev["_look_day"] = look_date
                    ev["_look_day_name"] = look_date.strftime("%A")
                all_lookahead.extend(look_events)
        except Exception as e:
            print(f"Error processing calendar {url}: {e}")
            continue

    # Sort: all-day events first, then timed events by start time
    all_today.sort(key=lambda e: (0 if e["all_day"] else 1, e["start"].isoformat() if e["start"] else ""))
    all_tomorrow.sort(key=lambda e: (0 if e["all_day"] else 1, e["start"].isoformat() if e["start"] else ""))
    all_lookahead.sort(key=lambda e: (e["_look_day"], 0 if e["all_day"] else 1, e["start"].isoformat() if e["start"] else ""))

    return {
        "today": all_today,
        "tomorrow": all_tomorrow,
        "lookahead": all_lookahead,
        "fetched_at": now.astimezone().isoformat(),
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
