"""Main polling loop for the stock monitor."""

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from config import settings
from monitor.alerts import send_error_alert, send_out_of_stock_alert, send_stock_alert
from monitor.discovery import poll_category_pages
from monitor.health import log_poll_result, write_heartbeat
from monitor.scraper import fetch_product
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

            try:
                data = await fetch_product(client, url)
                polled += 1

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
                        logger.info("STOCK CHANGE: %s → InStock", product_id)
                    elif data.availability == "OutOfStock":
                        await send_out_of_stock_alert(data, state=state)
                        logger.info("STOCK CHANGE: %s → OutOfStock", product_id)

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

            except Exception as exc:
                polled += 1
                error_msg = f"{type(exc).__name__}: {exc}"
                logger.error("Poll failed for %s: %s", product_id, error_msg)

                await log_poll_result(
                    state,
                    product_id=product_id,
                    success=False,
                    error_message=error_msg,
                )

                product = await state.get_product(product_id)
                failures = (product.get("consecutive_failures") or 0) if product else 0
                await send_error_alert(
                    product_id=product_id,
                    error_msg=error_msg,
                    consecutive_failures=failures,
                    product_name=p.get("name"),
                    product_url=url,
                    state=state,
                )

        # Write heartbeat after each cycle
        await write_heartbeat(state, polled)
        await asyncio.sleep(settings.poll_interval_product)


async def poll_categories(state: StateManager, client: httpx.AsyncClient) -> None:
    """Poll category pages for new product discovery."""
    while True:
        try:
            new_ids = await poll_category_pages(client, state)
            if new_ids:
                logger.info("Category poll found %d new products", len(new_ids))
        except Exception:
            logger.exception("Category poll cycle failed")

        await asyncio.sleep(settings.poll_interval_category)


async def run() -> None:
    """Main entry point: start all polling tasks."""
    logger.info("Starting Pokemon TCG Stock Monitor")
    logger.info("Target: %s", settings.bol_base_url)
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
