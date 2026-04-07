"""Main polling loop for the stock monitor."""

import asyncio
import logging
import time
from datetime import date, datetime, timezone

import httpx

from config import settings
from monitor.alerts import send_error_alert, send_out_of_stock_alert, send_stock_alert
from monitor.health import log_poll_result, write_heartbeat
from monitor.intelligence import scan_upcoming_sets
from monitor.rate_limiter import all_limiter_statuses, get_limiter
from monitor.shops.registry import SHOP_REGISTRY, get_adapter
from monitor.state import StateManager

KEYWORD_SCAN_INTERVAL = 300  # 5 minutes
QUEUE_CHECK_INTERVAL = 60  # 1 minute
QUEUE_ALERT_COOLDOWN = 600  # 10 minutes between queue alerts
COOKIE_ALERT_COOLDOWN = 3600  # 1 hour between cookie expiry alerts
CHALLENGE_THRESHOLD = 5  # consecutive challenges before cookie alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Track consecutive Akamai challenges per shop for cookie expiry alerts
_challenge_counts: dict[str, int] = {}
_last_cookie_alert: dict[str, float] = {}


def get_poll_interval(product: dict) -> int:
    """Determine poll interval based on release_date proximity."""
    release_date = product.get("release_date")
    priority = product.get("poll_priority", "normal")

    if priority == "critical":
        return 5

    if release_date is None:
        return 0  # use default

    today = date.today()
    if isinstance(release_date, datetime):
        release_date = release_date.date()

    days_until = (release_date - today).days
    if days_until <= 1:
        return 5
    if days_until <= 7:
        return 10
    if days_until <= 30:
        return 30
    return 0  # use default


async def poll_products(state: StateManager, client: httpx.AsyncClient) -> None:
    """Poll all active products on a fixed interval."""
    # Give bol adapter access to DB for cookie loading
    try:
        from monitor.shops.bol import set_state_manager
        set_state_manager(state)
    except ImportError:
        pass

    while True:
        products = await state.list_products(active_only=True)
        polled = 0

        # Cache module states for this cycle
        try:
            _modules = {m["shop_id"]: m for m in await state.list_shop_modules()}
        except Exception:
            _modules = {}

        for p in products:
            product_id = p["product_id"]
            url = p["url"]
            shop = p.get("shop", "bol")

            # Skip if shop module is disabled or monitoring is off
            mod = _modules.get(shop)
            if mod and (not mod.get("is_active") or not mod.get("monitoring_enabled")):
                continue

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

                # Handle Amazon-style blocks — don't count as failure
                if data.availability == "Blocked":
                    await log_poll_result(
                        state, product_id=product_id, success=True,
                        latency_ms=data.latency_ms, availability="Blocked",
                    )
                    logger.warning("Blocked response for %s [%s]", product_id, shop)
                    continue

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
                            f"?shop={shop}&sku={data.product_id}&offer={data.offer_uid or ''}"
                        )
                        await send_stock_alert(data, redirect_url, state=state, shop=shop)
                        logger.info("STOCK CHANGE: %s [%s] → InStock", product_id, shop)
                    elif data.availability == "OutOfStock":
                        await send_out_of_stock_alert(data, state=state, shop=shop)
                        logger.info("STOCK CHANGE: %s [%s] → OutOfStock", product_id, shop)

                # Update product state
                update_fields = {
                    "name": data.name,
                    "price": data.price,
                    "offer_uid": data.offer_uid,
                    "last_availability": data.availability,
                    "last_revision_id": data.revision_id,
                    "last_polled_at": datetime.now(timezone.utc),
                }
                if data.seller:
                    update_fields["seller"] = data.seller
                await state.update_product(product_id, **update_fields)

            except httpx.HTTPStatusError as exc:
                polled += 1
                status_code = exc.response.status_code
                limiter.record_result(success=False, status_code=status_code)
                error_msg = f"HTTP {status_code} for {url}"
                logger.error("Poll failed for %s [%s]: %s", product_id, shop, error_msg)

                # Track Akamai challenges (403) for cookie expiry alert
                if status_code == 403 and "challenge" in str(exc).lower():
                    _challenge_counts[shop] = _challenge_counts.get(shop, 0) + 1
                    if _challenge_counts[shop] >= CHALLENGE_THRESHOLD:
                        now_ts = time.monotonic()
                        last = _last_cookie_alert.get(shop, 0)
                        if now_ts - last > COOKIE_ALERT_COOLDOWN:
                            from monitor.alerts import send_cookie_expiry_alert
                            await send_cookie_expiry_alert(shop, state=state)
                            _last_cookie_alert[shop] = now_ts
                            _challenge_counts[shop] = 0
                else:
                    _challenge_counts[shop] = 0

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
                error_msg = f"{type(exc).__name__}: {exc} — {url}"
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

        # Update per-shop module stats
        for shop_id in {p.get("shop", "bol") for p in products}:
            try:
                lim = get_limiter(shop_id)
                stats = lim.status_dict()
                update = {
                    "last_poll_at": datetime.now(timezone.utc),
                    "success_rate_pct": int(100 - stats.get("error_rate", 0)),
                    "avg_latency_ms": 0,
                }
                if stats.get("total_errors") and stats.get("total_requests"):
                    update["last_error_at"] = datetime.now(timezone.utc)
                await state.update_shop_module(shop_id, **update)
            except Exception:
                pass

        # Write heartbeat after each cycle
        shop_status = {s["shop_id"]: s for s in all_limiter_statuses()}
        await write_heartbeat(state, polled, shop_status=shop_status)

        # Use the minimum interval: consider per-product release-day escalation
        if products:
            shops_in_use = {p.get("shop", "bol") for p in products}
            shop_interval = min(get_limiter(s).current_interval() for s in shops_in_use)
            # Check if any product has a release-day escalated interval
            product_intervals = [get_poll_interval(p) for p in products]
            product_intervals = [i for i in product_intervals if i > 0]
            if product_intervals:
                interval = min(shop_interval, min(product_intervals))
            else:
                interval = shop_interval
        else:
            interval = settings.poll_interval_product
        await asyncio.sleep(interval)


async def poll_categories(state: StateManager, client: httpx.AsyncClient) -> None:
    """Poll category pages for all shops for new product discovery."""
    while True:
        try:
            _modules = {m["shop_id"]: m for m in await state.list_shop_modules()}
        except Exception:
            _modules = {}

        for shop_id, adapter_cls in SHOP_REGISTRY.items():
            # Skip if shop module has discovery disabled
            mod = _modules.get(shop_id)
            if mod and (not mod.get("is_active") or not mod.get("discovery_enabled")):
                continue

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


async def poll_keywords(state: StateManager, client: httpx.AsyncClient) -> None:
    """Periodically scan shops using keyword engine."""
    while True:
        try:
            new_finds = await scan_upcoming_sets(client, state)
            if new_finds:
                logger.info("Keyword scan found %d new products", len(new_finds))
                for find in new_finds:
                    if find.get("notify_discord", True):
                        from monitor.alerts import send_discovery_alert
                        await send_discovery_alert(
                            find["product_id"], find["url"],
                            name=find.get("name"), state=state,
                        )
        except Exception:
            logger.exception("Keyword scan cycle failed")

        await asyncio.sleep(KEYWORD_SCAN_INTERVAL)


async def poll_queue(state: StateManager, client: httpx.AsyncClient) -> None:
    """Check Pokemon Center queue status every 60 seconds."""
    from datetime import datetime, timezone
    from monitor.shops.pokemoncenter import check_queue_status

    while True:
        try:
            result = await check_queue_status(client)

            if result["active"]:
                # Check cooldown — don't spam alerts
                heartbeat = await state.get_last_heartbeat()
                last_alert = (
                    heartbeat.get("last_queue_alert") if heartbeat else None
                )
                now = datetime.now(timezone.utc)

                should_alert = True
                if last_alert:
                    elapsed = (now - last_alert).total_seconds()
                    if elapsed < QUEUE_ALERT_COOLDOWN:
                        should_alert = False
                        logger.debug(
                            "Queue active but cooldown (%ds remaining)",
                            QUEUE_ALERT_COOLDOWN - elapsed,
                        )

                if should_alert:
                    from monitor.alerts import send_queue_alert
                    await send_queue_alert(result["url"], state=state)
                    # Update last_queue_alert in heartbeat
                    async with state._pool.acquire() as conn:
                        await conn.execute(
                            """UPDATE system_heartbeat
                               SET last_queue_alert = $1
                               WHERE timestamp = (
                                   SELECT timestamp FROM system_heartbeat
                                   ORDER BY timestamp DESC LIMIT 1
                               )""",
                            now,
                        )
                    logger.info("Pokemon Center queue detected and alert sent")
        except Exception:
            logger.exception("Queue check failed")

        await asyncio.sleep(QUEUE_CHECK_INTERVAL)


async def run() -> None:
    """Main entry point: start all polling tasks."""
    import os

    logger.info("Starting Pokemon TCG Stock Monitor")
    logger.info("Shops: %s", list(SHOP_REGISTRY.keys()))
    logger.info("Product poll interval: %ds", settings.poll_interval_product)
    logger.info("Category poll interval: %ds", settings.poll_interval_category)

    # Check for bol.com cookie file (important for Akamai bypass)
    cookie_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bol_cookies.json")
    if os.path.exists(cookie_path):
        logger.info("bol_cookies.json: FOUND")
    else:
        logger.warning("bol_cookies.json: MISSING — product pages may get Akamai challenged. Upload cookies via Dashboard > Modules > bol > Cookies")

    state = await StateManager.create()
    client = httpx.AsyncClient(timeout=15)

    try:
        await asyncio.gather(
            poll_products(state, client),
            poll_categories(state, client),
            poll_keywords(state, client),
            poll_queue(state, client),
        )
    finally:
        await client.aclose()
        await state.close()


if __name__ == "__main__":
    asyncio.run(run())
