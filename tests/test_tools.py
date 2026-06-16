"""
tests/test_tools.py

Tests for the FitFindr tools. The search_listings tests are deterministic and
assert on real behavior. The LLM-backed tools (suggest_outfit, create_fit_card)
are non-deterministic and require a live Groq key, so here we only assert on the
parts that do NOT call the API: the empty-outfit guard in create_fit_card.

Run with:
    pytest tests/
"""

import pytest

from tools import search_listings, create_fit_card
from utils.data_loader import load_listings


# ── search_listings: happy path ───────────────────────────────────────────────

def test_search_returns_relevant_results():
    """A common query returns a non-empty list of listing dicts."""
    results = search_listings("vintage graphic tee", None, None)
    assert isinstance(results, list)
    assert len(results) > 0
    # Every result is a full listing dict with the expected fields.
    first = results[0]
    for field in ("id", "title", "price", "size", "style_tags", "platform"):
        assert field in first


def test_search_sorted_by_relevance_descending():
    """Results are ordered best match first (non-increasing score)."""
    results = search_listings("vintage denim jacket", None, None)
    assert len(results) >= 2
    # The top result should clearly be denim-outerwear related.
    top = results[0]
    haystack = (top["title"] + " " + " ".join(top["style_tags"])).lower()
    assert "denim" in haystack or "jacket" in haystack


# ── search_listings: empty results (no exception) ─────────────────────────────

def test_search_no_match_returns_empty_list():
    """An impossible query returns [] and never raises."""
    results = search_listings("designer ballgown spacesuit", "XXS", 5)
    assert results == []


def test_search_nonsense_keywords_returns_empty_list():
    """Keywords with zero overlap score return []."""
    results = search_listings("xyzzy qwerty zzzz", None, None)
    assert results == []


# ── search_listings: price filter respected ───────────────────────────────────

def test_price_filter_excludes_expensive_items():
    """No returned item exceeds max_price."""
    max_price = 25.0
    results = search_listings("vintage", None, max_price)
    assert len(results) > 0
    assert all(item["price"] <= max_price for item in results)


def test_lower_price_ceiling_shrinks_results():
    """A stricter price ceiling returns a subset (<=) of a looser one."""
    loose = search_listings("vintage", None, 80)
    strict = search_listings("vintage", None, 20)
    assert len(strict) <= len(loose)
    assert all(item["price"] <= 20 for item in strict)


# ── search_listings: size filter respected ────────────────────────────────────

def test_size_filter_matches_case_insensitively():
    """Size filtering is case-insensitive substring matching."""
    results = search_listings("jacket", "m", None)
    assert all("m" in item["size"].lower() for item in results)


# ── create_fit_card: empty-outfit guard (no API call) ─────────────────────────

def test_create_fit_card_empty_outfit_returns_error_string():
    """An empty outfit returns a descriptive string, not an exception."""
    item = load_listings()[0]
    result = create_fit_card("", item)
    assert isinstance(result, str)
    assert "fit card" in result.lower()


def test_create_fit_card_whitespace_outfit_returns_error_string():
    """A whitespace-only outfit is treated as empty."""
    item = load_listings()[0]
    result = create_fit_card("   \n  ", item)
    assert isinstance(result, str)
    assert "generate an outfit first" in result.lower()
