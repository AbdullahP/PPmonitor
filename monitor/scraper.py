"""HTTP fetching + HTML parsing for bol.com product pages.

DEPRECATED: New code should use monitor.shops.get_adapter(shop_id) instead.
This module is kept for backwards compatibility and existing tests.
"""

import json
import logging
import re
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

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

# Regex patterns
RE_JSON_LD = re.compile(
    r'<script\s+type="application/ld\+json">\s*(.*?)\s*</script>',
    re.DOTALL,
)
RE_REVISION_ID = re.compile(r'\\?"revisionId\\?"\s*:\s*\\?"([a-f0-9-]+)\\?"')
RE_OFFER_UID = re.compile(r'\\?"offerUid\\?"\s*:\s*\\?"([a-f0-9-]+)\\?"')
RE_PRODUCT_HREF = re.compile(r'/nl/nl/p/[^/]+/(\d+)/')


@dataclass
class ProductData:
    product_id: str
    name: str | None = None
    price: str | None = None
    availability: str = "Unknown"  # "InStock" or "OutOfStock"
    offer_uid: str | None = None
    revision_id: str | None = None
    seller: str | None = None
    latency_ms: int = 0


def _parse_json_ld(html: str) -> dict | None:
    """Extract Product JSON-LD from HTML. Returns the parsed dict or None."""
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


def _parse_product_page(html: str) -> ProductData:
    """Parse a bol.com product page HTML into ProductData."""
    # PRIMARY: JSON-LD
    json_ld = _parse_json_ld(html)

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
            avail_url = offers.get("availability", "")
            if "InStock" in avail_url:
                availability = "InStock"
            elif "OutOfStock" in avail_url:
                availability = "OutOfStock"
            seller_obj = offers.get("seller", {})
            if isinstance(seller_obj, dict):
                seller = seller_obj.get("name")

    # SECONDARY: revisionId + offerUid from reactRouterContext
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


def parse_category_page(html: str) -> set[str]:
    """Extract product IDs from a category page."""
    return set(RE_PRODUCT_HREF.findall(html))


async def fetch_product(client: httpx.AsyncClient, url: str) -> ProductData:
    """Fetch a product page and parse it."""
    start = time.monotonic()
    resp = await client.get(url, headers=BROWSER_HEADERS, follow_redirects=True)
    latency_ms = int((time.monotonic() - start) * 1000)
    resp.raise_for_status()

    data = _parse_product_page(resp.text)
    data.latency_ms = latency_ms
    return data


async def fetch_category(client: httpx.AsyncClient, url: str) -> set[str]:
    """Fetch a category page and return product IDs found."""
    resp = await client.get(url, headers=BROWSER_HEADERS, follow_redirects=True)
    resp.raise_for_status()
    return parse_category_page(resp.text)
