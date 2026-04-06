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
    from monitor.shops.bol import BolAdapter

    # Patch BolAdapter to use httpx (not curl_cffi) and point at mock server
    monkeypatch.setattr(BolAdapter, "base_url", mock_server_url)

    # Override build_category_urls to use mock server paths
    monkeypatch.setattr(
        BolAdapter, "build_category_urls",
        lambda self: [f"{mock_server_url}/nl/nl/l/pokemon-kaarten/N/8299+16410/"],
    )

    # Override fetch_category to use httpx instead of curl_cffi
    async def _httpx_fetch_category(self, client, url):
        resp = await client.get(url, headers=self.get_headers(), follow_redirects=True)
        resp.raise_for_status()
        return self.parse_category(resp.text)

    monkeypatch.setattr(BolAdapter, "fetch_category", _httpx_fetch_category)

    # Skip curl_cffi warmup (module-level state)
    import monitor.shops.bol as bol_mod
    monkeypatch.setattr(bol_mod, "_session_warmed", True)

    async with httpx.AsyncClient() as client:
        new_ids = await poll_category_pages(client, state, shop="bol")

    # Mock server has 3+ seeded products, all should be new
    assert len(new_ids) >= 3
