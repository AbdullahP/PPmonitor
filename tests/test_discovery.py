"""Tests for the auto-discovery module."""

import httpx
import pytest

from monitor.discovery import poll_category_pages
from monitor.scraper import parse_category_page


def test_parse_category_extracts_ids():
    html = """
    <div class="product-list">
      <a href="/nl/nl/p/pokemon-a/9300000111111111/" class="product-title">A</a>
      <a href="/nl/nl/p/pokemon-b/9300000222222222/" class="product-title">B</a>
      <a href="/nl/nl/p/pokemon-c/9300000333333333/" class="product-title">C</a>
    </div>
    """
    ids = parse_category_page(html)
    assert len(ids) == 3
    assert "9300000111111111" in ids


@pytest.mark.asyncio
async def test_poll_category_finds_new_products(mock_server_url, state, monkeypatch):
    from config import settings
    from monitor.shops.bol import BolAdapter

    # Patch both the adapter's base_url and the settings for category paths
    monkeypatch.setattr(settings, "bol_base_url", mock_server_url)
    monkeypatch.setattr(BolAdapter, "base_url", mock_server_url)

    async with httpx.AsyncClient() as client:
        new_ids = await poll_category_pages(client, state, shop="bol")

    # Mock server has 3+ seeded products, all should be new
    assert len(new_ids) >= 3
