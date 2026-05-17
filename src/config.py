"""Configuration for today-page."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Load .env file so calendar URLs etc are available
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

# Location
LATITUDE = float(os.getenv("LATITUDE", "39.7392"))
LONGITUDE = float(os.getenv("LONGITUDE", "-104.9903"))
LOCATION_NAME = os.getenv("LOCATION_NAME", "Denver, CO")

# Personalization
USER_NAME = os.getenv("USER_NAME", "Friend")
PAGE_TITLE = os.getenv("PAGE_TITLE", "Your Morning Paper")

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))

# Refresh interval (seconds)
REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "3600"))  # 1 hour

# Timezone for date display / "today" determinations
from zoneinfo import ZoneInfo
TIMEZONE_NAME = os.getenv("TIMEZONE", "America/Denver")
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
