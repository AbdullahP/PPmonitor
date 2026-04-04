"""Tests for the scraper HTML parsing logic."""

import httpx
import pytest

from monitor.scraper import (
    _parse_product_page,
    fetch_product,
    parse_category_page,
)

SAMPLE_HTML_IN_STOCK = """\
<html>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "productID": "9300000239014079",
  "name": "Test Pokemon Product",
  "offers": {
    "@type": "Offer",
    "price": "35.99",
    "availability": "InStock",
    "seller": {"@type": "Organization", "name": "bol"}
  }
}
</script>
<script>
window.__reactRouterContext = {};
window.__reactRouterContext.streamController = {};
window.__reactRouterContext.streamController.enqueue(
  "{\\"revisionId\\": \\"abc12300-0000-0000-0000-000000000000\\", \\"offerUid\\": \\"def45600-0000-0000-0000-000000000000\\"}"
);
</script>
</html>
"""

SAMPLE_HTML_OUT_OF_STOCK = """\
<html>
<script type="application/ld+json">
{
  "@type": "Product",
  "productID": "9300000200000001",
  "name": "OOS Product",
  "offers": {
    "price": "59.99",
    "availability": "OutOfStock",
    "seller": {"name": "bol"}
  }
}
</script>
<script>
window.__reactRouterContext = {};
window.__reactRouterContext.streamController = {};
window.__reactRouterContext.streamController.enqueue(
  "{\\"revisionId\\": \\"a1b2c3d4-e5f6-7890-abcd-ef1234567890\\", \\"offerUid\\": \\"f0e1d2c3-b4a5-6789-0abc-def012345678\\"}"
);
</script>
</html>
"""


def test_parse_in_stock():
    data = _parse_product_page(SAMPLE_HTML_IN_STOCK)
    assert data.product_id == "9300000239014079"
    assert data.name == "Test Pokemon Product"
    assert data.price == "35.99"
    assert data.availability == "InStock"
    assert data.offer_uid == "def45600-0000-0000-0000-000000000000"
    assert data.revision_id == "abc12300-0000-0000-0000-000000000000"
    assert data.seller == "bol"


def test_parse_out_of_stock():
    data = _parse_product_page(SAMPLE_HTML_OUT_OF_STOCK)
    assert data.product_id == "9300000200000001"
    assert data.availability == "OutOfStock"
    assert data.revision_id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    assert data.offer_uid == "f0e1d2c3-b4a5-6789-0abc-def012345678"


def test_parse_category_page():
    html = """
    <a href="/nl/nl/p/pokemon-thing/9300000111111111/" class="product-title">A</a>
    <a href="/nl/nl/p/pokemon-other/9300000222222222/" class="product-title">B</a>
    """
    ids = parse_category_page(html)
    assert ids == {"9300000111111111", "9300000222222222"}


def test_parse_no_json_ld():
    data = _parse_product_page("<html><body>No data here</body></html>")
    assert data.availability == "Unknown"
    assert data.product_id == ""


@pytest.mark.asyncio
async def test_fetch_product_from_mock(mock_server_url):
    url = f"{mock_server_url}/nl/nl/p/pokemon-team-rockets-mewtwo-ex-league-battle-deck/9300000239014079/"
    async with httpx.AsyncClient() as client:
        data = await fetch_product(client, url)
    assert data.product_id == "9300000239014079"
    assert data.name is not None
    assert data.offer_uid is not None
    assert data.latency_ms >= 0
