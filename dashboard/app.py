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


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not settings.dashboard_auth_enabled:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error_block": ""})


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
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

    return templates.TemplateResponse(
        request, "login.html",
        {"error_block": '<div class="error">Invalid username or password</div>'},
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
# Test webhooks API
# ---------------------------------------------------------------------------

@app.post("/api/test-webhook")
async def api_test_webhook(state: StateManager = Depends(get_state)):
    from monitor.alerts import test_all_webhooks
    return await test_all_webhooks(state=state)


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

    try:
        discord_servers = await state.list_discord_servers(active_only=False)
    except Exception:
        logger.exception("Failed to list discord servers")
        discord_servers = []

    return templates.TemplateResponse(request, "index.html", {
        "active_page": "overview",
        "products": products,
        "sys_health": sys_health,
        "alerts_today": alerts_today,
        "discovered": discovered,
        "rate_limiters": rate_limiters,
        "upcoming_sets": get_upcoming_sets(),
        "discord_servers": discord_servers,
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
        "active_page": "overview",
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

    try:
        webhook_errors = await state.get_webhook_errors(limit=50)
    except Exception:
        logger.exception("Failed to get webhook errors")
        webhook_errors = []

    return templates.TemplateResponse(request, "logs.html", {
        "active_page": "logs",
        "errors": errors,
        "products": products,
        "selected_product": product_id,
        "webhook_errors": webhook_errors,
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
        "active_page": "alerts",
        "alerts": alerts,
    })


# ---------------------------------------------------------------------------
# Keywords management
# ---------------------------------------------------------------------------

@app.get("/keywords", response_class=HTMLResponse)
async def keywords_page(request: Request, state: StateManager = Depends(get_state)):
    try:
        keywords = await state.list_keywords(active_only=False)
    except Exception:
        logger.exception("Failed to list keywords")
        keywords = []

    try:
        match_counts = await state.get_keyword_match_counts()
    except Exception:
        logger.exception("Failed to get keyword match counts")
        match_counts = {}

    return templates.TemplateResponse(request, "keywords.html", {
        "active_page": "keywords",
        "keywords": keywords,
        "match_counts": match_counts,
    })


@app.post("/keywords/add")
async def add_keyword(
    keyword: str = Form(...),
    match_type: str = Form(default="contains"),
    priority: str = Form(default="normal"),
    shops: list[str] = Form(default=[]),
    auto_monitor: bool = Form(default=False),
    notes: str = Form(default=""),
    state: StateManager = Depends(get_state),
):
    all_shops = ["bol", "mediamarkt", "pocketgames",
                 "catchyourcards", "games_island", "dreamland"]
    selected_shops = shops if shops else all_shops
    await state.add_keyword(
        keyword=keyword,
        match_type=match_type,
        priority=priority,
        shops=selected_shops,
        auto_monitor=auto_monitor,
        notes=notes or None,
    )
    return RedirectResponse("/keywords", status_code=303)


@app.post("/keywords/delete/{keyword_id}")
async def delete_keyword(keyword_id: int, state: StateManager = Depends(get_state)):
    await state.delete_keyword(keyword_id)
    return RedirectResponse("/keywords", status_code=303)


@app.post("/keywords/toggle/{keyword_id}")
async def toggle_keyword(keyword_id: int, state: StateManager = Depends(get_state)):
    await state.toggle_keyword(keyword_id)
    return RedirectResponse("/keywords", status_code=303)


# ---------------------------------------------------------------------------
# Discord server management
# ---------------------------------------------------------------------------

@app.get("/discord", response_class=HTMLResponse)
async def discord_page(request: Request, state: StateManager = Depends(get_state)):
    try:
        servers = await state.list_discord_servers(active_only=False)
    except Exception:
        logger.exception("Failed to list discord servers")
        servers = []

    return templates.TemplateResponse(request, "discord.html", {
        "active_page": "discord",
        "servers": servers,
    })


@app.post("/discord/add")
async def add_discord_server(
    name: str = Form(...),
    description: str = Form(default=""),
    public_webhook: str = Form(default=""),
    admin_webhook: str = Form(default=""),
    discovery_webhook: str = Form(default=""),
    bot_token: str = Form(default=""),
    channel_id: str = Form(default=""),
    send_stock_alerts: bool = Form(default=False),
    send_discovery_alerts: bool = Form(default=False),
    send_admin_alerts: bool = Form(default=False),
    send_queue_alerts: bool = Form(default=False),
    state: StateManager = Depends(get_state),
):
    await state.add_discord_server(
        name=name,
        description=description or None,
        public_webhook=public_webhook or None,
        admin_webhook=admin_webhook or None,
        discovery_webhook=discovery_webhook or None,
        bot_token=bot_token or None,
        channel_id=channel_id or None,
        send_stock_alerts=send_stock_alerts,
        send_discovery_alerts=send_discovery_alerts,
        send_admin_alerts=send_admin_alerts,
        send_queue_alerts=send_queue_alerts,
    )
    return RedirectResponse("/discord", status_code=303)


@app.post("/discord/{server_id}/delete")
async def delete_discord_server(server_id: int, state: StateManager = Depends(get_state)):
    await state.delete_discord_server(server_id)
    return RedirectResponse("/discord", status_code=303)


@app.post("/discord/{server_id}/toggle")
async def toggle_discord_server(server_id: int, state: StateManager = Depends(get_state)):
    await state.toggle_discord_server(server_id)
    return RedirectResponse("/discord", status_code=303)


@app.post("/discord/{server_id}/test")
async def test_discord_server(server_id: int, state: StateManager = Depends(get_state)):
    server = await state.get_discord_server(server_id)
    if not server:
        raise HTTPException(404, "Server not found")

    from monitor.alerts import test_server_webhooks
    from datetime import datetime, timezone

    results = await test_server_webhooks(server, state=state)

    any_ok = any(r["ok"] for r in results.values() if r.get("configured"))
    any_failed = any(not r["ok"] for r in results.values() if r.get("configured"))
    test_result = "ok" if any_ok and not any_failed else "failed" if any_failed else "untested"
    test_error = None
    if any_failed:
        failed = [
            f"{k}: {r.get('error', '')[:100]}"
            for k, r in results.items()
            if r.get("configured") and not r["ok"]
        ]
        test_error = "; ".join(failed)

    await state.update_discord_server(
        server_id,
        last_tested_at=datetime.now(timezone.utc),
        last_test_result=test_result,
        last_test_error=test_error,
    )

    return results


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
        elif "amazon.co.uk" in url_lower:
            shop = "amazon_uk"
        else:
            shop = "bol"

    # Extract product_id: numeric ID for bol/mediamarkt, ASIN for Amazon, slug for others
    if shop in ("bol", "mediamarkt"):
        match = re.search(r'/(\d{5,})(?:[/.]|$)', url)
        if not match:
            raise HTTPException(400, "Could not extract product ID from URL")
        product_id = match.group(1)
    elif shop == "amazon_uk":
        match = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)', url)
        if not match:
            raise HTTPException(400, "Could not extract ASIN from Amazon URL")
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
