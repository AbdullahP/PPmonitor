-- 012_bol_cookies.sql — DB-stored cookies + seller/release tracking

-- Shop cookies table (replaces bol_cookies.json for Railway)
CREATE TABLE IF NOT EXISTS shop_cookies (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(50) NOT NULL,
    cookie_name VARCHAR(100) NOT NULL,
    cookie_value TEXT NOT NULL,
    domain VARCHAR(100) DEFAULT '.bol.com',
    expires_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(shop_id, cookie_name)
);

CREATE INDEX IF NOT EXISTS idx_shop_cookies_shop
    ON shop_cookies (shop_id);

-- Seller column on products
ALTER TABLE products ADD COLUMN IF NOT EXISTS seller VARCHAR(100);

-- Release date + poll priority for release-day escalation
ALTER TABLE products ADD COLUMN IF NOT EXISTS release_date DATE;
ALTER TABLE products ADD COLUMN IF NOT EXISTS poll_priority VARCHAR(20) DEFAULT 'normal';

-- Seed Perfect Order products (discovered 2026-04-07)
INSERT INTO products (product_id, url, name, shop, seller, release_date, poll_priority)
VALUES
    ('9300000271683065',
     'https://www.bol.com/nl/nl/p/-/9300000271683065/',
     'Pokemon TCG Perfect Order Booster Pack',
     'bol', NULL, '2026-04-25', 'normal'),
    ('9300000272060999',
     'https://www.bol.com/nl/nl/p/-/9300000272060999/',
     'Pokemon TCG Perfect Order Build & Battle Box',
     'bol', NULL, '2026-04-25', 'normal')
ON CONFLICT (product_id) DO UPDATE SET
    release_date = EXCLUDED.release_date,
    poll_priority = EXCLUDED.poll_priority;
