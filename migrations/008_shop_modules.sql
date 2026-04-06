-- Shop module configuration
CREATE TABLE IF NOT EXISTS shop_modules (
  id SERIAL PRIMARY KEY,
  shop_id VARCHAR(50) UNIQUE NOT NULL,
  display_name VARCHAR(100) NOT NULL,

  -- Sub-module toggles
  monitoring_enabled BOOLEAN DEFAULT FALSE,
  discovery_enabled BOOLEAN DEFAULT FALSE,
  keywords_enabled BOOLEAN DEFAULT FALSE,

  -- Certification
  is_certified BOOLEAN DEFAULT FALSE,
  certified_at TIMESTAMPTZ,
  last_test_at TIMESTAMPTZ,
  last_test_result VARCHAR(20),
  last_test_error TEXT,
  last_test_name TEXT,
  last_test_price TEXT,
  last_test_avail TEXT,

  -- Stats (updated by poller)
  success_rate_pct INTEGER DEFAULT 0,
  avg_latency_ms INTEGER DEFAULT 0,
  last_poll_at TIMESTAMPTZ,
  last_error_at TIMESTAMPTZ,
  last_error_msg TEXT,

  -- Config
  poll_interval_override INTEGER,
  is_active BOOLEAN DEFAULT FALSE,
  sort_order INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed all 7 shops
INSERT INTO shop_modules
  (shop_id, display_name, sort_order, is_active,
   monitoring_enabled, discovery_enabled, keywords_enabled)
VALUES
  ('bol',            'bol.com',        1, true,  true,  true,  true),
  ('mediamarkt',     'MediaMarkt',     2, false, false, false, false),
  ('pocketgames',    'PocketGames',    3, false, false, false, false),
  ('catchyourcards', 'CatchYourCards', 4, false, false, false, false),
  ('games_island',   'Games Island',   5, false, false, false, false),
  ('dreamland',      'Dreamland',      6, false, false, false, false),
  ('amazon_uk',      'Amazon UK',      7, false, false, false, false)
ON CONFLICT (shop_id) DO NOTHING;
