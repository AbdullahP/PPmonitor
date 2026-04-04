"""Sanity tests for the mock bol.com server."""

import httpx


def test_health(mock_server_url):
    resp = httpx.get(f"{mock_server_url}/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_product_page_returns_html(mock_server_url):
    url = f"{mock_server_url}/nl/nl/p/pokemon-team-rockets-mewtwo-ex-league-battle-deck/9300000239014079/"
    resp = httpx.get(url)
    assert resp.status_code == 200
    assert "application/ld+json" in resp.text
    assert "9300000239014079" in resp.text


def test_product_page_404(mock_server_url):
    resp = httpx.get(f"{mock_server_url}/nl/nl/p/fake/0000000000000000/")
    assert resp.status_code == 404


def test_set_stock_changes_revision(mock_server_url):
    resp = httpx.get(f"{mock_server_url}/admin/state")
    initial_rev = resp.json()["products"]["9300000239014079"]["revision_id"]

    resp = httpx.post(
        f"{mock_server_url}/admin/set-stock",
        json={"product_id": "9300000239014079", "status": "in_stock"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["new_stock"] == "in_stock"
    assert data["new_revision_id"] != initial_rev

    page = httpx.get(
        f"{mock_server_url}/nl/nl/p/pokemon-team-rockets-mewtwo-ex-league-battle-deck/9300000239014079/"
    )
    assert '"availability": "InStock"' in page.text


def test_category_page(mock_server_url):
    resp = httpx.get(f"{mock_server_url}/nl/nl/l/pokemon-kaarten/N/8299+16410/")
    assert resp.status_code == 200
    assert "9300000239014079" in resp.text


def test_category_page_sorted(mock_server_url):
    resp = httpx.get(f"{mock_server_url}/nl/nl/l/pokemon-kaarten/N/8299+16410/?sortering=4")
    assert resp.status_code == 200
    assert "product-title" in resp.text


def test_add_product(mock_server_url):
    resp = httpx.post(
        f"{mock_server_url}/admin/add-product",
        json={"product_id": "9300000999999999", "name": "Test Product", "price": "9.99"},
    )
    assert resp.status_code == 200
    cat = httpx.get(f"{mock_server_url}/nl/nl/l/pokemon-kaarten/N/8299+16410/")
    assert "9300000999999999" in cat.text
