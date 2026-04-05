"""Main polling loop for the stock monitor."""

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from config import settings
from monitor.alerts import send_error_alert, send_out_of_stock_alert, send_stock_alert
from monitor.health import log_poll_result, write_heartbeat
from monitor.rate_limiter import get_limiter
from monitor.shops.registry import SHOP_REGISTRY, get_adapter
from monitor.state import StateManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def poll_products(state: StateManager, client: httpx.AsyncClient) -> None:
    """Poll all active products on a fixed interval."""
    while True:
        products = await state.list_products(active_only=True)
        polled = 0

        for p in products:
            product_id = p["product_id"]
            url = p["url"]
            shop = p.get("shop", "bol")

            limiter = get_limiter(shop)

            # Skip if this shop is paused (e.g. after a 403)
            if limiter.is_paused():
                logger.debug("Skipping %s [%s] — shop paused", product_id, shop)
                continue

            try:
                adapter = get_adapter(shop)
                data = await adapter.fetch_product(client, url)
                polled += 1
                limiter.record_result(success=True)

                await log_poll_result(
                    state,
                    product_id=product_id,
                    success=True,
                    latency_ms=data.latency_ms,
                    availability=data.availability,
                    revision_id=data.revision_id,
                )

                # Detect stock change
                old_availability = p.get("last_availability")
                if old_availability and old_availability != data.availability:
                    if data.availability == "InStock":
                        redirect_url = (
                            f"{settings.redirect_base_url}/go"
                            f"?sku={data.product_id}&offer={data.offer_uid or ''}"
                        )
                        await send_stock_alert(data, redirect_url, state=state)
                        logger.info("STOCK CHANGE: %s [%s] → InStock", product_id, shop)
                    elif data.availability == "OutOfStock":
                        await send_out_of_stock_alert(data, state=state)
                        logger.info("STOCK CHANGE: %s [%s] → OutOfStock", product_id, shop)

                # Update product state
                await state.update_product(
                    product_id,
                    name=data.name,
                    price=data.price,
                    offer_uid=data.offer_uid,
                    last_availability=data.availability,
                    last_revision_id=data.revision_id,
                    last_polled_at=datetime.now(timezone.utc),
                )

            except httpx.HTTPStatusError as exc:
                polled += 1
                limiter.record_result(success=False, status_code=exc.response.status_code)
                error_msg = f"{type(exc).__name__}: {exc.response.status_code}"
                logger.error("Poll failed for %s [%s]: %s", product_id, shop, error_msg)

                await log_poll_result(
                    state, product_id=product_id, success=False, error_message=error_msg,
                )

                product = await state.get_product(product_id)
                failures = (product.get("consecutive_failures") or 0) if product else 0
                await send_error_alert(
                    product_id=product_id, error_msg=error_msg,
                    consecutive_failures=failures, product_name=p.get("name"),
                    product_url=url, state=state,
                )

            except Exception as exc:
                polled += 1
                limiter.record_result(success=False)
                error_msg = f"{type(exc).__name__}: {exc}"
                logger.error("Poll failed for %s [%s]: %s", product_id, shop, error_msg)

                await log_poll_result(
                    state, product_id=product_id, success=False, error_message=error_msg,
                )

                product = await state.get_product(product_id)
                failures = (product.get("consecutive_failures") or 0) if product else 0
                await send_error_alert(
                    product_id=product_id, error_msg=error_msg,
                    consecutive_failures=failures, product_name=p.get("name"),
                    product_url=url, state=state,
                )

        # Write heartbeat after each cycle
        await write_heartbeat(state, polled)

        # Use the minimum interval across all active shops' limiters
        if products:
            shops_in_use = {p.get("shop", "bol") for p in products}
            interval = min(get_limiter(s).current_interval() for s in shops_in_use)
        else:
            interval = settings.poll_interval_product
        await asyncio.sleep(interval)


async def poll_categories(state: StateManager, client: httpx.AsyncClient) -> None:
    """Poll category pages for all shops for new product discovery."""
    while True:
        for shop_id, adapter_cls in SHOP_REGISTRY.items():
            try:
                adapter = adapter_cls()
                category_urls = adapter.build_category_urls()

                all_found: set[str] = set()
                for url in category_urls:
                    try:
                        ids = await adapter.fetch_category(client, url)
                        all_found.update(ids)
                        logger.debug(
                            "Category [%s] %s returned %d IDs", shop_id, url, len(ids)
                        )
                    except Exception:
                        logger.exception("Failed to fetch category: %s", url)

                if not all_found:
                    continue

                known_ids = await state.get_known_product_ids()
                new_ids = all_found - known_ids

                if new_ids:
                    logger.info(
                        "Discovered %d new product(s) from %s: %s",
                        len(new_ids), shop_id, new_ids,
                    )
                    for pid in new_ids:
                        product_url = adapter.build_product_url(pid)
                        is_new = await state.add_discovered(
                            pid, product_url, source="category", shop=shop_id
                        )
                        if is_new:
                            from monitor.alerts import send_discovery_alert
                            await send_discovery_alert(pid, product_url, state=state)

            except Exception:
                logger.exception("Category poll cycle failed for %s", shop_id)

        await asyncio.sleep(settings.poll_interval_category)


async def run() -> None:
    """Main entry point: start all polling tasks."""
    logger.info("Starting Pokemon TCG Stock Monitor")
    logger.info("Shops: %s", list(SHOP_REGISTRY.keys()))
    logger.info("Product poll interval: %ds", settings.poll_interval_product)
    logger.info("Category poll interval: %ds", settings.poll_interval_category)

    state = await StateManager.create()
    client = httpx.AsyncClient(timeout=15)

    try:
        await asyncio.gather(
            poll_products(state, client),
            poll_categories(state, client),
        )
    finally:
        await client.aclose()
        await state.close()


if __name__ == "__main__":
    asyncio.run(run())
