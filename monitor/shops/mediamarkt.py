"""MediaMarkt.nl adapter — Apollo GraphQL __PRELOADED_STATE__ parser."""

from __future__ import annotations

import json
import logging
import re

from monitor.scraper import ProductData
from monitor.shops.base import ShopAdapter

logger = logging.getLogger(__name__)

RE_PRELOADED_STATE = re.compile(
    r'window\.__PRELOADED_STATE__\s*=\s*({.*?});\s*</script>',
    re.DOTALL,
)
RE_PRODUCT_ID_FROM_URL = re.compile(r'_(\d+)\.html')
RE_CATEGORY_PRODUCT = re.compile(r'/nl/product/_[^"]+?-(\d+)\.html')


class MediaMarktAdapter(ShopAdapter):
    shop_id = "mediamarkt"
    base_url = "https://www.mediamarkt.nl"

    def parse_product(self, html: str, url: str = "") -> ProductData:
        product_id = ""
        id_match = RE_PRODUCT_ID_FROM_URL.search(url)
        if id_match:
            product_id = id_match.group(1)

        name = None
        title_match = re.search(r'<title>([^<]+)</title>', html)
        if title_match:
            name = title_match.group(1).split(" | ")[0].strip()

        # Parse __PRELOADED_STATE__ for availability
        availability = "Unknown"
        state_match = RE_PRELOADED_STATE.search(html)
        if state_match:
            try:
                state_data = json.loads(state_match.group(1))
                # Look for Availability keys in the Apollo cache
                for key, value in state_data.items():
                    if key.startswith(f"Availability:Media:{product_id}") or (
                        "Availability" in key and product_id in key
                    ):
                        uber = value.get("uber")
                        # uber == null means in stock, object means out of stock
                        if uber is None:
                            availability = "InStock"
                        else:
                            availability = "OutOfStock"
                        break
            except (json.JSONDecodeError, AttributeError):
                logger.debug("Failed to parse __PRELOADED_STATE__ for %s", url)

        # Try price from meta tag
        price = None
        price_match = re.search(
            r'<meta[^>]+property="product:price:amount"[^>]+content="([^"]+)"', html
        )
        if price_match:
            price = price_match.group(1)

        return ProductData(
            product_id=product_id,
            name=name,
            price=price,
            availability=availability,
        )

    def parse_category(self, html: str) -> set[str]:
        return set(RE_CATEGORY_PRODUCT.findall(html))

    def build_product_url(self, product_id: str) -> str:
        return f"{self.base_url}/nl/product/_pokemon-{product_id}.html"

    def build_category_urls(self) -> list[str]:
        return [
            f"{self.base_url}/nl/search.html?query=pokemon&sort=date",
        ]
