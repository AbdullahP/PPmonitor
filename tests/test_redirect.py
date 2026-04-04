"""Tests for the redirect service."""

from fastapi.testclient import TestClient

from redirect.app import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_go_returns_form():
    resp = client.get("/go?sku=9300000239014079&offer=abc-123-def")
    assert resp.status_code == 200
    html = resp.text
    assert 'name="offerUid" value="abc-123-def"' in html
    assert 'name="skus[0]" value="9300000239014079"' in html
    assert 'name="quantity" value="1"' in html
    assert "bol.com/nl/order/basket/addItems.html" in html
    assert "document.getElementById('f').submit()" in html


def test_go_missing_params():
    assert client.get("/go").status_code == 422
    assert client.get("/go?sku=123").status_code == 422
