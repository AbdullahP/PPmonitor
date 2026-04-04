"""Redirect service: fast path from Discord alert to bol.com basket."""

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

app = FastAPI(title="Checkout Redirect")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "redirect"}


@app.get("/go", response_class=HTMLResponse)
async def go(sku: str = Query(...), offer: str = Query(...)):
    return f"""\
<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>Adding to cart...</title>
  <style>
    body {{ font-family: sans-serif; display: flex; justify-content: center;
           align-items: center; height: 100vh; margin: 0; background: #f5f5f5; }}
    .msg {{ text-align: center; }}
    .spinner {{ border: 4px solid #ddd; border-top: 4px solid #333;
                border-radius: 50%; width: 40px; height: 40px;
                animation: spin 0.8s linear infinite; margin: 20px auto; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  </style>
</head>
<body>
  <div class="msg">
    <div class="spinner"></div>
    <p>Adding to cart, please wait...</p>
  </div>
  <form id="f" method="POST"
        action="https://www.bol.com/nl/order/basket/addItems.html">
    <input type="hidden" name="offerUid" value="{offer}">
    <input type="hidden" name="quantity" value="1">
    <input type="hidden" name="skus[0]" value="{sku}">
  </form>
  <script>document.getElementById('f').submit();</script>
</body>
</html>
"""
