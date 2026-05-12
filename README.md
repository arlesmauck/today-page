# Today Page

A personal morning dashboard to replace doom-scrolling with intentional information.

## The Idea

One page that tells you what you need to know — weather, calendar, headlines, and curated reads — without the endless scroll, clickbait, or algorithmic manipulation. Built to feel calm, not frantic.

## Design Explorations

This repo contains three design direction sketches. Open them in any browser to compare:

| Variant | Feel | Best For |
|---------|------|----------|
| [001 Calm Editorial](./sketches/001-calm-editorial/) | Morning newspaper. Slow, readable, serif typography. | When you have 10–15 minutes to actually read. |
| [002 At-a-Glance Dashboard](./sketches/002-at-a-glance/) | Dark-mode instrument panel. Dense, scannable, efficient. | When you need situational awareness in 60 seconds. |
| [003 Zen Minimal](./sketches/003-zen-minimal/) | Barely anything on screen. Expand only if you want more. | Breaking the compulsive refresh habit. |

## How to View

Open any sketch directly in a browser:

```bash
# On Linux
xdg-open sketches/001-calm-editorial/index.html

# On macOS
open sketches/002-at-a-glance/index.html

# Or serve locally
cd sketches
python3 -m http.server 8080
# Visit http://localhost:8080/001-calm-editorial/
```

## Roadmap

- [ ] Pick a design direction
- [ ] Add live weather API
- [ ] Add calendar integration
- [ ] Add RSS feed aggregation
- [ ] Add Reddit curation
- [ ] Deploy to home server

## Tech Stack

- Plain HTML/CSS/JS (no build step)
- Tailwind CSS via CDN (for rapid prototyping)
- Self-hosted on a personal Linux server

---

Built by [Arles Mauck](https://github.com/arlesmauck) with help from Hermes Agent.
