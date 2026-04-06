"""Amazon NL and DE adapters — JSON-LD primary, HTML fallback."""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from monitor.scraper import ProductData
from monitor.shops.base import ShopAdapter, parse_json_ld_product, availability_from_schema_url

RE_ASIN = re.compile(r'"ASIN"\s*:\s*"([A-Z0-9]{10})"')
RE_PRODUCT_TITLE = re.compile(
    r'id="productTitle"[^>]*>\s*(.*?)\s*</span>', re.DOTALL
)
RE_PRICE = re.compile(r'"price"\s*:\s*"([0-9.]+)"')
RE_DATA_ASIN = re.compile(r'data-asin="([A-Z0-9]{10})"')
RE_AVAILABILITY = re.compile(
    r'id="availability"[^>]*>.*?<span[^>]*>(.*?)</span>', re.DOTALL
)

_NL_INSTOCK_WORDS = ("in stock", "op voorraad", "beschikbaar", "in voorraad")


class AmazonNLAdapter(ShopAdapter):
    """Amazon.nl adapter for Pokemon TCG products."""

    shop_id = "amazon_nl"
    base_url = "https://www.amazon.nl"

    def get_headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
        }

    def build_product_url(self, product_id: str) -> str:
        return f"{self.base_url}/dp/{product_id}"

    def build_category_urls(self) -> list[str]:
        return [
            f"{self.base_url}/s?k=pokemon+kaarten+tcg"
            "&rh=n%3A1887278031"
            "&s=date-desc-rank"
        ]

    def get_search_url(self, term: str) -> str:
        return f"{self.base_url}/s?k={quote(term)}&s=date-desc-rank"

    def parse_product(self, html: str, url: str = "") -> ProductData:
        # Try JSON-LD first
        json_ld = parse_json_ld_product(html)
        if json_ld:
            offers = json_ld.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            avail_url = offers.get("availability", "")
            return ProductData(
                product_id=self._extract_asin(html) or "",
                name=json_ld.get("name", ""),
                price=str(offers.get("price", "0")),
                availability=availability_from_schema_url(avail_url),
                offer_uid="",
                revision_id="",
            )

        # Fallback: scrape availability text
        avail_match = RE_AVAILABILITY.search(html)
        if avail_match:
            text = avail_match.group(1).strip().lower()
            in_stock = any(w in text for w in _NL_INSTOCK_WORDS)
            return ProductData(
                product_id=self._extract_asin(html) or "",
                name=self._extract_title(html),
                price=self._extract_price(html),
                availability="InStock" if in_stock else "OutOfStock",
                offer_uid="",
                revision_id="",
            )

        # Minimal fallback
        return ProductData(
            product_id=self._extract_asin(html) or "",
            name=self._extract_title(html),
            price=self._extract_price(html),
            availability="Unknown",
        )

    def _extract_asin(self, html: str) -> str | None:
        m = RE_ASIN.search(html)
        return m.group(1) if m else None

    def _extract_title(self, html: str) -> str:
        m = RE_PRODUCT_TITLE.search(html)
        return m.group(1).strip() if m else ""

    def _extract_price(self, html: str) -> str:
        m = RE_PRICE.search(html)
        return m.group(1) if m else "0"

    def parse_category(self, html: str) -> set[str]:
        asins = RE_DATA_ASIN.findall(html)
        # Deduplicate while preserving order, then return as set
        return set(dict.fromkeys(asins))

    def build_checkout_url(self, asin: str) -> str:
        return (
            f"{self.base_url}/gp/aws/cart/add.html"
            f"?ASIN.1={asin}&Quantity.1=1"
        )


class AmazonDEAdapter(AmazonNLAdapter):
    """German Amazon — same logic, different domain."""

    shop_id = "amazon_de"
    base_url = "https://www.amazon.de"

    def build_category_urls(self) -> list[str]:
        return [
            f"{self.base_url}/s?k=pokemon+tcg+english"
            "&rh=n%3A1187276031"
            "&s=date-desc-rank"
        ]

    def get_headers(self) -> dict[str, str]:
        headers = super().get_headers()
        headers["Accept-Language"] = "de-DE,de;q=0.9,en;q=0.8"
        return headers
