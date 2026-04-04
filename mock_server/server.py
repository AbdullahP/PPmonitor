"""Mock bol.com server for testing the stock monitor pipeline."""

import json
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Mock bol.com Server")

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

products: dict[str, dict] = {}


def _seed_products():
    seeds = [
        {
            "product_id": "9300000239014079",
            "slug": "pokemon-team-rockets-mewtwo-ex-league-battle-deck",
            "name": "Pokémon - Team Rocket's Mewtwo ex League Battle Deck",
            "price": "35.99",
            "stock": "out_of_stock",
            "offer_uid": str(uuid.uuid4()),
            "revision_id": str(uuid.uuid4()),
            "added_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "product_id": "9300000200000001",
            "slug": "pokemon-prismatic-evolutions-elite-trainer-box",
            "name": "Pokémon TCG - Prismatic Evolutions Elite Trainer Box",
            "price": "59.99",
            "stock": "out_of_stock",
            "offer_uid": str(uuid.uuid4()),
            "revision_id": str(uuid.uuid4()),
            "added_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "product_id": "9300000200000002",
            "slug": "pokemon-surging-sparks-booster-bundle",
            "name": "Pokémon TCG - Surging Sparks Booster Bundle",
            "price": "24.99",
            "stock": "in_stock",
            "offer_uid": str(uuid.uuid4()),
            "revision_id": str(uuid.uuid4()),
            "added_at": datetime.now(timezone.utc).isoformat(),
        },
    ]
    for s in seeds:
        products[s["product_id"]] = s


_seed_products()

# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

PRODUCT_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>{name} | bol.com</title>
</head>
<body>
  <div class="pdp-header">
    <h1 data-test="title">{name}</h1>
    <span class="promo-price" data-test="price">&euro;{price}</span>
    <span class="buy-block__availability" data-test="availability">{stock_text_nl}</span>
  </div>

  <!-- Schema.org JSON-LD (PRIMARY stock signal) -->
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Product",
    "@id": "https://www.bol.com/#{product_id}",
    "name": "{name}",
    "productID": "{product_id}",
    "offers": {{
      "@type": "Offer",
      "price": "{price}",
      "priceCurrency": "EUR",
      "itemCondition": "https://schema.org/NewCondition",
      "availability": "{availability_schema}",
      "seller": {{
        "@type": "Organization",
        "name": "bol"
      }}
    }}
  }}
  </script>

  <!-- React Router context (SECONDARY signals: revisionId, offerUid) -->
  <script>
    window.__reactRouterContext = {{}};
    window.__reactRouterContext.streamController = {{}};
    window.__reactRouterContext.streamController.enqueue(
      {react_router_payload}
    );
  </script>

  <!-- Add-to-cart link -->
  <a href="/nl/order/basket/addItems.html?productId={product_id}&offerUid={offer_uid}&quantity=1"
     class="js-btn-buy"
     data-test="buy-button">In winkelwagen</a>
</body>
</html>
"""

CATEGORY_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>Pokémon kaarten | bol.com</title>
</head>
<body>
  <div class="product-list">
    {product_links}
  </div>
</body>
</html>
"""


def _render_product_page(p: dict) -> str:
    in_stock = p["stock"] == "in_stock"
    stock_text_nl = "Op voorraad" if in_stock else "Niet op voorraad"
    availability_schema = "InStock" if in_stock else "OutOfStock"

    react_router_data = {
        "revisionId": p["revision_id"],
        "offerUid": p["offer_uid"],
        "stock": stock_text_nl,
        "purchaseType": "STANDARD" if in_stock else "NONE",
        "isScarce": False,
    }

    return PRODUCT_PAGE_TEMPLATE.format(
        name=p["name"],
        price=p["price"],
        product_id=p["product_id"],
        stock_text_nl=stock_text_nl,
        availability_schema=availability_schema,
        offer_uid=p["offer_uid"],
        react_router_payload=json.dumps(json.dumps(react_router_data)),
    )


def _render_category_page(sort_newest: bool = False) -> str:
    items = list(products.values())
    if sort_newest:
        items.sort(key=lambda p: p.get("added_at", ""), reverse=True)

    links = []
    for p in items:
        links.append(
            f'<a href="/nl/nl/p/{p["slug"]}/{p["product_id"]}/" '
            f'class="product-title">{p["name"]}</a>'
        )
    product_links = "\n    ".join(links) if links else "<p>Geen producten gevonden</p>"
    return CATEGORY_PAGE_TEMPLATE.format(product_links=product_links)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "mock_server"}


# ---------------------------------------------------------------------------
# Product page route
# ---------------------------------------------------------------------------

@app.get("/nl/nl/p/{slug}/{product_id}/", response_class=HTMLResponse)
async def product_page(slug: str, product_id: str):
    p = products.get(product_id)
    if not p:
        raise HTTPException(404, f"Product {product_id} not found")
    return _render_product_page(p)


# ---------------------------------------------------------------------------
# Category page routes (default sort + ?sortering=4 for newest)
# ---------------------------------------------------------------------------

@app.get("/nl/nl/l/pokemon-kaarten/N/8299+16410/", response_class=HTMLResponse)
async def category_page(sortering: int | None = Query(default=None)):
    sort_newest = sortering == 4
    return _render_category_page(sort_newest=sort_newest)


# ---------------------------------------------------------------------------
# Admin control endpoints
# ---------------------------------------------------------------------------

class SetStockRequest(BaseModel):
    product_id: str
    status: str  # "in_stock" or "out_of_stock"


class AddProductRequest(BaseModel):
    product_id: str
    name: str
    price: str
    slug: str | None = None


@app.post("/admin/set-stock")
async def set_stock(req: SetStockRequest):
    p = products.get(req.product_id)
    if not p:
        raise HTTPException(404, f"Product {req.product_id} not found")

    if req.status not in ("in_stock", "out_of_stock"):
        raise HTTPException(400, "status must be 'in_stock' or 'out_of_stock'")

    old_stock = p["stock"]
    p["stock"] = req.status
    p["revision_id"] = str(uuid.uuid4())

    return {
        "product_id": req.product_id,
        "old_stock": old_stock,
        "new_stock": req.status,
        "new_revision_id": p["revision_id"],
        "offer_uid": p["offer_uid"],
    }


@app.post("/admin/add-product")
async def add_product(req: AddProductRequest):
    if req.product_id in products:
        raise HTTPException(409, f"Product {req.product_id} already exists")

    slug = req.slug or req.name.lower().replace(" ", "-").replace("é", "e")
    products[req.product_id] = {
        "product_id": req.product_id,
        "slug": slug,
        "name": req.name,
        "price": req.price,
        "stock": "out_of_stock",
        "offer_uid": str(uuid.uuid4()),
        "revision_id": str(uuid.uuid4()),
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"product_id": req.product_id, "status": "added"}


@app.get("/admin/state")
async def admin_state():
    return {"products": products, "timestamp": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8099)
