"""Local scraper tester — verify all adapters can reach their shops.

Usage: python tests/test_scraper_local.py
"""

import asyncio

import httpx

from monitor.shops.registry import SHOP_REGISTRY


async def main() -> None:
    print("Testing shop adapters...")
    async with httpx.AsyncClient(timeout=15) as client:
        for shop_id, cls in SHOP_REGISTRY.items():
            adapter = cls()
            urls = adapter.build_category_urls()
            if not urls:
                print(f"  {shop_id}: no category URLs configured")
                continue
            try:
                resp = await client.get(
                    urls[0], headers=adapter.get_headers(), follow_redirects=True
                )
                ids = adapter.parse_category(resp.text)
                print(f"  {shop_id}: OK HTTP {resp.status_code}, found {len(ids)} products")
            except Exception as e:
                print(f"  {shop_id}: FAIL {e}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
