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

# AI news summarization (optional)
# AI_MODEL accepts any litellm model string:
#   Anthropic:  claude-haiku-4-5-20251001, claude-sonnet-4-6
#   OpenAI:     gpt-4o-mini, gpt-4o
#   Ollama:     ollama/llama3.2, ollama/mistral  (set AI_API_BASE for remote hosts)
#   Gemini:     gemini/gemini-1.5-flash
#   Groq:       groq/llama-3.1-8b-instant
AI_MODEL = os.getenv("AI_MODEL", "claude-haiku-4-5-20251001")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_API_BASE = os.getenv("AI_API_BASE", "")  # optional; required for remote Ollama
AI_SUMMARY_ENABLED = bool(AI_API_KEY) or AI_MODEL.startswith("ollama/")

# AI news curation — AI reviews all fetched stories and selects the most newsworthy
# per category before display. Requires AI_SUMMARY_ENABLED (uses the same AI_MODEL).
NEWS_CURATION_ENABLED = AI_SUMMARY_ENABLED and os.getenv("NEWS_CURATION_ENABLED", "true").lower() not in ("false", "0", "no", "off")

# Per-category quality gate for news curation.
# Returns 'strict' (absolute pass/fail — 0 stories ok) or 'relaxed' (2-4 best available).
# Env var format: NEWS_QUALITY_{CATEGORY} e.g. NEWS_QUALITY_WORLD=strict
def get_category_quality(category: str) -> str:
    key = f"NEWS_QUALITY_{category.upper().replace(' ', '_')}"
    val = os.getenv(key, "relaxed").lower().strip()
    return "strict" if val == "strict" else "relaxed"

# Optional second model for per-story background context (e.g. Perplexity sonar with web search)
CONTEXT_MODEL = os.getenv("CONTEXT_MODEL", "")
CONTEXT_ENABLED = bool(CONTEXT_MODEL and (AI_API_KEY or CONTEXT_MODEL.startswith("ollama/")))
# Max context LLM calls per enrichment cycle. Caps cost when many new stories arrive at once.
# Set to 0 to disable the cap (call context for every new story).
CONTEXT_MAX_PER_REFRESH = int(os.getenv("CONTEXT_MAX_PER_REFRESH", "10"))
