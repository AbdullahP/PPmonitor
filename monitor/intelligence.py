"""Upcoming Pokemon TCG set intelligence — auto-monitors products before release."""

import logging
from datetime import date

import httpx

from monitor.shops.registry import get_adapter
from monitor.state import StateManager

logger = logging.getLogger(__name__)

DAYS_BEFORE_RELEASE = 14

KNOWN_UPCOMING_SETS = [
    {
        "name": "Perfect Order",
        "release_date": "2026-04-25",
        "search_terms": ["perfect order pokemon", "mega zygarde ex"],
        "shops": ["bol", "mediamarkt"],
        "auto_monitor": True,
    },
    {
        "name": "Mega Evolution Chaos Rising",
        "release_date": "2026-05-22",
        "search_terms": ["chaos rising pokemon", "mega greninja ex"],
        "shops": ["bol", "mediamarkt", "pocketgames"],
        "auto_monitor": True,
    },
]


def get_upcoming_sets() -> list[dict]:
    """Return sets with enriched countdown information."""
    today = date.today()
    result = []
    for s in KNOWN_UPCOMING_SETS:
        release = date.fromisoformat(s["release_date"])
        days_until = (release - today).days
        result.append({
            **s,
            "days_until_release": days_until,
            "is_within_window": 0 <= days_until <= DAYS_BEFORE_RELEASE,
            "is_released": days_until < 0,
        })
    return result


def _match_terms_in_text(text: str, terms: list[str]) -> bool:
    """Check if any search term partially matches the text."""
    text_lower = text.lower()
    return any(term.lower() in text_lower for term in terms)


async def scan_upcoming_sets(
    client: httpx.AsyncClient, state: StateManager
) -> list[dict]:
    """Scan shops for upcoming sets that are within the monitoring window.

    Returns a list of newly discovered products.
    """
    today = date.today()
    new_finds: list[dict] = []

    for set_info in KNOWN_UPCOMING_SETS:
        if not set_info.get("auto_monitor", False):
            continue

        release = date.fromisoformat(set_info["release_date"])
        days_until = (release - today).days

        if days_until < 0 or days_until > DAYS_BEFORE_RELEASE:
            continue

        logger.info(
            "Scanning for '%s' (releases in %d days) across %s",
            set_info["name"], days_until, set_info["shops"],
        )

        for shop_id in set_info["shops"]:
            try:
                adapter = get_adapter(shop_id)

                # Collect URLs: category pages + search pages for each term
                scan_urls = list(adapter.build_category_urls())
                for term in set_info.get("search_terms", []):
                    scan_urls.append(adapter.get_search_url(term))

                for scan_url in scan_urls:
                    try:
                        product_ids = await adapter.fetch_category(client, scan_url)
                    except Exception:
                        logger.debug("Scan fetch failed for %s: %s", shop_id, scan_url)
                        continue

                    for pid in product_ids:
                        # Check if we already know this product
                        known = await state.get_known_product_ids()
                        if pid in known:
                            continue

                        # Try to fetch and check if it matches search terms
                        try:
                            product_url = adapter.build_product_url(pid)
                            data = await adapter.fetch_product(client, product_url)
                            if data.name and _match_terms_in_text(
                                data.name, set_info["search_terms"]
                            ):
                                is_new = await state.add_discovered(
                                    pid, product_url,
                                    name=data.name,
                                    source=f"intelligence:{set_info['name']}",
                                    shop=shop_id,
                                )
                                if is_new:
                                    logger.info(
                                        "Intelligence found: '%s' at %s [%s]",
                                        data.name, shop_id, set_info["name"],
                                    )
                                    new_finds.append({
                                        "product_id": pid,
                                        "name": data.name,
                                        "shop": shop_id,
                                        "set_name": set_info["name"],
                                        "url": product_url,
                                    })
                        except Exception:
                            logger.debug(
                                "Failed to fetch product %s from %s", pid, shop_id
                            )
            except Exception:
                logger.exception(
                    "Intelligence scan failed for %s on %s", set_info["name"], shop_id
                )

    return new_finds
