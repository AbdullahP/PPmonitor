"""Local Discord webhook tester — run before deploying.

Usage: python tests/test_discord_local.py
"""

import asyncio
import os

import httpx
from dotenv import load_dotenv

load_dotenv()


async def test_webhook(name: str, url: str | None) -> None:
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
        icon = "\u2705" if resp.status_code in (200, 204) else "\u274c"
        print(f"  {name}: {icon} HTTP {resp.status_code}")
    except Exception as e:
        print(f"  {name}: \u274c {e}")


async def main() -> None:
    print("Testing Discord webhooks from .env...")
    await test_webhook("Public", os.getenv("DISCORD_WEBHOOK_URL"))
    await test_webhook("Admin", os.getenv("DISCORD_ADMIN_WEBHOOK"))
    await test_webhook("Discovery", os.getenv("DISCORD_DISCOVERY_WEBHOOK"))
    print("Done. Check your Discord channels.")


if __name__ == "__main__":
    asyncio.run(main())
