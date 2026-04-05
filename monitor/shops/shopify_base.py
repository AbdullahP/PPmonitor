"""Reusable base for all Shopify-powered shops."""

from __future__ import annotations

import logging
import time
from urllib.parse import quote

import httpx

from monitor.scraper import ProductData
from monitor.shops.base import ShopAdapter, availability_from_schema_url, parse_json_ld_product

logger = logging.getLogger(__name__)


class ShopifyAdapter(ShopAdapter):
    """Base adapter for Shopify stores.

    Subclasses only need to set shop_id, base_url, and category_paths.
    The Shopify JSON API (/products/{handle}.json) is used as a fast path
    before falling back to HTML + JSON-LD parsing.
    """

    category_paths: list[str] = []
    search_path: str = "/search?q={term}&sort_by=created-descending"

    def _extract_handle_from_url(self, url: str) -> str | None:
        """Extract the product handle from a /products/{handle} URL."""
        # e.g. https://pocketgames.nl/products/some-pokemon-box
        parts = url.rstrip("/").split("/")
        try:
            idx = parts.index("products")
            return parts[idx + 1] if idx + 1 < len(parts) else None
        except ValueError:
            return None

    def parse_product(self, html: str, url: str = "") -> ProductData:
        """Fallback HTML parser using JSON-LD."""
        json_ld = parse_json_ld_product(html)
        if not json_ld:
            return ProductData(product_id="", availability="Unknown")

        offers = json_ld.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        return ProductData(
            product_id=json_ld.get("productID", json_ld.get("sku", "")),
            name=json_ld.get("name"),
            price=offers.get("price") if isinstance(offers, dict) else None,
            availability=availability_from_schema_url(
                offers.get("availability", "") if isinstance(offers, dict) else ""
            ),
        )

    def _parse_shopify_json(self, data: dict) -> ProductData:
        """Parse the Shopify /products/{handle}.json response."""
        product = data.get("product", {})
        variants = product.get("variants", [])

        any_available = any(v.get("available", False) for v in variants)
        price = variants[0].get("price") if variants else None

        return ProductData(
            product_id=str(product.get("id", "")),
            name=product.get("title"),
            price=price,
            availability="InStock" if any_available else "OutOfStock",
        )

    async def fetch_product(
        self, client: httpx.AsyncClient, url: str
    ) -> ProductData:
        """Try Shopify JSON API first, fall back to HTML."""
        handle = self._extract_handle_from_url(url)
        start = time.monotonic()

        if handle:
            json_url = f"{self.base_url}/products/{handle}.json"
            try:
                resp = await client.get(
                    json_url, headers=self.get_headers(), follow_redirects=True
                )
                if resp.status_code == 200:
                    latency_ms = int((time.monotonic() - start) * 1000)
                    data = self._parse_shopify_json(resp.json())
                    data.latency_ms = latency_ms
                    return data
            except Exception:
                logger.debug("Shopify JSON API failed for %s, falling back to HTML", handle)

        # Fallback to HTML
        resp = await client.get(
            url, headers=self.get_headers(), follow_redirects=True
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        resp.raise_for_status()
        data = self.parse_product(resp.text, url=url)
        data.latency_ms = latency_ms
        return data

    def parse_category(self, html: str) -> set[str]:
        """Extract product handles from Shopify collection page links."""
        import re
        return set(re.findall(r'/products/([\w-]+)', html))

    def build_product_url(self, product_id: str) -> str:
        return f"{self.base_url}/products/{product_id}"

    def build_category_urls(self) -> list[str]:
        return [f"{self.base_url}{path}" for path in self.category_paths]

    def get_search_url(self, term: str) -> str:
        return f"{self.base_url}{self.search_path.format(term=quote(term))}"
