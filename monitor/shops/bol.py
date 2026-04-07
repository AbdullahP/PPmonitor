"""Bol.com adapter — uses curl_cffi to bypass Akamai bot protection.

Bol.com uses Akamai for bot detection which blocks standard httpx/requests
based on TLS fingerprint. curl_cffi impersonates Chrome's TLS stack.

Two strategies for product data:
1. Direct product pages — requires Akamai cookies (_abck, ak_bmsc, bm_sz)
   loaded from DB or bol_cookies.json. Gives full JSON-LD (name, price, avail).
2. Search fallback — works without cookies, finds products by ID via search.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import quote

import httpx
from curl_cffi import requests as cffi_requests

from monitor.scraper import ProductData
from monitor.shops.base import ShopAdapter, parse_json_ld_product, availability_from_schema_url

logger = logging.getLogger(__name__)

RE_REVISION_ID = re.compile(r'\\?"revisionId\\?"\s*:\s*\\?"([a-f0-9-]+)\\?"')
RE_OFFER_UID = re.compile(r'\\?"offerUid\\?"\s*:\s*\\?"([a-f0-9-]+)\\?"')
RE_PRODUCT_ID = re.compile(r'/nl/nl/p/[^"]*?/(\d{7,})/')

# Cookie file path (optional — fallback if DB has no cookies)
_COOKIE_FILE = Path(__file__).resolve().parent.parent.parent / "bol_cookies.json"

# Shared session
_session: cffi_requests.Session | None = None
_session_ready: bool = False
# StateManager reference, set by poller before first fetch
_state_manager = None


def set_state_manager(state) -> None:
    """Called by poller to give bol adapter access to DB cookies."""
    global _state_manager
    _state_manager = state


def _get_session() -> cffi_requests.Session:
    global _session, _session_ready
    if _session is None:
        _session = cffi_requests.Session(impersonate="chrome131")
        _load_cookies_from_file(_session)
    return _session


def _load_cookies_from_file(session: cffi_requests.Session) -> None:
    """Load Akamai cookies from bol_cookies.json (fallback if DB empty)."""
    global _session_ready
    if not _COOKIE_FILE.exists():
        logger.debug("No bol_cookies.json found — will try DB or search fallback")
        return
    try:
        cookies_data = json.loads(_COOKIE_FILE.read_text(encoding="utf-8"))
        for c in cookies_data:
            session.cookies.set(
                c["name"], c["value"],
                domain=c.get("domain", ".bol.com"),
            )
        _session_ready = True
        logger.info("Loaded %d Akamai cookies from bol_cookies.json", len(cookies_data))
    except Exception:
        logger.warning("Failed to load bol_cookies.json", exc_info=True)


async def _load_cookies_from_db(session: cffi_requests.Session) -> bool:
    """Load cookies from DB. Returns True if cookies were loaded."""
    global _session_ready
    if _state_manager is None:
        return False
    try:
        cookies = await _state_manager.get_shop_cookies("bol")
        if not cookies:
            return False
        for c in cookies:
            session.cookies.set(
                c["cookie_name"], c["cookie_value"],
                domain=c.get("domain", ".bol.com"),
            )
        _session_ready = True
        logger.info("Loaded %d Akamai cookies from DB", len(cookies))
        return True
    except Exception:
        logger.warning("Failed to load cookies from DB", exc_info=True)
        return False


async def _ensure_session() -> None:
    """Ensure the session has valid cookies — DB first, then file, then warmup."""
    global _session_ready
    if _session_ready:
        return
    session = _get_session()

    # Try DB cookies first
    if not _session_ready:
        await _load_cookies_from_db(session)

    if _session_ready:
        return

    # Warmup via search page
    try:
        resp = session.get(
            "https://www.bol.com/nl/nl/s/?searchtext=pokemon+tcg&view=list",
            timeout=15,
        )
        if resp.status_code == 200 and len(resp.text) > 10000:
            _session_ready = True
            logger.info("Bol.com session warmed via search")
        else:
            logger.warning("Bol.com warmup: HTTP %d (%d bytes)", resp.status_code, len(resp.text))
    except Exception:
        logger.warning("Bol.com session warmup failed")


class BolAdapter(ShopAdapter):
    shop_id = "bol"
    base_url = "https://www.bol.com"

    def parse_product(self, html: str, url: str = "") -> ProductData:
        """Parse a product page — JSON-LD primary."""
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
        """Search pages for discovery (category pages are Remix SPA)."""
        return [
            f"{self.base_url}/nl/nl/s/?searchtext=pokemon+tcg&view=list",
            f"{self.base_url}/nl/nl/s/?searchtext=pokemon+kaarten+elite+trainer+box&view=list",
        ]

    def get_search_url(self, term: str) -> str:
        return f"{self.base_url}/nl/nl/s/?searchtext={quote(term)}&view=list"

    async def fetch_product(
        self, client: httpx.AsyncClient, url: str
    ) -> ProductData:
        """Fetch product page via curl_cffi with Akamai bypass."""
        start = time.monotonic()
        await _ensure_session()
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

            # Detect Akamai challenge page (small response)
            if len(resp.text) < 5000:
                global _session_ready, _session
                _session_ready = False
                _session = None
                logger.warning("Bol.com challenge page — session reset")
                raise httpx.HTTPStatusError(
                    "Akamai challenge page — will retry next cycle",
                    request=httpx.Request("GET", url),
                    response=httpx.Response(403),
                )

            data = self.parse_product(resp.text, url=url)
            data.latency_ms = latency_ms

            # If JSON-LD didn't have the product ID, extract from URL
            if not data.product_id:
                pid_match = re.search(r"(\d{7,})", url)
                if pid_match:
                    data.product_id = pid_match.group(1)

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
        """Fetch search/category page via curl_cffi."""
        await _ensure_session()
        try:
            session = _get_session()
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                logger.warning("Bol.com category HTTP %d", resp.status_code)
                return set()
            return self.parse_category(resp.text)
        except Exception:
            logger.exception("Bol.com category fetch failed: %s", url)
            return set()
