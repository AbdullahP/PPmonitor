-- 001_initial.sql — Pokemon TCG Stock Monitor schema
-- Runs automatically on service startup via state.py

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    product_id TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    name TEXT,
    price TEXT,
    offer_uid TEXT,
    is_active BOOLEAN DEFAULT true,
    last_polled_at TIMESTAMPTZ,
    last_availability TEXT,
    last_revision_id TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    added_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS poll_log (
    id SERIAL PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ DEFAULT now(),
    success BOOLEAN NOT NULL,
    latency_ms INTEGER,
    error_message TEXT,
    availability TEXT,
    revision_id TEXT
);

CREATE TABLE IF NOT EXISTS alerts_sent (
    id SERIAL PRIMARY KEY,
    product_id TEXT,
    timestamp TIMESTAMPTZ DEFAULT now(),
    alert_type TEXT NOT NULL,
    message TEXT
);

CREATE TABLE IF NOT EXISTS discovered_products (
    id SERIAL PRIMARY KEY,
    product_id TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    name TEXT,
    discovered_at TIMESTAMPTZ DEFAULT now(),
    source TEXT NOT NULL,
    promoted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS system_heartbeat (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT now(),
    monitor_alive BOOLEAN DEFAULT true,
    products_polled_count INTEGER
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_poll_log_product_ts
    ON poll_log (product_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_alerts_sent_ts
    ON alerts_sent (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_heartbeat_ts
    ON system_heartbeat (timestamp DESC);

-- Track which migrations have run
CREATE TABLE IF NOT EXISTS _migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT now()
);
