"""CatchYourCards.nl adapter — WordPress HTML parsing fallback."""

from __future__ import annotations

import re

from monitor.scraper import ProductData
from monitor.shops.base import ShopAdapter

RE_PRODUCT_LINK = re.compile(r'href="https?://(?:www\.)?catchyourcards\.nl/product/([^"/?]+)')


class CatchYourCardsAdapter(ShopAdapter):
    shop_id = "catchyourcards"
    base_url = "https://catchyourcards.nl"

    def parse_product(self, html: str, url: str = "") -> ProductData:
        html_lower = html.lower()

        # Determine availability from Dutch stock text or add-to-cart button
        availability = "Unknown"
        if "op voorraad" in html_lower and "niet op voorraad" not in html_lower:
            availability = "InStock"
        elif "niet op voorraad" in html_lower or "uitverkocht" in html_lower:
            availability = "OutOfStock"
        elif 'name="add-to-cart"' in html or "add_to_cart" in html:
            availability = "InStock"

        name = None
        title_match = re.search(r'<h1[^>]*class="product_title[^"]*"[^>]*>([^<]+)</h1>', html)
        if title_match:
            name = title_match.group(1).strip()

        price = None
        price_match = re.search(
            r'<span class="woocommerce-Price-amount[^"]*">[^<]*<bdi>(?:[^<]*?)(\d+[.,]\d{2})</bdi>',
            html,
        )
        if price_match:
            price = price_match.group(1)

        # Extract product ID from URL slug
        slug = url.rstrip("/").split("/")[-1] if url else ""

        return ProductData(
            product_id=slug,
            name=name,
            price=price,
            availability=availability,
        )

    def parse_category(self, html: str) -> set[str]:
        return set(RE_PRODUCT_LINK.findall(html))

    def build_product_url(self, product_id: str) -> str:
        return f"{self.base_url}/product/{product_id}/"

    def build_category_urls(self) -> list[str]:
        return [f"{self.base_url}/product-category/pokemon/"]
