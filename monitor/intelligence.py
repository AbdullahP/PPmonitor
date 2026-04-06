"""Keyword-based product discovery engine.

Replaces the old hardcoded KNOWN_UPCOMING_SETS with a database-driven
keyword system. Keywords are managed via the dashboard and matched
against product names found on category/search pages.
"""

import json
import logging
import re

import httpx

from monitor.shops.registry import SHOP_REGISTRY
from monitor.state import StateManager

logger = logging.getLogger(__name__)

DAYS_BEFORE_RELEASE = 14


def get_upcoming_sets() -> list[dict]:
    """Return empty list — upcoming sets are now driven by keywords."""
    return []


class KeywordEngine:
    """Scan shop category pages and match product names against DB keywords."""

    async def load_keywords(self, state: StateManager) -> list[dict]:
        """Load active keywords from DB."""
        return await state.list_keywords(active_only=True)

    async def matches_any_keyword(
        self, product_name: str, keywords: list[dict]
    ) -> dict | None:
        """Return the first matching keyword record, or None."""
        name_lower = product_name.lower()
        for kw in keywords:
            kw_text = kw["keyword"].lower()
            match_type = kw.get("match_type", "contains")

            if match_type == "contains":
                if kw_text in name_lower:
                    return kw
            elif match_type == "exact":
                if kw_text == name_lower:
                    return kw
            elif match_type == "regex":
                try:
                    if re.search(kw_text, name_lower, re.IGNORECASE):
                        return kw
                except re.error:
                    logger.warning("Invalid regex keyword: %s", kw["keyword"])
        return None

    async def run(
        self,
        state: StateManager,
        client: httpx.AsyncClient,
    ) -> list[dict]:
        """Scan all shops for products matching active keywords.

        Returns a list of newly discovered/monitored products.
        """
        keywords = await self.load_keywords(state)
        if not keywords:
            return []

        new_finds: list[dict] = []
        known_ids = await state.get_known_product_ids()

        for shop_id, adapter_cls in SHOP_REGISTRY.items():
            # Check which keywords apply to this shop
            shop_keywords = []
            for kw in keywords:
                shops = kw.get("shops")
                if isinstance(shops, str):
                    shops = json.loads(shops)
                if shops is None or shop_id in shops:
                    shop_keywords.append(kw)
            if not shop_keywords:
                continue

            try:
                adapter = adapter_cls()
                scan_urls = list(adapter.build_category_urls())

                # Also search for high-priority keywords
                for kw in shop_keywords:
                    if kw.get("priority") == "high":
                        scan_urls.append(adapter.get_search_url(kw["keyword"]))

                all_found: set[str] = set()
                for url in scan_urls:
                    try:
                        ids = await adapter.fetch_category(client, url)
                        all_found.update(ids)
                    except Exception:
                        logger.debug("Keyword scan fetch failed: %s %s", shop_id, url)

                new_ids = all_found - known_ids
                if not new_ids:
                    continue

                for pid in new_ids:
                    try:
                        product_url = adapter.build_product_url(pid)
                        data = await adapter.fetch_product(client, product_url)
                        if not data or not data.name:
                            continue

                        match = await self.matches_any_keyword(
                            data.name, shop_keywords
                        )
                        if not match:
                            continue

                        if match.get("auto_monitor", False):
                            # Auto-add to active monitoring
                            await state.add_product(
                                pid, product_url,
                                name=data.name, shop=shop_id,
                            )
                            known_ids.add(pid)
                            logger.info(
                                "Keyword auto-monitor: '%s' at %s [keyword=%s]",
                                data.name, shop_id, match["keyword"],
                            )
                        else:
                            # Add to discovered for manual approval
                            is_new = await state.add_discovered(
                                pid, product_url,
                                name=data.name,
                                source=f"keyword:{match['keyword']}",
                                shop=shop_id,
                            )
                            if not is_new:
                                continue
                            known_ids.add(pid)
                            logger.info(
                                "Keyword discovered: '%s' at %s [keyword=%s]",
                                data.name, shop_id, match["keyword"],
                            )

                        new_finds.append({
                            "product_id": pid,
                            "name": data.name,
                            "shop": shop_id,
                            "keyword": match["keyword"],
                            "auto_monitored": match.get("auto_monitor", False),
                            "url": product_url,
                            "notify_discord": match.get("notify_discord", True),
                        })
                    except Exception:
                        logger.debug(
                            "Failed to fetch product %s from %s", pid, shop_id
                        )
            except Exception:
                logger.exception("Keyword scan failed for %s", shop_id)

        return new_finds


# Module-level singleton
keyword_engine = KeywordEngine()


async def scan_upcoming_sets(
    client: httpx.AsyncClient, state: StateManager
) -> list[dict]:
    """Run the keyword engine (replaces old hardcoded set scanning)."""
    return await keyword_engine.run(state, client)
