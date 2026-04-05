"""Dreamland.nl adapter — Belgian toy chain, JSON-LD with HTML fallback."""

from __future__ import annotations

import re

from monitor.scraper import ProductData
from monitor.shops.base import ShopAdapter, availability_from_schema_url, parse_json_ld_product

RE_PRODUCT_LINK = re.compile(r'href="https?://(?:www\.)?dreamland\.be/e/[^"]*?/(\d+)')


class DreamlandAdapter(ShopAdapter):
    shop_id = "dreamland"
    base_url = "https://www.dreamland.be"

    def parse_product(self, html: str, url: str = "") -> ProductData:
        # Try JSON-LD first
        json_ld = parse_json_ld_product(html)
        if json_ld:
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

        # HTML fallback
        html_lower = html.lower()
        availability = "Unknown"
        if "in voorraad" in html_lower or "op voorraad" in html_lower:
            availability = "InStock"
        elif "uitverkocht" in html_lower or "niet beschikbaar" in html_lower:
            availability = "OutOfStock"

        name = None
        title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if title_match:
            name = title_match.group(1).strip()

        slug = url.rstrip("/").split("/")[-1] if url else ""
        return ProductData(product_id=slug, name=name, availability=availability)

    def parse_category(self, html: str) -> set[str]:
        return set(RE_PRODUCT_LINK.findall(html))

    def build_product_url(self, product_id: str) -> str:
        return f"{self.base_url}/e/nl/p/{product_id}"

    def build_category_urls(self) -> list[str]:
        return [f"{self.base_url}/e/nl/catalogsearch/result/?q=pokemon"]
