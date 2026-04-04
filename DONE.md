# Pokemon TCG Stock Monitor — Build Complete

## What was built

| Service | File | Description |
|---------|------|-------------|
| **Monitor** | `monitor/poller.py` | Polls product pages every 10s, category pages every 60s, detects stock changes |
| **Scraper** | `monitor/scraper.py` | Parses JSON-LD (primary) + revisionId/offerUid from reactRouterContext (secondary) |
| **Health** | `monitor/health.py` | Poll logging, heartbeat every 30s, unhealthy detection (>45s no success) |
| **Alerts** | `monitor/alerts.py` | 3 Discord webhooks: stock drops, errors (after 3 failures), new discoveries |
| **Discovery** | `monitor/discovery.py` | Category page polling, diffs product IDs, inserts to discovered_products |
| **State** | `monitor/state.py` | asyncpg PostgreSQL layer, auto-runs SQL migrations on startup |
| **Discord Bot** | `bot/bot.py` | `/monitor add`, `/monitor list`, `/monitor remove`, `/monitor test` |
| **Redirect** | `redirect/app.py` | `/go?sku=X&offer=Y` → auto-submit form POST to bol.com basket |
| **Dashboard** | `dashboard/app.py` | FastAPI + Jinja2 + HTMX + Pico CSS, live-refresh, HTTP Basic auth |
| **Mock Server** | `mock_server/server.py` | Fake bol.com for dev/testing with admin stock toggle |

## How to run locally

```bash
# 1. Install Docker Desktop for Windows
# 2. Clone repo and configure
cp .env.example .env
# Edit .env — fill in Discord credentials

# 3. Start everything
make dev

# Services available:
#   http://localhost:3000  — Dashboard (admin/changeme)
#   http://localhost:8080  — Redirect service
#   http://localhost:8099  — Mock server admin

# 4. Test a stock flip
make mock-stock    # → triggers alert in monitor logs
make mock-oos      # → resets to out of stock
```

## Environment variables that need real values

| Variable | Where to get it |
|----------|----------------|
| `DISCORD_BOT_TOKEN` | Discord Developer Portal → Bot → Token |
| `DISCORD_WEBHOOK_URL` | Discord channel → Settings → Integrations → Webhooks |
| `DISCORD_ADMIN_WEBHOOK` | Same, for admin/error channel |
| `DISCORD_DISCOVERY_WEBHOOK` | Same, for new-products channel |
| `DISCORD_CHANNEL_ID` | Right-click channel in Discord → Copy Channel ID |
| `DASHBOARD_PASS` | Choose a strong password (default: `changeme`) |

## How to deploy to Railway

1. Create GitHub repo, push code
2. Go to [railway.app](https://railway.app), create new project
3. Add **PostgreSQL** plugin — copy the `DATABASE_URL`
4. Add 4 services from the repo:
   - **monitor** — Dockerfile: `Dockerfile.monitor`
   - **bot** — Dockerfile: `Dockerfile.bot`
   - **redirect** — Dockerfile: `Dockerfile.redirect`, expose port 8080
   - **dashboard** — Dockerfile: `Dockerfile.dashboard`, expose port 3000
5. Set environment variables on each service:
   - `DATABASE_URL` (from Railway PostgreSQL)
   - `DISCORD_ENABLED=true`
   - `BOL_BASE_URL=https://www.bol.com`
   - All `DISCORD_*` tokens/webhooks
   - `DASHBOARD_USER` + `DASHBOARD_PASS`
   - `REDIRECT_BASE_URL=https://your-redirect.up.railway.app`
6. Get the deploy webhook URL from Railway project settings
7. Add `DEPLOY_WEBHOOK_URL` as a GitHub Actions secret
8. Push to `main` → CI runs → auto-deploys

## Known limitations / next steps

- **DB tests require PostgreSQL**: `test_health.py`, `test_discovery.py`, `test_dashboard.py` need a running PG instance (handled by Docker or CI)
- **No proxy rotation**: Single-IP polling is fine for <20 products at 10s intervals
- **No WebSocket live updates**: Dashboard uses HTMX polling (every 10s), not WebSocket push
- **Category discovery is URL-only**: Doesn't scrape product names during discovery (would need an extra fetch per new product)
- **No price history tracking**: Could add a price_log table to track price changes over time
- **No rate limit handling**: If bol.com starts returning 429s, could add exponential backoff
