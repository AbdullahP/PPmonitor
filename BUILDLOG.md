# Build Log

Phase 1: Scaffolding — config.py, requirements.txt, Makefile, CI/CD, .env.example, .gitignore, README.md
Phase 2: Mock server — fake bol.com with JSON-LD + reactRouterContext, admin controls, /health
Phase 3: PostgreSQL schema — migrations/001_initial.sql with 5 tables + indexes + _migrations tracker
Phase 4: State manager — asyncpg CRUD for all tables, auto-migration on startup
Phase 5: Scraper — JSON-LD primary, revisionId/offerUid secondary regex, category page parser
Phase 6: Health — poll_log writes, heartbeat every 30s, healthy/slow/dead status calc
Phase 7: Alerts — 3 webhooks (public/admin/discovery), DISCORD_ENABLED flag, alert logging
Phase 8: Poller — asyncio dual-loop (10s products, 60s categories), heartbeat writes
Phase 9: Discovery — category page differ, new IDs → discovered_products → Discord
Phase 10: Redirect — FastAPI auto-submit form POST to bol.com basket
Phase 11: Dashboard — FastAPI + Jinja2 + HTMX + Pico CSS, HTTP Basic auth, 5 pages
Phase 12: Discord bot — /monitor add|list|remove|test slash commands
Phase 13: Docker — 5 Dockerfiles, docker-compose.yml (prod), docker-compose.override.yml (dev)
Phase 14: Tests — 15 tests passing (mock server, scraper, redirect), ruff clean
Phase 15: Shop adapters — 6 adapters (bol, mediamarkt, pocketgames, catchyourcards, games_island, dreamland) with base class, Shopify fast path, registry
Phase 16: Adapter wiring — poller + discovery use adapter registry, shop column in DB, auto-detect shop from URL
Phase 17: Rate limiter — adaptive per-shop rate limiting with backoff (429/503), pause (403), and recovery
Phase 18: Intelligence — upcoming sets scanner, auto-discovers products 14 days before release
Phase 19: Predictor — restock drop prediction from poll history transitions, confidence scoring
Phase 20: Dashboard redesign — Tailwind dark theme, sidebar nav, shop pills, rate limiter + upcoming sets sections
Phase 21: Redirect — multi-shop redirect service (bol form POST, mediamarkt fetch API, Shopify/WooCommerce, fallback redirects)
Phase 22: Alerts — shop-aware Discord embeds with per-shop emoji, shop param in redirect URLs
Phase 23: Search URLs — get_search_url() per adapter, intelligence engine uses search + category URLs
Phase 24: Health — per-shop rate limiter status persisted in heartbeat JSONB, dashboard prefers heartbeat data
Phase 25: Tests — 42 tests: rate limiter, all 6 adapters, redirect per shop, intelligence module
