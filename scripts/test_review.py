"""
Code review test suite — runs without external services (no HTTP, no LLM).
Usage: python scripts/test_review.py
"""
import sys
import os

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_passed = 0
_failed = 0


def run_test(name: str, fn) -> None:
    global _passed, _failed
    try:
        fn()
        print(f"  PASS  {name}")
        _passed += 1
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        _failed += 1


# ─────────────────────────────────────────────────────────
# Section 1: ai_summarizer._parse_llm_response
# ─────────────────────────────────────────────────────────
print("\n[1] ai_summarizer._parse_llm_response")

from src.ai_summarizer import _parse_llm_response as parse_summary


def test_parse_correct():
    result = parse_summary("BRIEF: Something happened.\nDETAIL: More details here.")
    assert result == ("Something happened.", "More details here."), f"Got {result}"


def test_parse_markdown_bold_labels():
    result = parse_summary("**BRIEF:** Something happened.\n**DETAIL:** More details here.")
    assert result is not None, "Expected tuple, got None"
    assert result[0] == "Something happened."
    assert result[1] == "More details here."


def test_parse_missing_detail():
    result = parse_summary("BRIEF: Only a brief.")
    assert result is None, f"Expected None, got {result}"


def test_parse_empty():
    result = parse_summary("")
    assert result is None, f"Expected None, got {result}"


def test_parse_detail_no_newline():
    # DETAIL: immediately after BRIEF with no preceding newline
    result = parse_summary("BRIEF: Short.DETAIL: Details follow.")
    # The regex uses \n?DETAIL: so this should still parse
    assert result is not None, "Expected tuple, got None"
    assert result[1] == "Details follow."


run_test("correct input", test_parse_correct)
run_test("markdown bold labels", test_parse_markdown_bold_labels)
run_test("missing DETAIL returns None", test_parse_missing_detail)
run_test("empty string returns None", test_parse_empty)
run_test("DETAIL without preceding newline", test_parse_detail_no_newline)


# ─────────────────────────────────────────────────────────
# Section 2: news_curator._parse_llm_response
# ─────────────────────────────────────────────────────────
print("\n[2] news_curator._parse_llm_response")

from src.news_curator import _parse_llm_response as parse_curation


def _make_id_map():
    return {1: {"url": "https://example.com/story1"}, 2: {"url": "https://example.com/story2"}}


def test_curation_parse_correct():
    raw = '{"World": [{"id": 1, "reason": "important event"}]}'
    result = parse_curation(raw, _make_id_map())
    assert result == {"https://example.com/story1": "important event"}, f"Got {result}"


def test_curation_parse_markdown_fences():
    raw = '```json\n{"World": [{"id": 2, "reason": "test"}]}\n```'
    result = parse_curation(raw, _make_id_map())
    assert result == {"https://example.com/story2": "test"}, f"Got {result}"


def test_curation_parse_extra_whitespace():
    raw = '  { "World": [{"id": 1, "reason": "trimmed"}] }  '
    result = parse_curation(raw, _make_id_map())
    assert result == {"https://example.com/story1": "trimmed"}, f"Got {result}"


def test_curation_parse_invalid_json():
    result = parse_curation("not json at all", _make_id_map())
    assert result == {}, f"Expected empty dict, got {result}"


def test_curation_parse_missing_id():
    raw = '{"World": [{"id": 99, "reason": "phantom"}]}'
    result = parse_curation(raw, _make_id_map())
    assert result == {}, f"Expected empty dict (id 99 not in map), got {result}"


def test_curation_parse_not_object():
    result = parse_curation("[1, 2, 3]", _make_id_map())
    assert result == {}, f"Expected empty dict, got {result}"


run_test("correct JSON parse", test_curation_parse_correct)
run_test("JSON with markdown fences", test_curation_parse_markdown_fences)
run_test("extra whitespace stripped", test_curation_parse_extra_whitespace)
run_test("invalid JSON returns empty dict", test_curation_parse_invalid_json)
run_test("missing ID silently skipped", test_curation_parse_missing_id)
run_test("non-object JSON returns empty dict", test_curation_parse_not_object)


# ─────────────────────────────────────────────────────────
# Section 3: news_clusterer helpers
# ─────────────────────────────────────────────────────────
print("\n[3] news_clusterer: _sig_words, _jaccard")

from src.news_clusterer import _sig_words, _jaccard, _detect_clusters


def test_sig_words_stopwords_removed():
    words = _sig_words("The cat sat on the mat")
    assert "the" not in words
    assert "on" not in words
    assert "cat" in words
    assert "sat" in words
    assert "mat" in words


def test_sig_words_min_length():
    # "is" (2 chars) should be excluded; "big" (3 chars) should be included
    words = _sig_words("is big")
    assert "is" not in words
    assert "big" in words


def test_jaccard_identical():
    score = _jaccard("Apple releases new iPhone model", "Apple releases new iPhone model")
    assert score == 1.0, f"Expected 1.0, got {score}"


def test_jaccard_disjoint():
    score = _jaccard("tornado warning issued", "quantum computer breakthrough")
    assert score == 0.0, f"Expected 0.0, got {score}"


def test_jaccard_partial():
    # "Apple releases iPhone" vs "Apple releases Samsung"
    # "new" is a stopword so use "releases" instead
    # sig_words: {"apple", "releases", "iphone"} vs {"apple", "releases", "samsung"}
    # intersection=2, union=4 → jaccard=0.5
    score = _jaccard("Apple releases iPhone", "Apple releases Samsung")
    assert 0.0 < score < 1.0, f"Expected partial overlap, got {score}"
    assert abs(score - 0.5) < 0.01, f"Expected ~0.5, got {score}"


run_test("stopwords removed", test_sig_words_stopwords_removed)
run_test("words shorter than 3 chars excluded", test_sig_words_min_length)
run_test("identical headlines → jaccard 1.0", test_jaccard_identical)
run_test("disjoint headlines → jaccard 0.0", test_jaccard_disjoint)
run_test("partial overlap → correct ratio", test_jaccard_partial)


# ─────────────────────────────────────────────────────────
# Section 4: news_clusterer._detect_clusters
# ─────────────────────────────────────────────────────────
print("\n[4] news_clusterer._detect_clusters")


def test_detect_clusters_similar():
    stories = [
        {"headline": "Apple unveils new iPhone 16 model", "url": "https://a.com/1"},
        {"headline": "Apple releases new iPhone model update", "url": "https://b.com/2"},
    ]
    clusters = _detect_clusters(stories)
    assert len(clusters) == 1, f"Expected 1 cluster, got {len(clusters)}"
    assert len(clusters[0]) == 2, f"Expected 2 stories in cluster, got {len(clusters[0])}"


def test_detect_clusters_dissimilar():
    stories = [
        {"headline": "Ukraine ceasefire talks collapse", "url": "https://a.com/1"},
        {"headline": "Earthquake strikes eastern Turkey", "url": "https://b.com/2"},
    ]
    clusters = _detect_clusters(stories)
    assert len(clusters) == 2, f"Expected 2 clusters, got {len(clusters)}"
    assert all(len(c) == 1 for c in clusters), "Each cluster should have 1 story"


def test_detect_clusters_single_story():
    stories = [{"headline": "Only one story today", "url": "https://a.com/1"}]
    clusters = _detect_clusters(stories)
    assert len(clusters) == 1
    assert len(clusters[0]) == 1


def test_detect_clusters_empty():
    clusters = _detect_clusters([])
    assert clusters == []


run_test("similar headlines cluster together", test_detect_clusters_similar)
run_test("dissimilar headlines stay separate", test_detect_clusters_dissimilar)
run_test("single story → single cluster", test_detect_clusters_single_story)
run_test("empty input → empty output", test_detect_clusters_empty)


# ─────────────────────────────────────────────────────────
# Section 5: news_curator._input_hash
# ─────────────────────────────────────────────────────────
print("\n[5] news_curator._input_hash")

from src.news_curator import _input_hash


def test_input_hash_deterministic():
    stories = [{"url": "https://a.com"}, {"url": "https://b.com"}]
    assert _input_hash(stories) == _input_hash(stories)


def test_input_hash_order_independence():
    s1 = [{"url": "https://a.com"}, {"url": "https://b.com"}]
    s2 = [{"url": "https://b.com"}, {"url": "https://a.com"}]
    assert _input_hash(s1) == _input_hash(s2), "Hash should not depend on story order"


def test_input_hash_different_for_different_stories():
    s1 = [{"url": "https://a.com"}]
    s2 = [{"url": "https://b.com"}]
    assert _input_hash(s1) != _input_hash(s2)


run_test("deterministic hash", test_input_hash_deterministic)
run_test("order-independent hash", test_input_hash_order_independence)
run_test("different stories → different hash", test_input_hash_different_for_different_stories)


# ─────────────────────────────────────────────────────────
# Section 6: news.load_news with missing file
# ─────────────────────────────────────────────────────────
print("\n[6] news.load_news with missing file")

import src.news as _news_module
from pathlib import Path


def test_load_news_missing_file():
    original = _news_module.NEWS_FILE
    try:
        _news_module.NEWS_FILE = Path("/tmp/nonexistent_news_file_12345.json")
        result = _news_module.load_news()
        assert result == [], f"Expected [], got {result}"
    finally:
        _news_module.NEWS_FILE = original


run_test("missing news file returns empty list", test_load_news_missing_file)


# ─────────────────────────────────────────────────────────
# Section 7: Import smoke tests
# ─────────────────────────────────────────────────────────
print("\n[7] Import smoke tests")


def test_import_config():
    import src.config  # noqa: F401


def test_import_llm():
    import src.llm  # noqa: F401


def test_import_news():
    import src.news  # noqa: F401


def test_import_ai_summarizer():
    import src.ai_summarizer  # noqa: F401


def test_import_news_curator():
    import src.news_curator  # noqa: F401


def test_import_news_clusterer():
    import src.news_clusterer  # noqa: F401


def test_import_morning_briefer():
    import src.morning_briefer  # noqa: F401


def test_import_scheduler():
    import src.scheduler  # noqa: F401


def test_import_server():
    import src.server  # noqa: F401


run_test("import src.config", test_import_config)
run_test("import src.llm", test_import_llm)
run_test("import src.news", test_import_news)
run_test("import src.ai_summarizer", test_import_ai_summarizer)
run_test("import src.news_curator", test_import_news_curator)
run_test("import src.news_clusterer", test_import_news_clusterer)
run_test("import src.morning_briefer", test_import_morning_briefer)
run_test("import src.scheduler", test_import_scheduler)
run_test("import src.server", test_import_server)


# ─────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────
total = _passed + _failed
print(f"\n{'='*50}")
print(f"{_passed}/{total} tests passed", "✓" if _failed == 0 else "✗")
if _failed:
    print(f"{_failed} test(s) FAILED")
sys.exit(0 if _failed == 0 else 1)
