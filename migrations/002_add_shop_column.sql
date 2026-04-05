-- 002_add_shop_column.sql — Add shop identifier to products and discovered_products

ALTER TABLE products ADD COLUMN IF NOT EXISTS shop TEXT DEFAULT 'bol';
ALTER TABLE discovered_products ADD COLUMN IF NOT EXISTS shop TEXT DEFAULT 'bol';

CREATE INDEX IF NOT EXISTS idx_products_shop ON products (shop);
CREATE INDEX IF NOT EXISTS idx_discovered_shop ON discovered_products (shop);
