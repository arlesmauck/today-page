# Today Page

A self-hosted personal dashboard that replaces doom-scrolling with intentional information. One page shows you what you need to know — weather, your calendar, and real news headlines — without the endless scroll, clickbait, or algorithmic manipulation.

![Design: Calm Editorial](./sketches/001-calm-editorial/)

## Features

- **Weather** — current conditions, daily high, wind, and humidity via [Open-Meteo](https://open-meteo.com) (free, no API key, works anywhere in the world)
- **Calendar** — pulls from any iCal feed (Google Calendar, Apple Calendar, Outlook). Shows today, tomorrow, and the next 7 days
- **News** — real headlines from configurable RSS feeds, organized into tabs by category
- **Auto-refresh** — the page reloads itself on a configurable interval so it stays fresh as a browser dashboard
- **Self-hosted** — runs entirely in Docker on your own hardware. No cloud accounts, no subscriptions

## Quick Start

**1. Clone and configure**

```bash
git clone https://github.com/arlesmauck/today-page.git
cd today-page
cp .env.example .env
```

Edit `.env` and add your calendar URLs (see [Calendar Setup](#calendar-setup) below).

**2. Configure `docker-compose.dev.yml`**

Open [docker-compose.dev.yml](docker-compose.dev.yml) and set your location and name:

```yaml
environment:
  LATITUDE: "39.7392"
  LONGITUDE: "-104.9903"
  LOCATION_NAME: "Denver, CO"
  TIMEZONE: "America/Denver"
  USER_NAME: "Your Name"
```

**3. Run**

```bash
docker compose -f docker-compose.dev.yml up --build
```

Open `http://localhost:8787` once you see `Page rebuilt` in the logs.

## Calendar Setup

Today Page works with any service that exports an iCal (`.ics`) URL.

**Google Calendar**
1. Go to [calendar.google.com](https://calendar.google.com) → Settings (gear icon)
2. Click a calendar name in the left sidebar → "Integrate calendar"
3. Copy the **"Secret address in iCal format"** link

**Apple / iCloud Calendar**
1. Calendar app → right-click a calendar → Share Calendar
2. Enable "Public Calendar" and copy the link

**Outlook**
1. Calendar settings → "Publish a calendar" → copy the ICS link

Add as many calendars as you like to `.env`:

```bash
PERSONAL_CALENDAR_URL=https://calendar.google.com/calendar/ical/.../basic.ics
WORK_CALENDAR_URL=https://calendar.google.com/calendar/ical/.../basic.ics
```

Any variable ending in `_CALENDAR_URL` is picked up automatically.

## News Feeds

Default feeds are included out of the box (Reuters World News, Ars Technica Science & Tech) — no configuration required.

To override or add feeds, set these in your `.env`:

```bash
NEWS_FEED_WORLD_URL=https://feeds.reuters.com/reuters/topNews
NEWS_FEED_TECH_URL=https://feeds.arstechnica.com/arstechnica/technology-lab
NEWS_FEED_LOCAL_URL=https://your-local-paper.com/rss
```

Any variable matching `NEWS_FEED_*_URL` is loaded. The label shown in the tab is derived from the variable name (e.g. `NEWS_FEED_LOCAL_URL` → "Local" tab).

## Configuration Reference

All settings in `docker-compose.dev.yml` (or `docker-compose.yml` for production):

| Variable | Description | Default |
|----------|-------------|---------|
| `LATITUDE` | Your latitude | `39.7392` |
| `LONGITUDE` | Your longitude | `-104.9903` |
| `LOCATION_NAME` | Display name for weather | `Denver, CO` |
| `TIMEZONE` | [IANA timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) | `America/Denver` |
| `USER_NAME` | Your name (used in greeting) | `Friend` |
| `PAGE_TITLE` | Title shown in masthead | `Your Morning Paper` |
| `REFRESH_INTERVAL` | How often to refresh data, in seconds | `900` |
| `PORT` | Internal port the app listens on | `8080` |
| `DATA_DIR` | Where to cache weather/calendar/news data | `/app/data` |

## Production (TrueNAS / Home Server)

The production compose file pulls a pre-built image from GitHub Container Registry:

```bash
docker compose pull
docker compose up -d
```

The image is built and pushed automatically on every push to `main` via GitHub Actions.

Update the volume path in [docker-compose.yml](docker-compose.yml) to match your server's storage:

```yaml
volumes:
  - /your/data/path:/app/data
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | The dashboard page |
| `GET /api/weather` | Cached weather JSON |
| `GET /api/calendar` | Cached calendar JSON |
| `GET /api/news` | Cached news JSON |
| `GET /api/health` | Health check |
| `POST /api/weather/refresh` | Manually trigger a weather refresh |

## Tech Stack

- **Python** — FastAPI, httpx, icalendar, feedparser, Jinja2
- **Docker** — multi-stage build, non-root user, health check
- **Weather** — [Open-Meteo](https://open-meteo.com) (free, no API key)
- **Calendar** — iCalendar / RFC 5545 standard
- **News** — RSS / Atom feeds via feedparser

---

Built by [Arles Mauck](https://github.com/arlesmauck).
