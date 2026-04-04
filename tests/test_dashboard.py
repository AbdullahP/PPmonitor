"""Tests for the dashboard web interface."""

import base64

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def dashboard_client():
    from dashboard.app import app

    return TestClient(app, raise_server_exceptions=False)


def _auth_header(user="admin", password="changeme"):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_health_no_auth(dashboard_client):
    resp = dashboard_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "dashboard"


def test_index_requires_auth(dashboard_client):
    assert dashboard_client.get("/").status_code == 401


def test_index_with_auth(dashboard_client):
    resp = dashboard_client.get("/", headers=_auth_header())
    assert resp.status_code == 200
    assert "Pokemon Monitor" in resp.text


def test_logs_page(dashboard_client):
    resp = dashboard_client.get("/logs", headers=_auth_header())
    assert resp.status_code == 200
    assert "Error Logs" in resp.text


def test_alerts_page(dashboard_client):
    resp = dashboard_client.get("/alerts", headers=_auth_header())
    assert resp.status_code == 200
    assert "Alert History" in resp.text
