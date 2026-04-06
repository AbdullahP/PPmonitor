-- Add queue webhook and bot mode columns to discord_servers
ALTER TABLE discord_servers
  ADD COLUMN IF NOT EXISTS queue_webhook VARCHAR(500),
  ADD COLUMN IF NOT EXISTS guild_id VARCHAR(50),
  ADD COLUMN IF NOT EXISTS guild_name VARCHAR(100),
  ADD COLUMN IF NOT EXISTS mode VARCHAR(20) DEFAULT 'webhook',
  ADD COLUMN IF NOT EXISTS stock_channel_id VARCHAR(50),
  ADD COLUMN IF NOT EXISTS admin_channel_id VARCHAR(50),
  ADD COLUMN IF NOT EXISTS discovery_channel_id VARCHAR(50),
  ADD COLUMN IF NOT EXISTS queue_channel_id VARCHAR(50);
