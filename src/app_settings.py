"""Runtime-editable app settings, persisted to data/settings.json.

Precedence: values in settings.json override environment variables; env vars
(.env / docker-compose) remain the defaults, so a deployment without a
settings file behaves exactly as before. Settings are read dynamically per
call — no restart needed after saving.

Not managed here (stay env-only): secrets used before the UI exists
(HOST, PORT, DATA_DIR), the refresh interval, and AI credentials/model
(AI_MODEL, AI_API_KEY, CONTEXT_MODEL, ...).

Calendar URLs contain private tokens, so they are write-only over the API:
GET returns a deterministic masked form, and POST accepts either a new URL
or the mask back (meaning "unchanged").
"""
import hashlib
import json
import logging
import threading
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from src.config import (
    DATA_DIR, USER_NAME, PAGE_TITLE, LOCATION_NAME,
    LATITUDE, LONGITUDE, TIMEZONE_NAME,
    NEWS_CURATION_ENABLED, CONTEXT_MAX_PER_REFRESH,
    STORIES_PER_CATEGORY, CLUSTER_THRESHOLD, get_category_quality,
)

logger = logging.getLogger("app_settings")

SETTINGS_FILE = DATA_DIR / "settings.json"

# Bumped when the settings shape changes so readers can reject old files
SETTINGS_VERSION = 1

_lock = threading.Lock()
_cache: tuple[float, dict] | None = None  # (mtime, effective settings)

# Calendar URL masks look like "https://host/…/basic.ics (a1b2c3)" — the "…"
# marks them as masks so a real URL can never collide with one.
MASK_ELLIPSIS = "…"


def _env_defaults() -> dict:
    """Settings as implied by environment variables alone."""
    return {
        "version": SETTINGS_VERSION,
        "user_name": USER_NAME,
        "page_title": PAGE_TITLE,
        "location_name": LOCATION_NAME,
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "timezone": TIMEZONE_NAME,
        "news_curation_enabled": NEWS_CURATION_ENABLED,
        "context_max_per_refresh": CONTEXT_MAX_PER_REFRESH,
        "stories_per_category": STORIES_PER_CATEGORY,
        "cluster_threshold": CLUSTER_THRESHOLD,
        "quality_gates": {},
    }


def load_settings() -> dict:
    """Return effective settings: env defaults overlaid with settings.json."""
    global _cache
    with _lock:
        try:
            mtime = SETTINGS_FILE.stat().st_mtime
        except OSError:
            mtime = 0.0
        if _cache is not None and _cache[0] == mtime:
            return _cache[1]
        merged = _env_defaults()
        if mtime:
            try:
                data = json.loads(SETTINGS_FILE.read_text())
                if isinstance(data, dict):
                    merged.update(data)
                else:
                    logger.warning("settings.json is not an object — using env defaults")
            except (json.JSONDecodeError, OSError):
                logger.warning("settings.json unreadable — using env defaults")
        _cache = (mtime, merged)
        return merged


def save_settings(data: dict) -> None:
    """Persist settings and refresh the cache atomically enough for our use."""
    global _cache
    with _lock:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        try:
            mtime = SETTINGS_FILE.stat().st_mtime
        except OSError:
            mtime = 0.0
        _cache = (mtime, data)


def delete_settings() -> bool:
    """Remove settings.json, reverting to env defaults. Returns True if deleted."""
    global _cache
    with _lock:
        _cache = None
        try:
            SETTINGS_FILE.unlink()
            return True
        except FileNotFoundError:
            return False


def settings_exist() -> bool:
    return SETTINGS_FILE.exists()


# ── Getters (fall back to env defaults on missing/invalid values) ────────────

def get_user_name() -> str:
    return load_settings().get("user_name") or USER_NAME


def get_page_title() -> str:
    return load_settings().get("page_title") or PAGE_TITLE


def get_location_name() -> str:
    return load_settings().get("location_name") or LOCATION_NAME


def get_latitude() -> float:
    try:
        return float(load_settings().get("latitude"))
    except (TypeError, ValueError):
        return LATITUDE


def get_longitude() -> float:
    try:
        return float(load_settings().get("longitude"))
    except (TypeError, ValueError):
        return LONGITUDE


def get_timezone_name() -> str:
    return load_settings().get("timezone") or TIMEZONE_NAME


_tz_cache: dict[str, ZoneInfo] = {}


def get_timezone() -> ZoneInfo:
    name = get_timezone_name()
    tz = _tz_cache.get(name)
    if tz is None:
        try:
            tz = ZoneInfo(name)
        except Exception:
            logger.warning("Invalid timezone %r — falling back to %r", name, TIMEZONE_NAME)
            tz = ZoneInfo(TIMEZONE_NAME)
        _tz_cache[name] = tz
    return tz


def get_feeds() -> list[dict] | None:
    """
    Configured news feeds as [{"category", "label", "url"}], or None when
    settings.json does not override them (caller falls back to env scanning).
    An empty list also counts as "not overridden" so an accidental wipe
    cannot blank the whole news page.
    """
    feeds = load_settings().get("feeds")
    if not isinstance(feeds, list) or not feeds:
        return None
    valid = [
        {"category": str(f.get("category", "")).strip() or "News",
         "label": str(f.get("label", "")).strip(),
         "url": str(f.get("url", "")).strip()}
        for f in feeds if isinstance(f, dict) and str(f.get("url", "")).strip()
    ]
    return valid or None


def get_calendars() -> list[dict] | None:
    """
    Configured calendars as [{"label", "url"}], or None when settings.json
    does not override them (caller falls back to env scanning).
    """
    cals = load_settings().get("calendars")
    if not isinstance(cals, list) or not cals:
        return None
    valid = [
        {"label": str(c.get("label", "")).strip() or "Calendar",
         "url": str(c.get("url", "")).strip()}
        for c in cals if isinstance(c, dict) and str(c.get("url", "")).strip()
    ]
    return valid or None


def get_news_curation_enabled() -> bool:
    return bool(load_settings().get("news_curation_enabled"))


def get_quality_gate(category: str) -> str:
    """'strict' or 'relaxed' for a category — settings first, then env, then 'relaxed'."""
    gates = load_settings().get("quality_gates")
    if isinstance(gates, dict):
        val = str(gates.get(category, "")).lower().strip()
        if val in ("strict", "relaxed"):
            return val
    return get_category_quality(category)


def get_context_max_per_refresh() -> int:
    try:
        val = int(load_settings().get("context_max_per_refresh"))
        return max(0, val)
    except (TypeError, ValueError):
        return CONTEXT_MAX_PER_REFRESH


def get_stories_per_category() -> int:
    try:
        val = int(load_settings().get("stories_per_category"))
        return min(50, max(1, val))
    except (TypeError, ValueError):
        return STORIES_PER_CATEGORY


def get_cluster_threshold() -> float:
    try:
        val = float(load_settings().get("cluster_threshold"))
        return min(1.0, max(0.0, val))
    except (TypeError, ValueError):
        return CLUSTER_THRESHOLD


# ── Calendar URL masking (write-only secrets) ────────────────────────────────

def mask_secret_url(url: str) -> str:
    """
    Deterministic, reversible-by-lookup mask of a secret URL.
    Shows scheme, host, and last path segment plus a short hash, e.g.
    "https://calendar.google.com/…/basic.ics (a1b2c3)".
    """
    try:
        parts = urlsplit(url.strip())
        host = parts.netloc.rsplit("@", 1)[-1]  # strip userinfo credentials if present
        segments = [s for s in parts.path.split("/") if s]
        tail = segments[-1] if segments else ""
        digest = hashlib.sha256(url.strip().encode()).hexdigest()[:6]
        return f"{parts.scheme}://{host}/{MASK_ELLIPSIS}/{tail} ({digest})"
    except Exception:
        return f"•••••• ({hashlib.sha256(url.encode()).hexdigest()[:6]})"


def resolve_submitted_calendar_url(submitted: str, existing: list[dict]) -> str | None:
    """
    Map a submitted calendar URL field to a real URL.
    A mask (contains the ellipsis) means "unchanged" — look it up among the
    existing calendar URLs. Anything else is treated as a fresh URL.
    Returns None when a mask does not match any known calendar.
    """
    submitted = (submitted or "").strip()
    if MASK_ELLIPSIS not in submitted:
        return submitted
    for c in existing:
        if mask_secret_url(c["url"]) == submitted:
            return c["url"]
    return None
