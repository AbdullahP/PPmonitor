"""Discord webhook alert sender with delivery tracking."""

import asyncio
import json as _json
import logging
from datetime import datetime, timezone

import httpx

from config import settings
from monitor.scraper import ProductData
from monitor.state import StateManager

logger = logging.getLogger(__name__)

ERROR_ALERT_THRESHOLD = 3  # Fire error alert after N consecutive failures
WEBHOOK_DELAY = 1.0  # seconds between webhook calls to avoid rate limits

SHOP_EMOJI: dict[str, str] = {
    "bol": "\U0001f7e0",
    "mediamarkt": "\U0001f534",
    "pocketgames": "\U0001f7e3",
    "catchyourcards": "\U0001f7e1",
    "games_island": "\U0001f7e2",
    "dreamland": "\U0001f535",
    "amazon_uk": "\U0001f4e6",
    "pokemoncenter": "\U0001f534",
}

# Map webhook URLs to their type name for logging
_WEBHOOK_TYPES = {}


def _webhook_type(url: str) -> str:
    """Identify which webhook type a URL corresponds to."""
    if url == settings.discord_webhook_url:
        return "public"
    if url == settings.discord_admin_webhook:
        return "admin"
    if url == settings.discord_discovery_webhook:
        return "discovery"
    return "unknown"


async def _post_webhook(
    webhook_url: str,
    payload: dict,
    state: StateManager | None = None,
    alert_id: int | None = None,
) -> dict:
    """Post to Discord webhook with delivery tracking.

    Returns dict with 'ok', 'status_code', 'error' keys.
    """
    wh_type = _webhook_type(webhook_url)
    payload_snippet = _json.dumps(payload)[:200]

    if not settings.discord_enabled:
        logger.info("Discord disabled, skipping webhook post")
        return {"ok": False, "status_code": 0, "error": "Discord disabled"}

    if not webhook_url:
        logger.warning("Webhook URL not configured, skipping alert")
        return {"ok": False, "status_code": 0, "error": "URL not configured"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            status = resp.status_code
            body = resp.text

            if status == 429:
                # Rate limited — extract retry_after and wait
                retry_after = 5.0
                try:
                    data = resp.json()
                    retry_after = data.get("retry_after", 5.0)
                except Exception:
                    pass
                logger.warning(
                    "Discord rate limited (%s), retrying in %.1fs",
                    wh_type, retry_after,
                )
                await asyncio.sleep(retry_after)
                # Retry once
                resp = await client.post(webhook_url, json=payload)
                status = resp.status_code
                body = resp.text

            if status not in (200, 204):
                logger.error(
                    "Discord webhook failed (%s): HTTP %d — %s",
                    wh_type, status, body[:200],
                )
                # Log to webhook_log table
                if state:
                    await state.log_webhook(
                        wh_type, status, success=False,
                        error_message=body[:500],
                        payload_snippet=payload_snippet,
                    )
                    if alert_id:
                        await state.update_alert_delivery(
                            alert_id, sent=False,
                            status_code=status, error=body[:500],
                        )
                return {"ok": False, "status_code": status, "error": body[:500]}

            logger.info("Discord webhook delivered (%s): HTTP %d", wh_type, status)
            if state:
                await state.log_webhook(
                    wh_type, status, success=True,
                    payload_snippet=payload_snippet,
                )
                if alert_id:
                    await state.update_alert_delivery(
                        alert_id, sent=True, status_code=status,
                    )
            # Delay between webhook calls to avoid rate limits
            await asyncio.sleep(WEBHOOK_DELAY)
            return {"ok": True, "status_code": status, "error": None}

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Discord webhook exception (%s): %s", wh_type, error_msg)
        if state:
            await state.log_webhook(
                wh_type, 0, success=False,
                error_message=error_msg[:500],
                payload_snippet=payload_snippet,
            )
            if alert_id:
                await state.update_alert_delivery(
                    alert_id, sent=False, status_code=0, error=error_msg[:500],
                )
        return {"ok": False, "status_code": 0, "error": error_msg}


async def send_stock_alert(
    product: ProductData,
    redirect_url: str,
    state: StateManager | None = None,
    shop: str = "bol",
) -> None:
    """Stock available alert -> public webhook with @everyone."""
    emoji = SHOP_EMOJI.get(shop, "\U0001f7e0")
    display_name = product.name or product.product_id
    embed = {
        "title": f"{emoji} IN STOCK [{shop}]: {display_name}",
        "description": f"**Seller:** {product.seller or 'Unknown'}",
        "url": redirect_url,
        "color": 0x00FF00,
        "fields": [
            {"name": "Price", "value": f"\u20ac{product.price or '?'}", "inline": True},
            {"name": "Quick Buy", "value": f"[Add to Cart]({redirect_url})", "inline": True},
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload = {
        "content": "@everyone Pokemon TCG stock detected!",
        "embeds": [embed],
    }

    alert_id = None
    if state:
        msg = f"Stock alert: {product.name} - InStock - {redirect_url}"
        alert_id = await state.log_alert(product.product_id, "stock_change", msg)

    await _post_webhook(settings.discord_webhook_url, payload, state=state, alert_id=alert_id)
    logger.info("Stock alert sent for %s [%s]", product.product_id, shop)


async def send_out_of_stock_alert(
    product: ProductData,
    state: StateManager | None = None,
    shop: str = "bol",
) -> None:
    """Product went out of stock -> public webhook, no ping."""
    emoji = SHOP_EMOJI.get(shop, "\U0001f7e0")
    display_name = product.name or product.product_id
    embed = {
        "title": f"{emoji} OUT OF STOCK [{shop}]: {display_name}",
        "description": f"**Price:** \u20ac{product.price or '?'}",
        "color": 0xFF0000,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload = {"embeds": [embed]}

    alert_id = None
    if state:
        msg = f"OOS alert: {product.name} - OutOfStock"
        alert_id = await state.log_alert(product.product_id, "stock_change", msg)

    await _post_webhook(settings.discord_webhook_url, payload, state=state, alert_id=alert_id)
    logger.info("Out-of-stock alert sent for %s [%s]", product.product_id, shop)


async def send_error_alert(
    product_id: str,
    error_msg: str,
    consecutive_failures: int,
    product_name: str | None = None,
    product_url: str | None = None,
    state: StateManager | None = None,
) -> None:
    """Error alert -> admin webhook. Only fires after ERROR_ALERT_THRESHOLD failures."""
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

    alert_id = None
    if state:
        msg = f"Error alert: {product_id} - {consecutive_failures} failures - {error_msg[:200]}"
        alert_id = await state.log_alert(product_id, "error", msg)

    await _post_webhook(settings.discord_admin_webhook, payload, state=state, alert_id=alert_id)
    logger.warning("Error alert sent for %s (%d failures)", product_id, consecutive_failures)


async def send_queue_alert(
    pc_url: str, state: StateManager | None = None
) -> None:
    """Pokemon Center queue is active -- alert users to join now."""
    embed = {
        "title": "\u26a0\ufe0f Pok\u00e9mon Center Queue Active",
        "description": (
            "The Pok\u00e9mon Center virtual queue is live!\n"
            "**Join now to get ahead of the crowd.**\n\n"
            f"[\u2192 Enter the queue]({pc_url})"
        ),
        "color": 0xFFCC00,
        "footer": {"text": "Join early = better position"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload = {
        "content": "@everyone Pok\u00e9mon Center queue detected!",
        "embeds": [embed],
    }

    alert_id = None
    if state:
        alert_id = await state.log_alert(None, "queue", f"PC queue active: {pc_url}")

    await _post_webhook(settings.discord_webhook_url, payload, state=state, alert_id=alert_id)
    logger.info("Queue alert sent for Pokemon Center: %s", pc_url)


async def send_discovery_alert(
    product_id: str, url: str, name: str | None = None, state: StateManager | None = None
) -> None:
    """New product discovered -> discovery webhook."""
    embed = {
        "title": f"New Product: {name or product_id}",
        "description": f"**Product ID:** {product_id}\n**URL:** {url}",
        "url": url,
        "color": 0x0099FF,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload = {"embeds": [embed]}

    alert_id = None
    if state:
        msg = f"Discovery: {product_id} - {url}"
        alert_id = await state.log_alert(product_id, "discovery", msg)

    await _post_webhook(settings.discord_discovery_webhook, payload, state=state, alert_id=alert_id)
    logger.info("Discovery alert sent for %s", product_id)


async def test_all_webhooks() -> dict:
    """Send a test message to all configured webhooks. Returns status per webhook."""
    test_payload = {
        "embeds": [{
            "title": "Webhook Test",
            "description": "This is a test message from Pokemon Monitor.",
            "color": 0x7289DA,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }

    results = {}
    for name, url in [
        ("public_webhook", settings.discord_webhook_url),
        ("admin_webhook", settings.discord_admin_webhook),
        ("discovery_webhook", settings.discord_discovery_webhook),
    ]:
        if not url:
            results[name] = {"status": 0, "ok": False, "error": "Not configured"}
            continue
        result = await _post_webhook(url, test_payload)
        results[name] = {
            "status": result["status_code"],
            "ok": result["ok"],
            "error": result.get("error"),
        }

    return results
