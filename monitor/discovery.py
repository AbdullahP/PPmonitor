"""Auto-discovery of new Pokemon products via category page polling.

DEPRECATED: Category polling is now handled directly in poller.py via the
shop adapter registry. This module is kept for backwards compatibility only.
"""

import logging

import httpx

from monitor.shops.registry import get_adapter
from monitor.state import StateManager

logger = logging.getLogger(__name__)


async def poll_category_pages(
    client: httpx.AsyncClient, state: StateManager, shop: str = "bol"
) -> set[str]:
    """Fetch category URLs for a single shop and return newly discovered product IDs."""
    adapter = get_adapter(shop)
    all_found_ids: set[str] = set()

    for url in adapter.build_category_urls():
        try:
            ids = await adapter.fetch_category(client, url)
            all_found_ids.update(ids)
            logger.debug("Category %s returned %d product IDs", url, len(ids))
        except Exception:
            logger.exception("Failed to fetch category page: %s", url)

    if not all_found_ids:
        return set()

    known_ids = await state.get_known_product_ids()
    new_ids = all_found_ids - known_ids

    if new_ids:
        logger.info("Discovered %d new product(s): %s", len(new_ids), new_ids)
        await process_new_discoveries(new_ids, state, adapter, shop)

    return new_ids


async def process_new_discoveries(
    new_ids: set[str], state: StateManager, adapter, shop: str
) -> None:
    """Insert newly discovered products and send alerts."""
    from monitor.alerts import send_discovery_alert

    for product_id in new_ids:
        url = adapter.build_product_url(product_id)
        is_new = await state.add_discovered(product_id, url, source="category", shop=shop)
        if is_new:
            await send_discovery_alert(product_id, url, state=state)
