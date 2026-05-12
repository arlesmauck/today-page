"""Fetch and cache weather data from the National Weather Service."""
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.config import DATA_DIR, LATITUDE, LONGITUDE, LOCATION_NAME


WEATHER_FILE = DATA_DIR / "weather.json"
NWS_BASE = "https://api.weather.gov"
USER_AGENT = "today-page/1.0 (personal dashboard)"

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/geo+json",
}


async def fetch_json(client: httpx.AsyncClient, url: str) -> dict:
    """Fetch JSON from a URL with error handling."""
    resp = await client.get(url, headers=HEADERS, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


async def fetch_weather() -> dict:
    """Fetch current conditions and forecast from NWS."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Get gridpoint info for our lat/lon
        points_url = f"{NWS_BASE}/points/{LATITUDE},{LONGITUDE}"
        points_data = await fetch_json(client, points_url)
        
        props = points_data.get("properties", {})
        grid_id = props.get("gridId")
        grid_x = props.get("gridX")
        grid_y = props.get("gridY")
        
        if not all([grid_id, grid_x, grid_y]):
            raise ValueError(f"Could not resolve gridpoint for {LATITUDE},{LONGITUDE}")
        
        # Step 2: Get current conditions from nearest station
        stations_url = props.get("observationStations")
        current = {}
        if stations_url:
            stations_data = await fetch_json(client, stations_url)
            stations = stations_data.get("features", [])
            if stations:
                station_id = stations[0]["properties"]["stationIdentifier"]
                obs_url = f"{NWS_BASE}/stations/{station_id}/observations/latest"
                try:
                    obs_data = await fetch_json(client, obs_url)
                    obs_props = obs_data.get("properties", {})
                    current = {
                        "temperature_c": obs_props.get("temperature", {}).get("value"),
                        "temperature_f": _c_to_f(obs_props.get("temperature", {}).get("value")),
                        "humidity": _safe_percent(obs_props.get("relativeHumidity", {}).get("value")),
                        "wind_speed_mph": _safe_mph(obs_props.get("windSpeed", {}).get("value")),
                        "wind_direction": obs_props.get("windDirection", {}).get("value"),
                        "description": obs_props.get("textDescription", ""),
                        "station_id": station_id,
                    }
                except Exception:
                    pass  # Fall back to forecast if current obs fails
        
        # Step 3: Get forecast
        forecast_url = f"{NWS_BASE}/gridpoints/{grid_id}/{grid_x},{grid_y}/forecast"
        forecast_data = await fetch_json(client, forecast_url)
        forecast_props = forecast_data.get("properties", {})
        periods = forecast_props.get("periods", [])
        
        # Step 4: Get hourly forecast
        hourly_url = f"{NWS_BASE}/gridpoints/{grid_id}/{grid_x},{grid_y}/forecast/hourly"
        hourly_data = await fetch_json(client, hourly_url)
        hourly_props = hourly_data.get("properties", {})
        hourly_periods = hourly_props.get("periods", [])
        
        # Build forecast list
        daily_forecast = []
        for p in periods[:7]:
            daily_forecast.append({
                "name": p.get("name", ""),
                "temp_f": p.get("temperature"),
                "short_desc": p.get("shortForecast", ""),
                "detailed": p.get("detailedForecast", ""),
                "is_daytime": p.get("isDaytime", True),
            })
        
        hourly_forecast = []
        for p in hourly_periods[:24]:
            hourly_forecast.append({
                "time": p.get("startTime", ""),
                "temp_f": p.get("temperature"),
                "short_desc": p.get("shortForecast", ""),
                "precip_chance": p.get("probabilityOfPrecipitation", {}).get("value"),
            })
        
        # If we couldn't get current conditions, use the first hourly period
        if not current and hourly_periods:
            p = hourly_periods[0]
            current = {
                "temperature_f": p.get("temperature"),
                "description": p.get("shortForecast", ""),
                "humidity": None,
                "wind_speed_mph": None,
                "wind_direction": None,
                "station_id": None,
            }
        
        result = {
            "location": LOCATION_NAME,
            "lat": LATITUDE,
            "lon": LONGITUDE,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "current": current,
            "daily": daily_forecast,
            "hourly": hourly_forecast,
        }
        
        return result


def _c_to_f(c: float | None) -> float | None:
    if c is None:
        return None
    return round(c * 9 / 5 + 32, 1)


def _safe_percent(val: float | None) -> int | None:
    if val is None:
        return None
    return int(round(val))


def _safe_mph(val: float | None) -> float | None:
    if val is None:
        return None
    # NWS windSpeed is in km/h by default in observations
    return round(val * 0.621371, 1)


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
