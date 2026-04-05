"""Games-Island.eu adapter — German shop with JSON-LD."""

from __future__ import annotations

import re
from urllib.parse import quote

from monitor.scraper import ProductData
from monitor.shops.base import ShopAdapter, parse_json_ld_product

RE_PRODUCT_LINK = re.compile(r'href="https?://(?:www\.)?games-island\.eu/p/([^"/?]+/[^"/?]+)')


class GamesIslandAdapter(ShopAdapter):
    shop_id = "games_island"
    base_url = "https://games-island.eu"

    def get_headers(self) -> dict[str, str]:
        headers = super().get_headers()
        headers["Accept-Language"] = "de-DE,de;q=0.9,nl;q=0.8,en;q=0.7"
        return headers

    def parse_product(self, html: str, url: str = "") -> ProductData:
        json_ld = parse_json_ld_product(html)
        if not json_ld:
            # Fallback: try German availability text
            html_lower = html.lower()
            availability = "Unknown"
            if "auf lager" in html_lower and "nicht auf lager" not in html_lower:
                availability = "InStock"
            elif "nicht auf lager" in html_lower or "ausverkauft" in html_lower:
                availability = "OutOfStock"

            name = None
            title_match = re.search(r'<title>([^<]+)</title>', html)
            if title_match:
                name = title_match.group(1).split(" | ")[0].strip()

            slug = url.rstrip("/").split("/")[-1] if url else ""
            return ProductData(
                product_id=slug, name=name, availability=availability
            )

        offers = json_ld.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        availability = "Unknown"
        if isinstance(offers, dict):
            avail_url = offers.get("availability", "")
            if "InStock" in avail_url:
                availability = "InStock"
            elif "OutOfStock" in avail_url:
                availability = "OutOfStock"
            # German text fallback
            elif "auf lager" in avail_url.lower():
                availability = "InStock"

        return ProductData(
            product_id=json_ld.get("productID", json_ld.get("sku", "")),
            name=json_ld.get("name"),
            price=offers.get("price") if isinstance(offers, dict) else None,
            availability=availability,
        )

    def parse_category(self, html: str) -> set[str]:
        return set(RE_PRODUCT_LINK.findall(html))

    def build_product_url(self, product_id: str) -> str:
        return f"{self.base_url}/p/{product_id}"

    def build_category_urls(self) -> list[str]:
        return [f"{self.base_url}/c/Pokemon"]

    def get_search_url(self, term: str) -> str:
        return f"{self.base_url}/search?search={quote(term)}"
