"""Bol.com adapter — JSON-LD primary, reactRouterContext secondary."""

from __future__ import annotations

import re

from config import settings
from monitor.scraper import ProductData
from monitor.shops.base import ShopAdapter, availability_from_schema_url, parse_json_ld_product

RE_REVISION_ID = re.compile(r'\\?"revisionId\\?"\s*:\s*\\?"([a-f0-9-]+)\\?"')
RE_OFFER_UID = re.compile(r'\\?"offerUid\\?"\s*:\s*\\?"([a-f0-9-]+)\\?"')
RE_PRODUCT_HREF = re.compile(r'/nl/nl/p/[^/]+/(\d+)/')


class BolAdapter(ShopAdapter):
    shop_id = "bol"
    base_url = "https://www.bol.com"

    def parse_product(self, html: str, url: str = "") -> ProductData:
        json_ld = parse_json_ld_product(html)

        product_id = ""
        name = None
        price = None
        availability = "Unknown"
        seller = None

        if json_ld:
            product_id = json_ld.get("productID", "")
            name = json_ld.get("name")
            offers = json_ld.get("offers", {})
            if isinstance(offers, dict):
                price = offers.get("price")
                availability = availability_from_schema_url(
                    offers.get("availability", "")
                )
                seller_obj = offers.get("seller", {})
                if isinstance(seller_obj, dict):
                    seller = seller_obj.get("name")

        revision_match = RE_REVISION_ID.search(html)
        revision_id = revision_match.group(1) if revision_match else None

        offer_match = RE_OFFER_UID.search(html)
        offer_uid = offer_match.group(1) if offer_match else None

        return ProductData(
            product_id=product_id,
            name=name,
            price=price,
            availability=availability,
            offer_uid=offer_uid,
            revision_id=revision_id,
            seller=seller,
        )

    def parse_category(self, html: str) -> set[str]:
        return set(RE_PRODUCT_HREF.findall(html))

    def build_product_url(self, product_id: str) -> str:
        return f"{self.base_url}/nl/nl/p/-/{product_id}/"

    def build_category_urls(self) -> list[str]:
        return [f"{self.base_url}{path}" for path in settings.category_paths]
