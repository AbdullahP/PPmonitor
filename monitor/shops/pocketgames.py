"""PocketGames.nl adapter — Shopify store."""

from monitor.shops.shopify_base import ShopifyAdapter


class PocketGamesAdapter(ShopifyAdapter):
    shop_id = "pocketgames"
    base_url = "https://pocketgames.nl"
    category_paths = ["/collections/pokemon"]
