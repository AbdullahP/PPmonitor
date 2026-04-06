"""Central registry of all shop adapters."""

from __future__ import annotations

from monitor.shops.amazon_uk import AmazonUKAdapter
from monitor.shops.base import ShopAdapter
from monitor.shops.bol import BolAdapter
from monitor.shops.catchyourcards import CatchYourCardsAdapter
from monitor.shops.dreamland import DreamlandAdapter
from monitor.shops.games_island import GamesIslandAdapter
from monitor.shops.mediamarkt import MediaMarktAdapter
from monitor.shops.pocketgames import PocketGamesAdapter

SHOP_REGISTRY: dict[str, type[ShopAdapter]] = {
    "bol": BolAdapter,
    "mediamarkt": MediaMarktAdapter,
    "pocketgames": PocketGamesAdapter,
    "catchyourcards": CatchYourCardsAdapter,
    "games_island": GamesIslandAdapter,
    "dreamland": DreamlandAdapter,
    "amazon_uk": AmazonUKAdapter,
}


def get_adapter(shop_id: str) -> ShopAdapter:
    """Instantiate and return an adapter by shop ID."""
    cls = SHOP_REGISTRY.get(shop_id)
    if cls is None:
        raise ValueError(f"Unknown shop: {shop_id!r}. Available: {list(SHOP_REGISTRY)}")
    return cls()
