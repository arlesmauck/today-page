# Today Page

A self-hosted personal dashboard that replaces doom-scrolling with intentional information. One page shows you what you need to know — weather, your calendar, real news headlines, and today's tasks — without the endless scroll, clickbait, or algorithmic manipulation.

Design: [Calm Editorial sketch](./sketches/001-calm-editorial/) (the repo root `index.html` is a full design preview).

## Features

- **Weather** — current conditions, daily high, wind, and humidity via [Open-Meteo](https://open-meteo.com) (free, no API key, works anywhere in the world)
- **Calendar** — pulls from any iCal feed (Google Calendar, Apple Calendar, Outlook). Shows today, tomorrow, and the next 7 days
- **News** — headlines from configurable RSS feeds, organized into tabs by category. With an AI key configured, stories are curated, deduplicated, and summarized; a prose morning briefing opens the page (see [AI News Pipeline](#ai-news-pipeline))
- **Tasks** — a small to-do list for the day, persisted to disk, with automatic cleanup
- **Settings panel** — every user-facing setting is editable live in the app (⚙ at the bottom of the page). No restarts, no `.env` editing after the initial setup
- **Auto-refresh** — a background scheduler refetches everything on a configurable interval and rebuilds the page as static HTML; the browser reloads itself to pick it up
- **Self-hosted** — runs entirely in Docker on your own hardware. No cloud accounts, no subscriptions

## Quick Start

**1. Clone and configure**

```bash
git clone https://github.com/arlesmauck/today-page.git
cd today-page
cp .env.example .env
```

The defaults work out of the box. The main reason to edit `.env` is to add an AI API key (optional — see [AI News Pipeline](#ai-news-pipeline)).

**2. Set your location**

You can do this later in the app's ⚙ settings panel, but to seed it up front, edit [docker-compose.dev.yml](docker-compose.dev.yml):

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

**4. Configure in the app**

Click the ⚙ gear at the bottom of the page. Everything user-facing lives there: your name, page title, location, calendars, news feeds and categories, AI curation toggles, and tuning knobs. Settings are saved to `data/settings.json` and take effect immediately — the page rebuilds, and if the data pool changed (feeds, location, categories), a background refresh kicks off automatically. A reset button reverts everything to the env defaults.

## AI News Pipeline

With `AI_API_KEY` set (or a local Ollama model), the news goes through an editorial pipeline before it reaches the page. Without a key, the page falls back to raw RSS headlines and excerpts.

Summaries are powered by [litellm](https://github.com/BerriAI/litellm), so `AI_MODEL` accepts any litellm model string:

```bash
AI_MODEL=openrouter/google/gemini-2.5-flash-lite   # cheap, fast (openrouter.ai/keys)
AI_MODEL=claude-haiku-4-5-20251001                 # Anthropic direct
AI_MODEL=gpt-4o-mini                               # OpenAI direct
AI_MODEL=ollama/llama3.2                           # local; AI_API_BASE for remote hosts
```

**Curation** — the AI reviews every fetched story and keeps only what passes an editorial bar: real consequences, named sources, substance over noise. Clickbait, outrage bait, celebrity gossip, listicles, and speculation are set aside. Each category uses a quality gate: `relaxed` (default) shows the 2–4 best available stories even on a thin news day; `strict` shows only stories that fully pass, even if that means none. Gates are editable per category in the settings panel.

**Clustering** — when multiple outlets cover the same event, the stories are merged into one with a synthesized lede, so you read an event once, not six times.

**Summaries** — each story gets a neutral, factual summary written from the article text (fetched and extracted with trafilatura). Cached for 7 days; click a story on the page to summarize it on demand.

**Morning briefing** — the AI picks the 3–5 most consequential stories of the day and writes a prose briefing paragraph that opens the page.

**Background context** — optionally, a second model writes a per-story "Background" primer. Point `CONTEXT_MODEL` at something with built-in web search for best results, e.g. `openrouter/perplexity/sonar`:

```bash
CONTEXT_MODEL=openrouter/perplexity/sonar
CONTEXT_API_KEY=          # only if it differs from AI_API_KEY
```

The number of context calls per refresh is capped (settings panel) to bound cost when many new stories arrive at once.

**Custom prompts** — every prompt in the pipeline (summary, context, curation, briefing, selection) can be edited in the settings panel and is persisted to `data/prompts.json`. Reset to the built-in defaults from the same panel.

## Calendar Setup

Today Page works with any service that exports an iCal (`.ics`) URL. Add calendars in the ⚙ settings panel (URLs are write-only — the panel never displays them back).

**Google Calendar**
1. Go to [calendar.google.com](https://calendar.google.com) → Settings (gear icon)
2. Click a calendar name in the left sidebar → "Integrate calendar"
3. Copy the **"Secret address in iCal format"** link

**Apple / iCloud Calendar**
1. Calendar app → right-click a calendar → Share Calendar
2. Enable "Public Calendar" and copy the link

**Outlook**
1. Calendar settings → "Publish a calendar" → copy the ICS link

Calendars can also be seeded via env vars — any variable ending in `_CALENDAR_URL` is picked up automatically:

```bash
PERSONAL_CALENDAR_URL=https://calendar.google.com/calendar/ical/.../basic.ics
WORK_CALENDAR_URL=https://calendar.google.com/calendar/ical/.../basic.ics
```

## News Feeds

Default feeds are included out of the box — BBC World, Ars Technica Technology, ScienceDaily, BBC Health, and NPR US — with Google News topic feeds merged in alongside for broader coverage. No configuration required.

Manage feeds and categories in the app: click the ⚙ gear at the bottom of the page. Adding, renaming, or removing a category updates the tabs and the feeds that fill them.

To override or add feeds via env vars instead, set these before first run (the settings panel then takes over):

```bash
NEWS_FEED_WORLD_URL=https://feeds.reuters.com/reuters/topNews
NEWS_FEED_TECH_URL=https://feeds.arstechnica.com/arstechnica/technology-lab
NEWS_FEED_LOCAL_URL=https://your-local-paper.com/rss
```

Any variable matching `NEWS_FEED_*_URL` is loaded; the label comes from the variable name (`NEWS_FEED_LOCAL_URL` → "Local"). Google News supplements can be disabled per category with `NEWS_GNEWS_WORLD=false` (etc.).

## Tasks

The page includes a small task list: type a task, check it off when done. Today's tasks are listed first; tasks from earlier in the week appear in a collapsed panel below.

Tasks clean themselves up — completed tasks disappear at the end of their day, and anything still unfinished is cleared at the end of its week (Monday-based). Everything lives in `data/tasks.json`.

## Configuration Reference

Most settings are managed in the ⚙ settings panel (`data/settings.json`) and are seeded from env vars as initial defaults. These are env-only and cannot be changed from the panel:

| Variable | Description | Default |
|----------|-------------|---------|
| `HOST` | Bind address | `0.0.0.0` |
| `PORT` | Internal port the app listens on | `8080` |
| `DATA_DIR` | Where settings, caches, and task data live | `/app/data` |
| `REFRESH_INTERVAL` | Seconds between refresh cycles | `3600` |
| `LOG_LEVEL` | Python log level | `INFO` |
| `AI_MODEL` | litellm model string for summaries/curation/briefing | `claude-haiku-4-5-20251001` |
| `AI_API_KEY` | API key for the model above (empty disables AI) | — |
| `AI_API_BASE` | Custom base URL (e.g. remote Ollama) | — |
| `CONTEXT_MODEL` | Second model for per-story background | — |
| `CONTEXT_API_KEY` | Key for the context model if it differs | falls back to `AI_API_KEY` |
| `CONTEXT_MAX_PER_REFRESH` | Cap on background-context LLM calls per cycle | `10` |
| `NEWS_CURATION_ENABLED` | Enable AI curation by default | `true` |
| `NEWS_QUALITY_{CATEGORY}` | Per-category gate: `strict` or `relaxed` | `relaxed` |
| `NEWS_GNEWS_{CATEGORY}` | Include Google News supplements: `true`/`false` | `true` |
| `MAX_ARTICLE_CHARS` | Article text sent to the summarizer | `8000` |
| `MAX_BRIEFING_CANDIDATES` | Stories considered for the morning briefing | `15` |

Seeded defaults (change them in the settings panel instead of `.env`): `LATITUDE`, `LONGITUDE`, `LOCATION_NAME`, `TIMEZONE`, `USER_NAME`, `PAGE_TITLE`, `NEWS_FEED_*_URL`, `*_CALENDAR_URL`, `STORIES_PER_CATEGORY`, `CLUSTER_THRESHOLD`.

## Production (TrueNAS / Home Server)

The production compose file pulls a pre-built image from GitHub Container Registry:

```bash
docker compose pull
docker compose up -d
```

The image is built and pushed automatically on version tags (`v*`) and manual workflow dispatch via GitHub Actions; pull requests build without pushing. See [docs/DEPLOY.md](docs/DEPLOY.md) for a full TrueNAS SCALE walkthrough.

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
| `GET /api/tasks` | Persisted task list |
| `POST /api/tasks` | Create a task |
| `PATCH /api/tasks/{id}` | Mark a task complete or incomplete |
| `GET /api/config/settings` | Effective settings (env defaults + `settings.json`) |
| `POST /api/config/settings` | Validate and save settings |
| `DELETE /api/config/settings` | Revert to env defaults |
| `GET /api/config/prompts` | Active and default AI prompts |
| `POST /api/config/prompts` | Save custom prompts |
| `DELETE /api/config/prompts` | Reset prompts to defaults |
| `GET /api/story/summarize` | On-demand AI summary (cache-first) |
| `GET /api/health` | Health check |
| `POST /api/weather/refresh` | Manually trigger a weather refresh |

## Tech Stack

- **Python** — FastAPI, httpx, icalendar, feedparser, Jinja2, litellm, trafilatura
- **Docker** — multi-stage build, non-root user, health check, amd64 + arm64 images
- **Weather** — [Open-Meteo](https://open-meteo.com) (free, no API key)
- **Calendar** — iCalendar / RFC 5545 standard
- **News** — RSS / Atom feeds via feedparser
- **AI** — any litellm-supported model (Anthropic, OpenAI, Gemini, Ollama, OpenRouter, …)

## Local Development (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

This starts the scheduler and the web server together on port 8080. AI features activate when `AI_API_KEY` is set in the environment; without it the pipeline is skipped and RSS excerpts are shown.

---

Built by [Arles Mauck](https://github.com/arlesmauck).