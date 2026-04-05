"""Health monitoring: poll logging, heartbeat, status calculation."""

import logging
from datetime import datetime, timedelta, timezone

from monitor.state import StateManager

logger = logging.getLogger(__name__)

UNHEALTHY_THRESHOLD = timedelta(seconds=45)
SLOW_THRESHOLD = timedelta(seconds=20)
CRITICAL_HEARTBEAT_GAP = timedelta(minutes=2)


async def log_poll_result(
    state: StateManager,
    product_id: str,
    success: bool,
    latency_ms: int | None = None,
    error_message: str | None = None,
    availability: str | None = None,
    revision_id: str | None = None,
) -> None:
    """Write a poll result to poll_log and update product state."""
    await state.log_poll(
        product_id=product_id,
        success=success,
        latency_ms=latency_ms,
        error_message=error_message,
        availability=availability,
        revision_id=revision_id,
    )

    if success:
        await state.update_product(
            product_id,
            last_polled_at=datetime.now(timezone.utc),
            consecutive_failures=0,
        )
    else:
        product = await state.get_product(product_id)
        if product:
            failures = (product.get("consecutive_failures") or 0) + 1
            await state.update_product(
                product_id,
                last_polled_at=datetime.now(timezone.utc),
                consecutive_failures=failures,
            )


async def write_heartbeat(state: StateManager, products_polled_count: int, shop_status: dict | None = None) -> None:
    await state.write_heartbeat(products_polled_count, shop_status=shop_status)


def get_product_status(last_polled_at: datetime | None, latency_ms: int | None) -> str:
    """Returns 'healthy', 'slow', or 'dead'."""
    if last_polled_at is None:
        return "dead"

    now = datetime.now(timezone.utc)
    if last_polled_at.tzinfo is None:
        last_polled_at = last_polled_at.replace(tzinfo=timezone.utc)

    age = now - last_polled_at
    if age > UNHEALTHY_THRESHOLD:
        return "dead"
    if latency_ms is not None and latency_ms > SLOW_THRESHOLD.total_seconds() * 1000:
        return "slow"
    return "healthy"


async def get_system_health(state: StateManager) -> dict:
    """Overall system health check."""
    try:
        heartbeat = await state.get_last_heartbeat()
    except Exception:
        logger.exception("Failed to get last heartbeat")
        heartbeat = None

    try:
        products = await state.list_products(active_only=True)
    except Exception:
        logger.exception("Failed to list products for health check")
        products = []

    now = datetime.now(timezone.utc)
    monitor_alive = False
    if heartbeat and heartbeat.get("timestamp"):
        hb_ts = heartbeat["timestamp"]
        if hb_ts.tzinfo is None:
            hb_ts = hb_ts.replace(tzinfo=timezone.utc)
        monitor_alive = (now - hb_ts) < CRITICAL_HEARTBEAT_GAP

    healthy = 0
    slow = 0
    dead = 0
    for p in products:
        status = get_product_status(p.get("last_polled_at"), None)
        if status == "healthy":
            healthy += 1
        elif status == "slow":
            slow += 1
        else:
            dead += 1

    return {
        "monitor_alive": monitor_alive,
        "total_products": len(products),
        "healthy": healthy,
        "slow": slow,
        "dead": dead,
        "last_heartbeat": heartbeat,
    }
