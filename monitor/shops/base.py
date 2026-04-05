"""Base class for all shop adapters."""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod

import httpx

from monitor.scraper import ProductData

logger = logging.getLogger(__name__)

RE_JSON_LD = re.compile(
    r'<script\s+type="application/ld\+json">\s*(.*?)\s*</script>',
    re.DOTALL,
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}


def parse_json_ld_product(html: str) -> dict | None:
    """Extract the first Product JSON-LD block from HTML."""
    for match in RE_JSON_LD.finditer(html):
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and data.get("@type") == "Product":
                return data
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Product":
                        return item
        except json.JSONDecodeError:
            continue
    return None


def availability_from_schema_url(url: str) -> str:
    """Map a schema.org availability URL to InStock/OutOfStock."""
    if "InStock" in url:
        return "InStock"
    if "OutOfStock" in url:
        return "OutOfStock"
    return "Unknown"


class ShopAdapter(ABC):
    """Base adapter that every shop must implement."""

    shop_id: str  # e.g. "bol", "mediamarkt"
    base_url: str  # e.g. "https://www.bol.com"

    def get_headers(self) -> dict[str, str]:
        return BROWSER_HEADERS.copy()

    @abstractmethod
    def parse_product(self, html: str, url: str = "") -> ProductData:
        """Parse a product page into ProductData."""

    @abstractmethod
    def parse_category(self, html: str) -> set[str]:
        """Parse a category page into a set of product IDs or handles."""

    @abstractmethod
    def build_product_url(self, product_id: str) -> str:
        """Build a full product URL from a product identifier."""

    @abstractmethod
    def build_category_urls(self) -> list[str]:
        """Return all category URLs to poll for this shop."""

    @abstractmethod
    def get_search_url(self, term: str) -> str:
        """Return the shop's search URL for a given search term."""

    async def fetch_product(
        self, client: httpx.AsyncClient, url: str
    ) -> ProductData:
        """Fetch and parse a product page. Override for custom fetch logic."""
        start = time.monotonic()
        resp = await client.get(
            url, headers=self.get_headers(), follow_redirects=True
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        resp.raise_for_status()

        data = self.parse_product(resp.text, url=url)
        data.latency_ms = latency_ms
        return data

    async def fetch_category(
        self, client: httpx.AsyncClient, url: str
    ) -> set[str]:
        """Fetch and parse a category page."""
        resp = await client.get(
            url, headers=self.get_headers(), follow_redirects=True
        )
        resp.raise_for_status()
        return self.parse_category(resp.text)
