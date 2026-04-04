"""Auto-discovery of new Pokemon products via category page polling."""

import logging

import httpx

from config import settings
from monitor.alerts import send_discovery_alert
from monitor.scraper import fetch_category
from monitor.state import StateManager

logger = logging.getLogger(__name__)


async def poll_category_pages(
    client: httpx.AsyncClient, state: StateManager
) -> set[str]:
    """Fetch all configured category URLs and return newly discovered product IDs."""
    all_found_ids: set[str] = set()

    for path in settings.category_paths:
        url = f"{settings.bol_base_url}{path}"
        try:
            ids = await fetch_category(client, url)
            all_found_ids.update(ids)
            logger.debug("Category %s returned %d product IDs", path, len(ids))
        except Exception:
            logger.exception("Failed to fetch category page: %s", url)

    if not all_found_ids:
        return set()

    known_ids = await state.get_known_product_ids()
    new_ids = all_found_ids - known_ids

    if new_ids:
        logger.info("Discovered %d new product(s): %s", len(new_ids), new_ids)
        await process_new_discoveries(new_ids, state)

    return new_ids


async def process_new_discoveries(new_ids: set[str], state: StateManager) -> None:
    """Insert newly discovered products and send alerts."""
    for product_id in new_ids:
        url = f"{settings.bol_base_url}/nl/nl/p/-/{product_id}/"
        is_new = await state.add_discovered(product_id, url, source="category")
        if is_new:
            await send_discovery_alert(product_id, url, state=state)
