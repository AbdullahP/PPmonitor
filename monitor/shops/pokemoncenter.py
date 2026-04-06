"""Pokemon Center queue detection adapter.

This is a queue-only monitor — it does NOT scrape products.
It detects when the Pokemon Center virtual queue (Cloudflare
waiting room) is active and triggers alerts so users can join
the queue early.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.pokemoncenter.com"

QUEUE_INDICATORS = [
    "waiting-room",
    "queue-it",
    "queueit",
    "virtual queue",
    "waiting room",
    "your turn will come",
    "you are now in line",
    "queue position",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}


async def check_queue_status(client: httpx.AsyncClient) -> dict:
    """Check if the Pokemon Center queue/waiting room is active.

    Returns:
        dict with keys:
        - active (bool): whether queue is detected
        - url (str): final URL after redirects
        - status_code (int): HTTP status
        - error (str | None): error message if request failed
    """
    try:
        resp = await client.get(
            BASE_URL,
            headers=HEADERS,
            follow_redirects=True,
            timeout=10,
        )

        body_lower = resp.text.lower()
        queue_active = (
            any(ind in body_lower for ind in QUEUE_INDICATORS)
            or "queue-it.net" in str(resp.url)
        )

        return {
            "active": queue_active,
            "url": str(resp.url),
            "status_code": resp.status_code,
            "error": None,
        }
    except Exception as exc:
        logger.debug("Pokemon Center queue check failed: %s", exc)
        return {
            "active": False,
            "url": BASE_URL,
            "status_code": 0,
            "error": str(exc),
        }
