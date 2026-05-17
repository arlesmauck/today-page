# Roadmap

Features and capabilities planned for future releases, in rough priority order.

---

## Phase 2 — Quick Wins

Low implementation effort, high day-to-day value. Target after the current AI news digest is stable.

| Feature | Description |
|---------|-------------|
| **Local news** | Add a "Local" tab automatically using the configured `LOCATION_NAME` as a Google News search query. No extra config needed. |
| **Source count badge** | Show "4 sources" on cards where multiple publishers covered the same story, as a signal of significance. |
| **Headlines-only mode** | A compact toggle that collapses all story cards to just the headline and brief — for busy mornings. CSS + 1 line of JS. |
| **Audio mode** | Read the morning briefing aloud using the browser's built-in Web Speech API. ~5 lines of JS. |
| **Background context** | A third expandable section per story: "What do I need to know?" — a one-paragraph primer on the broader topic. Fold into the existing Claude prompt at minimal extra cost. |

---

## Phase 3 — Smarter Digest

More significant backend work. Requires stable data model from Phase 1–2.

| Feature | Description |
|---------|-------------|
| **Story clustering** | Detect when multiple sources cover the same event and collapse them into a single card. Show "covered by Reuters, BBC, AP" rather than three separate cards. High noise-reduction value. |
| **Prose morning briefing** | A single AI-generated narrative paragraph at the top of the news section — like a personal newsletter opener — written across all of the day's top stories. |

---

## Phase 4 — Personalization & Memory

Complex features that require storing state across refresh cycles.

| Feature | Description |
|---------|-------------|
| **Developing story tracking** | Flag stories that have been updated since the last refresh. Show a subtle "updated" indicator and optionally surface what changed. Requires storing story history in `data/`. |
| **Weekly digest** | On Sundays, generate a narrative summary of the week's most significant stories. Requires a multi-day story archive. |
| **Topic following** | Let users specify topics of interest (e.g., "AI regulation", "housing policy"). Surface stories matching those topics regardless of which feed category they fall into. Requires semantic matching. |
| **Calendar-aware news** | Surface news stories relevant to upcoming calendar events. If a trip to Chicago is on the calendar, show Chicago news. If a healthcare board meeting is coming up, flag relevant policy stories. |

---

## Notes

- Features in Phase 2 are explicitly designed to be additive and non-breaking — they can be added in any order.
- Story clustering (Phase 3) is a prerequisite for the prose briefing to be maximally useful, since the briefing should reflect de-duplicated events.
- Calendar-aware news (Phase 4) requires the calendar and news data pipelines to share a common context layer, which is a meaningful architectural change.
