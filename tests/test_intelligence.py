"""Tests for the keyword-based intelligence module."""

import pytest

from monitor.intelligence import KeywordEngine, get_upcoming_sets


def test_get_upcoming_sets_returns_list():
    """get_upcoming_sets now returns empty list (keywords are DB-driven)."""
    results = get_upcoming_sets()
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_keyword_engine_contains_match():
    engine = KeywordEngine()
    keywords = [
        {"keyword": "perfect order", "match_type": "contains"},
        {"keyword": "chaos rising", "match_type": "contains"},
    ]
    match = await engine.matches_any_keyword(
        "Pokemon Perfect Order Elite Trainer Box", keywords
    )
    assert match is not None
    assert match["keyword"] == "perfect order"


@pytest.mark.asyncio
async def test_keyword_engine_exact_match():
    engine = KeywordEngine()
    keywords = [
        {"keyword": "perfect order etb", "match_type": "exact"},
    ]
    # Exact match succeeds (case-insensitive)
    match = await engine.matches_any_keyword("Perfect Order ETB", keywords)
    assert match is not None

    # Partial string should NOT match exact
    match = await engine.matches_any_keyword(
        "Pokemon Perfect Order ETB Box", keywords
    )
    assert match is None


@pytest.mark.asyncio
async def test_keyword_engine_regex_match():
    engine = KeywordEngine()
    keywords = [
        {"keyword": r"mega \w+ ex", "match_type": "regex"},
    ]
    match = await engine.matches_any_keyword(
        "Mega Zygarde EX Premium Collection", keywords
    )
    assert match is not None

    match = await engine.matches_any_keyword("Regular Booster Box", keywords)
    assert match is None


@pytest.mark.asyncio
async def test_keyword_engine_no_match():
    engine = KeywordEngine()
    keywords = [
        {"keyword": "perfect order", "match_type": "contains"},
        {"keyword": "chaos rising", "match_type": "contains"},
    ]
    match = await engine.matches_any_keyword(
        "Pokemon Prismatic Evolutions", keywords
    )
    assert match is None


@pytest.mark.asyncio
async def test_keyword_engine_case_insensitive():
    engine = KeywordEngine()
    keywords = [{"keyword": "perfect order", "match_type": "contains"}]
    match = await engine.matches_any_keyword("PERFECT ORDER BOX", keywords)
    assert match is not None
