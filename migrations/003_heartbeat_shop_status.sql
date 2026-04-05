-- 003_heartbeat_shop_status.sql — Add per-shop status to heartbeat

ALTER TABLE system_heartbeat ADD COLUMN IF NOT EXISTS shop_status JSONB DEFAULT '{}';
