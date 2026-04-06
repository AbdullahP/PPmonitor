"""Amazon UK adapter — English Pokemon TCG products shipped to NL/BE."""

from __future__ import annotations

import re
from urllib.parse import quote

from monitor.scraper import ProductData
from monitor.shops.base import ShopAdapter

RE_ASIN = re.compile(r'"ASIN"\s*:\s*"([A-Z0-9]{10})"')
RE_PRODUCT_TITLE = re.compile(
    r'id="productTitle"[^>]*>\s*(.*?)\s*</span>', re.DOTALL
)
RE_PRICE_AMOUNT = re.compile(r'"priceAmount"\s*:\s*([0-9.]+)')
RE_PRICE_WHOLE = re.compile(r'<span class="a-price-whole">([0-9,]+)</span>')
RE_DATA_ASIN = re.compile(r'data-asin="([A-Z0-9]{10})"')
RE_AVAILABILITY = re.compile(
    r'id="availability"[^>]*>.*?<span[^>]*>\s*(.*?)\s*</span>', re.DOTALL
)

_INSTOCK_PHRASES = ("in stock", "usually dispatched", "only")


class AmazonUKAdapter(ShopAdapter):
    """Amazon.co.uk adapter for English Pokemon TCG products."""

    shop_id = "amazon_uk"
    base_url = "https://www.amazon.co.uk"

    def get_headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
        }

    def build_product_url(self, product_id: str) -> str:
        return f"{self.base_url}/dp/{product_id}"

    def build_category_urls(self) -> list[str]:
        return [
            f"{self.base_url}/s"
            "?k=pokemon+tcg+english"
            "&rh=n%3A300721"
            "&s=date-desc-rank"
        ]

    def get_search_url(self, term: str) -> str:
        return f"{self.base_url}/s?k={quote(term)}&s=date-desc-rank"

    def parse_product(self, html: str, url: str = "") -> ProductData:
        asin = self._extract_asin(html) or ""
        title = self._extract_title(html)

        # Availability from #availability span
        avail_match = RE_AVAILABILITY.search(html)
        avail_text = avail_match.group(1).strip().lower() if avail_match else ""
        is_in_stock = any(p in avail_text for p in _INSTOCK_PHRASES)

        # Price — try structured data first, then HTML
        price_match = RE_PRICE_AMOUNT.search(html)
        if not price_match:
            price_match = RE_PRICE_WHOLE.search(html)
        price = price_match.group(1).replace(",", "") if price_match else "0"

        return ProductData(
            product_id=asin,
            name=title,
            price=price,
            availability="InStock" if is_in_stock else "OutOfStock",
            offer_uid="",
            revision_id=avail_text,
        )

    def _extract_asin(self, html: str) -> str | None:
        m = RE_ASIN.search(html)
        return m.group(1) if m else None

    def _extract_title(self, html: str) -> str:
        m = RE_PRODUCT_TITLE.search(html)
        return m.group(1).strip() if m else ""

    def parse_category(self, html: str) -> set[str]:
        asins = RE_DATA_ASIN.findall(html)
        return set(dict.fromkeys(asins))

    def build_checkout_url(self, asin: str) -> str:
        return (
            f"{self.base_url}/gp/aws/cart/add.html"
            f"?ASIN.1={asin}&Quantity.1=1"
        )
