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
    state.get_last_heartbeat = AsyncMock(return_value=None)
    state.get_recent_errors = AsyncMock(return_value=[])
    state.get_alerts = AsyncMock(return_value=[])
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
    # Session auth redirects to /login (303)
    assert resp.status_code == 303
    assert "/login" in resp.headers.get("location", "")


def test_index_with_auth(dashboard_client):
    _login(dashboard_client)
    resp = dashboard_client.get("/")
    assert resp.status_code == 200
    assert "Monitor" in resp.text


def test_logs_page(dashboard_client):
    _login(dashboard_client)
    resp = dashboard_client.get("/logs")
    assert resp.status_code == 200
    assert "Error Logs" in resp.text


def test_alerts_page(dashboard_client):
    _login(dashboard_client)
    resp = dashboard_client.get("/alerts")
    assert resp.status_code == 200
    assert "Alert History" in resp.text
