"""PostgreSQL state management for the stock monitor."""

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
        pool = await asyncpg.create_pool(url, min_size=2, max_size=10)
        mgr = cls(pool)
        await mgr._run_migrations()
        return mgr

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

    async def add_product(self, product_id: str, url: str, name: str | None = None) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO products (product_id, url, name)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (product_id) DO UPDATE SET is_active = true, url = $2
                   RETURNING *""",
                product_id, url, name,
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

    async def log_alert(self, product_id: str | None, alert_type: str, message: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO alerts_sent (product_id, alert_type, message)
                   VALUES ($1, $2, $3)""",
                product_id, alert_type, message,
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

    # ----- Discovered products -----

    async def add_discovered(
        self, product_id: str, url: str, name: str | None = None, source: str = "category"
    ) -> bool:
        """Returns True if this is a new discovery."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """INSERT INTO discovered_products (product_id, url, name, source)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (product_id) DO NOTHING""",
                product_id, url, name, source,
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

    # ----- System heartbeat -----

    async def write_heartbeat(self, products_polled_count: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO system_heartbeat (monitor_alive, products_polled_count)
                   VALUES (true, $1)""",
                products_polled_count,
            )

    async def get_last_heartbeat(self) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM system_heartbeat ORDER BY timestamp DESC LIMIT 1"
            )
            return dict(row) if row else None
