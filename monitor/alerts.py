"""Discord webhook alert sender with delivery tracking and multi-server support."""

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


async def _get_webhook_urls(
    state: StateManager | None, webhook_type: str
) -> list[str]:
    """Get webhook URLs from DB servers, falling back to env vars.

    webhook_type: 'public', 'admin', 'discovery'
    Returns a list of URLs (one per active server that has this webhook).
    """
    if state:
        try:
            servers = await state.list_discord_servers(active_only=True)
            if servers:
                field_map = {
                    "public": "public_webhook",
                    "admin": "admin_webhook",
                    "discovery": "discovery_webhook",
                }
                toggle_map = {
                    "public": "send_stock_alerts",
                    "admin": "send_admin_alerts",
                    "discovery": "send_discovery_alerts",
                }
                field = field_map.get(webhook_type, "public_webhook")
                toggle = toggle_map.get(webhook_type, "send_stock_alerts")
                urls = []
                for s in servers:
                    if s.get(toggle, True) and s.get(field):
                        urls.append(s[field])
                return urls
        except Exception:
            logger.debug("Failed to load discord servers from DB, using env fallback")

    # Fallback to env vars
    env_map = {
        "public": settings.discord_webhook_url,
        "admin": settings.discord_admin_webhook,
        "discovery": settings.discord_discovery_webhook,
    }
    url = env_map.get(webhook_type, "")
    return [url] if url else []


async def _get_queue_urls(state: StateManager | None) -> list[str]:
    """Get webhook URLs for queue alerts from DB servers."""
    if state:
        try:
            servers = await state.list_discord_servers(active_only=True)
            if servers:
                return [
                    s["public_webhook"] for s in servers
                    if s.get("send_queue_alerts", True) and s.get("public_webhook")
                ]
        except Exception:
            logger.debug("Failed to load discord servers for queue, using env fallback")
    url = settings.discord_webhook_url
    return [url] if url else []


async def _post_webhook(
    webhook_url: str,
    payload: dict,
    webhook_type: str = "unknown",
    state: StateManager | None = None,
    alert_id: int | None = None,
) -> dict:
    """Post to Discord webhook with delivery tracking.

    Returns dict with 'ok', 'status_code', 'error' keys.
    """
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
                retry_after = 5.0
                try:
                    data = resp.json()
                    retry_after = data.get("retry_after", 5.0)
                except Exception:
                    pass
                logger.warning(
                    "Discord rate limited (%s), retrying in %.1fs",
                    webhook_type, retry_after,
                )
                await asyncio.sleep(retry_after)
                resp = await client.post(webhook_url, json=payload)
                status = resp.status_code
                body = resp.text

            if status not in (200, 204):
                logger.error(
                    "Discord webhook failed (%s): HTTP %d — %s",
                    webhook_type, status, body[:200],
                )
                if state:
                    await state.log_webhook(
                        webhook_type, status, success=False,
                        error_message=body[:500],
                        payload_snippet=payload_snippet,
                    )
                    if alert_id:
                        await state.update_alert_delivery(
                            alert_id, sent=False,
                            status_code=status, error=body[:500],
                        )
                return {"ok": False, "status_code": status, "error": body[:500]}

            logger.info("Discord webhook delivered (%s): HTTP %d", webhook_type, status)
            if state:
                await state.log_webhook(
                    webhook_type, status, success=True,
                    payload_snippet=payload_snippet,
                )
                if alert_id:
                    await state.update_alert_delivery(
                        alert_id, sent=True, status_code=status,
                    )
            await asyncio.sleep(WEBHOOK_DELAY)
            return {"ok": True, "status_code": status, "error": None}

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Discord webhook exception (%s): %s", webhook_type, error_msg)
        if state:
            await state.log_webhook(
                webhook_type, 0, success=False,
                error_message=error_msg[:500],
                payload_snippet=payload_snippet,
            )
            if alert_id:
                await state.update_alert_delivery(
                    alert_id, sent=False, status_code=0, error=error_msg[:500],
                )
        return {"ok": False, "status_code": 0, "error": error_msg}


async def _send_to_all(
    webhook_type: str,
    payload: dict,
    state: StateManager | None = None,
    alert_id: int | None = None,
) -> None:
    """Send payload to all active servers' webhooks of the given type."""
    urls = await _get_webhook_urls(state, webhook_type)
    for url in urls:
        await _post_webhook(
            url, payload,
            webhook_type=webhook_type, state=state, alert_id=alert_id,
        )


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

    await _send_to_all("public", payload, state=state, alert_id=alert_id)
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

    await _send_to_all("public", payload, state=state, alert_id=alert_id)
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

    await _send_to_all("admin", payload, state=state, alert_id=alert_id)
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

    urls = await _get_queue_urls(state)
    for url in urls:
        await _post_webhook(
            url, payload, webhook_type="public", state=state, alert_id=alert_id,
        )
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

    await _send_to_all("discovery", payload, state=state, alert_id=alert_id)
    logger.info("Discovery alert sent for %s", product_id)


async def test_server_webhooks(
    server: dict, state: StateManager | None = None,
) -> dict:
    """Send a test message to all configured webhooks for a server."""
    test_payload = {
        "embeds": [{
            "title": f"Webhook Test — {server.get('name', 'Unknown')}",
            "description": "This is a test message from Pok\u00e9mon Monitor.",
            "color": 0x7289DA,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }

    results = {}
    for wh_type, field in [
        ("public", "public_webhook"),
        ("admin", "admin_webhook"),
        ("discovery", "discovery_webhook"),
    ]:
        url = server.get(field)
        if not url:
            results[wh_type] = {"configured": False, "status": 0, "ok": False, "error": "Not configured"}
            continue
        result = await _post_webhook(url, test_payload, webhook_type=wh_type, state=state)
        results[wh_type] = {
            "configured": True,
            "status": result["status_code"],
            "ok": result["ok"],
            "error": result.get("error"),
        }

    return results


async def test_all_webhooks(state: StateManager | None = None) -> dict:
    """Test all active servers' webhooks (or env var fallback)."""
    if state:
        try:
            servers = await state.list_discord_servers(active_only=True)
            if servers:
                all_results = {}
                for server in servers:
                    results = await test_server_webhooks(server, state=state)
                    # Update test status in DB
                    any_ok = any(r["ok"] for r in results.values() if r.get("configured"))
                    any_failed = any(
                        not r["ok"] for r in results.values() if r.get("configured")
                    )
                    test_result = "ok" if any_ok and not any_failed else "failed" if any_failed else "untested"
                    test_error = None
                    if any_failed:
                        failed = [
                            f"{k}: {r.get('error', '')[:100]}"
                            for k, r in results.items()
                            if r.get("configured") and not r["ok"]
                        ]
                        test_error = "; ".join(failed)
                    await state.update_discord_server(
                        server["id"],
                        last_tested_at=datetime.now(timezone.utc),
                        last_test_result=test_result,
                        last_test_error=test_error,
                    )
                    all_results[server["name"]] = results
                return all_results
        except Exception:
            logger.exception("Failed to test DB servers, falling back to env")

    # Fallback: test env var webhooks
    test_payload = {
        "embeds": [{
            "title": "Webhook Test",
            "description": "This is a test message from Pok\u00e9mon Monitor.",
            "color": 0x7289DA,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }
    results = {}
    for name, url in [
        ("public", settings.discord_webhook_url),
        ("admin", settings.discord_admin_webhook),
        ("discovery", settings.discord_discovery_webhook),
    ]:
        if not url:
            results[name] = {"configured": False, "status": 0, "ok": False, "error": "Not configured"}
            continue
        result = await _post_webhook(url, test_payload, webhook_type=name)
        results[name] = {
            "configured": True,
            "status": result["status_code"],
            "ok": result["ok"],
            "error": result.get("error"),
        }
    return results
