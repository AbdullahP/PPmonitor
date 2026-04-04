"""Discord webhook alert sender."""

import logging
from datetime import datetime, timezone

import httpx

from config import settings
from monitor.scraper import ProductData
from monitor.state import StateManager

logger = logging.getLogger(__name__)

ERROR_ALERT_THRESHOLD = 3  # Fire error alert after N consecutive failures


async def _post_webhook(webhook_url: str, payload: dict) -> None:
    if not settings.discord_enabled:
        logger.info("Discord disabled, skipping webhook post")
        return
    if not webhook_url:
        logger.warning("Webhook URL not configured, skipping alert")
        return
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(webhook_url, json=payload)
        if resp.status_code >= 400:
            logger.error("Webhook POST failed: %s %s", resp.status_code, resp.text)


async def send_stock_alert(
    product: ProductData, redirect_url: str, state: StateManager | None = None
) -> None:
    """Stock available alert → public webhook with @everyone."""
    embed = {
        "title": f"IN STOCK: {product.name or product.product_id}",
        "description": (
            f"**Price:** \u20ac{product.price or '?'}\n"
            f"**Seller:** {product.seller or 'Unknown'}"
        ),
        "url": redirect_url,
        "color": 0x00FF00,
        "fields": [
            {"name": "Quick Buy", "value": f"[Add to Cart]({redirect_url})", "inline": True},
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload = {
        "content": "@everyone Pokemon TCG stock detected!",
        "embeds": [embed],
    }
    await _post_webhook(settings.discord_webhook_url, payload)

    if state:
        msg = f"Stock alert: {product.name} - InStock - {redirect_url}"
        await state.log_alert(product.product_id, "stock_change", msg)
    logger.info("Stock alert sent for %s", product.product_id)


async def send_out_of_stock_alert(
    product: ProductData, state: StateManager | None = None
) -> None:
    """Product went out of stock → public webhook, no ping."""
    embed = {
        "title": f"OUT OF STOCK: {product.name or product.product_id}",
        "description": f"**Price:** \u20ac{product.price or '?'}",
        "color": 0xFF0000,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload = {"embeds": [embed]}
    await _post_webhook(settings.discord_webhook_url, payload)

    if state:
        msg = f"OOS alert: {product.name} - OutOfStock"
        await state.log_alert(product.product_id, "stock_change", msg)
    logger.info("Out-of-stock alert sent for %s", product.product_id)


async def send_error_alert(
    product_id: str,
    error_msg: str,
    consecutive_failures: int,
    product_name: str | None = None,
    product_url: str | None = None,
    state: StateManager | None = None,
) -> None:
    """Error alert → admin webhook. Only fires after ERROR_ALERT_THRESHOLD failures."""
    if consecutive_failures < ERROR_ALERT_THRESHOLD:
        return

    embed = {
        "title": f"Monitor Error: {product_name or product_id}",
        "description": (
            f"**Consecutive failures:** {consecutive_failures}\n"
            f"**Error:** {error_msg[:500]}\n"
            f"**URL:** {product_url or 'N/A'}"
        ),
        "color": 0xFF6600,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload = {"embeds": [embed]}
    await _post_webhook(settings.discord_admin_webhook, payload)

    if state:
        msg = f"Error alert: {product_id} - {consecutive_failures} failures - {error_msg[:200]}"
        await state.log_alert(product_id, "error", msg)
    logger.warning("Error alert sent for %s (%d failures)", product_id, consecutive_failures)


async def send_discovery_alert(
    product_id: str, url: str, name: str | None = None, state: StateManager | None = None
) -> None:
    """New product discovered → discovery webhook."""
    embed = {
        "title": f"New Product: {name or product_id}",
        "description": f"**Product ID:** {product_id}\n**URL:** {url}",
        "url": url,
        "color": 0x0099FF,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload = {"embeds": [embed]}
    await _post_webhook(settings.discord_discovery_webhook, payload)

    if state:
        msg = f"Discovery: {product_id} - {url}"
        await state.log_alert(product_id, "discovery", msg)
    logger.info("Discovery alert sent for %s", product_id)
