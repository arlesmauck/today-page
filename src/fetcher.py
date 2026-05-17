"""Fetch and cache weather data from Open-Meteo (free, global, no API key)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.config import DATA_DIR, LATITUDE, LONGITUDE, LOCATION_NAME, TIMEZONE_NAME


WEATHER_FILE = DATA_DIR / "weather.json"
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

# WMO Weather interpretation codes → human-readable description
WMO_DESCRIPTIONS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Icy fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight showers",
    81: "Moderate showers",
    82: "Heavy showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


def _wmo_desc(code: int | None) -> str:
    if code is None:
        return "Unknown"
    return WMO_DESCRIPTIONS.get(int(code), f"Weather code {code}")


async def fetch_weather() -> dict:
    """Fetch current conditions and forecast from Open-Meteo."""
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": "temperature_2m_max,weather_code",
        "wind_speed_unit": "mph",
        "temperature_unit": "fahrenheit",
        "timezone": TIMEZONE_NAME,
        "forecast_days": 7,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(OPEN_METEO_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()

    current = data.get("current", {})
    hourly = data.get("hourly", {})
    daily = data.get("daily", {})

    current_out = {
        "temperature_f": current.get("temperature_2m"),
        "humidity": current.get("relative_humidity_2m"),
        "wind_speed_mph": current.get("wind_speed_10m"),
        "description": _wmo_desc(current.get("weather_code")),
    }

    # Daily forecast (7 days)
    daily_times = daily.get("time", [])
    daily_max = daily.get("temperature_2m_max", [])
    daily_codes = daily.get("weather_code", [])
    daily_forecast = []
    for i, t in enumerate(daily_times):
        daily_forecast.append({
            "date": t,
            "temp_f": daily_max[i] if i < len(daily_max) else None,
            "short_desc": _wmo_desc(daily_codes[i] if i < len(daily_codes) else None),
            "is_daytime": True,
        })

    # Hourly forecast (next 24 hours)
    hourly_times = hourly.get("time", [])
    hourly_temps = hourly.get("temperature_2m", [])
    hourly_precip = hourly.get("precipitation_probability", [])
    hourly_codes = hourly.get("weather_code", [])
    hourly_forecast = []
    for i in range(min(24, len(hourly_times))):
        hourly_forecast.append({
            "time": hourly_times[i],
            "temp_f": hourly_temps[i] if i < len(hourly_temps) else None,
            "short_desc": _wmo_desc(hourly_codes[i] if i < len(hourly_codes) else None),
            "precip_chance": hourly_precip[i] if i < len(hourly_precip) else None,
        })

    return {
        "location": LOCATION_NAME,
        "lat": LATITUDE,
        "lon": LONGITUDE,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "current": current_out,
        "daily": daily_forecast,
        "hourly": hourly_forecast,
    }


async def refresh_weather() -> dict:
    """Fetch fresh weather and save to disk."""
    data = await fetch_weather()
    WEATHER_FILE.write_text(json.dumps(data, indent=2))
    return data


def load_weather() -> dict | None:
    """Load cached weather from disk."""
    if not WEATHER_FILE.exists():
        return None
    try:
        return json.loads(WEATHER_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None
