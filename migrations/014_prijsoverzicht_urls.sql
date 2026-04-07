-- 014_prijsoverzicht_urls.sql — Switch bol.com products to prijsoverzicht URLs

UPDATE products SET url =
    'https://www.bol.com/nl/nl/prijsoverzicht/ppmonitor/' || product_id || '/'
WHERE shop = 'bol';
