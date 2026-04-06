"""Tests for the dashboard web interface."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


def _mock_state():
    """Mock StateManager that returns empty data for all queries."""
    state = AsyncMock()
    state.list_products = AsyncMock(return_value=[])
    state.get_alerts_today_count = AsyncMock(return_value=0)
    state.list_discovered = AsyncMock(return_value=[])
    state.list_discovered_filtered = AsyncMock(return_value=[])
    state.get_last_heartbeat = AsyncMock(return_value=None)
    state.get_recent_errors = AsyncMock(return_value=[])
    state.get_alerts = AsyncMock(return_value=[])
    state.get_discord_status = AsyncMock(return_value={})
    state.get_webhook_errors = AsyncMock(return_value=[])
    state.list_discord_servers = AsyncMock(return_value=[])
    state.list_shop_modules = AsyncMock(return_value=[])
    state.get_in_stock_count = AsyncMock(return_value=0)
    state.list_keywords = AsyncMock(return_value=[])
    state.get_keyword_match_counts = AsyncMock(return_value={})
    state.get_table_counts = AsyncMock(return_value={})
    return state


@pytest.fixture
def dashboard_client():
    from dashboard.app import app, get_state

    mock_state = _mock_state()
    app.dependency_overrides[get_state] = lambda: mock_state
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


def _login(client):
    """Log in via the session cookie flow."""
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "changeme"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return client


def test_health_no_auth(dashboard_client):
    resp = dashboard_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "dashboard"


def test_index_requires_auth(dashboard_client):
    resp = dashboard_client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers.get("location", "")


def test_index_with_auth(dashboard_client):
    _login(dashboard_client)
    resp = dashboard_client.get("/")
    assert resp.status_code == 200
    assert "Monitor" in resp.text


def test_modules_page(dashboard_client):
    _login(dashboard_client)
    resp = dashboard_client.get("/modules")
    assert resp.status_code == 200
    assert "Modules" in resp.text


def test_products_page(dashboard_client):
    _login(dashboard_client)
    resp = dashboard_client.get("/products")
    assert resp.status_code == 200
    assert "Products" in resp.text


def test_discoveries_page(dashboard_client):
    _login(dashboard_client)
    resp = dashboard_client.get("/discoveries")
    assert resp.status_code == 200
    assert "Discoveries" in resp.text


def test_logs_page(dashboard_client):
    _login(dashboard_client)
    resp = dashboard_client.get("/logs")
    assert resp.status_code == 200
    assert "Logs" in resp.text


def test_alerts_page(dashboard_client):
    _login(dashboard_client)
    resp = dashboard_client.get("/alerts")
    assert resp.status_code == 200
    assert "Alert History" in resp.text


def test_keywords_page(dashboard_client):
    _login(dashboard_client)
    resp = dashboard_client.get("/keywords")
    assert resp.status_code == 200
    assert "Keywords" in resp.text


def test_discord_page(dashboard_client):
    _login(dashboard_client)
    resp = dashboard_client.get("/discord")
    assert resp.status_code == 200
    assert "Discord" in resp.text


def test_system_page(dashboard_client):
    _login(dashboard_client)
    resp = dashboard_client.get("/system")
    assert resp.status_code == 200
    assert "System" in resp.text
