-- Added after seed.sql: signups that never ordered (every seeded customer has 4 orders), and an audit history.
ALTER TABLE customers DISABLE TRIGGER customers_audit;
INSERT INTO customers (id, email, name, plan, status, created_at)
SELECT g, 'signup' || g || '@example.com', 'Signup ' || g, 'free', 'trial', now() - interval '3 days'
FROM generate_series(20001, 20010) g;
ALTER TABLE customers ENABLE TRIGGER customers_audit;
INSERT INTO sessions SELECT 100000 + (g - 20001) * 3 + k, g, md5((g * 10 + k)::text), now() + interval '5 days'
FROM generate_series(20001, 20010) g, generate_series(1, 3) k;
INSERT INTO invoices SELECT 30000 + g - 20000, g, 0, 'open', now() - interval '2 days' FROM generate_series(20001, 20010) g;
INSERT INTO audit_log (table_name, row_id, action, at)
SELECT 'customers', (1 + g % 20000)::text, (ARRAY['UPDATE','DELETE'])[1 + (g % 9 = 0)::int], now() - (g % 730) * interval '1 day'
FROM generate_series(1, 50000) g;
VACUUM ANALYZE;
-- Run later on the seed database only (the labeler was too slow with 6M events on a shared machine):
-- DELETE FROM events WHERE id > 1500000; VACUUM FULL events; ANALYZE events;
