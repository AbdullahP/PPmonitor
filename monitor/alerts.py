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

ERROR_ALERT_THRESHOLD = 3
WEBHOOK_DELAY = 1.0

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


# ---------------------------------------------------------------------------
# Low-level webhook POST — never checks DISCORD_ENABLED
# ---------------------------------------------------------------------------

async def _raw_post(
    webhook_url: str,
    payload: dict,
    webhook_type: str = "unknown",
    state: StateManager | None = None,
    alert_id: int | None = None,
) -> dict:
    """POST to a Discord webhook URL. Always fires — caller decides gating."""
    payload_snippet = _json.dumps(payload)[:200]

    if not webhook_url:
        return {"ok": False, "status_code": 0, "error": "URL not configured"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            status = resp.status_code
            body = resp.text

            if status == 429:
                retry_after = 5.0
                try:
                    retry_after = resp.json().get("retry_after", 5.0)
                except Exception:
                    pass
                logger.warning("Discord rate limited (%s), retrying in %.1fs", webhook_type, retry_after)
                await asyncio.sleep(retry_after)
                resp = await client.post(webhook_url, json=payload)
                status = resp.status_code
                body = resp.text

            if status not in (200, 204):
                logger.error("Discord webhook failed (%s): HTTP %d — %s", webhook_type, status, body[:200])
                if state:
                    await state.log_webhook(webhook_type, status, success=False, error_message=body[:500], payload_snippet=payload_snippet)
                    if alert_id:
                        await state.update_alert_delivery(alert_id, sent=False, status_code=status, error=body[:500])
                return {"ok": False, "status_code": status, "error": body[:500]}

            logger.info("Discord webhook delivered (%s): HTTP %d", webhook_type, status)
            if state:
                await state.log_webhook(webhook_type, status, success=True, payload_snippet=payload_snippet)
                if alert_id:
                    await state.update_alert_delivery(alert_id, sent=True, status_code=status)
            await asyncio.sleep(WEBHOOK_DELAY)
            return {"ok": True, "status_code": status, "error": None}

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Discord webhook exception (%s): %s", webhook_type, error_msg)
        if state:
            await state.log_webhook(webhook_type, 0, success=False, error_message=error_msg[:500], payload_snippet=payload_snippet)
            if alert_id:
                await state.update_alert_delivery(alert_id, sent=False, status_code=0, error=error_msg[:500])
        return {"ok": False, "status_code": 0, "error": error_msg}


# ---------------------------------------------------------------------------
# Alert routing — DB servers first, env vars as fallback
# ---------------------------------------------------------------------------

_WEBHOOK_FIELD = {"public": "public_webhook", "admin": "admin_webhook", "discovery": "discovery_webhook", "queue": "queue_webhook"}
_TOGGLE_FIELD = {"public": "send_stock_alerts", "admin": "send_admin_alerts", "discovery": "send_discovery_alerts", "queue": "send_queue_alerts"}
_CHANNEL_FIELD = {"public": "stock_channel_id", "admin": "admin_channel_id", "discovery": "discovery_channel_id", "queue": "queue_channel_id"}


async def _send_to_server(
    server: dict, webhook_type: str, payload: dict,
    state: StateManager, alert_id: int | None = None,
) -> None:
    """Send to a single server — webhook or bot-queue depending on mode."""
    toggle = _TOGGLE_FIELD.get(webhook_type, "send_stock_alerts")
    if not server.get(toggle, True):
        return

    mode = server.get("mode", "webhook")

    if mode == "bot":
        # Bot-direct: enqueue for the bot process to pick up
        channel_field = _CHANNEL_FIELD.get(webhook_type)
        channel_id = server.get(channel_field) if channel_field else None
        if not channel_id:
            return
        # Extract embed and content from payload
        embeds = payload.get("embeds", [])
        embed_json = embeds[0] if embeds else {}
        content = payload.get("content")
        await state.enqueue_discord_message(
            server["id"], channel_id, embed_json, content=content,
        )
        logger.info("Enqueued bot message for server %s channel %s (%s)", server["name"], channel_id, webhook_type)
    else:
        # Webhook mode: POST directly
        wh_field = _WEBHOOK_FIELD.get(webhook_type, "public_webhook")
        # For queue type, prefer queue_webhook, fall back to public_webhook
        if webhook_type == "queue":
            url = server.get("queue_webhook") or server.get("public_webhook")
        else:
            url = server.get(wh_field)
        if url:
            await _raw_post(url, payload, webhook_type=webhook_type, state=state, alert_id=alert_id)


async def _send_to_all(
    webhook_type: str,
    payload: dict,
    state: StateManager | None = None,
    alert_id: int | None = None,
) -> None:
    """Send to all active DB servers, falling back to env vars.

    DB servers are INDEPENDENT of DISCORD_ENABLED — they always send.
    Env var fallback is gated by DISCORD_ENABLED.
    """
    if state:
        try:
            servers = await state.list_discord_servers(active_only=True)
            if servers:
                for s in servers:
                    await _send_to_server(s, webhook_type, payload, state=state, alert_id=alert_id)
                return
        except Exception:
            logger.debug("Failed to load discord servers, falling back to env")

    # Fallback to env vars — gated by DISCORD_ENABLED
    if not settings.discord_enabled:
        logger.info("Discord disabled and no DB servers configured, skipping")
        return

    env_map = {
        "public": settings.discord_webhook_url,
        "admin": settings.discord_admin_webhook,
        "discovery": settings.discord_discovery_webhook,
        "queue": settings.discord_queue_webhook or settings.discord_webhook_url,
    }
    url = env_map.get(webhook_type, "")
    if url:
        await _raw_post(url, payload, webhook_type=webhook_type, state=state, alert_id=alert_id)


# ---------------------------------------------------------------------------
# Public alert functions
# ---------------------------------------------------------------------------

async def send_stock_alert(
    product: ProductData, redirect_url: str,
    state: StateManager | None = None, shop: str = "bol",
) -> None:
    emoji = SHOP_EMOJI.get(shop, "\U0001f7e0")
    display_name = product.name or product.product_id
    payload = {
        "content": "@everyone Pokemon TCG stock detected!",
        "embeds": [{
            "title": f"{emoji} IN STOCK [{shop}]: {display_name}",
            "description": f"**Seller:** {product.seller or 'Unknown'}",
            "url": redirect_url,
            "color": 0x00FF00,
            "fields": [
                {"name": "Price", "value": f"\u20ac{product.price or '?'}", "inline": True},
                {"name": "Quick Buy", "value": f"[Add to Cart]({redirect_url})", "inline": True},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }
    alert_id = None
    if state:
        alert_id = await state.log_alert(product.product_id, "stock_change", f"Stock alert: {product.name} - InStock - {redirect_url}")
    await _send_to_all("public", payload, state=state, alert_id=alert_id)
    logger.info("Stock alert sent for %s [%s]", product.product_id, shop)


async def send_out_of_stock_alert(
    product: ProductData, state: StateManager | None = None, shop: str = "bol",
) -> None:
    emoji = SHOP_EMOJI.get(shop, "\U0001f7e0")
    display_name = product.name or product.product_id
    payload = {
        "embeds": [{
            "title": f"{emoji} OUT OF STOCK [{shop}]: {display_name}",
            "description": f"**Price:** \u20ac{product.price or '?'}",
            "color": 0xFF0000,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }
    alert_id = None
    if state:
        alert_id = await state.log_alert(product.product_id, "stock_change", f"OOS alert: {product.name} - OutOfStock")
    await _send_to_all("public", payload, state=state, alert_id=alert_id)
    logger.info("Out-of-stock alert sent for %s [%s]", product.product_id, shop)


async def send_error_alert(
    product_id: str, error_msg: str, consecutive_failures: int,
    product_name: str | None = None, product_url: str | None = None,
    state: StateManager | None = None,
) -> None:
    if consecutive_failures < ERROR_ALERT_THRESHOLD:
        return
    payload = {
        "embeds": [{
            "title": f"Monitor Error: {product_name or product_id}",
            "description": f"**Consecutive failures:** {consecutive_failures}\n**Error:** {error_msg[:500]}\n**URL:** {product_url or 'N/A'}",
            "color": 0xFF6600,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }
    alert_id = None
    if state:
        alert_id = await state.log_alert(product_id, "error", f"Error alert: {product_id} - {consecutive_failures} failures - {error_msg[:200]}")
    await _send_to_all("admin", payload, state=state, alert_id=alert_id)
    logger.warning("Error alert sent for %s (%d failures)", product_id, consecutive_failures)


async def send_queue_alert(pc_url: str, state: StateManager | None = None) -> None:
    payload = {
        "content": "@everyone Pok\u00e9mon Center queue detected!",
        "embeds": [{
            "title": "\u26a0\ufe0f Pok\u00e9mon Center Queue Active",
            "description": f"The Pok\u00e9mon Center virtual queue is live!\n**Join now to get ahead of the crowd.**\n\n[\u2192 Enter the queue]({pc_url})",
            "color": 0xFFCC00,
            "footer": {"text": "Join early = better position"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }
    alert_id = None
    if state:
        alert_id = await state.log_alert(None, "queue", f"PC queue active: {pc_url}")
    await _send_to_all("queue", payload, state=state, alert_id=alert_id)
    logger.info("Queue alert sent for Pokemon Center: %s", pc_url)


async def send_discovery_alert(
    product_id: str, url: str, name: str | None = None, state: StateManager | None = None
) -> None:
    payload = {
        "embeds": [{
            "title": f"New Product: {name or product_id}",
            "description": f"**Product ID:** {product_id}\n**URL:** {url}",
            "url": url,
            "color": 0x0099FF,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }
    alert_id = None
    if state:
        alert_id = await state.log_alert(product_id, "discovery", f"Discovery: {product_id} - {url}")
    await _send_to_all("discovery", payload, state=state, alert_id=alert_id)
    logger.info("Discovery alert sent for %s", product_id)


# ---------------------------------------------------------------------------
# Test functions — ALWAYS fire, ignore DISCORD_ENABLED
# ---------------------------------------------------------------------------

async def test_server_webhooks(server: dict, state: StateManager | None = None) -> dict:
    """Test all configured webhooks for a single server. Always fires."""
    test_payload = {
        "embeds": [{
            "title": f"\U0001f9ea Test — {server.get('name', 'Unknown')}",
            "description": "Test from Pok\u00e9mon Monitor \u2014 webhook working!",
            "color": 0x22C55E,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }
    results = {}
    for wh_type, field in [
        ("public", "public_webhook"), ("admin", "admin_webhook"),
        ("discovery", "discovery_webhook"), ("queue", "queue_webhook"),
    ]:
        url = server.get(field)
        if not url:
            results[wh_type] = {"configured": False, "status": 0, "ok": False, "error": "Not configured"}
            continue
        # Always fire — _raw_post never checks DISCORD_ENABLED
        result = await _raw_post(url, test_payload, webhook_type=wh_type, state=state)
        results[wh_type] = {"configured": True, "status": result["status_code"], "ok": result["ok"], "error": result.get("error")}
    return results


async def test_all_webhooks(state: StateManager | None = None) -> dict:
    """Test all active servers (or env var fallback). Always fires."""
    if state:
        try:
            servers = await state.list_discord_servers(active_only=True)
            if servers:
                all_results = {}
                for server in servers:
                    results = await test_server_webhooks(server, state=state)
                    any_ok = any(r["ok"] for r in results.values() if r.get("configured"))
                    any_failed = any(not r["ok"] for r in results.values() if r.get("configured"))
                    test_result = "ok" if any_ok and not any_failed else "failed" if any_failed else "untested"
                    test_error = "; ".join(
                        f"{k}: {r.get('error', '')[:100]}" for k, r in results.items()
                        if r.get("configured") and not r["ok"]
                    ) or None
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

    # Fallback: test env var webhooks (always fires for testing)
    test_payload = {
        "embeds": [{
            "title": "\U0001f9ea Webhook Test",
            "description": "Test from Pok\u00e9mon Monitor \u2014 webhook working!",
            "color": 0x22C55E,
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
        result = await _raw_post(url, test_payload, webhook_type=name)
        results[name] = {"configured": True, "status": result["status_code"], "ok": result["ok"], "error": result.get("error")}
    return results
