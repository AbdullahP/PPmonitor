-- Track the last queue alert timestamp to avoid spamming
ALTER TABLE system_heartbeat
  ADD COLUMN IF NOT EXISTS last_queue_alert TIMESTAMPTZ;
