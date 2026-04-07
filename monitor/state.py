"""PostgreSQL state management for the stock monitor."""

import asyncio
import json
import logging
from pathlib import Path

import asyncpg

from config import settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


class StateManager:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @classmethod
    async def create(cls, database_url: str | None = None) -> "StateManager":
        url = database_url or settings.database_url
        pool = await cls._connect_with_retry(url)
        mgr = cls(pool)
        await mgr._run_migrations()
        await mgr.seed_discord_servers_from_env()
        return mgr

    @staticmethod
    async def _connect_with_retry(
        url: str,
        max_attempts: int = 10,
        base_delay: float = 2.0,
    ) -> asyncpg.Pool:
        for attempt in range(1, max_attempts + 1):
            try:
                pool = await asyncpg.create_pool(url, min_size=2, max_size=10)
                logger.info("Connected to database (attempt %d)", attempt)
                return pool
            except (OSError, asyncpg.PostgresError) as exc:
                if attempt == max_attempts:
                    raise
                delay = base_delay * attempt
                logger.warning(
                    "Database connection failed (attempt %d/%d): %s — retrying in %.0fs",
                    attempt, max_attempts, exc, delay,
                )
                await asyncio.sleep(delay)

    async def close(self):
        await self._pool.close()

    # ----- Migration runner -----

    async def _run_migrations(self) -> None:
        """Run all .sql files in migrations/ that haven't been applied yet."""
        async with self._pool.acquire() as conn:
            # Ensure _migrations table exists (bootstrap)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ DEFAULT now()
                )
            """)
            applied = {
                r["filename"]
                for r in await conn.fetch("SELECT filename FROM _migrations")
            }

            sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
            for f in sql_files:
                if f.name not in applied:
                    logger.info("Applying migration: %s", f.name)
                    sql = f.read_text(encoding="utf-8")
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO _migrations (filename) VALUES ($1) ON CONFLICT DO NOTHING",
                        f.name,
                    )

    # ----- Products CRUD -----

    async def add_product(
        self, product_id: str, url: str, name: str | None = None, shop: str = "bol"
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO products (product_id, url, name, shop)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (product_id) DO UPDATE SET is_active = true, url = $2, shop = $4
                   RETURNING *""",
                product_id, url, name, shop,
            )
            return dict(row)

    async def remove_product(self, product_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE products SET is_active = false WHERE product_id = $1",
                product_id,
            )
            return result == "UPDATE 1"

    async def list_products(self, active_only: bool = True) -> list[dict]:
        async with self._pool.acquire() as conn:
            if active_only:
                rows = await conn.fetch(
                    "SELECT * FROM products WHERE is_active = true ORDER BY added_at DESC"
                )
            else:
                rows = await conn.fetch("SELECT * FROM products ORDER BY added_at DESC")
            return [dict(r) for r in rows]

    async def get_product(self, product_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM products WHERE product_id = $1", product_id
            )
            return dict(row) if row else None

    async def update_product(self, product_id: str, **kwargs) -> None:
        if not kwargs:
            return
        sets = []
        values = []
        for i, (key, val) in enumerate(kwargs.items(), start=1):
            sets.append(f"{key} = ${i}")
            values.append(val)
        values.append(product_id)
        query = f"UPDATE products SET {', '.join(sets)} WHERE product_id = ${len(values)}"
        async with self._pool.acquire() as conn:
            await conn.execute(query, *values)

    # ----- Poll log -----

    async def log_poll(
        self,
        product_id: str,
        success: bool,
        latency_ms: int | None = None,
        error_message: str | None = None,
        availability: str | None = None,
        revision_id: str | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO poll_log
                   (product_id, success, latency_ms, error_message, availability, revision_id)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                product_id, success, latency_ms, error_message, availability, revision_id,
            )

    async def get_poll_history(self, product_id: str, limit: int = 100) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM poll_log
                   WHERE product_id = $1
                   ORDER BY timestamp DESC LIMIT $2""",
                product_id, limit,
            )
            return [dict(r) for r in rows]

    async def get_recent_errors(self, product_id: str | None = None, limit: int = 20) -> list[dict]:
        async with self._pool.acquire() as conn:
            if product_id:
                rows = await conn.fetch(
                    """SELECT * FROM poll_log
                       WHERE product_id = $1 AND success = false
                       ORDER BY timestamp DESC LIMIT $2""",
                    product_id, limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT * FROM poll_log
                       WHERE success = false
                       ORDER BY timestamp DESC LIMIT $1""",
                    limit,
                )
            return [dict(r) for r in rows]

    # ----- Alerts sent -----

    async def log_alert(self, product_id: str | None, alert_type: str, message: str) -> int | None:
        """Insert alert and return its ID for delivery tracking."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO alerts_sent (product_id, alert_type, message)
                   VALUES ($1, $2, $3)
                   RETURNING id""",
                product_id, alert_type, message,
            )
            return row["id"] if row else None

    async def update_alert_delivery(
        self, alert_id: int, sent: bool,
        status_code: int | None = None, error: str | None = None,
    ) -> None:
        """Update Discord delivery status on an alert row."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE alerts_sent
                   SET discord_sent = $1, discord_status_code = $2, discord_error = $3
                   WHERE id = $4""",
                sent, status_code, error, alert_id,
            )

    async def get_alerts(self, limit: int = 50) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM alerts_sent ORDER BY timestamp DESC LIMIT $1", limit
            )
            return [dict(r) for r in rows]

    async def get_alerts_today_count(self) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM alerts_sent WHERE timestamp >= CURRENT_DATE"
            )
            return row["cnt"]

    async def get_discord_status(self) -> dict:
        """Get last delivery status per webhook type."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT ON (webhook_type)
                    webhook_type, success, status_code, error_message, timestamp
                FROM webhook_log
                ORDER BY webhook_type, timestamp DESC
            """)
            return {r["webhook_type"]: dict(r) for r in rows}

    # ----- Webhook log -----

    async def log_webhook(
        self, webhook_type: str, status_code: int, success: bool = False,
        error_message: str | None = None, payload_snippet: str | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO webhook_log
                   (webhook_type, status_code, success, error_message, payload_snippet)
                   VALUES ($1, $2, $3, $4, $5)""",
                webhook_type, status_code, success, error_message, payload_snippet,
            )

    async def get_webhook_errors(self, limit: int = 50) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM webhook_log
                   WHERE success = false
                   ORDER BY timestamp DESC LIMIT $1""",
                limit,
            )
            return [dict(r) for r in rows]

    # ----- Discord message queue -----

    async def enqueue_discord_message(
        self, server_id: int, channel_id: str,
        embed_json: dict, content: str | None = None,
    ) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO discord_queue (server_id, channel_id, content, embed_json)
                   VALUES ($1, $2, $3, $4::jsonb) RETURNING id""",
                server_id, channel_id, content, json.dumps(embed_json),
            )
            return row["id"]

    async def get_pending_messages(self, limit: int = 50) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM discord_queue
                   WHERE sent = FALSE
                   ORDER BY created_at LIMIT $1""",
                limit,
            )
            return [dict(r) for r in rows]

    async def mark_message_sent(self, message_id: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE discord_queue SET sent = TRUE, sent_at = NOW() WHERE id = $1",
                message_id,
            )

    async def mark_message_failed(self, message_id: int, error: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE discord_queue SET error = $1 WHERE id = $2",
                error[:500], message_id,
            )

    # ----- Discovered products -----

    async def add_discovered(
        self, product_id: str, url: str, name: str | None = None,
        source: str = "category", shop: str = "bol",
    ) -> bool:
        """Returns True if this is a new discovery."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """INSERT INTO discovered_products (product_id, url, name, source, shop)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (product_id) DO NOTHING""",
                product_id, url, name, source, shop,
            )
            return result == "INSERT 0 1"

    async def list_discovered(self, pending_only: bool = True) -> list[dict]:
        async with self._pool.acquire() as conn:
            if pending_only:
                rows = await conn.fetch(
                    """SELECT * FROM discovered_products
                       WHERE promoted_at IS NULL
                       ORDER BY discovered_at DESC"""
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM discovered_products ORDER BY discovered_at DESC"
                )
            return [dict(r) for r in rows]

    async def promote_discovered(self, product_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE discovered_products SET promoted_at = now() WHERE product_id = $1",
                product_id,
            )

    async def get_known_product_ids(self) -> set[str]:
        """All product IDs we know about (monitored + discovered)."""
        async with self._pool.acquire() as conn:
            monitored = await conn.fetch("SELECT product_id FROM products")
            discovered = await conn.fetch("SELECT product_id FROM discovered_products")
            ids = {r["product_id"] for r in monitored}
            ids.update(r["product_id"] for r in discovered)
            return ids

    # ----- Keywords -----

    async def list_keywords(self, active_only: bool = True) -> list[dict]:
        async with self._pool.acquire() as conn:
            if active_only:
                rows = await conn.fetch(
                    "SELECT * FROM keywords WHERE is_active = TRUE ORDER BY created_at DESC"
                )
            else:
                rows = await conn.fetch("SELECT * FROM keywords ORDER BY created_at DESC")
            result = []
            for r in rows:
                d = dict(r)
                # Parse JSONB shops field if it's a string
                if isinstance(d.get("shops"), str):
                    d["shops"] = json.loads(d["shops"])
                result.append(d)
            return result

    async def add_keyword(
        self, keyword: str, match_type: str = "contains",
        priority: str = "normal", shops: list[str] | None = None,
        auto_monitor: bool = True, notify_discord: bool = True,
        notes: str | None = None,
    ) -> dict:
        if shops is None:
            shops = ["bol", "mediamarkt", "pocketgames",
                     "catchyourcards", "games_island", "dreamland", "amazon_uk"]
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO keywords
                   (keyword, match_type, priority, shops, auto_monitor, notify_discord, notes)
                   VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
                   RETURNING *""",
                keyword, match_type, priority, json.dumps(shops),
                auto_monitor, notify_discord, notes,
            )
            return dict(row)

    async def delete_keyword(self, keyword_id: int) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM keywords WHERE id = $1", keyword_id
            )
            return result == "DELETE 1"

    async def toggle_keyword(self, keyword_id: int) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE keywords SET is_active = NOT is_active WHERE id = $1",
                keyword_id,
            )
            return result == "UPDATE 1"

    async def get_keyword_match_counts(self) -> dict[int, int]:
        """Count how many monitored products match each keyword (by name contains)."""
        async with self._pool.acquire() as conn:
            keywords = await conn.fetch(
                "SELECT id, keyword, match_type FROM keywords"
            )
            products = await conn.fetch(
                "SELECT name FROM products WHERE is_active = true AND name IS NOT NULL"
            )
            counts: dict[int, int] = {}
            product_names = [(r["name"] or "").lower() for r in products]
            for kw in keywords:
                kw_id = kw["id"]
                kw_text = (kw["keyword"] or "").lower()
                match_type = kw["match_type"] or "contains"
                count = 0
                for pname in product_names:
                    if match_type == "contains" and kw_text in pname:
                        count += 1
                    elif match_type == "exact" and kw_text == pname:
                        count += 1
                    elif match_type == "regex":
                        import re
                        try:
                            if re.search(kw_text, pname, re.IGNORECASE):
                                count += 1
                        except re.error:
                            pass
                counts[kw_id] = count
            return counts

    # ----- Shop modules -----

    async def list_shop_modules(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM shop_modules ORDER BY sort_order, shop_id"
            )
            return [dict(r) for r in rows]

    async def get_shop_module(self, shop_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM shop_modules WHERE shop_id = $1", shop_id
            )
            return dict(row) if row else None

    async def update_shop_module(self, shop_id: str, **kwargs) -> None:
        if not kwargs:
            return
        sets = []
        values = []
        for i, (key, val) in enumerate(kwargs.items(), start=1):
            sets.append(f"{key} = ${i}")
            values.append(val)
        values.append(shop_id)
        query = f"UPDATE shop_modules SET {', '.join(sets)} WHERE shop_id = ${len(values)}"
        async with self._pool.acquire() as conn:
            await conn.execute(query, *values)

    async def toggle_shop_module_field(self, shop_id: str, field: str) -> bool:
        """Toggle a boolean field on a shop module. Returns new value."""
        allowed = {"is_active", "monitoring_enabled", "discovery_enabled", "keywords_enabled"}
        if field not in allowed:
            raise ValueError(f"Cannot toggle field: {field}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE shop_modules SET {field} = NOT {field} WHERE shop_id = $1 RETURNING {field}",
                shop_id,
            )
            return row[field] if row else False

    async def get_in_stock_count(self) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM products WHERE is_active = true AND last_availability = 'InStock'"
            )
            return row["cnt"]

    async def get_table_counts(self) -> dict[str, int]:
        async with self._pool.acquire() as conn:
            tables = ["products", "poll_log", "alerts_sent", "discovered_products",
                       "keywords", "discord_servers", "shop_modules", "webhook_log"]
            counts = {}
            for t in tables:
                try:
                    row = await conn.fetchrow(f"SELECT COUNT(*) as cnt FROM {t}")
                    counts[t] = row["cnt"]
                except Exception:
                    counts[t] = 0
            return counts

    async def clear_old_poll_logs(self, days: int = 30) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM poll_log WHERE timestamp < NOW() - INTERVAL '{days} days'"
            )
            return int(result.split()[-1]) if result else 0

    async def clear_all_discoveries(self) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM discovered_products")
            return int(result.split()[-1]) if result else 0

    async def list_discovered_filtered(
        self, shop: str | None = None, source: str | None = None,
        pending_only: bool = True, limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            conditions = []
            params = []
            idx = 1
            if pending_only:
                conditions.append("promoted_at IS NULL")
            if shop:
                conditions.append(f"shop = ${idx}")
                params.append(shop)
                idx += 1
            if source:
                conditions.append(f"source LIKE ${idx}")
                params.append(f"%{source}%")
                idx += 1
            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            params.extend([limit, offset])
            rows = await conn.fetch(
                f"SELECT * FROM discovered_products {where} ORDER BY discovered_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
                *params,
            )
            return [dict(r) for r in rows]

    async def bulk_approve_discoveries(self, product_ids: list[str]) -> int:
        """Move discovered products to active monitoring."""
        count = 0
        for pid in product_ids:
            async with self._pool.acquire() as conn:
                disc = await conn.fetchrow(
                    "SELECT * FROM discovered_products WHERE product_id = $1", pid
                )
                if disc:
                    await self.add_product(
                        pid, disc["url"], name=disc.get("name"),
                        shop=disc.get("shop", "bol"),
                    )
                    await self.promote_discovered(pid)
                    count += 1
        return count

    async def delete_discoveries(self, product_ids: list[str]) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM discovered_products WHERE product_id = ANY($1)",
                product_ids,
            )
            return int(result.split()[-1]) if result else 0

    # ----- Discord servers -----

    async def list_discord_servers(self, active_only: bool = False) -> list[dict]:
        async with self._pool.acquire() as conn:
            if active_only:
                rows = await conn.fetch(
                    "SELECT * FROM discord_servers WHERE is_active = TRUE ORDER BY created_at"
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM discord_servers ORDER BY created_at"
                )
            return [dict(r) for r in rows]

    async def get_discord_server(self, server_id: int) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM discord_servers WHERE id = $1", server_id
            )
            return dict(row) if row else None

    async def add_discord_server(
        self, name: str, description: str | None = None,
        public_webhook: str | None = None, admin_webhook: str | None = None,
        discovery_webhook: str | None = None, bot_token: str | None = None,
        channel_id: str | None = None, is_default: bool = False,
        send_stock_alerts: bool = True, send_discovery_alerts: bool = True,
        send_admin_alerts: bool = True, send_queue_alerts: bool = True,
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO discord_servers
                   (name, description, public_webhook, admin_webhook,
                    discovery_webhook, bot_token, channel_id, is_default,
                    send_stock_alerts, send_discovery_alerts,
                    send_admin_alerts, send_queue_alerts)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                   RETURNING *""",
                name, description, public_webhook, admin_webhook,
                discovery_webhook, bot_token, channel_id, is_default,
                send_stock_alerts, send_discovery_alerts,
                send_admin_alerts, send_queue_alerts,
            )
            return dict(row)

    async def update_discord_server(self, server_id: int, **kwargs) -> None:
        if not kwargs:
            return
        sets = []
        values = []
        for i, (key, val) in enumerate(kwargs.items(), start=1):
            sets.append(f"{key} = ${i}")
            values.append(val)
        values.append(server_id)
        query = f"UPDATE discord_servers SET {', '.join(sets)} WHERE id = ${len(values)}"
        async with self._pool.acquire() as conn:
            await conn.execute(query, *values)

    async def delete_discord_server(self, server_id: int) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM discord_servers WHERE id = $1", server_id
            )
            return result == "DELETE 1"

    async def toggle_discord_server(self, server_id: int) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE discord_servers SET is_active = NOT is_active WHERE id = $1",
                server_id,
            )
            return result == "UPDATE 1"

    async def seed_discord_servers_from_env(self) -> None:
        """Seed the discord_servers table from env vars if empty."""
        from config import settings as s
        async with self._pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM discord_servers")
            if count == 0 and (s.discord_webhook_url or s.discord_admin_webhook or s.discord_discovery_webhook):
                row = await conn.fetchrow(
                    """INSERT INTO discord_servers
                       (name, description, public_webhook, admin_webhook,
                        discovery_webhook, bot_token, channel_id,
                        is_active, is_default)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,true,true)
                       RETURNING id""",
                    "Default",
                    "Migrated from environment variables",
                    s.discord_webhook_url or None,
                    s.discord_admin_webhook or None,
                    s.discord_discovery_webhook or None,
                    s.discord_bot_token or None,
                    s.discord_channel_id or None,
                )
                # Set queue webhook if configured
                if row and getattr(s, "discord_queue_webhook", ""):
                    await conn.execute(
                        "UPDATE discord_servers SET queue_webhook = $1 WHERE id = $2",
                        s.discord_queue_webhook, row["id"],
                    )
                logger.info("Seeded Discord server from env vars")

    # ----- Shop cookies -----

    async def get_shop_cookies(self, shop_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM shop_cookies WHERE shop_id = $1 ORDER BY cookie_name",
                shop_id,
            )
            return [dict(r) for r in rows]

    async def save_shop_cookies(self, shop_id: str, cookies: list[dict]) -> int:
        """Upsert cookies for a shop. Returns count saved."""
        count = 0
        async with self._pool.acquire() as conn:
            for c in cookies:
                name = c.get("name", "").strip()
                value = c.get("value", "")
                if not name:
                    continue
                domain = c.get("domain", ".bol.com")
                expires_at = None
                if c.get("expires") or c.get("expirationDate"):
                    import datetime as _dt
                    ts = c.get("expires") or c.get("expirationDate")
                    try:
                        expires_at = _dt.datetime.fromtimestamp(float(ts), tz=_dt.timezone.utc)
                    except (ValueError, TypeError, OSError):
                        pass
                await conn.execute(
                    """INSERT INTO shop_cookies (shop_id, cookie_name, cookie_value, domain, expires_at, updated_at)
                       VALUES ($1, $2, $3, $4, $5, NOW())
                       ON CONFLICT (shop_id, cookie_name)
                       DO UPDATE SET cookie_value = $3, domain = $4, expires_at = $5, updated_at = NOW()""",
                    shop_id, name, value, domain, expires_at,
                )
                count += 1
        return count

    async def delete_shop_cookies(self, shop_id: str) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM shop_cookies WHERE shop_id = $1", shop_id
            )
            return int(result.split()[-1]) if result else 0

    async def get_cookie_health(self, shop_id: str) -> dict:
        """Return cookie freshness info for a shop."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT COUNT(*) as count,
                          MIN(updated_at) as oldest_update,
                          MAX(updated_at) as newest_update
                   FROM shop_cookies WHERE shop_id = $1""",
                shop_id,
            )
            if not row or row["count"] == 0:
                return {"status": "missing", "count": 0, "age_hours": None}
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            age = now - row["newest_update"]
            age_hours = age.total_seconds() / 3600
            if age_hours < 24:
                status = "fresh"
            elif age_hours < 72:
                status = "stale"
            else:
                status = "expired"
            return {
                "status": status,
                "count": row["count"],
                "age_hours": round(age_hours, 1),
                "updated_at": row["newest_update"],
            }

    # ----- System heartbeat -----

    async def write_heartbeat(self, products_polled_count: int, shop_status: dict | None = None) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO system_heartbeat (monitor_alive, products_polled_count, shop_status)
                   VALUES (true, $1, $2)""",
                products_polled_count, json.dumps(shop_status or {}),
            )

    async def get_last_heartbeat(self) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM system_heartbeat ORDER BY timestamp DESC LIMIT 1"
            )
            return dict(row) if row else None
