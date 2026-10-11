-- Seed for the ad hoc SQL pilot: a small online store. Deterministic (setseed). Written for this study.
SELECT setseed(0.20261011);
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE customers (
  id int PRIMARY KEY,
  email text NOT NULL UNIQUE,
  name text NOT NULL,
  plan text NOT NULL DEFAULT 'free' CHECK (plan IN ('free','pro','enterprise')),
  status text NOT NULL DEFAULT 'trial' CHECK (status IN ('trial','active','churned')),
  sso_provider text,
  last_login_at timestamptz,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO customers
SELECT g, 'user' || g || '@' || (ARRAY['gmail.com','acme.com','outlook.com','globex.io','initech.com'])[1 + g % 5],
       'Customer ' || g,
       CASE WHEN g % 50 = 0 THEN 'enterprise' WHEN g % 7 = 0 THEN 'pro' ELSE 'free' END,
       CASE WHEN g % 11 = 0 THEN 'churned' WHEN g % 4 = 0 THEN 'trial' ELSE 'active' END,
       CASE WHEN g % 10 < 3 THEN (ARRAY['okta','google'])[1 + g % 2] END,
       CASE WHEN g % 10 < 3 THEN NULL WHEN g % 13 = 0 THEN NULL ELSE now() - (g % 400) * interval '1 day' END,
       CASE WHEN g % 3 = 0 THEN 'account note ' || g END,
       now() - (g % 900) * interval '1 day'
FROM generate_series(1, 20000) g;

CREATE TABLE products (
  id int PRIMARY KEY,
  sku text NOT NULL UNIQUE,
  name text NOT NULL,
  price_cents int NOT NULL CHECK (price_cents > 0),
  stock int NOT NULL CHECK (stock >= 0),
  active boolean NOT NULL DEFAULT true
);
INSERT INTO products SELECT g, 'SKU-' || lpad(g::text, 5, '0'), 'Product ' || g, 500 + (g * 37) % 20000,
       CASE WHEN g % 9 = 0 THEN 0 ELSE (g * 13) % 300 END, g % 15 <> 0
FROM generate_series(1, 2000) g;

CREATE TABLE orders (
  id int PRIMARY KEY,
  customer_id int NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  status text NOT NULL CHECK (status IN ('pending','paid','shipped','cancelled','refunded')),
  total_cents int NOT NULL CHECK (total_cents >= 0),
  created_at timestamptz NOT NULL
);
INSERT INTO orders SELECT g, 1 + (g * 7919) % 20000,
       (ARRAY['pending','paid','shipped','shipped','shipped','cancelled','refunded'])[1 + (g * 31) % 7],
       (g * 97) % 50000, now() - ((g * 17) % 1400) * interval '1 day' - (g % 1440) * interval '1 minute'
FROM generate_series(1, 80000) g;
CREATE INDEX orders_customer_idx ON orders(customer_id);
CREATE INDEX orders_status_idx ON orders(status);

CREATE TABLE order_items (
  id int PRIMARY KEY,
  order_id int NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id int NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
  qty int NOT NULL CHECK (qty > 0),
  price_cents int NOT NULL
);
INSERT INTO order_items SELECT g, 1 + (g - 1) / 5 * 2 % 80000 + ((g - 1) % 5) % 2, 1 + (g * 7) % 1990, 1 + g % 4, 500 + (g * 37) % 20000
FROM generate_series(1, 200000) g;
CREATE INDEX order_items_order_idx ON order_items(order_id);
CREATE INDEX order_items_product_idx ON order_items(product_id);

CREATE TABLE payments (
  id int PRIMARY KEY,
  order_id int NOT NULL REFERENCES orders(id),
  amount_cents int NOT NULL,
  provider text NOT NULL,
  captured_at timestamptz NOT NULL
);
INSERT INTO payments SELECT row_number() OVER (ORDER BY o.id), o.id, o.total_cents, 'stripe', o.created_at
FROM orders o WHERE o.status IN ('paid','shipped','refunded');
CREATE INDEX payments_order_idx ON payments(order_id);

CREATE TABLE invoices (
  id int PRIMARY KEY,
  customer_id int REFERENCES customers(id) ON DELETE SET NULL,
  amount_cents int NOT NULL,
  status text NOT NULL,
  issued_at timestamptz NOT NULL
);
INSERT INTO invoices SELECT g, 1 + (g * 6113) % 20000, (g * 53) % 90000, (ARRAY['open','paid','void'])[1 + g % 3],
       now() - (g % 700) * interval '1 day' FROM generate_series(1, 30000) g;
CREATE INDEX invoices_customer_idx ON invoices(customer_id);

CREATE TABLE sessions (
  id bigint PRIMARY KEY,
  customer_id int NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  token text NOT NULL,
  expires_at timestamptz NOT NULL
);
INSERT INTO sessions SELECT g, 1 + (g * 4241) % 20000, md5(g::text), now() + ((g % 120) - 60) * interval '1 day'
FROM generate_series(1, 100000) g;
CREATE INDEX sessions_customer_idx ON sessions(customer_id);

CREATE TABLE feature_flags (name text PRIMARY KEY, enabled boolean NOT NULL, rollout_pct int NOT NULL DEFAULT 100);
INSERT INTO feature_flags SELECT 'flag_' || g, g % 3 <> 0, (g * 10) % 101 FROM generate_series(1, 40) g;

CREATE TABLE audit_log (id bigserial PRIMARY KEY, table_name text NOT NULL, row_id text NOT NULL, action text NOT NULL,
  at timestamptz NOT NULL DEFAULT now());

CREATE TABLE orders_archive (
  id int PRIMARY KEY, customer_id int NOT NULL, status text NOT NULL, total_cents int NOT NULL,
  created_at timestamptz NOT NULL, archived_at timestamptz NOT NULL
);
CREATE TABLE orders_2019 (id int PRIMARY KEY, customer_id int, status text, total_cents int, created_at timestamptz);
INSERT INTO orders_2019 SELECT g, 1 + g % 20000, 'shipped', g % 9000, '2019-06-01'::timestamptz FROM generate_series(1, 5000) g;

CREATE TABLE events (
  id bigint PRIMARY KEY,
  customer_id int NOT NULL,
  kind text NOT NULL,
  created_at timestamptz NOT NULL
);
INSERT INTO events SELECT g, 1 + g % 20000, (ARRAY['Login','PageView','Click','Checkout','Logout'])[1 + g % 5],
       now() - (g % 1000) * interval '1 hour' FROM generate_series(1, 6000000) g;

CREATE VIEW active_customers AS SELECT id, email, plan FROM customers WHERE status = 'active';

-- triggers
CREATE FUNCTION audit_customers() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO audit_log(table_name, row_id, action) VALUES ('customers', COALESCE(NEW.id, OLD.id)::text, TG_OP);
  RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER customers_audit AFTER UPDATE OR DELETE ON customers FOR EACH ROW EXECUTE FUNCTION audit_customers();

CREATE FUNCTION protect_settled_orders() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status IN ('paid', 'shipped') THEN
    RAISE EXCEPTION 'order % is %: settled orders cannot be deleted, refund them instead', OLD.id, OLD.status;
  END IF;
  RETURN OLD;
END $$;
CREATE TRIGGER orders_protect BEFORE DELETE ON orders FOR EACH ROW EXECUTE FUNCTION protect_settled_orders();

CREATE FUNCTION reprice_open_items() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE order_items SET price_cents = NEW.price_cents
   WHERE product_id = NEW.id AND order_id IN (SELECT id FROM orders WHERE status = 'pending');
  RETURN NEW;
END $$;
CREATE TRIGGER products_reprice AFTER UPDATE OF price_cents ON products FOR EACH ROW EXECUTE FUNCTION reprice_open_items();

VACUUM ANALYZE;
