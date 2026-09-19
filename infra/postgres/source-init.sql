CREATE USER zhixi_reader WITH PASSWORD 'reader-local-only' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

REVOKE CREATE, TEMPORARY ON DATABASE factory_demo FROM zhixi_reader;
GRANT CONNECT ON DATABASE factory_demo TO zhixi_reader;

CREATE TABLE production_orders (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_no text NOT NULL UNIQUE,
    product_code text NOT NULL,
    planned_quantity integer NOT NULL CHECK (planned_quantity > 0),
    completed_quantity integer NOT NULL DEFAULT 0,
    started_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE quality_inspections (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id bigint NOT NULL REFERENCES production_orders(id),
    inspected_quantity integer NOT NULL,
    defect_quantity integer NOT NULL DEFAULT 0,
    result text NOT NULL CHECK (result IN ('passed', 'failed')),
    inspected_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_quality_inspections_order_id ON quality_inspections(order_id);
CREATE INDEX ix_quality_inspections_inspected_at ON quality_inspections(inspected_at);

INSERT INTO production_orders
    (order_no, product_code, planned_quantity, completed_quantity, started_at)
VALUES
    ('MO-2025-010', 'MOTOR-A', 1000, 955, '2025-10-02T08:00:00Z'),
    ('MO-2025-011', 'MOTOR-B', 1000, 948, '2025-11-02T08:00:00Z'),
    ('MO-2025-012', 'MOTOR-A', 1000, 962, '2025-12-02T08:00:00Z'),
    ('MO-2026-001', 'MOTOR-B', 1000, 951, '2026-01-02T08:00:00Z'),
    ('MO-2026-002', 'MOTOR-A', 1000, 966, '2026-02-02T08:00:00Z'),
    ('MO-2026-003', 'MOTOR-B', 1000, 944, '2026-03-02T08:00:00Z'),
    ('MO-2026-004', 'MOTOR-A', 1000, 958, '2026-04-02T08:00:00Z'),
    ('MO-2026-005', 'MOTOR-B', 1000, 969, '2026-05-02T08:00:00Z'),
    ('MO-2026-006', 'MOTOR-A', 1000, 953, '2026-06-02T08:00:00Z'),
    ('MO-2026-007', 'MOTOR-B', 1000, 972, '2026-07-02T08:00:00Z'),
    ('MO-2026-008', 'MOTOR-A', 1000, 961, '2026-08-02T08:00:00Z'),
    ('MO-2026-009', 'MOTOR-B', 1000, 947, '2026-09-02T08:00:00Z');

INSERT INTO quality_inspections
    (order_id, inspected_quantity, defect_quantity, result, inspected_at)
VALUES
    (1, 200, 5, 'failed', '2025-10-05T09:00:00Z'),
    (1, 200, 4, 'failed', '2025-10-20T09:00:00Z'),
    (2, 200, 3, 'passed', '2025-11-05T09:00:00Z'),
    (2, 200, 5, 'failed', '2025-11-20T09:00:00Z'),
    (3, 200, 2, 'passed', '2025-12-05T09:00:00Z'),
    (3, 200, 3, 'passed', '2025-12-20T09:00:00Z'),
    (4, 200, 4, 'failed', '2026-01-05T09:00:00Z'),
    (4, 200, 5, 'failed', '2026-01-20T09:00:00Z'),
    (5, 200, 2, 'passed', '2026-02-05T09:00:00Z'),
    (5, 200, 4, 'failed', '2026-02-20T09:00:00Z'),
    (6, 200, 6, 'failed', '2026-03-05T09:00:00Z'),
    (6, 200, 7, 'failed', '2026-03-20T09:00:00Z'),
    (7, 200, 3, 'passed', '2026-04-05T09:00:00Z'),
    (7, 200, 4, 'failed', '2026-04-20T09:00:00Z'),
    (8, 200, 2, 'passed', '2026-05-05T09:00:00Z'),
    (8, 200, 3, 'passed', '2026-05-20T09:00:00Z'),
    (9, 200, 4, 'failed', '2026-06-05T09:00:00Z'),
    (9, 200, 5, 'failed', '2026-06-20T09:00:00Z'),
    (10, 200, 3, 'passed', '2026-07-05T09:00:00Z'),
    (10, 200, 4, 'failed', '2026-07-20T09:00:00Z'),
    (11, 200, 5, 'failed', '2026-08-05T09:00:00Z'),
    (11, 200, 6, 'failed', '2026-08-20T09:00:00Z'),
    (12, 200, 8, 'failed', '2026-09-05T09:00:00Z'),
    (12, 200, 4, 'failed', '2026-09-20T09:00:00Z');

GRANT USAGE ON SCHEMA public TO zhixi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO zhixi_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO zhixi_reader;
