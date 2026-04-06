"""Bol.com adapter — uses curl_cffi to bypass Akamai bot protection.

Bol.com uses Akamai for bot detection which blocks standard httpx/requests
based on TLS fingerprint. curl_cffi impersonates Chrome's TLS stack.

Strategy: warm up a session with a search page (sets Akamai cookies),
then fetch product pages normally — they return full JSON-LD data.
"""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import quote

import httpx
from curl_cffi import requests as cffi_requests

from monitor.scraper import ProductData
from monitor.shops.base import ShopAdapter, parse_json_ld_product, availability_from_schema_url

logger = logging.getLogger(__name__)

RE_REVISION_ID = re.compile(r'\\?"revisionId\\?"\s*:\s*\\?"([a-f0-9-]+)\\?"')
RE_OFFER_UID = re.compile(r'\\?"offerUid\\?"\s*:\s*\\?"([a-f0-9-]+)\\?"')
RE_PRODUCT_ID = re.compile(r'/nl/nl/p/[^"]*?/(\d{7,})/')

# Shared session for Akamai cookie persistence
_session: cffi_requests.Session | None = None
_session_warmed: bool = False


def _get_session() -> cffi_requests.Session:
    global _session
    if _session is None:
        _session = cffi_requests.Session(impersonate="chrome131")
    return _session


async def _ensure_warmed() -> None:
    """Warm up the session with a search page to get Akamai cookies."""
    global _session_warmed
    if _session_warmed:
        return
    session = _get_session()
    try:
        resp = session.get(
            "https://www.bol.com/nl/nl/s/?searchtext=pokemon+tcg&view=list",
            timeout=15,
        )
        if resp.status_code == 200 and len(resp.text) > 10000:
            _session_warmed = True
            logger.info("Bol.com session warmed (Akamai cookies set)")
        else:
            logger.warning("Bol.com warmup returned HTTP %d (%d bytes)", resp.status_code, len(resp.text))
    except Exception:
        logger.warning("Bol.com session warmup failed")


class BolAdapter(ShopAdapter):
    shop_id = "bol"
    base_url = "https://www.bol.com"

    def parse_product(self, html: str, url: str = "") -> ProductData:
        """Parse a product page with JSON-LD data."""
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
                if price is not None:
                    price = str(price)
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
        return set(RE_PRODUCT_ID.findall(html))

    def build_product_url(self, product_id: str) -> str:
        return f"{self.base_url}/nl/nl/p/-/{product_id}/"

    def build_category_urls(self) -> list[str]:
        """Use search pages for discovery (category pages are Remix SPA)."""
        return [
            f"{self.base_url}/nl/nl/s/?searchtext=pokemon+tcg&view=list",
            f"{self.base_url}/nl/nl/s/?searchtext=pokemon+kaarten+elite+trainer+box&view=list",
        ]

    def get_search_url(self, term: str) -> str:
        return f"{self.base_url}/nl/nl/s/?searchtext={quote(term)}&view=list"

    async def fetch_product(
        self, client: httpx.AsyncClient, url: str
    ) -> ProductData:
        """Fetch product page using curl_cffi with warmed Akamai session."""
        start = time.monotonic()
        await _ensure_warmed()

        session = _get_session()
        try:
            resp = session.get(url, timeout=15)
            latency_ms = int((time.monotonic() - start) * 1000)

            if resp.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}",
                    request=httpx.Request("GET", url),
                    response=httpx.Response(resp.status_code),
                )

            # Check for challenge page (small response = Akamai block)
            if len(resp.text) < 5000:
                title_match = re.search(r"<title>(.*?)</title>", resp.text)
                title = title_match.group(1) if title_match else ""
                if "challenge" in title.lower() or "bol" == title.lower():
                    # Reset session and retry warmup
                    global _session_warmed, _session
                    _session_warmed = False
                    _session = None
                    logger.warning("Bol.com challenge page detected, resetting session")
                    raise httpx.HTTPStatusError(
                        "Akamai challenge page — session reset, will retry",
                        request=httpx.Request("GET", url),
                        response=httpx.Response(403),
                    )

            data = self.parse_product(resp.text, url=url)
            data.latency_ms = latency_ms
            return data

        except httpx.HTTPStatusError:
            raise
        except Exception as exc:
            raise httpx.HTTPStatusError(
                f"curl_cffi error: {exc}",
                request=httpx.Request("GET", url),
                response=httpx.Response(500),
            ) from exc

    async def fetch_category(
        self, client: httpx.AsyncClient, url: str
    ) -> set[str]:
        """Fetch search/category page using curl_cffi."""
        await _ensure_warmed()
        try:
            session = _get_session()
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                logger.warning("Bol.com category returned HTTP %d", resp.status_code)
                return set()
            return self.parse_category(resp.text)
        except Exception:
            logger.exception("Bol.com category fetch failed: %s", url)
            return set()
