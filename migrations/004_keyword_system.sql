CREATE TABLE IF NOT EXISTS keywords (
  id SERIAL PRIMARY KEY,
  keyword VARCHAR(200) NOT NULL,
  match_type VARCHAR(20) DEFAULT 'contains',
  shops JSONB DEFAULT '["bol","mediamarkt","pocketgames","catchyourcards","games_island","dreamland"]',
  priority VARCHAR(10) DEFAULT 'normal',
  auto_monitor BOOLEAN DEFAULT TRUE,
  notify_discord BOOLEAN DEFAULT TRUE,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  created_by VARCHAR(100) DEFAULT 'admin',
  notes TEXT
);

-- Seed with current relevant keywords
INSERT INTO keywords (keyword, priority, auto_monitor, notes) VALUES
  ('perfect order', 'high', true, 'April 2026 set'),
  ('chaos rising', 'high', true, 'May 2026 set'),
  ('elite trainer box', 'normal', false, 'any ETB — manual approval'),
  ('booster box', 'normal', false, 'any booster box'),
  ('league battle deck', 'normal', true, 'battle decks always hype'),
  ('premium collection', 'normal', false, 'premium boxes'),
  ('mega evolution', 'high', true, 'current series'),
  ('destined rivals', 'normal', true, 'recent set — monitor if OOS');
