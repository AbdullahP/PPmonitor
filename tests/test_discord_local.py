"""Local Discord webhook tester — run before deploying.

Usage: python tests/test_discord_local.py

NOT a pytest test — this sends real messages to Discord.
"""

import asyncio
import os

import httpx
from dotenv import load_dotenv

load_dotenv()


async def _check_webhook(name: str, url: str | None) -> None:
    if not url:
        print(f"  {name}: NOT CONFIGURED")
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={
                "embeds": [{
                    "title": f"\U0001f9ea Local Test \u2014 {name}",
                    "description": "Discord webhook is working!",
                    "color": 0x22C55E,
                }],
            })
        icon = "OK" if resp.status_code in (200, 204) else "FAIL"
        print(f"  {name}: {icon} HTTP {resp.status_code}")
    except Exception as e:
        print(f"  {name}: FAIL {e}")


async def main() -> None:
    print("Testing Discord webhooks from .env...")
    await _check_webhook("Public", os.getenv("DISCORD_WEBHOOK_URL"))
    await _check_webhook("Admin", os.getenv("DISCORD_ADMIN_WEBHOOK"))
    await _check_webhook("Discovery", os.getenv("DISCORD_DISCOVERY_WEBHOOK"))
    await _check_webhook("Queue", os.getenv("DISCORD_QUEUE_WEBHOOK"))
    print("Done. Check your Discord channels.")


if __name__ == "__main__":
    asyncio.run(main())
