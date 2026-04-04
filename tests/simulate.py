"""End-to-end simulation: mock server + monitor -> stock change -> alert.

Usage:
    1. Start all services: make dev
    2. Run: python tests/simulate.py

Scenario:
    - Resets product to out_of_stock
    - Adds product to monitor DB
    - Waits for first poll
    - Toggles stock to in_stock
    - Waits for detection + measures latency
"""

import asyncio
import time

import httpx

from monitor.state import StateManager

MOCK_URL = "http://localhost:8099"
PRODUCT_ID = "9300000239014079"
PRODUCT_PAGE = f"{MOCK_URL}/nl/nl/p/pokemon-team-rockets-mewtwo-ex-league-battle-deck/{PRODUCT_ID}/"


async def main():
    print("=== Pokemon Monitor E2E Simulation ===\n")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{MOCK_URL}/admin/set-stock",
            json={"product_id": PRODUCT_ID, "status": "out_of_stock"},
        )
        print(f"1. Reset to out_of_stock: {resp.json()['new_stock']}")

    state = await StateManager.create()
    await state.add_product(PRODUCT_ID, PRODUCT_PAGE)
    print(f"2. Added {PRODUCT_ID} to monitor")

    print("3. Waiting 12s for first poll cycle...")
    await asyncio.sleep(12)

    product = await state.get_product(PRODUCT_ID)
    print(f"   Current availability: {product.get('last_availability')}")

    toggle_time = time.monotonic()
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{MOCK_URL}/admin/set-stock",
            json={"product_id": PRODUCT_ID, "status": "in_stock"},
        )
    print("4. Toggled to in_stock — waiting for detection...")

    for _ in range(30):
        await asyncio.sleep(1)
        product = await state.get_product(PRODUCT_ID)
        if product.get("last_availability") == "InStock":
            latency = time.monotonic() - toggle_time
            print(f"\n   DETECTED in {latency:.1f}s ({int(latency * 1000)}ms)")
            break
    else:
        print("\n   TIMEOUT: Not detected within 30s")

    alerts = await state.get_alerts(limit=5)
    print(f"\n5. Alerts sent ({len(alerts)}):")
    for a in alerts:
        print(f"   [{a['alert_type']}] {a['message']}")

    await state.close()
    print("\n=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
