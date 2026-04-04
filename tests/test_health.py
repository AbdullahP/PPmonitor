"""Tests for the health monitoring module."""

import pytest
from datetime import datetime, timedelta, timezone

from monitor.health import get_product_status, log_poll_result, write_heartbeat, get_system_health


def test_product_status_healthy():
    now = datetime.now(timezone.utc)
    assert get_product_status(now, 50) == "healthy"


def test_product_status_slow():
    now = datetime.now(timezone.utc)
    assert get_product_status(now, 25000) == "slow"


def test_product_status_dead_old():
    old = datetime.now(timezone.utc) - timedelta(seconds=60)
    assert get_product_status(old, 50) == "dead"


def test_product_status_dead_none():
    assert get_product_status(None, None) == "dead"


@pytest.mark.asyncio
async def test_log_poll_result(state):
    await state.add_product("test-001", "http://example.com/test")
    await log_poll_result(
        state,
        product_id="test-001",
        success=True,
        latency_ms=42,
        availability="InStock",
        revision_id="rev-1",
    )

    history = await state.get_poll_history("test-001", limit=5)
    assert len(history) == 1
    assert history[0]["success"] is True
    assert history[0]["latency_ms"] == 42

    await log_poll_result(state, product_id="test-001", success=False, error_message="timeout")
    product = await state.get_product("test-001")
    assert product["consecutive_failures"] == 1


@pytest.mark.asyncio
async def test_heartbeat(state):
    await write_heartbeat(state, 5)
    hb = await state.get_last_heartbeat()
    assert hb is not None
    assert hb["products_polled_count"] == 5


@pytest.mark.asyncio
async def test_system_health(state):
    health = await get_system_health(state)
    assert "monitor_alive" in health
    assert "total_products" in health
