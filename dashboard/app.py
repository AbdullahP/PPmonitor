"""Admin dashboard: FastAPI + Jinja2 + HTMX."""

import json
import logging
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from monitor.health import get_product_status, get_system_health
from monitor.predictor import get_restock_prediction
from monitor.rate_limiter import all_limiter_statuses
from monitor.state import StateManager

logger = logging.getLogger(__name__)

app = FastAPI(title="Pokemon Monitor Dashboard", debug=True)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_state: StateManager | None = None
_signer = URLSafeTimedSerializer(settings.dashboard_secret_key)
_start_time = datetime.now(timezone.utc)

SESSION_COOKIE = "dashboard_session"
SESSION_MAX_AGE = 86400
PUBLIC_PATHS = {"/health", "/login", "/logout"}

_EMPTY_HEALTH = {
    "monitor_alive": False,
    "total_products": 0,
    "healthy": 0,
    "slow": 0,
    "dead": 0,
    "last_heartbeat": None,
}

SHOP_EMOJI = {
    "bol": "\U0001f7e0", "mediamarkt": "\U0001f534",
    "pocketgames": "\U0001f7e3", "catchyourcards": "\U0001f7e1",
    "games_island": "\U0001f7e2", "dreamland": "\U0001f535",
    "amazon_uk": "\U0001f4e6",
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
            SESSION_COOKIE, create_session_cookie(username),
            max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
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
# API endpoints
# ---------------------------------------------------------------------------

@app.post("/api/test-webhook")
async def api_test_webhook(state: StateManager = Depends(get_state)):
    from monitor.alerts import test_all_webhooks
    return await test_all_webhooks(state=state)


@app.get("/api/discord/guilds")
async def api_discord_guilds():
    """Fetch guilds the bot is a member of via Discord REST API."""
    import httpx
    token = settings.discord_bot_token
    if not token:
        return JSONResponse({"error": "DISCORD_BOT_TOKEN not configured"}, status_code=400)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://discord.com/api/v10/users/@me/guilds",
            headers={"Authorization": f"Bot {token}"},
        )
        if resp.status_code != 200:
            return JSONResponse({"error": f"Discord API error: {resp.status_code}"}, status_code=502)
        guilds = resp.json()
        return [{"id": g["id"], "name": g["name"], "icon": g.get("icon")} for g in guilds]


@app.get("/api/discord/guilds/{guild_id}/channels")
async def api_discord_channels(guild_id: str):
    """Fetch text channels for a guild via Discord REST API."""
    import httpx
    token = settings.discord_bot_token
    if not token:
        return JSONResponse({"error": "DISCORD_BOT_TOKEN not configured"}, status_code=400)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"https://discord.com/api/v10/guilds/{guild_id}/channels",
            headers={"Authorization": f"Bot {token}"},
        )
        if resp.status_code != 200:
            return JSONResponse({"error": f"Discord API error: {resp.status_code}"}, status_code=502)
        channels = resp.json()
        # type=0 is text channel
        return [
            {"id": c["id"], "name": c["name"]}
            for c in channels if c.get("type") == 0
        ]


# ---------------------------------------------------------------------------
# Overview (stripped down)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, state: StateManager = Depends(get_state)):
    try:
        sys_health = await get_system_health(state)
    except Exception:
        logger.exception("Failed to get system health")
        sys_health = _EMPTY_HEALTH

    try:
        alerts_today = await state.get_alerts_today_count()
    except Exception:
        alerts_today = 0

    try:
        modules = await state.list_shop_modules()
    except Exception:
        modules = []

    try:
        in_stock = await state.get_in_stock_count()
    except Exception:
        in_stock = 0

    try:
        recent_alerts = await state.get_alerts(limit=10)
    except Exception:
        recent_alerts = []

    active_modules = sum(1 for m in modules if m.get("is_active"))

    return templates.TemplateResponse(request, "index.html", {
        "active_page": "overview",
        "sys_health": sys_health,
        "alerts_today": alerts_today,
        "modules": modules,
        "active_modules": active_modules,
        "in_stock": in_stock,
        "recent_alerts": recent_alerts,
    })


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------

@app.get("/modules", response_class=HTMLResponse)
async def modules_page(request: Request, state: StateManager = Depends(get_state)):
    try:
        modules = await state.list_shop_modules()
    except Exception:
        logger.exception("Failed to list shop modules")
        modules = []

    rate_limiters = {s["shop_id"]: s for s in all_limiter_statuses()}

    # Get cookie health for shops that use cookies (bol)
    cookie_health = {}
    for m in modules:
        if m["shop_id"] == "bol":
            try:
                cookie_health[m["shop_id"]] = await state.get_cookie_health(m["shop_id"])
            except Exception:
                cookie_health[m["shop_id"]] = {"status": "missing", "count": 0, "age_hours": None}

    return templates.TemplateResponse(request, "modules.html", {
        "active_page": "modules",
        "modules": modules,
        "rate_limiters": rate_limiters,
        "shop_emoji": SHOP_EMOJI,
        "cookie_health": cookie_health,
    })


@app.post("/modules/{shop_id}/toggle/{field}")
async def toggle_module_field(shop_id: str, field: str, state: StateManager = Depends(get_state)):
    await state.toggle_shop_module_field(shop_id, field)
    return RedirectResponse("/modules", status_code=303)


@app.post("/modules/{shop_id}/test")
async def test_module(shop_id: str, state: StateManager = Depends(get_state)):
    import httpx
    from monitor.shops.registry import get_adapter

    try:
        adapter = get_adapter(shop_id)

        # Cookie status for shops that use cookies
        cookie_info = None
        if shop_id == "bol":
            try:
                cookie_info = await state.get_cookie_health(shop_id)
            except Exception:
                cookie_info = {"status": "unknown"}

        async with httpx.AsyncClient(timeout=15) as client:
            # Fetch category page to find products
            urls = adapter.build_category_urls()
            product_ids: set[str] = set()
            for url in urls[:1]:
                try:
                    product_ids = await adapter.fetch_category(client, url)
                except Exception:
                    pass
                if product_ids:
                    break

            if not product_ids:
                await state.update_shop_module(
                    shop_id,
                    last_test_at=datetime.now(timezone.utc),
                    last_test_result="fail",
                    last_test_error="No products found on category page",
                )
                return JSONResponse({"ok": False, "error": "No products found on category page", "cookies": cookie_info})

            # Test up to 3 products to get names
            discovered_names = []
            test_data = None
            for pid in list(product_ids)[:3]:
                product_url = adapter.build_product_url(pid)
                try:
                    data = await adapter.fetch_product(client, product_url)
                    if data.name:
                        discovered_names.append(data.name)
                    if test_data is None:
                        test_data = data
                except Exception:
                    pass

            if test_data is None:
                await state.update_shop_module(
                    shop_id,
                    last_test_at=datetime.now(timezone.utc),
                    last_test_result="fail",
                    last_test_error="Category found products but could not fetch any",
                )
                return JSONResponse({
                    "ok": False,
                    "error": "Category found products but could not fetch any",
                    "products_found": len(product_ids),
                    "cookies": cookie_info,
                })

            result = {
                "ok": True,
                "name": test_data.name or "",
                "price": test_data.price or "",
                "availability": test_data.availability or "",
                "seller": test_data.seller or "",
                "product_id": test_data.product_id or next(iter(product_ids)),
                "products_found": len(product_ids),
                "discovered_names": discovered_names,
                "cookies": cookie_info,
                "error": None,
            }

            is_certified = bool(test_data.name and test_data.price and test_data.availability != "Unknown")
            now = datetime.now(timezone.utc)
            update = {
                "last_test_at": now,
                "last_test_result": "pass",
                "last_test_error": None,
                "last_test_name": test_data.name,
                "last_test_price": test_data.price,
                "last_test_avail": test_data.availability,
            }
            if is_certified:
                update["is_certified"] = True
                update["certified_at"] = now

            await state.update_shop_module(shop_id, **update)
            return JSONResponse(result)

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        await state.update_shop_module(
            shop_id,
            last_test_at=datetime.now(timezone.utc),
            last_test_result="fail",
            last_test_error=error_msg[:500],
        )
        return JSONResponse({"ok": False, "error": error_msg[:200]})


# ---------------------------------------------------------------------------
# Cookie management
# ---------------------------------------------------------------------------

@app.get("/modules/{shop_id}/cookies", response_class=HTMLResponse)
async def cookies_page(
    request: Request, shop_id: str, state: StateManager = Depends(get_state),
):
    try:
        cookies = await state.get_shop_cookies(shop_id)
    except Exception:
        cookies = []
    try:
        health = await state.get_cookie_health(shop_id)
    except Exception:
        health = {"status": "missing", "count": 0, "age_hours": None}

    return templates.TemplateResponse(request, "cookies.html", {
        "active_page": "modules",
        "shop_id": shop_id,
        "cookies": cookies,
        "health": health,
    })


@app.post("/modules/{shop_id}/cookies")
async def save_cookies(
    shop_id: str,
    request: Request,
    state: StateManager = Depends(get_state),
):
    body = await request.body()
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        try:
            cookies_data = json.loads(body)
        except json.JSONDecodeError:
            return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    else:
        # Form submission with textarea
        form = await request.form()
        raw = form.get("cookies_json", "")
        try:
            cookies_data = json.loads(raw)
        except json.JSONDecodeError:
            return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    if not isinstance(cookies_data, list):
        return JSONResponse({"ok": False, "error": "Expected JSON array"}, status_code=400)

    count = await state.save_shop_cookies(shop_id, cookies_data)

    # If this is a form submission, redirect back
    if "application/json" not in content_type:
        return RedirectResponse(f"/modules/{shop_id}/cookies", status_code=303)

    return JSONResponse({"ok": True, "saved": count})


@app.post("/modules/{shop_id}/cookies/delete")
async def delete_cookies(shop_id: str, state: StateManager = Depends(get_state)):
    await state.delete_shop_cookies(shop_id)
    return RedirectResponse(f"/modules/{shop_id}/cookies", status_code=303)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@app.get("/products", response_class=HTMLResponse)
async def products_page(
    request: Request,
    shop: str = Query(default=""),
    availability: str = Query(default=""),
    state: StateManager = Depends(get_state),
):
    try:
        products = await state.list_products(active_only=True)
    except Exception:
        products = []

    for p in products:
        try:
            last_poll = await state.get_poll_history(p["product_id"], limit=1)
            latency = last_poll[0]["latency_ms"] if last_poll else None
        except Exception:
            latency = None
        p["status"] = get_product_status(p.get("last_polled_at"), latency)

    # Apply filters
    if shop:
        products = [p for p in products if p.get("shop") == shop]
    if availability:
        products = [p for p in products if p.get("last_availability") == availability]

    return templates.TemplateResponse(request, "products.html", {
        "active_page": "products",
        "products": products,
        "filter_shop": shop,
        "filter_availability": availability,
    })


# HTMX partial: just the products table body
@app.get("/partials/products", response_class=HTMLResponse)
async def partial_products(request: Request, state: StateManager = Depends(get_state)):
    try:
        products = await state.list_products(active_only=True)
    except Exception:
        products = []

    for p in products:
        try:
            last_poll = await state.get_poll_history(p["product_id"], limit=1)
            latency = last_poll[0]["latency_ms"] if last_poll else None
        except Exception:
            latency = None
        p["status"] = get_product_status(p.get("last_polled_at"), latency)

    return templates.TemplateResponse(request, "_products_table.html", {"products": products})


@app.post("/monitor/add")
async def add_product(
    url: str = Form(...),
    name: str = Form(default=""),
    shop: str = Form(default=""),
    state: StateManager = Depends(get_state),
):
    import re

    if not shop:
        url_lower = url.lower()
        shop_map = [
            ("bol.com", "bol"), ("mediamarkt", "mediamarkt"),
            ("pocketgames", "pocketgames"), ("catchyourcards", "catchyourcards"),
            ("games-island", "games_island"), ("dreamland", "dreamland"),
            ("amazon.co.uk", "amazon_uk"),
        ]
        shop = "bol"
        for pattern, shop_id in shop_map:
            if pattern in url_lower:
                shop = shop_id
                break

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
        product_id = url.rstrip("/").split("/")[-1]

    await state.add_product(product_id, url, name=name or None, shop=shop)
    return RedirectResponse("/products", status_code=303)


@app.post("/monitor/remove/{product_id}")
async def remove_product(product_id: str, state: StateManager = Depends(get_state)):
    await state.remove_product(product_id)
    return RedirectResponse("/products", status_code=303)


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
        poll_history = []
    try:
        errors = await state.get_recent_errors(product_id, limit=20)
    except Exception:
        errors = []
    try:
        alerts = await state.get_alerts(limit=50)
    except Exception:
        alerts = []
    product_alerts = [a for a in alerts if a.get("product_id") == product_id]
    try:
        prediction = await get_restock_prediction(state, product_id)
    except Exception:
        prediction = {"restock_count": 0, "confidence": "low"}

    return templates.TemplateResponse(request, "product.html", {
        "active_page": "products",
        "product": product,
        "poll_history": poll_history,
        "errors": errors,
        "alerts": product_alerts,
        "prediction": prediction,
    })


# ---------------------------------------------------------------------------
# Discoveries
# ---------------------------------------------------------------------------

@app.get("/discoveries", response_class=HTMLResponse)
async def discoveries_page(
    request: Request,
    shop: str = Query(default=""),
    source: str = Query(default=""),
    state: StateManager = Depends(get_state),
):
    try:
        discovered = await state.list_discovered_filtered(
            shop=shop or None, source=source or None,
            pending_only=True, limit=200,
        )
    except Exception:
        logger.exception("Failed to list discoveries")
        discovered = []

    return templates.TemplateResponse(request, "discoveries.html", {
        "active_page": "discoveries",
        "discovered": discovered,
        "filter_shop": shop,
        "filter_source": source,
    })


@app.post("/discoveries/approve")
async def approve_discoveries(
    product_ids: list[str] = Form(default=[]),
    state: StateManager = Depends(get_state),
):
    if product_ids:
        await state.bulk_approve_discoveries(product_ids)
    return RedirectResponse("/discoveries", status_code=303)


@app.post("/discoveries/delete")
async def delete_discoveries_action(
    product_ids: list[str] = Form(default=[]),
    state: StateManager = Depends(get_state),
):
    if product_ids:
        await state.delete_discoveries(product_ids)
    return RedirectResponse("/discoveries", status_code=303)


@app.post("/discoveries/approve-pokemon")
async def approve_pokemon_discoveries(state: StateManager = Depends(get_state)):
    from monitor.intelligence import is_pokemon_product
    discovered = await state.list_discovered(pending_only=True)
    pokemon_ids = [
        d["product_id"] for d in discovered
        if d.get("name") and is_pokemon_product(d["name"])
    ]
    if pokemon_ids:
        await state.bulk_approve_discoveries(pokemon_ids)
    return RedirectResponse("/discoveries", status_code=303)


# ---------------------------------------------------------------------------
# Logs page
# ---------------------------------------------------------------------------

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    product_id: str | None = None,
    shop: str = Query(default=""),
    state: StateManager = Depends(get_state),
):
    try:
        errors = await state.get_recent_errors(product_id, limit=200)
    except Exception:
        errors = []

    # Filter by shop if specified
    if shop:
        try:
            shop_products = await state.list_products(active_only=False)
            shop_pids = {p["product_id"] for p in shop_products if p.get("shop") == shop}
            errors = [e for e in errors if e.get("product_id") in shop_pids]
        except Exception:
            pass

    # Group consecutive identical errors
    grouped: list[dict] = []
    for e in errors:
        msg = e.get("error_message", "")
        if grouped and grouped[-1].get("error_message") == msg and grouped[-1].get("product_id") == e.get("product_id"):
            grouped[-1]["count"] = grouped[-1].get("count", 1) + 1
        else:
            grouped.append({**e, "count": 1})

    try:
        products = await state.list_products(active_only=False)
    except Exception:
        products = []
    try:
        webhook_errors = await state.get_webhook_errors(limit=50)
    except Exception:
        webhook_errors = []

    # Build product→shop lookup for badges
    product_shops = {p["product_id"]: p.get("shop", "bol") for p in products}

    return templates.TemplateResponse(request, "logs.html", {
        "active_page": "logs",
        "errors": grouped,
        "products": products,
        "product_shops": product_shops,
        "selected_product": product_id,
        "filter_shop": shop,
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
        keywords = []
    try:
        match_counts = await state.get_keyword_match_counts()
    except Exception:
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
                 "catchyourcards", "games_island", "dreamland", "amazon_uk"]
    selected_shops = shops if shops else all_shops
    await state.add_keyword(
        keyword=keyword, match_type=match_type, priority=priority,
        shops=selected_shops, auto_monitor=auto_monitor, notes=notes or None,
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
    queue_webhook: str = Form(default=""),
    mode: str = Form(default="webhook"),
    guild_id: str = Form(default=""),
    guild_name: str = Form(default=""),
    stock_channel_id: str = Form(default=""),
    admin_channel_id: str = Form(default=""),
    discovery_channel_id: str = Form(default=""),
    queue_channel_id: str = Form(default=""),
    send_stock_alerts: bool = Form(default=False),
    send_discovery_alerts: bool = Form(default=False),
    send_admin_alerts: bool = Form(default=False),
    send_queue_alerts: bool = Form(default=False),
    state: StateManager = Depends(get_state),
):
    server = await state.add_discord_server(
        name=name, description=description or None,
        public_webhook=public_webhook or None, admin_webhook=admin_webhook or None,
        discovery_webhook=discovery_webhook or None,
        send_stock_alerts=send_stock_alerts, send_discovery_alerts=send_discovery_alerts,
        send_admin_alerts=send_admin_alerts, send_queue_alerts=send_queue_alerts,
    )
    # Set extra fields that aren't in add_discord_server params
    updates = {}
    if queue_webhook:
        updates["queue_webhook"] = queue_webhook
    if mode == "bot":
        updates["mode"] = "bot"
    if guild_id:
        updates["guild_id"] = guild_id
    if guild_name:
        updates["guild_name"] = guild_name
    if stock_channel_id:
        updates["stock_channel_id"] = stock_channel_id
    if admin_channel_id:
        updates["admin_channel_id"] = admin_channel_id
    if discovery_channel_id:
        updates["discovery_channel_id"] = discovery_channel_id
    if queue_channel_id:
        updates["queue_channel_id"] = queue_channel_id
    if updates:
        await state.update_discord_server(server["id"], **updates)
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
# System
# ---------------------------------------------------------------------------

@app.get("/system", response_class=HTMLResponse)
async def system_page(request: Request, state: StateManager = Depends(get_state)):
    try:
        sys_health = await get_system_health(state)
    except Exception:
        sys_health = _EMPTY_HEALTH

    try:
        table_counts = await state.get_table_counts()
    except Exception:
        table_counts = {}

    import subprocess
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        git_hash = "unknown"

    uptime_seconds = int((datetime.now(timezone.utc) - _start_time).total_seconds())
    uptime_str = f"{uptime_seconds // 3600}h {(uptime_seconds % 3600) // 60}m"

    return templates.TemplateResponse(request, "system.html", {
        "active_page": "system",
        "sys_health": sys_health,
        "table_counts": table_counts,
        "git_hash": git_hash,
        "python_version": sys.version.split()[0],
        "uptime": uptime_str,
        "poll_interval_product": settings.poll_interval_product,
        "poll_interval_category": settings.poll_interval_category,
    })


@app.post("/system/clear-poll-logs")
async def clear_poll_logs(state: StateManager = Depends(get_state)):
    await state.clear_old_poll_logs(days=30)
    return RedirectResponse("/system", status_code=303)


@app.post("/system/clear-discoveries")
async def clear_discoveries(state: StateManager = Depends(get_state)):
    await state.clear_all_discoveries()
    return RedirectResponse("/system", status_code=303)
