"""Shop adapters for multi-store Pokemon TCG stock monitoring."""

from monitor.shops.registry import SHOP_REGISTRY, get_adapter

__all__ = ["SHOP_REGISTRY", "get_adapter"]
