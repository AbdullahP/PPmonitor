-- Message queue for bot-direct posting (monitor writes, bot reads)
CREATE TABLE IF NOT EXISTS discord_queue (
  id SERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  server_id INTEGER REFERENCES discord_servers(id) ON DELETE CASCADE,
  channel_id VARCHAR(50) NOT NULL,
  content TEXT,
  embed_json JSONB NOT NULL,
  sent BOOLEAN DEFAULT FALSE,
  sent_at TIMESTAMPTZ,
  error TEXT
);

CREATE INDEX IF NOT EXISTS idx_discord_queue_pending
  ON discord_queue (sent, created_at) WHERE sent = FALSE;
