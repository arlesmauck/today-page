#!/usr/bin/env python3
"""
Test script for article fetching and AI summarization.
Runs outside Docker against a live Google News URL.

Usage:
    python scripts/test_fetch.py
    python scripts/test_fetch.py "https://news.google.com/rss/articles/CBMi..."
"""
import asyncio
import base64
import logging
import re
import sys
from pathlib import Path

import httpx

# Make src importable from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("trafilatura").setLevel(logging.WARNING)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def decode_google_news_url(url: str) -> str | None:
    """Attempt to extract real article URL from Google News base64 article ID."""
    match = re.search(r'/articles/([A-Za-z0-9_-]+)', url)
    if not match:
        print("  No /articles/ segment found in URL")
        return None
    article_id = match.group(1)
    print(f"  Article ID: {article_id[:40]}...")
    padding = (4 - len(article_id) % 4) % 4
    try:
        # Level 1: decode article ID → protobuf bytes
        outer = base64.urlsafe_b64decode(article_id + "=" * padding)
        print(f"  Level 1 decoded ({len(outer)} bytes): {outer[:80]!r}")

        # Level 2: find and decode inner base64url string
        inner_match = re.search(rb'(AU_[A-Za-z0-9_-]{20,})', outer)
        if not inner_match:
            print("  No inner base64 string (AU_...) found in protobuf")
            return None
        inner_b64 = inner_match.group(1)
        print(f"  Inner base64 string ({len(inner_b64)} bytes): {inner_b64[:60]!r}...")
        inner_padding = (4 - len(inner_b64) % 4) % 4
        inner = base64.urlsafe_b64decode(inner_b64 + b"=" * inner_padding)
        print(f"  Level 2 decoded ({len(inner)} bytes): {inner[:120]!r}")

        url_match = re.search(rb'https?://[^\x00-\x1f\x7f-\xff\s]+', inner)
        if url_match:
            real_url = url_match.group(0).decode("ascii", errors="ignore").rstrip(".")
            return real_url
        print("  No https:// URL found in level 2 decoded bytes")
    except Exception as e:
        print(f"  Decode exception: {e}")
    return None


async def test_url(url: str):
    print(f"\n{'='*60}")
    print(f"Testing: {url[:80]}...")
    print(f"{'='*60}")

    # Step 1: decode
    print("\n[1] Decoding Google News URL...")
    decoded = decode_google_news_url(url)
    if decoded:
        print(f"  SUCCESS: {decoded}")
    else:
        print("  FAILED — will try redirect fallback")

    fetch_url = decoded or url

    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0) as client:
        # Step 2: redirect follow (if decode failed)
        if not decoded:
            print("\n[2] Following redirect...")
            try:
                resp = await client.get(url, follow_redirects=True)
                final = str(resp.url)
                print(f"  Final URL: {final}")
                if "google.com" in final:
                    print("  BLOCKED — stayed on google.com")
                    return
                fetch_url = final
            except Exception as e:
                print(f"  ERROR: {e}")
                return
        else:
            print("\n[2] Skipping redirect (decoded URL available)")

        # Step 3: fetch article
        print(f"\n[3] Fetching article content from: {fetch_url[:80]}")
        try:
            resp = await client.get(fetch_url, follow_redirects=True)
            print(f"  HTTP {resp.status_code} — {len(resp.text)} chars received")

            import trafilatura
            text = trafilatura.extract(resp.text)
            if text:
                print(f"  Extracted {len(text)} chars")
                print(f"  Preview: {text[:200]!r}")
            else:
                print("  trafilatura returned None — likely paywalled or bot-blocked")
                return
        except Exception as e:
            print(f"  ERROR: {e}")
            return

    # Step 4: LLM summary
    print("\n[4] Calling LLM...")
    try:
        from src.config import AI_MODEL, AI_API_KEY, AI_API_BASE, AI_SUMMARY_ENABLED
        if not AI_SUMMARY_ENABLED:
            print("  AI_SUMMARY_ENABLED is False — set AI_API_KEY in .env to test LLM")
            return

        import litellm
        kwargs = {
            "model": AI_MODEL,
            "max_tokens": 512,
            "messages": [
                {"role": "system", "content": "Output format: BRIEF: [1-2 sentences]\nDETAIL: [5-8 sentences]"},
                {"role": "user", "content": f"Article:\n{text[:3000]}"},
            ],
        }
        if AI_API_KEY:
            kwargs["api_key"] = AI_API_KEY
        if AI_API_BASE:
            kwargs["api_base"] = AI_API_BASE

        response = await litellm.acompletion(**kwargs)
        output = response.choices[0].message.content.strip()
        print(f"  Model: {AI_MODEL}")
        print(f"  Response:\n{output}")
    except Exception as e:
        print(f"  ERROR: {e}")


async def main():
    if len(sys.argv) > 1:
        urls = sys.argv[1:]
    else:
        # Default: fetch the first article from BBC World (real URL, no Google redirect)
        print("No URL provided — fetching first article from BBC World feed...")
        import feedparser
        feed = feedparser.parse("https://feeds.bbci.co.uk/news/world/rss.xml")
        if not feed.entries:
            print("No entries in feed — check network connectivity")
            return
        urls = [feed.entries[0].get("link", "")]
        print(f"Testing first entry: {feed.entries[0].get('title', '')}")

    for url in urls:
        await test_url(url)


if __name__ == "__main__":
    asyncio.run(main())
