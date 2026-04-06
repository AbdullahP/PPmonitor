"""Adaptive per-shop rate limiter that backs off on errors and recovers on success."""

import logging
import time

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 10.0
MAX_INTERVAL = 120.0
MIN_INTERVAL = 5.0
BAN_PAUSE_SECONDS = 300  # 5 minutes for 403
RECOVERY_STREAK = 3  # consecutive successes needed to step down


class AdaptiveRateLimiter:
    """Rate limiter for a single shop."""

    def __init__(self, shop_id: str, base_interval: float = DEFAULT_INTERVAL):
        self.shop_id = shop_id
        self.base_interval = base_interval
        self._interval = base_interval
        self.ban_score: int = 0
        self.consecutive_failures: int = 0
        self.consecutive_successes: int = 0
        self._paused_until: float = 0.0
        self.total_requests: int = 0
        self.total_errors: int = 0

    def record_result(self, success: bool, status_code: int | None = None) -> None:
        """Record the result of a fetch and adjust the interval."""
        self.total_requests += 1

        if not success or (status_code and status_code >= 400):
            self.consecutive_successes = 0
            self.consecutive_failures += 1
            self.total_errors += 1

            if status_code in (429, 503):
                # Rate limited or service unavailable — double interval
                self._interval = min(self._interval * 2, MAX_INTERVAL)
                self.ban_score += 2
                logger.warning(
                    "[%s] Rate limited (%s), interval → %.0fs",
                    self.shop_id, status_code, self._interval,
                )
            elif status_code == 403:
                # Banned — pause for 5 minutes
                self._paused_until = time.monotonic() + BAN_PAUSE_SECONDS
                self.ban_score += 5
                logger.warning(
                    "[%s] 403 Forbidden — paused for %ds", self.shop_id, BAN_PAUSE_SECONDS
                )
            else:
                # Generic error — small bump
                self._interval = min(self._interval * 1.5, MAX_INTERVAL)
        else:
            self.consecutive_failures = 0
            self.consecutive_successes += 1

            if self.consecutive_successes >= RECOVERY_STREAK:
                # Step interval back down toward base
                self._interval = max(
                    self._interval * 0.75, self.base_interval, MIN_INTERVAL
                )
                self.consecutive_successes = 0
                if self.ban_score > 0:
                    self.ban_score = max(0, self.ban_score - 1)

    def current_interval(self) -> float:
        """Return the current polling interval in seconds."""
        return self._interval

    def is_paused(self) -> bool:
        """Return True if this shop is currently paused (e.g. after a 403)."""
        if self._paused_until <= 0:
            return False
        if time.monotonic() >= self._paused_until:
            self._paused_until = 0.0
            return False
        return True

    def pause_remaining(self) -> float:
        """Seconds remaining in the current pause, or 0."""
        if not self.is_paused():
            return 0.0
        return max(0.0, self._paused_until - time.monotonic())

    def status_dict(self) -> dict:
        """Return a snapshot of limiter state for the dashboard."""
        return {
            "shop_id": self.shop_id,
            "interval": round(self._interval, 1),
            "ban_score": self.ban_score,
            "consecutive_failures": self.consecutive_failures,
            "paused": self.is_paused(),
            "pause_remaining": round(self.pause_remaining()),
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "error_rate": (
                round(self.total_errors / self.total_requests * 100, 1)
                if self.total_requests > 0 else 0.0
            ),
        }


# Global limiter registry — one per shop
_limiters: dict[str, AdaptiveRateLimiter] = {}


# Shops that need higher default intervals to avoid blocks
_SHOP_BASE_INTERVALS: dict[str, float] = {
    "amazon_uk": 30.0,
}


def get_limiter(shop_id: str) -> AdaptiveRateLimiter:
    """Get or create a rate limiter for a shop."""
    if shop_id not in _limiters:
        base = _SHOP_BASE_INTERVALS.get(shop_id, DEFAULT_INTERVAL)
        _limiters[shop_id] = AdaptiveRateLimiter(shop_id, base_interval=base)
    return _limiters[shop_id]


def all_limiter_statuses() -> list[dict]:
    """Return status dicts for all active limiters."""
    return [limiter.status_dict() for limiter in _limiters.values()]
