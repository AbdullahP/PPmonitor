CREATE TABLE IF NOT EXISTS discord_servers (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  description TEXT,

  -- Webhook URLs
  public_webhook VARCHAR(500),
  admin_webhook VARCHAR(500),
  discovery_webhook VARCHAR(500),

  -- Bot config
  bot_token VARCHAR(200),
  channel_id VARCHAR(50),

  -- Settings
  is_active BOOLEAN DEFAULT TRUE,
  is_default BOOLEAN DEFAULT FALSE,

  -- Alert toggles per server
  send_stock_alerts BOOLEAN DEFAULT TRUE,
  send_discovery_alerts BOOLEAN DEFAULT TRUE,
  send_admin_alerts BOOLEAN DEFAULT TRUE,
  send_queue_alerts BOOLEAN DEFAULT TRUE,

  -- Metadata
  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_tested_at TIMESTAMPTZ,
  last_test_result VARCHAR(20) DEFAULT 'untested',
  last_test_error TEXT
);
