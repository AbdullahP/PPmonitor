-- Track Discord webhook delivery status on alerts
ALTER TABLE alerts_sent
  ADD COLUMN IF NOT EXISTS discord_sent BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS discord_status_code INTEGER,
  ADD COLUMN IF NOT EXISTS discord_error TEXT;

-- Separate webhook log for diagnosing Discord failures
CREATE TABLE IF NOT EXISTS webhook_log (
  id SERIAL PRIMARY KEY,
  timestamp TIMESTAMPTZ DEFAULT NOW(),
  webhook_type VARCHAR(20),
  status_code INTEGER,
  success BOOLEAN DEFAULT FALSE,
  error_message TEXT,
  payload_snippet TEXT
);

CREATE INDEX IF NOT EXISTS idx_webhook_log_timestamp
  ON webhook_log (timestamp DESC);
