#!/usr/bin/env python3
"""
Debug tool for the morning briefing pipeline.

Shows every step: candidate pool → LLM story selection → briefing input → output.

Usage:
    python scripts/debug_briefing.py          # Show candidate pool + cached output
    python scripts/debug_briefing.py --regen  # Force regenerate (clears cache)
    python scripts/debug_briefing.py --dry    # Show candidates + prompt, no LLM calls
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.news import load_news
from src.morning_briefer import (
    BRIEFING_FILE,
    DEFAULT_BRIEFING_PROMPT,
    DEFAULT_SELECTION_PROMPT,
    _MAX_CANDIDATES,
    _build_candidate_message,
    _get_briefing_prompt,
    _get_selection_prompt,
    _input_hash,
    _select_stories,
    generate_briefing,
)


SEP = "=" * 60


def show_candidates(candidates: list[dict]) -> None:
    print(f"\n{SEP}")
    print(f"STEP 1 — CANDIDATE POOL ({len(candidates)} stories)")
    print(SEP)
    print(_build_candidate_message(candidates))


def show_selection_prompt() -> None:
    prompt = _get_selection_prompt()
    is_custom = prompt != DEFAULT_SELECTION_PROMPT
    print(f"\n{SEP}")
    print(f"STEP 2 — SELECTION PROMPT {'[custom]' if is_custom else '[default]'}")
    print(SEP)
    print(prompt)


def show_selected(selected: list[dict]) -> None:
    print(f"\n{SEP}")
    print(f"STEP 3 — SELECTED STORIES ({len(selected)} chosen)")
    print(SEP)
    for i, s in enumerate(selected, 1):
        syn = " [synthesized]" if s.get("synthesized") else ""
        print(f"  {i}. [{s.get('category','')} / {s.get('source','')}]{syn}")
        print(f"     {s.get('headline','')}")
        lede = s.get("lede", "")
        if lede:
            print(f"     {lede[:120]}{'…' if len(lede) > 120 else ''}")


def show_briefing_prompt() -> None:
    prompt = _get_briefing_prompt()
    is_custom = prompt != DEFAULT_BRIEFING_PROMPT
    print(f"\n{SEP}")
    print(f"STEP 4 — BRIEFING PROMPT {'[custom]' if is_custom else '[default]'}")
    print(SEP)
    print(prompt)


def show_cache() -> None:
    print(f"\n{SEP}")
    print("CACHED OUTPUT")
    print(SEP)
    if not BRIEFING_FILE.exists():
        print("  (no cache — briefing has not been generated yet)")
        return
    try:
        cache = json.loads(BRIEFING_FILE.read_text())
        print(f"  Generated:  {cache.get('generated_at', 'unknown')}")
        print(f"  Hash:       {cache.get('input_hash', 'unknown')}")
        headlines = cache.get("selected_headlines")
        if headlines:
            print(f"\n  Stories used in briefing:")
            for h in headlines:
                print(f"    • {h}")
        print(f"\n  Briefing text:\n")
        briefing = cache.get("briefing", "(empty)")
        for line in briefing.split(". "):
            print(f"  {line.strip()}.")
    except Exception as e:
        print(f"  Error reading cache: {e}")


async def run_regen() -> None:
    print(f"\n  Clearing cache and regenerating (2 LLM calls)…")
    if BRIEFING_FILE.exists():
        BRIEFING_FILE.unlink()
    briefing = await generate_briefing()
    print(f"\n{SEP}")
    print("NEW BRIEFING OUTPUT")
    print(SEP)
    if briefing:
        print(f"\n{briefing}")
        print()
        cache = json.loads(BRIEFING_FILE.read_text())
        headlines = cache.get("selected_headlines", [])
        if headlines:
            print(f"\n  Stories used:")
            for h in headlines:
                print(f"    • {h}")
    else:
        print("  (generation failed — check logs / API key)")


async def run_dry(candidates: list[dict]) -> None:
    print(f"\n  [--dry] Running selection LLM call only…")
    selected = await _select_stories(candidates)
    show_selected(selected)
    show_briefing_prompt()
    print(f"\n  [--dry] Skipping briefing write step.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug the morning briefing pipeline")
    parser.add_argument("--regen", action="store_true",
                        help="Force regenerate: clear cache and run both LLM steps")
    parser.add_argument("--dry", action="store_true",
                        help="Run selection step only, show what briefing would receive")
    args = parser.parse_args()

    all_stories = load_news()
    if not all_stories:
        print("No stories in news.json — run a news refresh first.")
        sys.exit(1)

    candidates = all_stories[:_MAX_CANDIDATES]
    current_hash = _input_hash(candidates)

    print(f"\nTotal stories: {len(all_stories)}  |  Candidates: {len(candidates)}  |  Hash: {current_hash}")

    show_candidates(candidates)
    show_selection_prompt()

    if args.regen:
        asyncio.run(run_regen())
    elif args.dry:
        asyncio.run(run_dry(candidates))
    else:
        show_cache()


if __name__ == "__main__":
    main()
