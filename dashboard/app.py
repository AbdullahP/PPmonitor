"""Admin dashboard: FastAPI + Jinja2 + HTMX + Tailwind."""

import json as _json
import logging
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from monitor.health import get_product_status, get_system_health
from monitor.intelligence import get_upcoming_sets
from monitor.predictor import get_restock_prediction
from monitor.rate_limiter import all_limiter_statuses
from monitor.state import StateManager

logger = logging.getLogger(__name__)

app = FastAPI(title="Pokemon Monitor Dashboard", debug=True)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_state: StateManager | None = None
_signer = URLSafeTimedSerializer(settings.dashboard_secret_key)

SESSION_COOKIE = "dashboard_session"
SESSION_MAX_AGE = 86400  # 24 hours

PUBLIC_PATHS = {"/health", "/login", "/logout"}

# Safe-default dict for get_system_health when it fails
_EMPTY_HEALTH = {
    "monitor_alive": False,
    "total_products": 0,
    "healthy": 0,
    "slow": 0,
    "dead": 0,
    "last_heartbeat": None,
}


async def get_state() -> StateManager:
    global _state
    if _state is None:
        _state = await StateManager.create()
    return _state


@app.on_event("shutdown")
async def shutdown():
    global _state
    if _state:
        await _state.close()
        _state = None


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def create_session_cookie(username: str) -> str:
    return _signer.dumps({"user": username})


def verify_session_cookie(value: str) -> str | None:
    try:
        data = _signer.loads(value, max_age=SESSION_MAX_AGE)
        return data.get("user")
    except (BadSignature, SignatureExpired):
        return None


# ---------------------------------------------------------------------------
# Auth middleware — skipped entirely when DASHBOARD_AUTH_ENABLED=false
# ---------------------------------------------------------------------------

class SessionAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.dashboard_auth_enabled:
            return await call_next(request)

        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        cookie = request.cookies.get(SESSION_COOKIE)
        if cookie and verify_session_cookie(cookie):
            return await call_next(request)

        return RedirectResponse("/login", status_code=303)


app.add_middleware(SessionAuthMiddleware)


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

_LOGIN_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Login — Pokemon Monitor</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>tailwindcss.config={{theme:{{extend:{{colors:{{bg:'#0f1117',card:'#1a1d2e',border:'#2d3148',accent:'#3b82f6'}}}}}}}}}</script>
</head>
<body class="bg-bg min-h-screen flex items-center justify-center">
  <div class="bg-card border border-border rounded-xl p-8 w-full max-w-sm shadow-2xl">
    <h2 class="text-xl font-bold text-slate-100 mb-6 text-center">Pokemon Monitor</h2>
    {error}
    <form method="post" action="/login" class="space-y-4">
      <div>
        <label for="username" class="block text-sm text-slate-400 mb-1">Username</label>
        <input type="text" id="username" name="username" required autofocus
               class="w-full bg-bg border border-border rounded-lg px-3 py-2 text-slate-100 focus:border-accent focus:outline-none">
      </div>
      <div>
        <label for="password" class="block text-sm text-slate-400 mb-1">Password</label>
        <input type="password" id="password" name="password" required
               class="w-full bg-bg border border-border rounded-lg px-3 py-2 text-slate-100 focus:border-accent focus:outline-none">
      </div>
      <button type="submit" class="w-full bg-accent hover:bg-blue-600 text-white font-medium py-2 rounded-lg transition">Sign in</button>
    </form>
  </div>
</body>
</html>"""


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    if not settings.dashboard_auth_enabled:
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(_LOGIN_HTML.format(error=""))


@app.post("/login")
async def login_submit(username: str = Form(...), password: str = Form(...)):
    if not settings.dashboard_auth_enabled:
        return RedirectResponse("/", status_code=303)

    if (
        secrets.compare_digest(username, settings.dashboard_user)
        and secrets.compare_digest(password, settings.dashboard_pass)
    ):
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            create_session_cookie(username),
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
        return response

    return HTMLResponse(
        _LOGIN_HTML.format(error='<p class="text-red-400 text-sm mb-4 text-center">Invalid username or password.</p>'),
        status_code=401,
    )


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Health (no auth)
# ---------------------------------------------------------------------------

@app.get("/health")
async def health(state: StateManager = Depends(get_state)):
    sys_health = await get_system_health(state)
    return {
        "status": "ok" if sys_health["monitor_alive"] else "degraded",
        "service": "dashboard",
        "monitor_alive": sys_health["monitor_alive"],
        "products": sys_health["total_products"],
    }


# ---------------------------------------------------------------------------
# Overview page
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, state: StateManager = Depends(get_state)):
    try:
        products = await state.list_products(active_only=True)
    except Exception:
        logger.exception("Failed to list products")
        products = []

    try:
        sys_health = await get_system_health(state)
    except Exception:
        logger.exception("Failed to get system health")
        sys_health = _EMPTY_HEALTH

    try:
        alerts_today = await state.get_alerts_today_count()
    except Exception:
        logger.exception("Failed to get alerts today count")
        alerts_today = 0

    try:
        discovered = await state.list_discovered(pending_only=True)
    except Exception:
        logger.exception("Failed to list discovered products")
        discovered = []

    # Enrich products with status badge
    for p in products:
        try:
            last_poll = await state.get_poll_history(p["product_id"], limit=1)
            latency = last_poll[0]["latency_ms"] if last_poll else None
        except Exception:
            latency = None
        p["status"] = get_product_status(p.get("last_polled_at"), latency)

    # Prefer shop health from heartbeat (persisted) over in-memory limiters
    shop_health: dict = {}
    if sys_health.get("last_heartbeat") and sys_health["last_heartbeat"].get("shop_status"):
        raw = sys_health["last_heartbeat"]["shop_status"]
        shop_health = _json.loads(raw) if isinstance(raw, str) else (raw or {})

    rate_limiters = list(shop_health.values()) if shop_health else all_limiter_statuses()

    return templates.TemplateResponse(request, "index.html", {
        "products": products,
        "sys_health": sys_health,
        "alerts_today": alerts_today,
        "discovered": discovered,
        "rate_limiters": rate_limiters,
        "upcoming_sets": get_upcoming_sets(),
    })


# HTMX partial: just the products table body
@app.get("/partials/products", response_class=HTMLResponse)
async def partial_products(request: Request, state: StateManager = Depends(get_state)):
    try:
        products = await state.list_products(active_only=True)
    except Exception:
        logger.exception("Failed to list products")
        products = []

    for p in products:
        try:
            last_poll = await state.get_poll_history(p["product_id"], limit=1)
            latency = last_poll[0]["latency_ms"] if last_poll else None
        except Exception:
            latency = None
        p["status"] = get_product_status(p.get("last_polled_at"), latency)

    return templates.TemplateResponse(request, "_products_table.html", {
        "products": products,
    })


# ---------------------------------------------------------------------------
# Product detail
# ---------------------------------------------------------------------------

@app.get("/product/{product_id}", response_class=HTMLResponse)
async def product_detail(
    request: Request, product_id: str, state: StateManager = Depends(get_state)
):
    product = await state.get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    try:
        poll_history = await state.get_poll_history(product_id, limit=100)
    except Exception:
        logger.exception("Failed to get poll history for %s", product_id)
        poll_history = []

    try:
        errors = await state.get_recent_errors(product_id, limit=20)
    except Exception:
        logger.exception("Failed to get recent errors for %s", product_id)
        errors = []

    try:
        alerts = await state.get_alerts(limit=50)
    except Exception:
        logger.exception("Failed to get alerts")
        alerts = []

    product_alerts = [a for a in alerts if a.get("product_id") == product_id]

    try:
        prediction = await get_restock_prediction(state, product_id)
    except Exception:
        logger.exception("Failed to get prediction for %s", product_id)
        prediction = {"restock_count": 0, "confidence": "low"}

    return templates.TemplateResponse(request, "product.html", {
        "product": product,
        "poll_history": poll_history,
        "errors": errors,
        "alerts": product_alerts,
        "prediction": prediction,
    })


# ---------------------------------------------------------------------------
# Logs page
# ---------------------------------------------------------------------------

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    product_id: str | None = None,
    state: StateManager = Depends(get_state),
):
    try:
        errors = await state.get_recent_errors(product_id, limit=100)
    except Exception:
        logger.exception("Failed to get recent errors")
        errors = []

    try:
        products = await state.list_products(active_only=False)
    except Exception:
        logger.exception("Failed to list products")
        products = []

    return templates.TemplateResponse(request, "logs.html", {
        "errors": errors,
        "products": products,
        "selected_product": product_id,
    })


# ---------------------------------------------------------------------------
# Alerts page
# ---------------------------------------------------------------------------

@app.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request, state: StateManager = Depends(get_state)):
    try:
        alerts = await state.get_alerts(limit=200)
    except Exception:
        logger.exception("Failed to get alerts")
        alerts = []

    return templates.TemplateResponse(request, "alerts.html", {
        "alerts": alerts,
    })


# ---------------------------------------------------------------------------
# Add / remove product
# ---------------------------------------------------------------------------

@app.post("/monitor/add")
async def add_product(
    url: str = Form(...),
    name: str = Form(default=""),
    shop: str = Form(default=""),
    state: StateManager = Depends(get_state),
):
    import re

    # Auto-detect shop from URL if not specified
    if not shop:
        url_lower = url.lower()
        if "bol.com" in url_lower:
            shop = "bol"
        elif "mediamarkt" in url_lower:
            shop = "mediamarkt"
        elif "pocketgames" in url_lower:
            shop = "pocketgames"
        elif "catchyourcards" in url_lower:
            shop = "catchyourcards"
        elif "games-island" in url_lower:
            shop = "games_island"
        elif "dreamland" in url_lower:
            shop = "dreamland"
        else:
            shop = "bol"

    # Extract product_id: numeric ID for bol/mediamarkt, slug for others
    if shop in ("bol", "mediamarkt"):
        match = re.search(r'/(\d{5,})(?:[/.]|$)', url)
        if not match:
            raise HTTPException(400, "Could not extract product ID from URL")
        product_id = match.group(1)
    else:
        # Use last path segment as ID
        product_id = url.rstrip("/").split("/")[-1]

    await state.add_product(product_id, url, name=name or None, shop=shop)
    return RedirectResponse("/", status_code=303)


@app.post("/monitor/remove/{product_id}")
async def remove_product(product_id: str, state: StateManager = Depends(get_state)):
    await state.remove_product(product_id)
    return RedirectResponse("/", status_code=303)
