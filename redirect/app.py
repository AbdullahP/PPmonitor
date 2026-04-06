"""Redirect service: fast path from Discord alert to shop basket."""

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI(title="Checkout Redirect")

_SPINNER_HEAD = """\
<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>Adding to cart...</title>
  <style>
    body { font-family: sans-serif; display: flex; justify-content: center;
           align-items: center; height: 100vh; margin: 0; background: #f5f5f5; }
    .msg { text-align: center; }
    .spinner { border: 4px solid #ddd; border-top: 4px solid #333;
                border-radius: 50%; width: 40px; height: 40px;
                animation: spin 0.8s linear infinite; margin: 20px auto; }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="msg">
    <div class="spinner"></div>
    <p>Adding to cart, please wait...</p>
  </div>"""

_SPINNER_TAIL = """\
</body>
</html>"""


def _wrap(body: str) -> str:
    return f"{_SPINNER_HEAD}\n{body}\n{_SPINNER_TAIL}"


def _bol_page(sku: str, offer: str) -> str:
    return _wrap(
        f'  <form id="f" method="POST"'
        f' action="https://www.bol.com/nl/order/basket/addItems.html">\n'
        f'    <input type="hidden" name="offerUid" value="{offer}">\n'
        f'    <input type="hidden" name="quantity" value="1">\n'
        f'    <input type="hidden" name="skus[0]" value="{sku}">\n'
        f"  </form>\n"
        f'  <script>document.getElementById("f").submit();</script>'
    )


def _mediamarkt_page(sku: str) -> str:
    return _wrap(
        f"  <script>\n"
        f"  fetch('https://www.mediamarkt.nl/api/basket-service/basket/add', {{\n"
        f"    method: 'POST',\n"
        f"    credentials: 'include',\n"
        f"    headers: {{'Content-Type': 'application/json'}},\n"
        f"    body: JSON.stringify({{productId: '{sku}', quantity: 1}})\n"
        f"  }}).then(() => window.location = 'https://www.mediamarkt.nl/nl/cart.html')\n"
        f"  </script>"
    )


def _pocketgames_page(variant: str) -> str:
    return _wrap(
        f'  <form id="f" method="POST" action="https://pocketgames.nl/cart/add">\n'
        f'    <input type="hidden" name="id" value="{variant}">\n'
        f'    <input type="hidden" name="quantity" value="1">\n'
        f"  </form>\n"
        f"  <script>\n"
        f'  document.getElementById("f").addEventListener("submit", function() {{\n'
        f"    setTimeout(function(){{ window.location = 'https://pocketgames.nl/cart'; }}, 1500);\n"
        f"  }});\n"
        f'  document.getElementById("f").submit();\n'
        f"  </script>"
    )


def _catchyourcards_page(sku: str) -> str:
    return _wrap(
        f'  <form id="f" method="POST"'
        f' action="https://catchyourcards.nl/?add-to-cart={sku}">\n'
        f"  </form>\n"
        f"  <script>\n"
        f'  document.getElementById("f").addEventListener("submit", function() {{\n'
        f"    setTimeout(function(){{ window.location = 'https://catchyourcards.nl/cart/'; }}, 1500);\n"
        f"  }});\n"
        f'  document.getElementById("f").submit();\n'
        f"  </script>"
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "redirect"}


@app.get("/go", response_class=HTMLResponse)
async def go(
    shop: str = Query("bol"),
    sku: str = Query(""),
    offer: str = Query(""),
    handle: str = Query(""),
    variant: str = Query(""),
):
    if shop == "bol":
        return HTMLResponse(_bol_page(sku, offer))

    if shop == "mediamarkt":
        return HTMLResponse(_mediamarkt_page(sku))

    if shop == "pocketgames":
        return HTMLResponse(_pocketgames_page(variant or sku))

    if shop == "catchyourcards":
        return HTMLResponse(_catchyourcards_page(sku))

    if shop == "amazon_nl":
        asin = sku
        return RedirectResponse(
            f"https://www.amazon.nl/gp/aws/cart/add.html?ASIN.1={asin}&Quantity.1=1",
            status_code=302,
        )

    if shop == "amazon_de":
        asin = sku
        return RedirectResponse(
            f"https://www.amazon.de/gp/aws/cart/add.html?ASIN.1={asin}&Quantity.1=1",
            status_code=302,
        )

    if shop == "games_island":
        return RedirectResponse(
            f"https://games-island.eu/search?q={sku}", status_code=302
        )

    # DECISION: dreamland.nl add-to-cart mechanism needs investigation.
    # For now redirect to the product page so the user lands on the site
    # with their existing session.
    if shop == "dreamland":
        return RedirectResponse(
            f"https://www.dreamland.be/e/nl/search?q={sku}", status_code=302
        )

    # Unknown shop — fall back to bol behaviour for backwards compat
    return HTMLResponse(_bol_page(sku, offer))
