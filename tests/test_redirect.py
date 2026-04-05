"""Tests for the redirect service."""

from fastapi.testclient import TestClient

from redirect.app import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "redirect"


def test_go_bol_default():
    resp = client.get("/go?sku=9300000239014079&offer=abc-123-def")
    assert resp.status_code == 200
    html = resp.text
    assert 'name="offerUid" value="abc-123-def"' in html
    assert 'name="skus[0]" value="9300000239014079"' in html
    assert 'name="quantity" value="1"' in html
    assert "bol.com/nl/order/basket/addItems.html" in html


def test_go_bol_explicit():
    resp = client.get("/go?shop=bol&sku=111&offer=222")
    assert resp.status_code == 200
    assert "bol.com/nl/order/basket/addItems.html" in resp.text


def test_go_mediamarkt():
    resp = client.get("/go?shop=mediamarkt&sku=12345")
    assert resp.status_code == 200
    html = resp.text
    assert "mediamarkt.nl/api/basket-service/basket/add" in html
    assert "12345" in html


def test_go_pocketgames():
    resp = client.get("/go?shop=pocketgames&variant=44455566")
    assert resp.status_code == 200
    html = resp.text
    assert "pocketgames.nl/cart/add" in html
    assert "44455566" in html


def test_go_catchyourcards():
    resp = client.get("/go?shop=catchyourcards&sku=pokemon-etb")
    assert resp.status_code == 200
    assert "catchyourcards.nl/?add-to-cart=pokemon-etb" in resp.text


def test_go_games_island_redirect():
    resp = client.get("/go?shop=games_island&sku=test", follow_redirects=False)
    assert resp.status_code == 302
    assert "games-island.eu" in resp.headers["location"]


def test_go_dreamland_redirect():
    resp = client.get("/go?shop=dreamland&sku=test", follow_redirects=False)
    assert resp.status_code == 302
    assert "dreamland.be" in resp.headers["location"]


def test_go_auto_submits():
    resp = client.get("/go?sku=111&offer=222")
    assert 'document.getElementById("f").submit()' in resp.text


def test_go_html_content_type():
    resp = client.get("/go?sku=111&offer=222")
    assert "text/html" in resp.headers["content-type"]


def test_go_spinner_present():
    resp = client.get("/go?sku=111&offer=222")
    assert "spinner" in resp.text
    assert "Adding to cart" in resp.text
