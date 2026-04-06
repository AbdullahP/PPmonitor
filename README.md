# Pokemon TCG Stock Monitor & Checkout Accelerator

Monitors bol.com for Pokemon TCG stock drops and gives Discord community members the fastest path to checkout.

## Architecture

| Service | Port | Description |
|---------|------|-------------|
| **Monitor** | — | Polls bol.com product pages every 10s, category pages every 60s |
| **Discord Bot** | — | Slash commands: `/monitor add`, `/monitor list`, `/monitor remove` |
| **Redirect** | 8080 | `/go?sku=X&offer=Y` → auto-submit form to bol.com basket |
| **Dashboard** | 3000 | Admin UI with live product status, logs, alerts (HTMX + Pico CSS) |
| **Mock Server** | 8099 | Fake bol.com for local development and testing |
| **PostgreSQL** | 5432 | Persistent state: products, poll logs, alerts, discoveries |

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env — fill in DISCORD_BOT_TOKEN and webhook URLs

# 2. Start everything (dev mode: mock server, Discord disabled)
make dev

# 3. Test a stock flip
make mock-stock   # Toggle product to in-stock
make mock-oos     # Toggle back to out-of-stock

# 4. Open dashboard
open http://localhost:3000   # admin / changeme
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `DISCORD_BOT_TOKEN` | For bot | Discord bot token |
| `DISCORD_WEBHOOK_URL` | For alerts | Public stock alerts webhook |
| `DISCORD_ADMIN_WEBHOOK` | Optional | Error alerts (admin channel) |
| `DISCORD_DISCOVERY_WEBHOOK` | Optional | New product discovery alerts |
| `DISCORD_ENABLED` | No | Set `false` to suppress all webhooks (default: `true`) |
| `DASHBOARD_USER` | No | Dashboard login (default: `admin`) |
| `DASHBOARD_PASS` | No | Dashboard password (default: `changeme`) |

## Development

```bash
make dev      # Start all services with live reload
make test     # Run pytest suite
make lint     # Run ruff linter
make logs     # Follow all service logs
make shell    # Shell into monitor container
make down     # Stop everything
```

## Deploy to Railway

1. Push repo to GitHub
2. Create a new Railway project
3. Add a PostgreSQL service
4. Add services for: monitor, bot, redirect, dashboard
5. Set environment variables (copy from `.env.example`)
6. Set `DISCORD_ENABLED=true`
7. Add `DEPLOY_WEBHOOK_URL` as a GitHub Actions secret
8. Push to `main` — CI runs, then auto-deploys
