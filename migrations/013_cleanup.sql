-- 013_cleanup.sql — Remove Amazon UK dead products, fix bol.com seed data

-- Remove Amazon UK discovered products
DELETE FROM discovered_products WHERE shop = 'amazon_uk';

-- Remove Amazon UK products (poll_log cascades via FK)
DELETE FROM products WHERE shop = 'amazon_uk';

-- Update Perfect Order products with correct URLs and names
UPDATE products SET
    url = 'https://www.bol.com/nl/nl/p/pokemon-tcg-mega-evolution-perfect-order-booster-10-kaarten-per-pakje/9300000271683065/',
    name = 'Pokemon TCG Mega Evolution Perfect Order Booster',
    is_active = true,
    poll_priority = 'high'
WHERE product_id = '9300000271683065';

UPDATE products SET
    url = 'https://www.bol.com/nl/nl/p/pokemon-tcg-mega-evolution-perfect-order-build-battle-box/9300000272060999/',
    name = 'Pokemon TCG Mega Evolution Perfect Order Build & Battle Box',
    is_active = true,
    poll_priority = 'high'
WHERE product_id = '9300000272060999';
