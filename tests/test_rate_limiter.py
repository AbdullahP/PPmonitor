"""Tests for the adaptive rate limiter."""

from monitor.rate_limiter import (
    AdaptiveRateLimiter,
    DEFAULT_INTERVAL,
    MAX_INTERVAL,
    RECOVERY_STREAK,
    get_limiter,
    _limiters,
)


def test_initial_state():
    limiter = AdaptiveRateLimiter("test_shop")
    assert limiter.current_interval() == DEFAULT_INTERVAL
    assert limiter.is_paused() is False
    assert limiter.consecutive_failures == 0
    assert limiter.consecutive_successes == 0
    assert limiter.ban_score == 0
    assert limiter.total_requests == 0
    assert limiter.total_errors == 0


def test_success_recovery():
    limiter = AdaptiveRateLimiter("test_shop")
    # First inflate the interval
    limiter.record_result(False, status_code=429)
    inflated = limiter.current_interval()
    assert inflated > DEFAULT_INTERVAL

    # Record RECOVERY_STREAK successes to step back down
    for _ in range(RECOVERY_STREAK):
        limiter.record_result(True, status_code=200)

    assert limiter.current_interval() < inflated


def test_429_doubles_interval():
    limiter = AdaptiveRateLimiter("test_shop")
    before = limiter.current_interval()
    limiter.record_result(False, status_code=429)
    assert limiter.current_interval() == before * 2


def test_503_doubles_interval():
    limiter = AdaptiveRateLimiter("test_shop")
    before = limiter.current_interval()
    limiter.record_result(False, status_code=503)
    assert limiter.current_interval() == before * 2


def test_403_pauses():
    limiter = AdaptiveRateLimiter("test_shop")
    limiter.record_result(False, status_code=403)
    assert limiter.is_paused() is True


def test_max_interval_cap():
    limiter = AdaptiveRateLimiter("test_shop")
    # Keep doubling via 429 errors
    for _ in range(20):
        limiter.record_result(False, status_code=429)
    assert limiter.current_interval() <= MAX_INTERVAL


def test_status_dict():
    limiter = AdaptiveRateLimiter("test_shop")
    limiter.record_result(True, status_code=200)
    status = limiter.status_dict()
    expected_keys = {
        "shop_id",
        "interval",
        "ban_score",
        "consecutive_failures",
        "paused",
        "pause_remaining",
        "total_requests",
        "total_errors",
        "error_rate",
    }
    assert set(status.keys()) == expected_keys
    assert status["shop_id"] == "test_shop"
    assert status["total_requests"] == 1
    assert status["total_errors"] == 0


def test_get_limiter_creates_once():
    # Clear registry to isolate test
    _limiters.clear()
    limiter1 = get_limiter("singleton_shop")
    limiter2 = get_limiter("singleton_shop")
    assert limiter1 is limiter2
    _limiters.clear()
